"""
Cash Application — Azure AI Foundry Agent Service
O2C Cash Application Pipeline

Key difference from Semantic Kernel approach:
  - AI Foundry Agent Service manages agent state, tool execution, and threads
  - Agents have native tools: CodeInterpreterTool (actual Python math),
    FileSearchTool (search uploaded documents)
  - ConnectedAgentTool lets one agent call another as a sub-agent natively
  - Platform handles retries, logging, tracing — we just define intent

Pipeline:
  BankStatementIntelligenceAgent  → parse + normalize transactions
          ↓ structured JSON via thread
  ARLedgerAgent                   → structure open invoices, aging, credits
          ↓ structured JSON via thread
  ReconciliationAgent             → 6-tier matching + CodeInterpreter math
          ↓ match results + exceptions
  MismatchReasoningAgent          → AI reasoning per exception
          ↓ exception register with deduction types
  CashPostingAgent                → final posting instructions
"""
import asyncio
import json
import os
from typing import AsyncGenerator

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# Optional: azure-ai-projects for register_agents.py script (not needed for inference)
try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import CodeInterpreterTool
    _AZURE_PROJECTS_AVAILABLE = True
except ImportError:
    _AZURE_PROJECTS_AVAILABLE = False


# ── AGENT SYSTEM PROMPTS ──────────────────────────────────────────────────────

BANK_STATEMENT_PROMPT = """You are the Bank Statement Intelligence Agent in a Cash Application swarm.

Your role: Parse and normalize raw bank statement transactions for downstream matching.

For each transaction extract and flag ALL of the following:

NORMALIZATION:
- Normalize payer name: strip noise words (AP DEPT, CORP, LLC suffix variations), expand abbreviations
- SWIFT 35-char truncation: if payer name ends abruptly or looks abbreviated, flag SWIFT_NAME_TRUNCATION
- Parse remittance text for: invoice numbers (INV-xxxx), PO numbers (PO-xxxx), legacy refs (LEGACY-xxxx),
  contract numbers, check numbers, credit memo refs (CM-xxxx)

ANOMALY FLAGS (add all that apply):
  MISSING_REMITTANCE    — remittance_text is blank or contains no actionable reference
  POSSIBLE_DUPLICATE    — same payer + amount already seen within 30 days in this statement
  NSF_RETURN            — negative amount or "R01/R02" return codes in payer/remittance
  FX_PAYMENT            — currency != USD or "EUR/GBP/CHF" appears in remittance
  SWIFT_NAME_TRUNCATION — payer name appears cut off (likely 35-char SWIFT field limit)
  POST_DATED_CHECK      — check payment_type and check date in future vs statement date
  STALE_CHECK           — check payment_type and check date >180 days before statement date
  THIRD_PARTY_PAYER     — payer name does not match any known customer; remittance names a different company
  PARENT_ENTITY_PAYMENT — payer name contains "HOLDINGS", "GROUP", "GLOBAL" and references a known subsidiary
  EDI_REMITTANCE_PENDING — no remittance but amount is large and round (likely EDI 820 arriving separately)
  PREPAYMENT            — remittance mentions "advance", "deposit", "Q[1-4]", "prepay", no invoice ref
  INTERCOMPANY_NET      — remittance mentions "net", "interco", "netting", "AR/AP"
  COMPLIANCE_HOLD       — payer name contains "FZE", "FZCO", "LLC UAE", "Trading" with Gulf/sanctioned region markers
  WRONG_LEGAL_ENTITY    — remittance references a different legal entity name than the receiving company
  DISPUTED_INVOICE      — remittance references an invoice that has status=DISPUTED or ON_HOLD in AR

For each transaction:
- check_date field: extract check date from remittance or bank_reference if available (else null)
- alias_lookup_needed: true if SWIFT_NAME_TRUNCATION, THIRD_PARTY_PAYER, or PARENT_ENTITY_PAYMENT flagged

Return ONLY this JSON:
{
  "agent": "BankStatementIntelligenceAgent",
  "transactions": [
    {
      "txn_id": "<id>",
      "date": "<YYYY-MM-DD>",
      "amount": <number>,
      "currency": "<USD|EUR|GBP>",
      "usd_amount": <number>,
      "payment_type": "<ACH|WIRE|CHECK|SWIFT>",
      "payer_raw": "<original payer name>",
      "payer_normalized": "<cleaned name>",
      "parsed_references": ["<INV-xxx>", "<PO-xxx>", "<LEGACY-xxx>"],
      "remittance_text": "<original>",
      "check_date": "<YYYY-MM-DD or null>",
      "alias_lookup_needed": <bool>,
      "flags": ["<FLAG_CODE>", ...]
    }
  ],
  "summary": {
    "total_transactions": <n>,
    "total_amount_usd": <n>,
    "flagged_count": <n>,
    "flags_breakdown": {
      "MISSING_REMITTANCE": <n>,
      "POSSIBLE_DUPLICATE": <n>,
      "NSF_RETURN": <n>,
      "FX_PAYMENT": <n>,
      "STALE_CHECK": <n>,
      "POST_DATED_CHECK": <n>,
      "THIRD_PARTY_PAYER": <n>,
      "PARENT_ENTITY_PAYMENT": <n>,
      "COMPLIANCE_HOLD": <n>,
      "WRONG_LEGAL_ENTITY": <n>,
      "EDI_REMITTANCE_PENDING": <n>,
      "PREPAYMENT": <n>,
      "INTERCOMPANY_NET": <n>
    },
    "payment_types": {"ACH": <n>, "WIRE": <n>, "CHECK": <n>, "SWIFT": <n>}
  }
}
After the JSON write exactly: NEXT: ARLedgerAgent"""

