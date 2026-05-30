# Cash Application Foundry

**5-agent AI swarm that reconciles bank payments to open invoices — built natively on Azure AI Foundry Agent Service.**

Demo: [live link] · Track: Microsoft Build AI — Theme 05 Agent Swarms

---

## What It Does

Enterprise AR teams spend hours manually matching bank deposits to invoices. This system replaces that work with a swarm of 5 specialized AI agents that handle every real-world edge case: SWIFT name truncation, parent/subsidiary relationships, OFAC compliance holds, disputed invoices, FX settlements, and more.

**35 edge cases across 7 categories handled end-to-end — in under 60 seconds.**

---

## Architecture

```
Bank Statement JSON  ──►  BankStatementIntelligenceAgent   (normalizes payer names, flags anomalies)
Open AR JSON        ──►  ARLedgerAgent                     (builds customer index, alias registry)
                         │
                         ▼
                   ReconciliationAgent  ←── CodeInterpreterTool (exact arithmetic in Python)
                         │
                         ▼
                   MismatchReasoningAgent  (7-category exception classification, risk tiers)
                         │
                         ▼
                   CashPostingAgent  (GL journal entries, workqueue by team, compliance holds)
```

All 5 agents share a single **Azure AI Foundry Thread**. Each agent appends its structured JSON output as an assistant message — the next agent reads the full thread history with no custom message passing needed.

**8-tier matching hierarchy**: EXACT → LEGACY_REF → ALIAS_MATCH → REMITTANCE_REF → DISCOUNT_EXACT → MULTI_INVOICE → CREDIT_NET → FIFO

**Pre-checks before matching (A–H)**: COMPLIANCE_HOLD, WRONG_ENTITY, DISPUTED_INVOICE, POST_DATED_CHECK, STALE_CHECK, INTERCOMPANY_NET, PREPAYMENT, EDI_PENDING

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Runtime | Azure AI Foundry Agent Service (`azure-ai-projects`) |
| Code Execution | Azure AI Foundry `CodeInterpreterTool` |
| Agent Chaining | Azure AI Foundry `ConnectedAgentTool` |
| Backend | FastAPI with Server-Sent Events (SSE) streaming |
| Frontend | Next.js 14 with real-time agent pipeline UI |

---

## Setup

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Demo mode (no Azure credentials needed)
echo "USE_FIXTURES=true" > .env

uvicorn main:app --port 8001 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, click **Load Demo Data**, then **Run Cash Application**.

### Live Azure Mode

```bash
# backend/.env
USE_FIXTURES=false
AZURE_AI_PROJECT_CONNECTION_STRING=<your connection string>
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o
```

---

## Deployment

### Backend → Railway

1. Connect GitHub repo in Railway
2. Set root to `/backend`
3. Railway auto-detects the `Dockerfile`
4. Add env var: `USE_FIXTURES=true`

### Frontend → Vercel

1. Connect GitHub repo in Vercel
2. Set root to `/frontend`
3. Add env var: `BACKEND_URL=https://your-railway-app.up.railway.app`

---

## Edge Case Coverage

| Category | Cases Handled |
|---|---|
| Amount Mismatch | Exact match, multi-invoice, early-pay discount, unauthorized short pay, freight deduction, damage claim, overpayment, credit memo net, wire fee write-off, late discount |
| Identity & Name | SWIFT 35-char truncation, DBA name, post-M&A name change, fuzzy alias matching |
| Multi-Entity | Parent pays subsidiary, third-party factoring, intercompany netting, wrong legal entity |
| Timing | Duplicate payment, installment, NSF return, post-dated check, stale check, prepayment |
| Remittance | No remittance (FIFO), vague remittance, PO number, legacy ERP ref, EDI 820 pending |
| FX & International | EUR SWIFT payment, FX rate verification via Code Interpreter |
| Compliance & Legal | OFAC sanctions hold, disputed invoice block, legal hold escalation |

---

## Team

Vinay Gangidi — [vinay.gangidi@gmail.com](mailto:vinay.gangidi@gmail.com)
