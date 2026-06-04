---
layout: default
title: System Design
---

# Cash Application Foundry - System Design

## Architecture Overview

This document describes the system design of the Cash Application Foundry, a 5-agent AI pipeline that processes bank statements and accounts receivable data to automate cash application and reconciliation.

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER (Frontend)                        │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  React/Next.js UI (Vercel)                                       │  │
│  │  - Real-time pipeline visualization                             │  │
│  │  - SSE streaming updates from backend                           │  │
│  │  - Interactive workqueue approval/rejection                    │  │
│  │  - Transaction flag badges and mismatch details                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    HTTP POST /analyze (JSON)
                    SSE streaming response
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   API LAYER (Backend - FastAPI)                         │
│                      Railway Container                                  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  main.py - API Endpoints                                        │  │
│  │  • GET /health          - Service status                        │  │
│  │  • GET /demo-data       - Load demo samples                    │  │
│  │  • GET /samples         - List available datasets              │  │
│  │  • POST /analyze        - Main pipeline entry point            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Orchestrator (cash_app.py)                                     │  │
│  │  • Routes requests through 5-agent pipeline                    │  │
│  │  • Extracts/parses JSON from streaming responses               │  │
│  │  • Manages agent sequencing and error handling                │  │
│  │  • Emits SSE events for frontend                              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    Streaming SSE (Agent Output)
                                    │
└─────────────────────────────────────────────────────────────────────────┐
│                      AGENT PIPELINE LAYER                               │
│                                                                         │
│  Sequential execution: Agent N+1 waits for Agent N output               │
│                                                                         │
│  ┌─────────────────────┐      ┌──────────────────────┐               │
│  │ Agent 1: Bank       │  ──► │ Agent 2: AR Ledger   │               │
│  │ Statement Parser    │      │ Builder              │               │
│  │                     │      │                      │               │
│  │ Model: GPT-4o-mini │      │ Model: GPT-4o-mini  │               │
│  │ Input: Raw bank    │      │ Input: Open invoices│               │
│  │   statement JSON    │      │ Output: Invoice index│               │
│  │ Output: Normalized │      │   + aliases + holds  │               │
│  │   transactions +   │      │                      │               │
│  │   flags            │      │                      │               │
│  └─────────────────────┘      └──────────────────────┘               │
│         │                              │                              │
│         └──────────────────┬───────────┘                              │
│                            │                                          │
│                            ▼                                          │
│  ┌─────────────────────────────────────────┐                       │
│  │ Agent 3: Reconciliation Engine          │                       │
│  │                                         │                       │
│  │ Model: GPT-4o + Code Interpreter       │                       │
│  │ Input: Normalized txns + invoice index │                       │
│  │ Logic:                                  │                       │
│  │  1. Pre-checks (compliance, disputes)   │                       │
│  │  2. 8 matching strategies (exact → fuzzy)                      │
│  │  3. Python code execution for math     │                       │
│  │ Output: Matched + unmatched txns       │                       │
│  └─────────────────────────────────────────┘                       │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────┐                                      │
│  │ Agent 4: Mismatch        │                                      │
│  │ Reasoning (Exceptions)   │                                      │
│  │                          │                                      │
│  │ Model: GPT-4o            │                                      │
│  │ Input: Unmatched txns    │                                      │
│  │ Output: Reasoning + risk │                                      │
│  │   tier + SLA for each    │                                      │
│  └──────────────────────────┘                                      │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────┐                                      │
│  │ Agent 5: Cash Posting    │                                      │
│  │                          │                                      │
│  │ Model: GPT-4o            │                                      │
│  │ Input: All results       │                                      │
│  │ Output: GL entries +     │                                      │
│  │   workqueue items        │                                      │
│  └──────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    Aggregated Results
                                    │