AR_LEDGER_PROMPT = """You are the AR Ledger Agent in a Cash Application swarm.

Your role: Structure and enrich open AR invoice data for reconciliation matching.
Also process the payer_alias_registry, parent_child_hierarchy, and intercompany_netting fields
from the open_ar data — these are critical for identity matching in the Reconciliation Agent.

For each invoice:
- Calculate aging bucket: CURRENT | 1-30 | 31-60 | 61-90 | 90+
- Parse payment terms for early-pay discount window (e.g. "2/10 NET 30" = 2% if paid within 10 days)
- Flag status: OPEN | PARTIAL | DISPUTED | ON_HOLD | LEGAL_HOLD | CLOSED
- DISPUTED and LEGAL_HOLD invoices: add do_not_auto_apply: true — these MUST be escalated, never auto-posted
- Build legacy invoice cross-reference: map legacy_invoice_id → current invoice_id where provided
- Build customer index including all aliases from payer_alias_registry

Return ONLY this JSON:
{
  "agent": "ARLedgerAgent",
  "invoices": [
    {
      "invoice_id": "<id>",
      "legacy_invoice_id": "<LEGACY-xxx or null>",
      "customer_id": "<id>",
      "customer_name": "<normalized>",
      "invoice_date": "<YYYY-MM-DD>",
      "due_date": "<YYYY-MM-DD>",
      "original_amount": <number>,
      "open_amount": <number>,
      "currency": "USD",
      "po_reference": "<PO-xxx or null>",
      "payment_terms": "<2/10 NET 30>",
      "discount_pct": <number or 0>,
      "discount_deadline": "<YYYY-MM-DD or null>",
      "aging_bucket": "<CURRENT|1-30|31-60|61-90|90+>",
      "aging_days": <number>,
      "status": "OPEN|PARTIAL|DISPUTED|ON_HOLD|LEGAL_HOLD|CLOSED",
      "do_not_auto_apply": <bool>,
      "dispute_reason": "<reason or null>",
      "existing_credit_memo": <number or 0>
    }
  ],
  "customer_index": {
    "<customer_id>": {
      "name": "<canonical name>",
      "aliases": ["<alias1>", "<alias2>"],
      "parent_customer_id": "<id or null>",
      "factoring_agent": "<company name or null>",
      "total_open": <number>,
      "invoice_count": <number>,
      "oldest_invoice_id": "<id>",
      "oldest_due_date": "<YYYY-MM-DD>",
      "has_credit_memos": <bool>,
      "has_disputes": <bool>
    }
  },
  "legacy_invoice_map": {
    "<LEGACY-xxx>": "<INV-xxxx>"
  },
  "intercompany_netting": [
    {
      "customer_id": "<id>",
      "customer_name": "<name>",
      "our_receivable": <number>,
      "our_payable": <number>,
      "expected_net_payment": <number>,
      "net_agreement_active": <bool>
    }
  ],
  "compliance_flags": {
    "disputed_invoice_ids": ["<id>"],
    "legal_hold_invoice_ids": ["<id>"],
    "do_not_auto_apply_customer_ids": ["<id>"]
  },
  "ar_summary": {
    "total_open_amount": <number>,
    "total_invoices": <number>,
    "disputed_count": <number>,
    "legal_hold_count": <number>,
    "total_credit_memos": <number>,
    "customers_with_aliases": <n>,
    "intercompany_customers": <n>
  }
}
After the JSON write exactly: NEXT: ReconciliationAgent"""

