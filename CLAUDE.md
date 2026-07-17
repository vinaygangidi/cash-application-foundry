# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo. Read this first, then
`.github/copilot-instructions.md` for deeper per-agent conventions. This file is the
authoritative record of *what the system is, how it's deployed, and what's been changed*.

---

## 1. What this is

**Cash Application Foundry** — a 5-agent AI pipeline that automates accounts-receivable
cash application: it matches bank deposits to open invoices and produces audit-ready GL
posting instructions. Built for the Microsoft Build AI Hackathon 2026 ("Agent Swarms" theme).
Runs on Azure AI Foundry via `AsyncAzureOpenAI`. Headline claim: ~35 transactions in ~60s
vs. ~6 hours manual.

- **GitHub:** https://github.com/vinaygangidi/cash-application-foundry
- **Live frontend:** https://cash-application-foundry.vercel.app
- **Live backend:** https://cash-application-foundry-production.up.railway.app
- **Docs site:** https://vinaygangidi.github.io/cash-application-foundry/

### ⚠️ Two repos exist — do not confuse them
There is a sibling repo/directory `cash-app-foundry-iq` (GitHub: `vinaygangidi/cash-app-foundry-iq`)
that adds a **Foundry IQ (RAG) integration** on top of this codebase. It has its own Railway
deployment (`cash-app-foundry-iq-backend-production.up.railway.app`). When debugging a
deployment, **confirm which backend URL you're hitting** — the two share almost identical code
but have different env config (notably `USE_FIXTURES`). `FOUNDRY_IQ_INTEGRATION.md` in *this*
repo is a **proposal/design doc**, not implemented here.

---

## 2. Architecture

Sequential 5-agent pipeline (NOT a parallel swarm). Hard dependencies: Agent 3 cannot start
until Agents 1 & 2 finish. Each agent is one file in `backend/agents/` exporting
`PROMPT`, `META`, `MODEL_ENV_KEY`, `DEFAULT_MODEL`, `MAX_TOKENS`. Orchestration lives in
`backend/agents/cash_app.py` (`AGENT_ORDER`, `AGENT_MODEL_KEYS`, model routing via env vars).

| # | Agent (key) | Role | Model | API |
|---|---|---|---|---|
| 1 | `BankStatementIntelligenceAgent` | Normalize payer names (SWIFT truncation, DBA), parse invoice refs | gpt-4o-mini | Chat Completions |
| 2 | `ARLedgerAgent` | Build customer/invoice index, aliases, flag disputes/holds | gpt-4o-mini | Chat Completions |
| 3 | `ReconciliationAgent` | 8-tier matching + pre-checks, **real Code Interpreter** for dollar math | gpt-4o | **Assistants API** |
| 4 | `MismatchReasoningAgent` | Reason about exceptions, assign RISK_TIER + SLA | gpt-4o | Chat Completions |
| 5 | `CashPostingAgent` | GL routing, workqueue, ERP-ready postings | gpt-4o | Chat Completions |

Model per agent is overridable via env vars (`MODEL_BANK_AGENT`, `MODEL_RECON_AGENT`, etc.);
defaults are in each agent module. Per-task routing is a deliberate cost optimization.

**Why Azure-native (not LangChain/CrewAI):** token-level SSE streaming, finance auditability,
and per-task model routing. The orchestration layer is a thin custom wrapper over
`AsyncAzureOpenAI`.

### Reconciliation logic (Agent 3) — key rules
- **Pre-checks** run before any matching tier and can block a txn: `COMPLIANCE_HOLD`,
  `WRONG_ENTITY`, `DISPUTED_INVOICE`, `POST_DATED_CHECK`, `STALE_CHECK` (>180d),
  `INTERCOMPANY_NET`, `PREPAYMENT`, `EDI_PENDING`.
- **8-tier match hierarchy** (in order): EXACT → LEGACY_REF → ALIAS_MATCH → REMITTANCE_REF →
  DISCOUNT_EXACT → MULTI_INVOICE → CREDIT_NET → FIFO.
- **Thresholds** (hardcoded in `reconciliation_agent.py` prompt): auto-writeoff ≤ $25.00 → GL 6020;
  fuzzy-name match ≥ 0.75; duplicate window 30 days; late-discount tolerance 0 days.