└─────────────────────────────────────────────────────────────────────────┐
│                      EXTERNAL SERVICES (Azure)                         │
│                                                                         │
│  ┌───────────────────────────┐  ┌──────────────────────────────────┐  │
│  │ Azure AI Foundry          │  │ Azure Blob Storage               │  │
│  │ (OpenAI-compatible API)   │  │ • Run inputs (bank statement)   │  │
│  │                           │  │ • Agent outputs                 │  │
│  │ • GPT-4o-mini             │  │ • Final results                 │  │
│  │ • GPT-4o                  │  │ • Audit trail (immutable)       │  │
│  │ • GPT-5                   │  │                                 │  │
│  │                           │  │ Path: {run_id}/                 │  │
│  │ Authentication:           │  │  ├── bank_statement.json        │  │
│  │ • DefaultAzureCredential  │  │  ├── open_ar.json              │  │
│  │ • Service Principal       │  │  ├── results.json              │  │
│  │ • (no API keys in prod)   │  │  └── agent_events.json         │  │
│  └───────────────────────────┘  └──────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Azure Application Insights (Monitoring)                         │  │
│  │ • OpenTelemetry instrumentation                                │  │
│  │ • Agent execution traces                                       │  │
│  │ • Model routing decisions                                      │  │
│  │ • Error tracking and alerts                                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow Diagram

```
INPUT DATA
    │
    ├── Bank Statement JSON
    │   ├── Transactions (id, date, payer, amount, remittance)
    │   └── Metadata (statement_date, bank_account)
    │
    └── AR Ledger JSON
        ├── Open invoices (invoice_id, customer, amount, due_date)
        ├── Holds/disputes (compliance flags)
        └── Aliases (customer name variations)
    │
    ▼
┌─────────────────────────────────────────┐
│ AGENT 1: Bank Statement Parser          │
├─────────────────────────────────────────┤
│ Process:                                │
│  1. Normalize payer names               │
│  2. Parse remittance text (regex)       │
│  3. Detect flags (SWIFT truncation,     │
│     stale checks, duplicates, FX)       │
│                                         │
│ Output JSON:                            │
│ {                                       │
│   "transactions": [                     │
│     {                                   │
│       "id": "TXN-001",                  │
│       "date": "2025-06-01",            │
│       "payer_original": "...",         │
│       "payer_normalized": "...",       │
│       "amount": 50000.00,              │
│       "remittance": "INV-1001",        │
│       "flags": ["SWIFT_NAME_TRUNCATION│
│     }                                   │
│   ]                                     │
│ }                                       │
└─────────────────────────────────────────┘
    │
    ├─────────────────┬────────────────────────┐
    │                 │                        │
    ▼                 ▼                        │
┌──────────────────────────────┐              │
│ AGENT 2: AR Ledger Builder   │              │
├──────────────────────────────┤              │
│ Build lookup structures:      │              │
│  • Customer aliases           │              │
│  • Invoice aging buckets      │              │
│  • Legacy invoice refs        │              │
│  • Hold/dispute flags         │              │
│                               │              │
│ Output JSON:                  │              │
│ {                             │              │
│   "invoices": {...},          │              │
│   "aliases": {...},           │              │
│   "holds": [...],             │              │
│   "disputes": [...]           │              │
│ }                             │              │
└──────────────────────────────┘              │
    │                                         │
    └──────────────────────┬──────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────┐
        │ AGENT 3: Reconciliation Engine           │
        ├──────────────────────────────────────────┤
        │ Matching strategies (in order):          │
        │  1. Exact match (amount + reference)    │
        │  2. Invoice match (normalization)       │
        │  3. Amount match (name fuzzy)           │
        │  4. Bundle match (multi-invoice)        │
        │  5. Early pay discount logic            │
        │  6. Freight/damage deduction            │
        │  7. Credit memo netting                 │
        │  8. Fuzzy match (all remaining)         │
        │                                         │
        │ Pre-checks:                             │
        │  • OFAC screening hold                  │
        │  • Disputed invoice                     │
        │  • Stale check (>180 days)             │
        │  • Post-dated check                    │
        │                                         │
        │ Python Code Execution:                  │
        │  • Verify math (no mental arithmetic)   │
        │  • FX rate calculations                 │
        │  • Discount calculations                │
        │                                         │
        │ Output JSON:                            │
        │ {                                       │
        │   "matched": [{txn_id, invoice_id,     │
        │               matched_amount, method}],│
        │   "unmatched": [{txn_id, reason,      │
        │                 deduction_amount}],   │
        │   "exceptions": [...]                  │
        │ }                                       │
        └──────────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────┐
        │ AGENT 4: Mismatch Reasoning              │
        │ (Deep Business Logic)                    │
        ├──────────────────────────────────────────┤
        │ For each unmatched transaction:          │
        │  • Why is there a delta?                 │
        │  • Is it legitimate?                     │
        │  • Who should handle it?                 │
        │  • What's the risk tier?                 │
        │  • What's the SLA?                       │
        │                                         │
        │ Output JSON:                            │
        │ {                                       │
        │   "exceptions": [{                      │
        │     "txn_id": "TXN-007",                │
        │     "reason": "Unauthorized short pay", │
        │     "reasoning": "...",                 │
        │     "risk_tier": "MEDIUM",              │
        │     "sla_hours": 24,                    │
        │     "escalate_to": "deductions_team"    │
        │   }]                                    │
        │ }                                       │
        └──────────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────┐
        │ AGENT 5: Cash Posting                    │
        ├──────────────────────────────────────────┤
        │ Generate posting instructions:           │
        │  • GL account codes                      │
        │  • Invoice closure flags                 │
        │  • Workqueue assignments                 │
        │  • Priority/urgency                      │
        │  • Compliance actions                    │
        │                                         │
        │ Output JSON:                            │
        │ {                                       │
        │   "workqueue": [{                       │
        │     "action": "post_and_close",         │
        │     "gl_account": "1010",               │
        │     "reference": "TXN-001",             │
        │     "amount": 50000.00,                 │
        │     "priority": "HIGH",                 │
        │     "assign_to": "ar_analyst_1"         │
        │   }]                                    │
        │ }                                       │
        └──────────────────────────────────────────┘
                           │
                           ▼
                    FINAL RESULTS
                    • Matched transactions
                    • Exceptions with reasoning
                    • Workqueue items
                    • Audit trail (Blob Storage)
```