RECONCILIATION_PROMPT = """You are the Reconciliation Agent in a Cash Application swarm.

Your role: Match every bank transaction to open AR invoices using an 8-tier matching hierarchy.
Use the Code Interpreter for ALL arithmetic — never calculate amounts mentally.

CONFIGURABLE THRESHOLDS (use these exactly):
  AUTO_WRITEOFF_THRESHOLD = 25.00      # Differences ≤ $25 auto write-off (bank fees, rounding)
  FUZZY_NAME_MATCH_THRESHOLD = 0.75   # Minimum similarity for alias/DBA matching
  DUPLICATE_WINDOW_DAYS = 30          # Flag duplicates within this window
  DISCOUNT_LATE_TOLERANCE_DAYS = 0    # No tolerance for late early-pay discounts

PRE-CHECKS (run BEFORE matching tiers — these block or redirect a transaction):
  A. COMPLIANCE_HOLD  — if txn has COMPLIANCE_HOLD flag → do NOT match, status=COMPLIANCE_HOLD
  B. WRONG_ENTITY     — if remittance references a different legal entity → status=WRONG_ENTITY
  C. DISPUTED_INVOICE — if parsed_references points to a do_not_auto_apply invoice → status=DISPUTED_INVOICE_HOLD
  D. POST_DATED_CHECK — if check_date > statement_date → status=POST_DATED_HOLD
  E. STALE_CHECK      — if check_date < statement_date - 180 days → status=STALE_CHECK_RETURN
  F. INTERCOMPANY_NET — if INTERCOMPANY_NET flag → match to intercompany_netting table, not invoices
  G. PREPAYMENT       — if PREPAYMENT flag → status=SUSPENSE_PREPAYMENT, no invoice match
  H. EDI_PENDING      — if EDI_REMITTANCE_PENDING flag → status=HOLD_EDI_PENDING, match after EDI arrives

8-TIER MATCHING HIERARCHY (apply in order after pre-checks):
  Tier 1 — EXACT:          amount == invoice.open_amount AND invoice_id in parsed_references
  Tier 2 — LEGACY_REF:     parsed_references contains a legacy_invoice_id → lookup in legacy_invoice_map
  Tier 3 — ALIAS_MATCH:    payer_normalized OR payer_raw matches customer alias table (fuzzy ≥75%) + amount match
  Tier 4 — REMITTANCE_REF: any parsed_reference matches invoice_id or po_reference (amount within AUTO_WRITEOFF_THRESHOLD)
  Tier 5 — DISCOUNT_EXACT: amount == invoice.open_amount × (1 - discount_pct/100) AND date <= discount_deadline
  Tier 6 — MULTI_INVOICE:  amount == sum of 2-4 open invoices for same customer (use Code Interpreter to enumerate)
  Tier 7 — CREDIT_NET:     amount == invoice.open_amount - existing_credit_memo
  Tier 8 — FIFO:           customer identified by alias/name → apply to oldest open invoice(s)

SPECIAL MATCH STATUSES (outside tiers):
  BANK_FEE_WRITEOFF   — amount = invoice - ($10 to $50 wire fee), delta ≤ AUTO_WRITEOFF_THRESHOLD → auto write-off delta
  OVERPAYMENT         — amount > all matched invoices → post invoices, create $X credit on account
  DUPLICATE_PAYMENT   — same payer + amount within DUPLICATE_WINDOW_DAYS → hold second occurrence
  INSTALLMENT         — remittance says "installment N of M" → partial match
  LATE_DISCOUNT       — discount taken but outside discount_deadline → UNAUTHORIZED_DISCOUNT exception
  PARENT_SUBSIDIARY   — payer is parent entity → match via parent_customer_id in customer_index
  THIRD_PARTY_FACTORING — payer is known factoring agent → match via factoring_agent in customer_index

Use Code Interpreter to:
  1. Verify all multi-invoice combinations sum exactly
  2. Verify discount calculations: payment_amount == invoice_amount * (1 - discount_pct/100)
  3. Verify FX: usd_amount == foreign_amount / fx_rate (within $1 rounding)
  4. Check check_date age: (statement_date - check_date).days
  5. Verify intercompany net: our_receivable - our_payable == payment_amount

Return ONLY this JSON:
{
  "agent": "ReconciliationAgent",
  "matches": [
    {
      "txn_id": "<id>",
      "match_status": "MATCHED|PARTIAL|DISCOUNT|MULTI_INVOICE|FIFO|BANK_FEE_WRITEOFF|OVERPAYMENT|DUPLICATE_PAYMENT|INSTALLMENT|LATE_DISCOUNT|COMPLIANCE_HOLD|WRONG_ENTITY|DISPUTED_INVOICE_HOLD|POST_DATED_HOLD|STALE_CHECK_RETURN|SUSPENSE_PREPAYMENT|HOLD_EDI_PENDING|INTERCOMPANY_NET|PARENT_SUBSIDIARY|THIRD_PARTY_FACTORING|ALIAS_MATCH|LEGACY_REF|UNMATCHED",
      "match_tier": "<1-8 or PRE-CHECK-A through PRE-CHECK-H or null>",
      "confidence_pct": <0-100>,
      "customer_resolved": "<canonical customer name>",
      "matched_invoices": [
        {"invoice_id": "<id>", "applied_amount": <number>, "remaining_open": <number>}
      ],
      "transaction_amount": <number>,
      "total_applied": <number>,
      "unapplied_amount": <number>,
      "delta": <number>,
      "auto_writeoff_delta": <number or 0>,
      "exception": true|false,
      "exception_reason": "<reason or null>",
      "pre_check_triggered": "<A-H or null>"
    }
  ],
  "reconciliation_summary": {
    "total_transactions": <n>,
    "matched_exact": <n>,
    "matched_with_exceptions": <n>,
    "compliance_holds": <n>,
    "pre_check_blocks": <n>,
    "unmatched": <n>,
    "auto_writeoffs": <n>,
    "auto_writeoff_total": <number>,
    "total_cash_received": <number>,
    "total_applied": <number>,
    "total_unapplied": <number>
  }
}
After the JSON write exactly: NEXT: MismatchReasoningAgent"""

