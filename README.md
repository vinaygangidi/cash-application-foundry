# Cash Application Foundry

A multi-agent AI system built on Microsoft's cloud platform that automates accounts receivable reconciliation. Processes 35 transactions in under 60 seconds with complete audit traceability. Replaces manual work that typically takes 6 hours.

Live Demo: https://cash-application-foundry.vercel.app

Full Documentation: https://vinaygangidi.github.io/cash-application-foundry/

---

## Why This Matters: 2.3 Trillion Dollars in Trapped Working Capital

Every company selling on credit has an AR team matching bank deposits to invoices. The problem is that this work requires judgment, not just pattern matching.

Real examples AR analysts face daily:

1. Freight deduction detective work: Customer sends $29,250 but invoice was $29,500. Is this a legitimate freight charge, a damaged goods claim, or an unauthorized short pay? Answer is 15 minutes of manual research.

2. SWIFT name truncation: Bank shows payer as "GREENFIELD TECH SOLUT" because wire transfers cut names at 35 characters. Actual customer is "Greenfield Technology Solutions LLC." Someone looks it up manually every time.

3. Factoring relationships: Payment arrives from "ACE Capital Partners" but your customer is "Riverside Manufacturing." Turns out ACE factored the invoice. Decision is to route to correct entity. This is compliance critical.

4. Legal holds: Payment arrives for an invoice in active dispute. Posting it violates compliance. Decision is to escalate to legal and don't process.

Why it matters financially:

- 2.3 trillion dollars in AR processed annually across US companies
- 1.4 million dollars per day of working capital trapped for every DSO (Days Sales Outstanding) increase for a $500M revenue company
- 8-10 edge cases per hour is what an experienced AR analyst can handle
- 35 edge cases in 60 seconds is what our system handles

Our system handles 35 different edge case patterns including partial payments, truncated names, factoring, multi-invoice bundles, OFAC holds, disputed invoices, FX conversions, and more. Each one requires reasoning, not just matching.

---

## How It Works: 5 Specialized AI Agents on Microsoft Azure

Instead of one AI trying to match transactions AND reason about exceptions AND generate postings, we built 5 specialists:

Agent 1: Bank Statement Intelligence (15 seconds)

Reads bank transactions, normalizes payer names (fixes SWIFT truncation, DBA names), parses invoice references, flags suspicious items.

Agent 2: AR Ledger Builder (20 seconds)

Builds customer lookup tables, identifies aliases and cross-references, flags disputes and holds, prepares invoice index for matching.

Agent 3: Reconciliation Engine (35 seconds)

Tries 8 matching strategies (exact match, partial match, multi-invoice, FX conversion, etc.), uses Python code to verify every dollar (no hallucination), pre-checks compliance holds and disputed invoices.

Agent 4: Mismatch Reasoning (15 seconds)

Uses a reasoning model to analyze exceptions. Questions: Is this a legitimate deduction or fraud? Should this route to deductions team or legal? Assigns risk tier and SLA to each exception.

Agent 5: Cash Posting (10 seconds)

Generates GL account routing, creates workqueue items sorted by urgency, produces ERP-ready posting instructions.

Why this architecture:

Sequential hand-off (not parallel swarm): This means dependencies are real, not design choices. Agents 1 and 2 must finish before Agent 3 can start. This creates a clean, auditable chain.

Right model for right task: Agents 1 and 2 use GPT-4o-mini (fast, cheap). Agent 3 uses GPT-4o (complex logic). Agent 4 uses GPT-5 (reasoning on exceptions). This saves 60 percent cost versus running everything on GPT-4o.

Built entirely on Microsoft Azure: Azure OpenAI Service (not public OpenAI), AsyncAzureOpenAI (Python async), Azure Blob Storage (immutable audit trail), Azure Identity (no API keys in code), Azure Monitor and OpenTelemetry (end-to-end tracing).

Why Microsoft matters: Your financial data stays in your Azure tenant. Never touches shared infrastructure. Microsoft doesn't use it to train future models. For finance, this is non-negotiable.