---

## 3. Agent Pipeline Details

### Agent 1: Bank Statement Parser (GPT-4o-mini)
**Purpose:** Normalize and enrich raw bank statement data

**Input:** Raw bank statement JSON
- Transaction list with payer name, amount, date, remittance text

**Process:**
1. Normalize payer names (trim, uppercase, remove special chars)
2. Parse remittance text (regex patterns for invoice/PO references)
3. Detect and flag edge cases:
   - SWIFT 35-char truncation
   - Foreign currency indicators
   - Stale checks (>180 days old)
   - Possible duplicates (same payer, amount within 2 hours)
   - Post-dated checks
   - NSF returns

**Output:** Structured transaction list with flags
```json
{
  "transactions": [
    {
      "id": "TXN-001",
      "date": "2025-06-01",
      "payer_original": "GREENFIELD TECH SOLUT",
      "payer_normalized": "GREENFIELD TECHNOLOGY SOLUTIONS",
      "amount": 29250.00,
      "remittance": "INV-1001",
      "flags": ["SWIFT_NAME_TRUNCATION", "POSSIBLE_SHORT_PAY"]
    }
  ]
}
```

---

### Agent 2: AR Ledger Builder (GPT-4o-mini)
**Purpose:** Build lookup structures from open AR ledger

**Input:** Open invoices list
- Invoice ID, customer name, amount, due date, status
- Any holds, disputes, or special flags