MISMATCH_REASONING_PROMPT = """You are the Mismatch Reasoning Agent in a Cash Application swarm.

Your role: For every exception transaction, provide specific AI reasoning about WHY it didn't match cleanly
and WHAT action the AR team should take. This is the intelligence layer — turn raw gaps into business actions.

RISK ESCALATION TIERS (assign to every exception — determines SLA and routing):
  CRITICAL (same-day) — Compliance holds, sanctions screening, wrong legal entity, disputed invoice payments,
                         NSF returns on large amounts, stale checks already deposited
  HIGH     (24 hours) — Unauthorized deductions >$1,000, overpayments >$5,000, duplicate payments,
                         parent/subsidiary mismatches, factoring agent payments
  MEDIUM   (3 days)   — Authorized deductions, EDI pending, post-dated checks, late discounts,
                         intercompany netting, prepayments, DBA/alias mismatches
  LOW      (5 days)   — Small balance write-offs, rounding differences, bank wire fees ≤$50

EXCEPTION CATEGORIES (all 7 category groups):

AMOUNT MISMATCHES:
  EARLY_PAY_DISCOUNT    — Valid % discount taken within contractual discount window
  UNAUTHORIZED_DISCOUNT — Discount taken outside window, or no discount terms exist
  FREIGHT_DEDUCTION     — Deduction matches freight allowance on distribution agreement
  DAMAGE_CLAIM          — Deduction matches damage/shortage claim pattern
  TRADE_PROMO           — Promotional allowance deduction
  PRICING_DISPUTE       — Customer disputes a line item price (requires credit memo or escalation)
  SHORT_SHIP            — Customer deducting for undelivered goods
  BANK_WIRE_FEE         — Delta $10-$50 = bank's wire transfer fee (auto write-off if ≤$25)
  LATE_DISCOUNT         — Discount taken but AFTER discount_deadline (unauthorized)
  OVERPAYMENT           — Payment exceeds invoice(s); excess becomes credit on account

IDENTITY & NAME ISSUES:
  SWIFT_NAME_TRUNCATION — Payer name cut at 35 chars; matched via alias table
  DBA_NAME_MISMATCH     — Payer is a registered DBA of a known customer
  POST_ACQUISITION_NAME — Payer uses former company name post M&A
  ALIAS_RESOLVED        — Name resolved through alias registry with high confidence

MULTI-ENTITY / RELATIONSHIP:
  PARENT_SUBSIDIARY     — Parent entity paying on behalf of subsidiary customer
  THIRD_PARTY_FACTORING — Factoring company paying on behalf of customer
  INTERCOMPANY_NET      — Net settlement between related entities (requires AP/AR bilateral entry)
  WRONG_LEGAL_ENTITY    — Payment intended for a different legal entity (return or redirect)

TIMING / SEQUENCING:
  DUPLICATE_PAYMENT     — Same payer + amount + invoice within 30-day window (hold second)
  POST_DATED_CHECK      — Check date is in the future; hold until check date
  STALE_CHECK           — Check >180 days old; cannot negotiate; return to issuer
  INSTALLMENT_PAYMENT   — Partial payment per installment agreement
  PREPAYMENT_ADVANCE    — No invoice; customer paying ahead of order; post to unearned revenue
  NSF_RETURN            — Prior ACH bounced; must reverse previous application and reopen invoice

REMITTANCE / REFERENCE:
  MISSING_REMITTANCE    — No reference; matched via FIFO or amount
  VAGUE_REMITTANCE      — "See attached" / "June invoices" with no specifics; amount-based match
  LEGACY_INVOICE_REF    — Customer used old ERP invoice numbering; cross-referenced via legacy map
  PO_REFERENCE          — Customer pays by PO number not invoice number
  EDI_REMITTANCE_PENDING — Payment held; EDI 820 file expected; do not FIFO match yet

FX & INTERNATIONAL:
  FX_PAYMENT            — Foreign currency payment; verify USD equivalent via exchange rate
  FX_RATE_MISMATCH      — FX conversion produces unexpected USD amount vs invoice

COMPLIANCE & LEGAL:
  COMPLIANCE_HOLD       — Payer triggers OFAC/sanctions screening; DO NOT POST; escalate to Compliance
  DISPUTED_INVOICE_HOLD — Invoice under active dispute/legal hold; DO NOT POST; escalate to Credit Manager
  LEGAL_HOLD            — Invoice or customer account has court/legal freeze

For each exception:
- Reference actual amounts, dates, and terms (not generic boilerplate)
- Assign risk_tier: CRITICAL | HIGH | MEDIUM | LOW
- Provide escalation_contact: the specific team or person to notify
- For COMPLIANCE_HOLD: always recommended_action=COMPLIANCE_ESCALATE, sla_hours=4

Return ONLY this JSON:
{
  "agent": "MismatchReasoningAgent",
  "exception_analysis": [
    {
      "txn_id": "<id>",
      "exception_type": "<category from list above>",
      "exception_category_group": "AMOUNT_MISMATCH|IDENTITY|MULTI_ENTITY|TIMING|REMITTANCE|FX|COMPLIANCE",
      "risk_tier": "CRITICAL|HIGH|MEDIUM|LOW",
      "reasoning": "<specific explanation referencing amounts/dates/invoice IDs/terms>",
      "confidence_pct": <0-100>,
      "recommended_action": "AUTO_APPLY|DEDUCTION_WORKITEM|MANUAL_REVIEW|RETURN_TO_CUSTOMER|WRITE_OFF|HOLD_EDI|HOLD_CHECK_DATE|COMPLIANCE_ESCALATE|LEGAL_ESCALATE|CREDIT_ESCALATE|REVERSE_AND_REOPEN|INTERCO_JOURNAL",
      "deduction_amount": <number or 0>,
      "suggested_gl_code": "<GL account code>",
      "gl_description": "<GL account name>",
      "sla_hours": <number>,
      "escalation_contact": "AR_ANALYST|DEDUCTIONS_TEAM|CREDIT_MANAGER|COMPLIANCE_OFFICER|TREASURY|LEGAL|NONE",
      "auto_resolvable": <bool>
    }
  ],
  "exception_summary": {
    "total_exceptions": <n>,
    "by_risk_tier": {
      "CRITICAL": <n>,
      "HIGH": <n>,
      "MEDIUM": <n>,
      "LOW": <n>
    },
    "by_category_group": {
      "AMOUNT_MISMATCH": <n>,
      "IDENTITY": <n>,
      "MULTI_ENTITY": <n>,
      "TIMING": <n>,
      "REMITTANCE": <n>,
      "FX": <n>,
      "COMPLIANCE": <n>
    },
    "auto_resolvable": <n>,
    "needs_manual_review": <n>,
    "compliance_escalations": <n>,
    "total_deduction_amount": <number>
  }
}
After the JSON write exactly: NEXT: CashPostingAgent"""

