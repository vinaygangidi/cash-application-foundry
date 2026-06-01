# Cash Application Foundry

**5-agent AI swarm that reconciles bank payments to open invoices — built natively on Azure AI Foundry.**

> Microsoft Build AI Hackathon 2026 · Theme 05 — Agent Swarms · ₹6,00,000 Prize Pool

**Live Demo:** [cash-application-foundry.vercel.app](https://cash-application-foundry.vercel.app) · **Architecture Docs:** [vinaygangidi.github.io/cash-application-foundry](https://vinaygangidi.github.io/cash-application-foundry)

---

## The Problem

Accounts Receivable (AR) cash application is one of the most manual, error-prone, and costly processes in enterprise finance. Every day, companies receive hundreds of bank deposits that must be manually matched to open invoices — a process that hasn't fundamentally changed in 30 years.

**What AR teams face daily:**
- Analysts spend **2–4 hours per batch** manually matching bank deposits to invoices in ERP systems
- Bank payer names are **truncated, abbreviated, or changed** due to SWIFT 35-char limits, DBA names, and post-acquisition renames
- Customers **pay wrong amounts** — early-pay discounts taken late, freight deductions, short pays, damage claims
- Payments arrive from **wrong entities** — parent companies paying for subsidiaries, factoring agents, intercompany transfers
- **OFAC/sanctions screening** must be done manually — a missed flag is a compliance incident
- Exception workqueues sit for **3–5 days** without SLA assignment, bloating DSO metrics

**Business impact:**
- 1 DSO day = ~$1.4M tied up in working capital (for a $500M revenue company)
- 3–8% manual error rate on exception transactions
- AR analyst time on cash application = ~40% of total AR headcount cost
- $2.3T in enterprise AR processed annually in the US alone

**Our 5-agent swarm processes the same 35-transaction batch in under 60 seconds.**

---

## Solution Architecture

```
Bank Statement JSON  ──►  Agent 1: BankStatementIntelligenceAgent   (GPT-4o-mini)
                              Normalizes payer names, detects 13 anomaly flag types
Open AR JSON        ──►  Agent 2: ARLedgerAgent                     (GPT-4o-mini)
                              Builds customer index, alias registry, legacy invoice map
                              │
                              ▼
                    Agent 3: ReconciliationAgent   (GPT-4o + CodeInterpreter)
                              8-tier matching + 8 pre-checks, exact arithmetic in Python
                              │
                              ▼
                    Agent 4: MismatchReasoningAgent  (GPT-5 / o3-mini)
                              Deep business reasoning per exception — 7 category groups, risk tiers
                              │
                              ▼
                    Agent 5: CashPostingAgent  (GPT-4o)
                              GL journal entries, workqueue by team + SLA, compliance actions
```

Each agent produces structured JSON. Downstream agents receive only the fields they need — no full context re-passing, no context bloat.

Every token each agent generates is streamed in real time via **Server-Sent Events (SSE)** — the UI lights up as agents think.

---

## Multi-Model Strategy — Right Model for Each Task

The defining architectural decision: **we don't use one model for everything.** Each agent is routed to the Azure OpenAI model whose capabilities match the cognitive complexity of its task.

| Agent | Model | Why This Model | Cost |
|---|---|---|---|
| BankStatementIntelligenceAgent | **GPT-4o-mini** | Structured text extraction — no deep reasoning needed. 60% cheaper, 3x faster than GPT-4o. | Low |
| ARLedgerAgent | **GPT-4o-mini** | Building a lookup index from structured JSON — deterministic, no nuance required. | Low |
| ReconciliationAgent | **GPT-4o** | Needs exact arithmetic via Python (no hallucination on multi-invoice sums). Complex 8-tier matching logic. | Medium |
| MismatchReasoningAgent | **GPT-5 / o3-mini** | The hardest task: classify 24 exceptions, assess risk tier, reason about contract terms and deduction legitimacy. A reasoning model is worth the cost here. | High (justified) |
| CashPostingAgent | **GPT-4o** | Complex output generation: 12 posting rules, GL account assignments, SLA-based workqueue routing across 4 teams. | Medium |

> Running all 5 agents on GPT-4o would cost ~4x more per batch. Our routing saves ~60% on the two extraction agents, which run on every batch. The GPT-5 spend on MismatchReasoningAgent is targeted — it only runs on the 20–30% of transactions with exceptions, and the reasoning quality directly prevents costly ERP errors.

---

## 35 Edge Cases Across 7 Categories

Every exception type that occurs in real-world enterprise AR — all handled end-to-end.

| Category | Cases Handled |
|---|---|
| **Amount Mismatches** (10) | Exact match, multi-invoice bundle, early-pay discount, unauthorized short pay, freight deduction, damage claim, overpayment → credit, credit memo net, wire fee write-off (≤$25 auto), late discount |
| **Identity & Name** (4) | SWIFT 35-char name truncation, DBA/trade name, post-M&A name change, fuzzy alias matching (≥75% similarity) |
| **Multi-Entity** (4) | Parent entity paying for subsidiary, third-party factoring agent, intercompany AP/AR netting, wrong legal entity redirect |
| **Timing & Sequencing** (6) | Duplicate payment (30-day window), installment/partial, NSF return + reversal, post-dated check hold, stale check (>180 days), prepayment to unearned revenue |
| **Remittance & Reference** (5) | No remittance → FIFO, vague remittance → amount match, PO number reference, legacy ERP invoice number cross-ref, EDI 820 pending hold |
| **FX & International** (2) | EUR SWIFT payment + FX conversion, FX rate verification via CodeInterpreter Python |
| **Compliance & Legal** (3) | OFAC/sanctions screening hold (same-day escalation), disputed invoice payment block (do-not-apply), legal hold escalation with SLA routing |

---

## Agent-by-Agent Design

### Agent 1 — BankStatementIntelligenceAgent `GPT-4o-mini`

**Input:** Raw bank statement JSON — transactions with `payer_raw`, `remittance_text`, `amount`, `payment_type`, `currency`, `check_date`

**Output:** Normalized payment records with 13 anomaly flags: `MISSING_REMITTANCE`, `POSSIBLE_DUPLICATE`, `NSF_RETURN`, `FX_PAYMENT`, `SWIFT_NAME_TRUNCATION`, `POST_DATED_CHECK`, `STALE_CHECK`, `THIRD_PARTY_PAYER`, `PARENT_ENTITY_PAYMENT`, `EDI_REMITTANCE_PENDING`, `PREPAYMENT`, `INTERCOMPANY_NET`, `COMPLIANCE_HOLD`

**Why separate:** Isolates all noisy text normalization before any invoice matching begins. Mini model handles this cheaply — no business logic reasoning needed.

### Agent 2 — ARLedgerAgent `GPT-4o-mini`

**Input:** Open AR JSON — invoices, credit memos, `payer_alias_registry`, `parent_child_hierarchy`, `intercompany_netting`, `compliance_config`

**Output:** `customer_index` keyed by normalized name, invoice lookup map, `legacy_invoice_map`, `do_not_auto_apply` list, `compliance_flags` dict, aging buckets, discount windows

**Why separate:** Builds all lookup structures once so ReconciliationAgent runs pure matching. AR structure changes don't touch matching logic.

### Agent 3 — ReconciliationAgent `GPT-4o + CodeInterpreter`

**Input:** Normalized payments (Agent 1) + AR customer index (Agent 2)

**8 Pre-checks (A–H) before matching:** COMPLIANCE_HOLD → WRONG_ENTITY → DISPUTED_INVOICE → POST_DATED_CHECK → STALE_CHECK → INTERCOMPANY_NET → PREPAYMENT → EDI_PENDING

**8-Tier Matching Hierarchy:**
1. EXACT — amount == invoice AND invoice_id in remittance
2. LEGACY_REF — parsed references contain a `legacy_invoice_id`
3. ALIAS_MATCH — payer name matches customer alias table (fuzzy ≥75%)
4. REMITTANCE_REF — any reference matches invoice_id or PO (amount within $25)
5. DISCOUNT_EXACT — amount == invoice × (1 − discount%) AND within deadline
6. MULTI_INVOICE — amount == sum of 2–4 invoices (CodeInterpreter verifies)
7. CREDIT_NET — amount == invoice − existing credit memo
8. FIFO — customer identified → apply to oldest open invoice(s)

**Output:** Match record per transaction with `match_tier`, `confidence_pct`, `matched_invoices`, `delta`, `pre_check_triggered`, `exception` flag

**Why GPT-4o + Code:** Writes real Python to verify `sum([8750+6500+14000]) == 29250`, `0.98 × 30000 == 29400`, `20000 EUR × 1.125 == 22500 USD`. Exact arithmetic, no hallucination.

### Agent 4 — MismatchReasoningAgent `GPT-5 / o3-mini`

**Input:** Exception transactions from Agent 3 (those with `exception: true`)

**Output per exception:** `exception_type`, `exception_category_group` (7 categories), `reasoning` text, `risk_tier` (CRITICAL/HIGH/MEDIUM/LOW), `suggested_gl_code`, `escalation_contact`, `sla_hours`, `recommended_action`

**Risk tiers:** CRITICAL (same-day) · HIGH (24h) · MEDIUM (3 days) · LOW (5 days)

**Why o3-mini:** Requires genuine business judgment — contract terms, deduction legitimacy, compliance risk, customer relationship context. Chain-of-thought reasoning dramatically outperforms standard models.

### Agent 5 — CashPostingAgent `GPT-4o`

**Input:** All 35 reconciliation matches + all exception analyses from Agents 3 and 4

**Output:** GL posting instructions (debit/credit/account per transaction), workqueue items with team routing and SLA, `cash_application_summary` with auto-posted/held/deduction breakdowns, executive summary

**Posting rules include:** Auto write-off ≤$25 → GL 6020, COMPLIANCE_HOLD → freeze + Compliance Officer 4h SLA, PREPAYMENT → GL 2050 Unearned Revenue, INTERCOMPANY_NET → bilateral DR/CR journal

**Why separate:** Isolates "think" (Agents 1–4) from "act" (Agent 5). ERP write-back target (SAP vs Oracle vs NetSuite) can be swapped without touching reasoning logic.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Inference | `AsyncAzureOpenAI` from `openai` package — chat completions with streaming |
| Azure AI | Azure AI Foundry (endpoint + model deployments) |
| Models | GPT-4o-mini · GPT-4o · GPT-5 (o3-mini) via Azure OpenAI |
| Observability | **Azure Application Insights** — auto-instrumented via OpenTelemetry |
| Run Storage | **Azure Blob Storage** (`cash-app-runs/`) — inputs + results per `run_id` |
| Auth (production) | `DefaultAzureCredential` + Service Principal with Managed Identity |
| Backend | FastAPI + Server-Sent Events streaming |
| SSE Reliability | `asyncio.Queue` keepalive heartbeats every 10s (prevents Railway proxy timeout) |
| Frontend | Next.js 14 — real-time agent pipeline UI with approve/reject workqueue |
| Backend hosting | Railway (Docker) |
| Frontend hosting | Vercel |

---

## Setup

### Backend — Demo Mode (no Azure credentials needed)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Demo mode — streams pre-baked fixture outputs with realistic token animation
echo "USE_FIXTURES=true" > .env

uvicorn main:app --port 8001 --reload
```

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8001 npm run dev
```

Open `http://localhost:3000`, click **Load Demo Data**, then **Run Cash Application**.

### Backend — Live Azure Mode

```bash
# backend/.env
AZURE_AI_ENDPOINT=https://<your-resource>.services.ai.azure.com
MODEL_BANK_AGENT=gpt-4o-mini
MODEL_AR_AGENT=gpt-4o-mini
MODEL_RECON_AGENT=gpt-4o
MODEL_REASONING_AGENT=gpt-5
MODEL_POSTING_AGENT=gpt-4o

# Optional: Azure Blob Storage (saves run inputs + results per run_id)
AZURE_STORAGE_ACCOUNT_URL=https://<your-storage>.blob.core.windows.net/

# Optional: Application Insights (auto-instruments FastAPI)
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...

USE_FIXTURES=false

# Auth: API key OR Service Principal
AZURE_API_KEY=<your-key>               # option A: API key
# OR
AZURE_CLIENT_ID=<sp-client-id>         # option B: Service Principal
AZURE_CLIENT_SECRET=<sp-secret>
AZURE_TENANT_ID=<tenant-id>
```

### Health Check

```bash
curl http://localhost:8001/health
# {"status":"ok","azure_blob_storage":true,"azure_app_insights":true,"use_fixtures":"false"}
```

---

## Deployment

### Backend → Railway

1. Connect GitHub repo in Railway, set root to `/backend`
2. Railway auto-detects the `Dockerfile`
3. Add environment variables from `backend/.env` (for live mode, add Service Principal vars)
4. Railway URL auto-configures via `railway up`

### Frontend → Vercel

1. Connect GitHub repo in Vercel, set root to `/frontend`
2. Add env var: `NEXT_PUBLIC_API_URL=https://your-railway-app.up.railway.app`
3. Push to `main` — Vercel auto-deploys

---

## MVP vs Production Architecture

Every MVP decision was made to maximize demo reliability and hackathon speed — each has a clear production upgrade path.

| Dimension | MVP (Today) | Production Target | Azure Service |
|---|---|---|---|
| Data Input | JSON fixture files or API payload | PDF bank statements + ERP AR export (CSV/XML) | **Azure Document Intelligence** (Form Recognizer) |
| Document Storage | Azure Blob Storage per run_id | Immutable archive with 7-year SOX retention | **Azure Blob Storage** WORM + lifecycle policy |
| Job Processing | Synchronous HTTP — one run at a time | Async queue — 100+ batches/hour | **Azure Service Bus** + **Azure Container Apps** workers |
| Persistence | Ephemeral — results lost on refresh | Full run history with replay and export | **Azure PostgreSQL Flexible Server** |
| Authentication | No auth | Entra ID SSO with RBAC (Analyst/Manager/Compliance) | **Microsoft Entra ID** + MSAL |
| Secrets | `.env` file | Centralized, auto-rotating, no keys in code | **Azure Key Vault** with Managed Identity |
| Compute | Single Railway container | Auto-scale 1–20 replicas on queue depth | **Azure Container Apps** with KEDA |
| ERP Integration | UI display only | Auto-post GL entries to SAP / Oracle / NetSuite | **Azure Logic Apps** + **Azure API Management** |
| Multi-Tenancy | Single company | Multiple companies with row-level security | **Azure PostgreSQL** RLS + **Entra ID** tenant isolation |

---

## Real-time PDF Ingestion Pipeline (Production)

Production cash application starts with PDF bank statements — not JSON files.

```
Bank Statement PDF          AR Ledger CSV/XML           EDI 820 Remittance
(uploaded via portal        (scheduled pull from         (received via Azure
  or FTP/SFTP from bank)     SAP / Oracle via            B2B Integration)
                             Azure Data Factory)
        │                         │                           │
        └──────────────┬──────────┘                           │
                       ▼                                      │
        ┌─────────────────────────────────┐                   │
        │ Azure Document Intelligence      │                   │
        │ Form Recognizer — Custom Model   │                   │
        │ PDF → structured JSON            │                   │
        │ 99.2% field accuracy             │                   │
        └──────────────┬──────────────────┘                   │
                       │         Azure Blob Storage            │
                       │         raw/{company}/{year}/         │
                       │         {month}/{run_id}/             │
                       │         WORM · 7-year retention       │
                       ▼                                      ▼
        ┌─────────────────────────────────────────────────────┐
        │ Azure Service Bus — Processing Queue                 │
        │ Message: run_id, company_id, blob_path, priority     │
        │ Dead-letter queue on 3 failures → ops alert          │
        │ KEDA autoscale: queue depth > 10 → scale out         │
        └──────────────────────────┬──────────────────────────┘
                                   ▼
                    ⚡ 5-Agent AI Swarm (unchanged)
                                   ▼
              PostgreSQL  ·  ERP Post  ·  Notifications  ·  Compliance
```

---

## Audit Trail Design

Enterprise finance requires complete, immutable records of every cash application decision. SOX Section 404, ASC 606, and internal audit requirements mandate traceability from bank deposit to GL entry.

**Database schema (Azure PostgreSQL):**

```sql
CREATE TABLE runs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    UUID NOT NULL,          -- tenant isolation
  submitted_by  TEXT NOT NULL,          -- Entra ID user UPN
  submitted_at  TIMESTAMPTZ DEFAULT now(),
  status        TEXT,                   -- pending|running|complete|failed
  blob_path_bank TEXT,                  -- Azure Blob path to original PDF
  blob_path_ar   TEXT,
  result_json   JSONB,                  -- full swarm output
  completed_at  TIMESTAMPTZ
);

CREATE TABLE agent_events (
  id         BIGSERIAL PRIMARY KEY,
  run_id     UUID REFERENCES runs(id),
  ts         TIMESTAMPTZ DEFAULT now(),
  agent      TEXT,                      -- agent name
  model      TEXT,                      -- actual model used
  event_type TEXT,                      -- start|complete|error|tool_call
  tokens_in  INT,
  tokens_out INT,
  payload    JSONB                      -- full agent input/output
);

CREATE TABLE work_queue (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          UUID REFERENCES runs(id),
  txn_id          TEXT,
  risk_tier       TEXT,
  action_required TEXT,
  amount          NUMERIC(14,2),
  team            TEXT,
  status          TEXT DEFAULT 'pending',  -- pending|approved|rejected
  actioned_by     TEXT,                    -- Entra ID user who approved/rejected
  actioned_at     TIMESTAMPTZ,
  override_note   TEXT                     -- why analyst overrode AI recommendation
);

CREATE TABLE gl_postings (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id       UUID REFERENCES runs(id),
  txn_id       TEXT,
  gl_account   TEXT,
  debit        NUMERIC(14,2),
  credit       NUMERIC(14,2),
  description  TEXT,
  erp_ref      TEXT,                     -- ERP transaction ID after posting
  posted_at    TIMESTAMPTZ,
  posted_by    TEXT                      -- 'AI_AUTO' or analyst UPN
);
```

**What gets logged:** Every agent's exact input and output · Model used + token consumption per agent · Every AI recommendation · Every human override with analyst UPN + justification note · GL entries with ERP transaction reference · Original source document Blob paths

**Immutability controls:** `agent_events` is append-only (no UPDATE/DELETE) · Blob WORM policy on raw PDFs · 7-year retention (SOX / ASC 606) · Row-level security by `company_id` (multi-tenant)

---

## Security Architecture

| Layer | Control |
|---|---|
| **Authentication** | Microsoft Entra ID SSO · MFA enforced · Managed Identity for all service-to-service calls · No API keys or client secrets stored in code |
| **RBAC Roles** | `AR_VIEWER` (read only) · `AR_ANALYST` (approve/reject + run batches) · `AR_MANAGER` (override AI + export GL) · `COMPLIANCE_OFFICER` (OFAC holds + legal escalations) · `ADMIN` (tenant config) |
| **Data at Rest** | AES-256 on Azure Storage + PostgreSQL TDE · Customer-managed keys via Azure Key Vault HSM for regulated industries |
| **Data in Transit** | TLS 1.3 enforced · Azure Front Door + WAF in front of Next.js UI · Private Endpoints for all backend services (no public internet) |
| **LLM Data Privacy** | Azure OpenAI processes data within your Azure tenant — data does NOT leave your subscription. Model is not retrained on your financial data. |
| **OFAC Screening** | Every payer name screened before any LLM matching. Positive match → COMPLIANCE_HOLD, zero processing, immediate escalation. No false negative tolerance. |
| **Segregation of Duties** | The agent that generates a GL posting cannot approve it. Human approval required for transactions >$10,000. CRITICAL items require manager-level role. |
| **SOX Controls** | All AI decisions logged with full evidence chain. No GL posting without a `run_id` traceable to original source document. |
| **Network** | All Azure resources in a dedicated VNet · WAF + DDoS Protection Standard · Microsoft Defender for Cloud · Alert on failed auth, COMPLIANCE_HOLD spikes, agent failure rate >5% |
| **Secrets** | Zero secrets in code in production. All credentials in Azure Key Vault, accessed via Managed Identity. 90-day auto-rotation policy. |

---

## Scale Roadmap

### Phase 1 — Now (Hackathon MVP)
- 1 company · 35 txns/batch · <60 sec fixture / ~4 min live Azure
- 5 AI agents end-to-end · 35 edge cases · SSE streaming UI · Azure Blob + App Insights

### Phase 2 — 3 Months (Production Beta)
- 3 pilot companies · 500 txns/day · async queue processing
- Add: Azure Document Intelligence PDF ingestion · Blob immutable storage · Service Bus queue · PostgreSQL audit trail · Entra ID auth · Azure Container Apps (replace Railway)
- Targets: 99.5% matching accuracy · <5 min end-to-end · 95% auto-post rate on clean transactions

### Phase 3 — 12 Months (Enterprise SaaS Platform)
- 50+ companies · 1M+ txns/month · multi-region
- Add: SAP/Oracle/NetSuite ERP connectors via Logic Apps · Azure Data Factory for automated AR pulls · Fine-tuned models on company-specific deduction patterns · Azure Marketplace listing
- Targets: Auto-scale 1→100 workers · Multi-region active/active (US + EU + APAC) · <2 min SLA · 99.99% uptime

**The compounding advantage:** Every batch processed feeds a fine-tuning dataset. After 10,000 batches, MismatchReasoningAgent is trained on your company's specific deduction patterns, customer behaviors, and contract terms — accuracy improves while cost drops. This is the moat generic AI tools cannot replicate.

---

## Repository Structure

```
cash-application-foundry/
├── backend/
│   ├── agents/
│   │   └── cash_app.py          # 5-agent swarm — all prompts, routing, streaming
│   ├── fixtures/
│   │   ├── bank_statement.json  # 35-transaction demo dataset
│   │   ├── open_ar.json         # 38-invoice demo AR ledger
│   │   └── cash_app_results.json # Pre-baked agent outputs for demo mode
│   ├── main.py                  # FastAPI app — SSE streaming, Blob Storage, App Insights
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── app/
│       └── page.js              # Next.js UI — real-time pipeline, tabs, workqueue
├── docs/
│   └── architecture.html        # Full architecture doc (GitHub Pages)
└── README.md
```

---

## Team

**Vinay Gangidi** — [vinay.gangidi@gmail.com](mailto:vinay.gangidi.com)

---

*Microsoft Build AI Hackathon 2026 · Theme 05 — Agent Swarms · [github.com/vinaygangidi/cash-application-foundry](https://github.com/vinaygangidi/cash-application-foundry)*