**Process:**
1. Build customer master index
   - Aliases and name variations (DBA, trade names, post-M&A names)
   - Parent/subsidiary relationships
   - Factoring agent information
2. Build invoice index
   - Legacy ERP reference numbers
   - Aging buckets
3. Capture holds and disputes
   - Compliance holds (OFAC, sanctions)
   - Legal holds
   - Disputed invoices (customer contests)
   - Credit memo balances

**Output:** Lookup structures
```json
{
  "invoices": {
    "INV-1001": {"customer_id": "CUST-001", "amount": 29500.00, ...}
  },
  "customer_aliases": {
    "GREENFIELD TECHNOLOGY SOLUTIONS": ["GREENFIELD TECH", "GREENFIELD TECH SOLUT"]
  },
  "holds": {
    "INV-1002": {"reason": "OFAC_SCREENING", "escalate_to": "compliance"}
  },
  "disputes": [...]
}
```

---

### Agent 3: Reconciliation Engine (GPT-4o + Code Interpreter)
**Purpose:** Match transactions to invoices using 8 strategies + pre-checks

**Input:**
- Normalized transactions from Agent 1
- Invoice index + aliases from Agent 2

**Pre-checks (blocking):**
1. OFAC/sanctions hold → immediately hold, don't process further
2. Disputed invoice → flag for legal review
3. Stale check → separate queue (may be unclaimed property)
4. Post-dated check → hold until clear date

**Matching Strategies (in order, stop at first match):**
1. **Exact Match:** Amount + invoice reference
2. **Invoice Match:** Customer normalization + reference
3. **Amount Match:** Fuzzy name match + exact amount
4. **Bundle Match:** Multiple invoices summing to amount
5. **Early Pay Discount:** Amount = invoice × (1 - discount %)
6. **Freight/Damage Deduction:** Amount = invoice - known deduction
7. **Credit Memo Netting:** Amount = invoice - credit balance
8. **Fuzzy Match:** Best-guess on name + amount proximity

**Code Execution:**
- No mental arithmetic—Python verifies every calculation
- FX conversion rates (EUR → USD via API or config)
- Discount application (e.g., 2% 10 net 30 terms)

**Output:** Matched + unmatched transactions
```json
{
  "matched": [
    {"txn_id": "TXN-001", "invoice_id": "INV-1001", "matched_amount": 29250.00, "method": "FREIGHT_DEDUCTION", "reasoning": "..."}
  ],
  "unmatched": [
    {"txn_id": "TXN-007", "amount": 5000.00, "reason": "NO_CUSTOMER_MATCH"}
  ]
}
```

---

### Agent 4: Mismatch Reasoning (GPT-4o)
**Purpose:** Deep business logic for exceptions

**Input:** Unmatched transactions + context
- Why didn't it match?
- What's the delta?
- Is it legitimate?

**Process:**
For each unmatched transaction, determine:
1. **Root cause:** Freight deduction? Damaged goods claim? Unauthorized short pay? Credit memo? Duplicate?
2. **Business judgment:** Is this acceptable? Does it need escalation?
3. **Routing:** Which team handles this?
   - Deductions team (freight, damage claims)
   - Legal team (disputes, compliance issues)
   - Collections team (short pays, overages)
4. **Risk tier:** LOW (common, auto-approvable) / MEDIUM (needs review) / HIGH (escalate immediately)
5. **SLA:** How quickly must this be resolved?

**Output:** Reasoning + routing
```json
{
  "exceptions": [
    {
      "txn_id": "TXN-007",
      "amount_delta": 250.00,
      "reason": "UNAUTHORIZED_SHORT_PAY",
      "reasoning": "Customer remitted $29,250 for $29,500 invoice. No deduction claim. This is a short pay and may indicate cash flow problems or billing dispute.",
      "risk_tier": "MEDIUM",
      "sla_hours": 24,
      "escalate_to": "collections_team",
      "suggested_action": "Call customer to confirm short pay reason"
    }
  ]
}
```