CASH_POSTING_PROMPT = """You are the Cash Posting Agent in a Cash Application swarm.

Your role: Generate the final, actionable cash posting instructions for the AR team and ERP system.
Every transaction must have a clear disposition — nothing left ambiguous.

POSTING RULES:
  1. AUTO_WRITEOFF threshold = $25.00. Deltas ≤ $25 (bank fees, rounding) → auto write-off to GL 6020 (Bank Charges).
  2. CRITICAL risk tier items → priority=IMMEDIATE, SLA=same day, route to COMPLIANCE_OFFICER or LEGAL.
  3. HIGH risk tier items → priority=TODAY, route to CREDIT_MANAGER.
  4. COMPLIANCE_HOLD transactions → action=FREEZE_PENDING_COMPLIANCE. Do NOT post. Notify Compliance Officer within 4 hours.
  5. WRONG_LEGAL_ENTITY → action=RETURN_TO_SENDER or ENTITY_TRANSFER. Cannot post to wrong entity's books.
  6. DISPUTED_INVOICE payments → action=HOLD_LEGAL_REVIEW. Post to suspense (GL 2099) until dispute resolved.
  7. PREPAYMENT → post to GL 2050 (Customer Deposits / Unearned Revenue). Create advance payment record.
  8. POST_DATED_CHECK → hold file until check date, then re-process.
  9. STALE_CHECK → action=RETURN_STALE_CHECK. Mark as void, notify customer, reopen original invoice.
  10. INTERCOMPANY_NET → requires simultaneous DR to AR and CR to AP. Document net agreement reference.
  11. THIRD_PARTY_FACTORING → post against customer's AR (not the factoring agent), note factor in payment memo.
  12. PARENT_SUBSIDIARY → post against subsidiary's AR customer ID, not parent. Document parent entity in notes.

WORKQUEUE PRIORITY SYSTEM:
  Priority 1 (Same-Day)  — COMPLIANCE_HOLD, WRONG_ENTITY, DISPUTED_INVOICE payment, large NSF returns
  Priority 2 (24-Hour)   — Unauthorized deductions >$1K, duplicates, overpayments, stale checks
  Priority 3 (3-Day)     — Authorized exceptions, EDI pending, post-dated checks, installment close-outs
  Priority 4 (5-Day)     — Small deductions, DBA aliases resolved, routine write-offs

Return ONLY this JSON:
{
  "agent": "CashPostingAgent",
  "executive_summary": "<4-5 sentences covering: total cash, auto-posted %, compliance holds, key exceptions, recommended priorities>",
  "posting_instructions": [
    {
      "txn_id": "<id>",
      "action": "POST_FULL|POST_PARTIAL|POST_WITH_WRITEOFF|HOLD_UNAPPLIED|RETURN_TO_SENDER|ENTITY_TRANSFER|REVERSE_DUPLICATE|DEDUCTION_WORKITEM|HOLD_EDI_PENDING|HOLD_CHECK_DATE|RETURN_STALE_CHECK|FREEZE_PENDING_COMPLIANCE|HOLD_LEGAL_REVIEW|SUSPENSE_PREPAYMENT|INTERCO_JOURNAL|POST_FACTORING|POST_PARENT_SUBSIDIARY",
      "risk_tier": "CRITICAL|HIGH|MEDIUM|LOW",
      "invoice_applications": [
        {"invoice_id": "<id>", "amount": <number>, "closes_invoice": true|false}
      ],
      "writeoff_amount": <number or 0>,
      "writeoff_reason": "<reason or null>",
      "writeoff_gl": "<GL code or null>",
      "unapplied_amount": <number or 0>,
      "suspense_amount": <number or 0>,
      "suspense_gl": "<2050 Unearned Revenue|2099 Suspense|null>",
      "deduction_code": "<code or null>",
      "gl_entries": [
        {"account": "<GL code>", "account_name": "<name>", "debit": <number>, "credit": <number>, "description": "<desc>"}
      ],
      "erp_action": "<specific ERP step>",
      "priority": "IMMEDIATE|TODAY|THIS_WEEK|NEXT_WEEK",
      "compliance_action": "<specific compliance step or null>",
      "notes": "<important context for the AR analyst including customer aliases, parent entities, or compliance flags>"
    }
  ],
  "cash_application_summary": {
    "total_received_usd": <number>,
    "auto_posted_usd": <number>,
    "auto_posted_pct": <number>,
    "held_compliance_usd": <number>,
    "held_other_usd": <number>,
    "deductions_usd": <number>,
    "auto_writeoffs_usd": <number>,
    "suspense_usd": <number>,
    "invoices_closed": <number>,
    "exceptions_requiring_action": <number>,
    "compliance_escalations": <number>
  },
  "workqueue_items": [
    {
      "priority": <1,2,3,4>,
      "risk_tier": "CRITICAL|HIGH|MEDIUM|LOW",
      "txn_id": "<id>",
      "team": "AR_ANALYST|DEDUCTIONS_TEAM|CREDIT_MANAGER|COMPLIANCE_OFFICER|TREASURY|LEGAL",
      "action_required": "<specific task>",
      "amount": <number>,
      "due_by": "<Same Day|24 Hours|3 Days|5 Days>",
      "escalation_note": "<why this matters / what happens if missed>"
    }
  ]
}
After the JSON write exactly: CASH_APP_COMPLETE"""