---

## Live Demo: What Judges Will See

Watch it live: https://cash-application-foundry.vercel.app

Real-time agent execution (90 seconds total):

- Agent 1 normalizes bank data (15 seconds)
- Agent 2 builds invoice index (20 seconds)
- Agent 3 matches transactions (35 seconds)
- Agent 4 reasons about exceptions (15 seconds)
- Agent 5 generates postings (10 seconds)

Results with 35 sample transactions:

Matched cleanly (32 of 35 = 91 percent auto-post rate):

- Transaction ID | Amount | Customer | Invoice | GL Account | Status: AUTO-POST

Exceptions with reasoning (3 of 35):

| Transaction | Amount | Issue | Agent 4 Reasoning | Routing |
|---|---|---|---|---|
| TXN-7 | $50,000 | Name mismatch: ACE Capital vs Riverside Mfg | Factoring relationship detected. ACE is a known factor. Invoice legitimately assigned. | Route to Riverside Mfg account |
| TXN-15 | $35,000 | Payer name matches OFAC list | Name on sanctions screening. Compliance hold required. Do not process. | COMPLIANCE HOLD, Escalate to Legal |
| TXN-23 | $45,000 | Short pay on disputed invoice | Invoice in active legal dispute. Posting would violate compliance. | LEGAL HOLD, Escalate to Legal |

Audit trail: Every decision logged, immutable, ready for auditors. SOX-compliant decision chain from raw bank data through agent 1 through agent 2 and onwards to final posting.

Business value: 6 hours of manual work compressed into 60 seconds. 32 auto-posted (zero AR analyst touch). 3 exceptions routed with complete reasoning and SLA.

---

## Run It Locally in 5 Minutes

Prerequisites: Python 3.11 or higher, Node.js 18 or higher, Git

Step 1: Clone and start the agents

```bash
git clone https://github.com/vinaygangidi/cash-application-foundry.git
cd cash-application-foundry/backend

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --port 8001 --reload
```

Step 2: Start the UI (open new terminal)

```bash
cd ../frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8001 npm run dev
```

Step 3: Open and watch

Visit http://localhost:3000

Click "Load Demo Data"

Click "Run Cash Application"

Watch all 5 agents execute in real-time

Each agent's work streams to your browser via Server-Sent Events (SSE). No buffering, complete transparency. Demo mode requires no Azure credentials. Everything runs on sample data.

For production mode with Azure: See IMPLEMENTATION_GUIDE.md

---

## Documentation and Deep Dives

All documentation available at: https://vinaygangidi.github.io/cash-application-foundry/

How It Works: https://github.com/vinaygangidi/cash-application-foundry/blob/main/docs/how-it-works.md (15 minutes)
Business explanation, real-world examples, ROI calculation, ERP integration

Quick Visual Guide: https://github.com/vinaygangidi/cash-application-foundry/blob/main/docs/QUICK_VISUAL_GUIDE.md (10 minutes)
Diagrams, data flow, before and after comparison, 35 edge case catalog

System Design: https://github.com/vinaygangidi/cash-application-foundry/blob/main/docs/SYSTEM_DESIGN.md (1 hour)
Complete architecture, why AsyncAzureOpenAI (not third-party frameworks), Azure services integration, security model, OFAC pre-checks, production roadmap (Phase 1, 2, and 3)

Implementation Guide: https://github.com/vinaygangidi/cash-application-foundry/blob/main/docs/IMPLEMENTATION_GUIDE.md (30 minutes)
Local setup, Azure AI Foundry configuration, Railway and Vercel deployment, environment variables, troubleshooting

Architecture Docs: https://vinaygangidi.github.io/cash-application-foundry/architecture.html
Visual diagrams and system flow

---

## Team

Vinay Gangidi

Email: vinay.gangidi@gmail.com

Built for Microsoft Build AI Hackathon 2026

Theme: Agent Swarms

Platform: Azure AI Foundry + AsyncAzureOpenAI

---

License: MIT - See LICENSE file