---

### Agent 5: Cash Posting (GPT-4o)
**Purpose:** Generate ERP posting instructions

**Input:** Full results from Agents 1–4

**Process:**
1. Determine GL accounts
   - Cash received → 1010 (AR Clearing)
   - Deduction taken → 5610 (Freight Allowance) / 5620 (Damage Allowance)
   - Compliance hold → 9999 (Suspense - pending review)
2. Determine invoice closure
   - Fully matched → mark as closed
   - Partially matched → reduce outstanding balance
   - Unmatched → hold for review
3. Create workqueue items
   - Assign to specific analyst based on priority/expertise
   - Set deadline based on SLA
4. Compliance actions
   - Document OFAC holds
   - Flag for audit trail

**Output:** Workqueue + GL entries
```json
{
  "workqueue": [
    {
      "id": "WQ-001",
      "action": "post_and_close",
      "txn_id": "TXN-001",
      "invoice_id": "INV-1001",
      "gl_account": "1010",
      "amount": 29250.00,
      "freight_deduction": 250.00,
      "deduction_gl_account": "5610",
      "priority": "HIGH",
      "assign_to": "analyst_1",
      "due_date": "2025-06-02",
      "notes": "Customer took unauthorized $250 freight deduction. Follow up within 24h."
    }
  ]
}
```

---

## 4. Technology Stack

### Frontend
- **Framework:** React 18 + Next.js 14
- **Styling:** Tailwind CSS + inline styles
- **Streaming:** Server-Sent Events (SSE) / EventSource API
- **Deployment:** Vercel
- **Features:**
  - Real-time pipeline visualization with status badges
  - Transaction detail view with matched/unmatched breakdown
  - Workqueue approval/rejection with override notes
  - Flag categorization (Remittance, Timing, FX, Identity, Entity, Amount, Compliance)

### Backend
- **Framework:** FastAPI (Python 3.11)
- **AI Models:** Azure OpenAI (GPT-4o-mini, GPT-4o, GPT-5)
- **Authentication:** Azure DefaultAzureCredential (Service Principal)
- **Streaming:** asyncio.Queue + SSE
- **Deployment:** Railway (Docker)

### Azure Services
1. **Azure AI Foundry** (OpenAI-compatible API)
   - Model routing per agent
   - Token budgets per agent
   - Streaming token output

2. **Azure Blob Storage**
   - Immutable audit trail
   - Per-run directory: `{run_id}/bank_statement.json`, `open_ar.json`, `results.json`, `agent_events.json`
   - Retention: 7-year compliance requirement

3. **Azure Application Insights**
   - OpenTelemetry instrumentation
   - Agent execution traces
   - Error tracking

4. **Azure Key Vault** (production)
   - Centralized secrets management
   - API key rotation

---

## 5. Data Models

### Transaction (Bank Statement)
```json
{
  "id": "TXN-001",
  "date": "2025-06-01",
  "payer_original": "GREENFIELD TECH SOLUT",
  "payer_normalized": "GREENFIELD TECHNOLOGY SOLUTIONS",
  "amount": 29250.00,
  "currency": "USD",
  "remittance": "INV-1001",
  "flags": ["SWIFT_NAME_TRUNCATION"],
  "matched": true,
  "matched_invoice_id": "INV-1001"
}
```

### Invoice (AR Ledger)
```json
{
  "id": "INV-1001",
  "customer_id": "CUST-001",
  "customer_name": "Greenfield Technology Solutions LLC",
  "amount": 29500.00,
  "due_date": "2025-07-01",
  "status": "open",
  "hold_reason": null,
  "dispute": false
}
```

### Match Result
```json
{
  "txn_id": "TXN-001",
  "invoice_id": "INV-1001",
  "matched_amount": 29250.00,
  "method": "FREIGHT_DEDUCTION",
  "delta": 250.00,
  "delta_reason": "Unauthorized short pay"
}
```