# ── AGENT METADATA ────────────────────────────────────────────────────────────

AGENT_META = {
    "BankStatementIntelligenceAgent": {
        "label": "Bank Statement Parser",
        "icon": "🏦",
        "color": "#3b82f6",
        "desc": "Normalizes transactions, parses remittance, flags anomalies",
    },
    "ARLedgerAgent": {
        "label": "Open AR Ledger",
        "icon": "📒",
        "color": "#10b981",
        "desc": "Structures invoices, calculates aging, identifies credits",
    },
    "ReconciliationAgent": {
        "label": "Reconciliation Engine",
        "icon": "⚖️",
        "color": "#f59e0b",
        "desc": "6-tier matching hierarchy with exact math via Code Interpreter",
    },
    "MismatchReasoningAgent": {
        "label": "Mismatch Reasoning",
        "icon": "🧠",
        "color": "#ef4444",
        "desc": "AI reasoning for every exception: deduction type, cause, action",
    },
    "CashPostingAgent": {
        "label": "Cash Posting",
        "icon": "✅",
        "color": "#8b5cf6",
        "desc": "Final posting instructions, GL entries, workqueue items",
    },
}

AGENT_ORDER = [
    "BankStatementIntelligenceAgent",
    "ARLedgerAgent",
    "ReconciliationAgent",
    "MismatchReasoningAgent",
    "CashPostingAgent",
]

AGENT_PROMPTS = {
    "BankStatementIntelligenceAgent": BANK_STATEMENT_PROMPT,
    "ARLedgerAgent":                  AR_LEDGER_PROMPT,
    "ReconciliationAgent":            RECONCILIATION_PROMPT,
    "MismatchReasoningAgent":         MISMATCH_REASONING_PROMPT,
    "CashPostingAgent":               CASH_POSTING_PROMPT,
}