- 35 edge cases grouped into 7 categories (amount / identity / multi-entity / timing /
  remittance / FX / compliance). Every exception gets a RISK_TIER (CRITICAL/HIGH/MEDIUM/LOW).

---

## 3. Backend (`backend/`)

- **Framework:** FastAPI. Entry: `backend/main.py`.
- **Endpoints:** `/health`, `/samples`, `/demo-data?sample=NN`, `POST /analyze` (SSE stream).
- **Streaming:** `/analyze` returns `text/event-stream`. Events: `agent_start`, `agent_token`,
  `agent_complete`, `swarm_complete`, plus `code_input`/`code_output` for Agent 3's Code
  Interpreter. A keepalive pump emits `: keepalive` every 10s to beat the Railway proxy timeout.
- **Persistence:** full run (inputs, results, agent_events) archived to Azure Blob Storage,
  keyed by `run_id` (UUID). Non-critical — silently skipped if storage unconfigured.
- **Telemetry:** Azure Application Insights via OpenTelemetry. Non-critical.

### Two run modes — `USE_FIXTURES` (this is the crux of the "inconsistent results" issue)
The switch lives in `backend/agents/cash_app.py::run_cash_application` (default `"true"`).
**Note:** `main.py` only *reports* `USE_FIXTURES` in `/health` — it does NOT gate `/analyze`.
The real branch is in `cash_app.py`.

- `USE_FIXTURES=true` → `_run_demo_swarm`: replays a static `backend/data/cash_app_results.json`
  with fake token animation. **Deterministic.** BUT:
  - ⚠️ **This repo's `cash_app_results.json` was deleted** (commit `8112c02` "Remove sensitive
    data"). With the file missing, the demo swarm yields a single `error` event and returns —
    no agent output. The `cash-app-foundry-iq` sibling repo *does* still have the file.
  - ⚠️ The demo swarm **ignores `bank_data`/`ar_data` entirely** — it returns the same static
    result regardless of which sample dataset you pick in the dropdown. So "different dataset,
    same output" is expected in fixtures mode.
- `USE_FIXTURES=false` → `_run_live_swarm`: real Azure OpenAI inference. **Nondeterministic**
  (see §6). **This is what production currently runs** (`/health` reports `use_fixtures: "false"`,
  blob + app-insights enabled).

### Sample data
- `backend/data/samples/sample_01/` … `sample_10/` — each has `bank_statement.json`,
  `open_ar.json`, `meta.json`. 10 curated scenarios (clean batch, deductions, compliance,
  multi-entity, FX, timing, remittance, overpayments, identity, mixed).
- `backend/data/bank_statement.json` + `open_ar.json` — legacy default fixture.
- `backend/scripts/generate_samples.py` — regenerates samples.

### Env vars (`backend/.env.example`)
```
AZURE_AI_ENDPOINT, AZURE_API_KEY, AZURE_OPENAI_API_VERSION
USE_FIXTURES=true
# optional: AZURE_STORAGE_ACCOUNT_URL, APPLICATIONINSIGHTS_CONNECTION_STRING
# optional model overrides: MODEL_BANK_AGENT, MODEL_AR_AGENT, MODEL_RECON_AGENT, ...
```
Production auth: `DefaultAzureCredential` (Service Principal) when `AZURE_API_KEY` is unset.

---

## 4. Frontend (`frontend/`)

- **Framework:** Next.js 14 (App Router). Single page: `frontend/app/page.js` (~1350 lines,
  everything in one file — all components + the `Home` container).
- **No client routing.** The app defines only `/`. "Overview / Bank Statement / Reconciliation
  / Exceptions / Cash Posting" are **tabs** driven by `activeTab` state (`setActiveTab`), NOT
  routes. A 404 in the browser therefore means a **Vercel deep-link/refresh on a non-`/` path**
  (no catch-all rewrite exists), not a broken in-app link.
- **API base:** `NEXT_PUBLIC_API_URL` (set to the Railway backend on Vercel). No local `app/api`
  proxy routes except a `/api/samples` fetch on mount.
- **SSE consumption:** reads the `/analyze` stream, accumulating `agentStates` (live tokens)
  and `agentResults` (parsed output per agent). Tabs render from `agentResults`.