### Workqueue Item
```json
{
  "id": "WQ-001",
  "action": "post_and_close",
  "txn_id": "TXN-001",
  "invoice_id": "INV-1001",
  "gl_account": "1010",
  "amount": 29250.00,
  "priority": "HIGH",
  "assign_to": "analyst_1",
  "due_date": "2025-06-02",
  "status": "pending"
}
```

---

## 6. Error Handling & Resilience

### Retry Logic
- Agent streaming failures → retry up to 3 times with exponential backoff
- Partial failures → log to audit trail, continue pipeline if possible
- JSON parsing failures → extract first valid JSON or fallback to string response

### Non-Critical Services
- **Azure Blob Storage:** If unavailable, app continues without audit trail persistence
- **Application Insights:** If unavailable, app continues without telemetry
- **These services are "nice to have," not blocking**

### Keepalive Mechanism
- 10-second heartbeat sent over SSE to prevent Railway proxy timeout during gaps between agents
- Prevents connection drops on long-running executions (2-4 minutes in Azure mode)

---

## 7. Security Model

### Authentication & Authorization
- **API:** No authentication in MVP (demo mode)
- **Production:** Microsoft Entra ID (SSO) + role-based access control
- **Service Principal:** For Azure service authentication (no API keys in production code)

### Data Protection
- **At rest:** AES-256 encryption in Azure Blob Storage
- **In transit:** TLS 1.3 for all connections
- **No data leaves Azure:** All inference happens in-tenant
- **Audit trail:** Immutable 7-year retention in Blob Storage

### Compliance Controls
- **OFAC screening:** Happens before any AI processing
- **Segregation of duties:** Agent generates postings, human approves
- **Approval threshold:** >$10K requires management sign-off

---

## 8. Monitoring & Observability

### Azure Application Insights
- **Agent latency:** Time per agent (bank parser, AR ledger, reconciliation, etc.)
- **Model routing:** Which model was assigned to each agent
- **Token usage:** Input + output tokens per agent
- **Error rates:** Parsing failures, API timeouts
- **End-to-end latency:** Total pipeline duration

### Blob Storage Audit Trail
- Per-run directory structure:
  ```
  {run_id}/
  ├── bank_statement.json      (input)
  ├── open_ar.json             (input)
  ├── results.json             (all 5 agents' outputs)
  └── agent_events.json        (timing + model info)
  ```
- Queryable for "why did agent X make decision Y?"

### Logging
- Agent start/complete events → Insights
- SSE error events → sent to frontend, logged to backend

---

## 9. Scaling & Production Roadmap

### Current (MVP)
- Single Railway container
- Synchronous pipeline (one analysis at a time)
- Demo mode (fixtures) + Live Azure mode
- ~30–60s in demo, ~2–4m in Azure

### Phase 2 (3 months)
- Azure Service Bus async queue
- 1–10 concurrent pipeline workers
- PostgreSQL audit trail (queryable)
- PDF ingestion via Document Intelligence
- 500 txns/day target

### Phase 3 (12 months)
- 1–20 auto-scaling workers on KEDA
- ERP connectors (SAP, Oracle, NetSuite)
- Fine-tuned models on company-specific data
- 1M+ txns/month

---

## 10. Entity Relationships