# ReconciliationAgent gets code_interpreter for exact arithmetic verification
AGENT_TOOLS = {
    "ReconciliationAgent": [{"type": "code_interpreter"}],
}


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """Extract the first valid JSON object from agent response text."""
    try:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
    except Exception:
        pass
    return None


def _build_openai_client() -> AsyncAzureOpenAI:
    """Build AsyncAzureOpenAI client using API key or DefaultAzureCredential."""
    endpoint = os.environ.get("AZURE_AI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_API_KEY", "")
    api_ver  = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    if not endpoint:
        raise EnvironmentError("Set AZURE_AI_ENDPOINT in backend/.env")

    if api_key:
        return AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_ver,
        )

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    return AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_ver,
    )


def _build_client():
    """Legacy AIProjectClient builder — used by register_agents.py script only."""
    if not _AZURE_PROJECTS_AVAILABLE:
        raise ImportError("azure-ai-projects is not installed. Run: pip install azure-ai-projects")
    endpoint       = os.environ.get("AZURE_AI_ENDPOINT", "")
    subscription   = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
    resource_group = os.environ.get("AZURE_RESOURCE_GROUP", "")
    project_name   = os.environ.get("AZURE_PROJECT_NAME", "")
    if not (endpoint and subscription and resource_group and project_name):
        raise EnvironmentError("Set AZURE_AI_ENDPOINT, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_PROJECT_NAME")
    return AIProjectClient(
        endpoint=endpoint,
        subscription_id=subscription,
        resource_group_name=resource_group,
        project_name=project_name,
        credential=DefaultAzureCredential(),
    )


# ── FIXTURE FALLBACK (demo mode) ──────────────────────────────────────────────

async def _run_fixture_swarm(
    bank_data: dict,
    ar_data: dict,
) -> AsyncGenerator[dict, None]:
    """
    Simulate the swarm using pre-computed fixture outputs when USE_FIXTURES=true.
    Streams token-by-token with realistic timing so the UI looks live.
    """
    import pathlib, time

    fixtures_dir = pathlib.Path(__file__).parent.parent / "fixtures"
    results_file = fixtures_dir / "cash_app_results.json"

    if not results_file.exists():
        yield {"event": "error", "message": "Fixture results file not found. Run with live credentials or add fixtures/cash_app_results.json"}
        return

    results = json.loads(results_file.read_text())

    for agent_name in AGENT_ORDER:
        meta = AGENT_META[agent_name]
        agent_result = results.get(agent_name, {})
        response_text = json.dumps(agent_result, indent=2)

        yield {
            "event": "agent_start",
            "agent": agent_name,
            "label": meta["label"],
            "icon":  meta["icon"],
            "color": meta["color"],
            "tool":  "code_interpreter" if agent_name == "ReconciliationAgent" else None,
        }

        # Stream tokens with slight delay to simulate live generation
        chunk_size = 4
        for i in range(0, len(response_text), chunk_size):
            token = response_text[i:i + chunk_size]
            yield {"event": "agent_token", "agent": agent_name, "token": token}
            await asyncio.sleep(0.008)

        yield {
            "event": "agent_complete",
            "agent":  agent_name,
            "label":  meta["label"],
            "icon":   meta["icon"],
            "color":  meta["color"],
            "output": agent_result,
        }
        await asyncio.sleep(0.1)

    yield {
        "event":  "swarm_complete",
        "results": results,
        "final":   results.get("CashPostingAgent", {}),
    }


# ── LIVE AI FOUNDRY SWARM ─────────────────────────────────────────────────────