- **Tab → component map:**
  - `pipeline` ("Overview") → `CashAppSummaryBanner` + one `AgentOutputSection` per agent
  - `bank` → `BankStatementTable`
  - `results` → `ReconciliationResults`
  - `exceptions` → `ExceptionAnalysis`
  - `posting` → `WorkQueue` + `PostingInstructions`
- `FLAG_BADGE` maps agent-emitted flag codes → colored UI badges (35 edge cases, 7 groups).

---

## 5. Running locally

```bash
# Backend (demo mode — but see the missing-fixtures caveat in §3)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "USE_FIXTURES=true" > .env
uvicorn main:app --port 8001 --reload

# Frontend (separate terminal)
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8001 npm run dev
# → http://localhost:3000  ·  Load Dataset → Run Cash Application
```

Verify a frontend change compiles: `cd frontend && npx --no-install next build`.

---

## 6. Known issues & investigation notes

### (a) FIXED — Overview tab crash: "a client-side exception has occurred"
**Symptom:** after running the agents, clicking the **Overview** tab threw a client-side
exception (blank Next.js error page).
**Root cause:** `ReferenceError` in `AgentOutputSection` (`frontend/app/page.js`). Its
`CashPostingAgent` branch referenced `wqStatus` and `handleWqAction`, which are defined in the
`Home` component and were **never passed as props**. The crash only fired on the Overview tab
after Agent 5 completed (that's when the Cash Posting card renders). The separate "Cash Posting"
tab was unaffected because it calls `WorkQueue` directly inside `Home`.
**Fix (3 edits in `page.js`):**
1. `AgentOutputSection({ ..., wqStatus, onWqAction })` — added the two props.
2. `WorkQueue ... onStatusChange={onWqAction}`.
3. Overview call site passes `wqStatus={wqStatus} onWqAction={handleWqAction}`.
Verified with `next build` (compiles clean). **Status: applied to working tree, not yet committed.**

### (b) OPEN — Inconsistent results on repeated identical runs (live mode)
Production runs `USE_FIXTURES=false` → real LLM inference, so repeat runs of the same dataset
naturally differ. Contributing factors, worst first:
1. **Agent 3 (Reconciliation) sets no `temperature` and no `seed`** — the Assistants-API +
   Code-Interpreter path (`_run_recon_with_code_interpreter`) samples at the model default
   (~1.0). This is the agent that decides matches → biggest source of variance.
2. Agents 1/2/4/5 set `temperature=0` but **no `seed`** — temp-0 still drifts on GPT-4o/GPT-5.
3. Code-Interpreter fallback: if Assistants API is unavailable, Agent 3 silently falls back to
   chat completions — a different code path with different results.
4. Silent JSON-parse failures: `_extract_json` returning `None` emits `{"raw": ...}` instead of
   structured output → one run looks complete, the next partial.

**Fix options (not yet applied):**
- Deterministic demo: set `USE_FIXTURES=true` on Railway **and** regenerate the missing
  `backend/data/cash_app_results.json` (ideally per-sample, keyed by `sample_id`).
- Consistent live runs: add `seed=` + keep `temperature=0` on the two `chat.completions.create`
  calls, and pass `temperature=0` into the Agent-3 Assistants `runs.stream(...)`.

---

## 7. Docs

- `README.md` — public overview, business case, quick start.
- `.github/copilot-instructions.md` — detailed per-agent conventions, thresholds, how to add
  an agent / matching tier. **Complements this file.**
- `docs/` — `SYSTEM_DESIGN.md`, `IMPLEMENTATION_GUIDE.md`, `how-it-works.md`,
  `QUICK_VISUAL_GUIDE.md`, `PRESENTATION_DECK.md`; Jekyll site (`_config.yml`, `_layouts/`).
- `FOUNDRY_IQ_INTEGRATION.md` — **proposal only**, not implemented in this repo (see §1).

---

## 8. Deployment

- **Frontend → Vercel** (Next.js). Set `NEXT_PUBLIC_API_URL` to the Railway backend URL.
- **Backend → Railway** (Docker, `backend/Dockerfile`, `railway.toml`). Env: Azure creds,
  `USE_FIXTURES`, optional storage/telemetry.
- **Docs → GitHub Pages** (Jekyll, `docs/`).
- Azure blob + app-insights are wired but degrade gracefully if unconfigured.