```
┌──────────────────────┐
│      Run (Batch)     │
├──────────────────────┤
│ id (UUID)            │
│ company_id           │
│ submitted_by         │
│ status               │
│ blob_path            │
└──────────────────────┘
         │
         ├─ n ─────────────────────┐
         │                         │
         ▼                         ▼
┌──────────────────────┐  ┌─────────────────────┐
│   BankStatement      │  │   AgentEvent        │
├──────────────────────┤  ├─────────────────────┤
│ run_id (FK)          │  │ run_id (FK)         │
│ txn_id               │  │ agent               │
│ payer               │  │ model               │
│ amount              │  │ tokens_in/out       │
│ remittance          │  │ payload (JSONB)     │
│ flags[]             │  │ timestamp           │
└──────────────────────┘  └─────────────────────┘
         │                         ▲
         │                         │
         ├─ n ─────────────────────┤
         │                         │
         ▼                         │
┌──────────────────────┐           │
│   MatchResult        │───────────┘
├──────────────────────┤
│ run_id (FK)          │
│ txn_id (FK)          │
│ invoice_id           │
│ matched_amount       │
│ method               │
│ reasoning            │
└──────────────────────┘
         │
         ├─ n ─────────────────────┐
         │                         │
         ▼                         ▼
┌──────────────────────┐  ┌─────────────────────┐
│   WorkqueueItem      │  │   ComplianceAction  │
├──────────────────────┤  ├─────────────────────┤
│ run_id (FK)          │  │ run_id (FK)         │
│ action               │  │ txn_id              │
│ gl_account           │  │ action_type         │
│ priority             │  │ urgency             │
│ assign_to            │  │ reason              │
│ status               │  └─────────────────────┘
│ due_date             │
└──────────────────────┘
```

---

## 11. API Contracts

### POST /analyze
**Request:**
```json
{
  "bank_data": {
    "statement_date": "2025-06-01",
    "transactions": [...]
  },
  "ar_data": {
    "invoices": [...],
    "holds": [...]
  }
}
```

**Response (SSE):**
```
data: {"event": "agent_start", "agent": "BankStatementIntelligenceAgent", "model": "gpt-4o-mini"}
data: {"event": "token_delta", "agent": "...", "delta": "The..."}
data: {"event": "token_delta", "agent": "...", "delta": " bank..."}
...
data: {"event": "agent_complete", "agent": "BankStatementIntelligenceAgent", "output": {...}}
data: {"event": "agent_start", "agent": "ARLedgerAgent", ...}
...
data: {"event": "swarm_complete", "results": {...}}
data: [DONE]
```

---

## 12. Edge Cases Handled

| Category | Count | Examples |
|----------|-------|----------|
| **Amount Mismatches** | 10 | Early-pay discount, freight deduction, damage claim, short pay, credit memo netting, wire fee, overpayment |
| **Identity Issues** | 4 | SWIFT truncation, DBA name, post-M&A name, fuzzy matching |
| **Multi-Entity** | 4 | Parent pays subsidiary, factoring agent, intercompany netting, wrong legal entity |
| **Timing** | 6 | Duplicate, installment, NSF return, post-dated check, stale check (>180d), prepayment |
| **Remittance** | 5 | No remittance, vague reference, PO only, legacy ERP ref, EDI 820 pending |
| **FX & Intl** | 2 | EUR SWIFT with FX, FX rate verification |
| **Compliance** | 3 | OFAC hold, disputed invoice, legal hold |

**Total: 35 edge cases**

---

## Summary

The Cash Application Foundry is a **5-agent AI pipeline** running on Azure AI Foundry and deployed to Railway + Vercel. Each agent is a specialist:

1. **Bank Statement Parser** (GPT-4o-mini) → normalize transactions + detect flags
2. **AR Ledger Builder** (GPT-4o-mini) → build lookup structures
3. **Reconciliation Engine** (GPT-4o + Code Interpreter) → 8 matching strategies + pre-checks
4. **Mismatch Reasoning** (GPT-4o) → business logic for exceptions
5. **Cash Posting** (GPT-4o) → GL entries + workqueue

The pipeline is **sequential** (Agent N waits for Agent N-1), **auditable** (Blob Storage), **observable** (Application Insights), and **secure** (no data leaves tenant, Service Principal auth). Real-time SSE streaming shows progress to the frontend.

This design processes 35 edge cases that a human analyst would spend 8-10 hours per day on, in under 60 seconds with full reasoning transparency.