async def _run_live_swarm(
    bank_data: dict,
    ar_data: dict,
) -> AsyncGenerator[dict, None]:
    """
    Live swarm using Azure AI Foundry via OpenAI-compatible chat completions.

    Architecture:
      - Each agent runs as a sequential chat completion with its own system prompt.
      - Agents 1-2 (extraction) receive the full raw input data.
      - Agents 3-5 receive compact structured outputs from prior agents — saves tokens.
      - All agents stream tokens in real time via AsyncAzureOpenAI.
      - ReconciliationAgent is instructed to show its math inline (no sandbox needed).
    """
    client = _build_openai_client()

    AGENT_MODELS = {
        "BankStatementIntelligenceAgent": os.environ.get("MODEL_BANK_AGENT",     "gpt-4o-mini"),
        "ARLedgerAgent":                  os.environ.get("MODEL_AR_AGENT",        "gpt-4o-mini"),
        "ReconciliationAgent":            os.environ.get("MODEL_RECON_AGENT",     "gpt-4o"),
        "MismatchReasoningAgent":         os.environ.get("MODEL_REASONING_AGENT", "gpt-4o"),
        "CashPostingAgent":               os.environ.get("MODEL_POSTING_AGENT",   "gpt-4o"),
    }

    # Max tokens per agent — reconciliation + posting outputs are large
    MAX_TOKENS = {
        "BankStatementIntelligenceAgent": 4096,
        "ARLedgerAgent":                  4096,
        "ReconciliationAgent":            8192,
        "MismatchReasoningAgent":         6144,
        "CashPostingAgent":               6144,
    }

    all_results: dict[str, dict] = {}

    def _build_user_content(agent_name: str) -> str:
        """Give each agent only the data it needs — avoids context bloat."""
        if agent_name == "BankStatementIntelligenceAgent":
            return json.dumps({
                "task": "Parse and normalize this bank statement. Extract all transactions with flags.",
                "bank_statement": bank_data,
            }, indent=None)

        if agent_name == "ARLedgerAgent":
            return json.dumps({
                "task": "Structure this open AR ledger data. Build customer index, aging, alias registry.",
                "open_ar": ar_data,
            }, indent=None)

        if agent_name == "ReconciliationAgent":
            bank = all_results.get("BankStatementIntelligenceAgent", {})
            ar   = all_results.get("ARLedgerAgent", {})
            return json.dumps({
                "task": "Match every bank transaction to open AR invoices using the 8-tier hierarchy.",
                "normalized_transactions": bank.get("transactions", []),
                "bank_summary":            bank.get("summary", {}),
                "invoices":                ar.get("invoices", []),
                "customer_index":          ar.get("customer_index", {}),
                "legacy_invoice_map":      ar.get("legacy_invoice_map", {}),
                "compliance_flags":        ar.get("compliance_flags", {}),
                "intercompany_netting":    ar.get("intercompany_netting", []),
            }, indent=None)

        if agent_name == "MismatchReasoningAgent":
            recon   = all_results.get("ReconciliationAgent", {})
            matches = recon.get("matches", [])
            exceptions = [m for m in matches if m.get("exception")]
            return json.dumps({
                "task": "Analyze each exception. Provide reasoning, risk tier, GL code, recommended action.",
                "exception_matches":      exceptions,
                "reconciliation_summary": recon.get("reconciliation_summary", {}),
            }, indent=None)

        if agent_name == "CashPostingAgent":
            recon    = all_results.get("ReconciliationAgent", {})
            mismatch = all_results.get("MismatchReasoningAgent", {})
            return json.dumps({
                "task": "Generate final GL posting instructions and workqueue items for every transaction.",
                "all_matches":          recon.get("matches", []),
                "reconciliation_summary": recon.get("reconciliation_summary", {}),
                "exception_analysis":   mismatch.get("exception_analysis", []),
                "exception_summary":    mismatch.get("exception_summary", {}),
            }, indent=None)

        return json.dumps({"task": "Continue.", "prior_outputs": all_results}, indent=None)

    for agent_name in AGENT_ORDER:
        meta  = AGENT_META[agent_name]
        model = AGENT_MODELS[agent_name]

        yield {
            "event": "agent_start",
            "agent": agent_name,
            "label": meta["label"],
            "icon":  meta["icon"],
            "color": meta["color"],
            "model": model,
            "tool":  "code_interpreter" if agent_name == "ReconciliationAgent" else None,
        }

        messages = [
            {"role": "system", "content": AGENT_PROMPTS[agent_name]},
            {"role": "user",   "content": _build_user_content(agent_name)},
        ]

        response_text = ""

        # Retry up to 2 times on connection errors
        last_error = None
        for attempt in range(3):
            try:
                response_text = ""
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    max_tokens=MAX_TOKENS[agent_name],
                    temperature=0.1,
                    timeout=300,
                )

                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        response_text += token
                        yield {
                            "event": "agent_token",
                            "agent": agent_name,
                            "token": token,
                        }
                last_error = None
                break  # success

            except Exception as e:
                last_error = e
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue

        if last_error:
            yield {
                "event":   "error",
                "agent":   agent_name,
                "message": f"{agent_name} failed after 3 attempts: {last_error}",
            }
            return

        parsed = _extract_json(response_text)
        if parsed:
            all_results[agent_name] = parsed

        yield {
            "event":  "agent_complete",
            "agent":  agent_name,
            "label":  meta["label"],
            "icon":   meta["icon"],
            "color":  meta["color"],
            "output": parsed or {"raw": response_text[:800]},
        }

        await asyncio.sleep(0.05)

    yield {
        "event":   "swarm_complete",
        "results": all_results,
        "final":   all_results.get("CashPostingAgent", {}),
    }


# ── PUBLIC ENTRY POINT ────────────────────────────────────────────────────────

async def run_cash_application(
    bank_data: dict,
    ar_data:   dict,
) -> AsyncGenerator[dict, None]:
    """
    Route to fixture swarm (demo mode) or live AI Foundry swarm.
    """
    use_fixtures = os.getenv("USE_FIXTURES", "true").lower() == "true"

    if use_fixtures:
        async for event in _run_fixture_swarm(bank_data, ar_data):
            yield event
    else:
        async for event in _run_live_swarm(bank_data, ar_data):
            yield event
