# Codex Build Prompt — Cash Application Foundry

> Paste everything below the line into ChatGPT / Codex as a single build brief.
> It reconstructs the full system (backend + frontend + architecture) from scratch.

---

You are a senior full-stack engineer. Build a production-quality demo application called
**Cash Application Foundry** — a multi-agent AI pipeline that automates accounts-receivable
(AR) cash application: it ingests a bank statement plus an open-AR ledger, matches every
bank deposit to open invoices, reasons about exceptions, and produces audit-ready GL posting
instructions. Build it exactly to the spec below. Do not add frameworks I did not ask for.

## 0. Product framing
- Domain: enterprise finance / accounts receivable. Headline claim to design around:
  "~35 transactions reconciled in ~60 seconds vs. ~6 hours of manual work."
- It is a **sequential 5-agent pipeline**, NOT a parallel swarm. Agent N+1 depends on
  Agent N's output. Agent 3 cannot start until Agents 1 & 2 finish.
- Runs on **Azure AI Foundry** through the OpenAI Python SDK's `AsyncAzureOpenAI` client.
  Do NOT use LangChain, CrewAI, AutoGen, or any agent framework — the orchestration is a
  thin, explicit custom wrapper. The reasons this matters: token-level SSE streaming to the
  UI, finance auditability (every arithmetic step must be inspectable), and per-agent model
  routing for cost control.

## 1. Tech stack (pin these)
- **Backend:** Python 3.11, FastAPI, Uvicorn. `openai>=1.50`, `azure-identity`,
  `azure-storage-blob`, `azure-monitor-opentelemetry`, `python-dotenv`, `python-multipart`.
- **Frontend:** Next.js 14.2 (App Router), React 18, plain JS (not TS), Tailwind CSS 3.
  No component library — hand-rolled components, inline styles + Tailwind.
- **Deploy targets:** backend → Railway (Docker); frontend → Vercel; docs → GitHub Pages
  (optional). Everything must degrade gracefully when Azure add-ons are unconfigured.

## 2. Repository layout
```
backend/
  main.py                     # FastAPI app: /health, /samples, /demo-data, POST /analyze (SSE)
  agents/
    cash_app.py               # orchestrator: AGENT_ORDER, routing, live+demo swarms, JSON extraction
    bank_statement_agent.py   # Agent 1
    ar_ledger_agent.py        # Agent 2
    reconciliation_agent.py   # Agent 3
    mismatch_agent.py         # Agent 4
    posting_agent.py          # Agent 5
  data/
    samples/sample_01..10/{bank_statement.json, open_ar.json, meta.json}
    bank_statement.json, open_ar.json   # legacy default fixture
  scripts/generate_samples.py
  requirements.txt
  Dockerfile
  railway.toml
  .env.example
frontend/
  app/{layout.js, page.js, globals.css}
  next.config.js, package.json, tailwind.config.js, postcss.config.js
```

## 3. Agent module contract
Every file in `backend/agents/` (except `cash_app.py`) exports exactly these module-level
constants so the orchestrator can treat agents uniformly:
- `PROMPT: str` — the full system prompt. It MUST end with the literal line
  `NEXT: <NextAgentName>` (or `NEXT: END` for the last agent) and instruct the model to
  "Return ONLY this JSON: { ... }".
- `META: dict` — `{ "label", "icon" (emoji), "color" (hex), "desc" }` for the UI.
- `MODEL_ENV_KEY: str` — env var name that overrides the model (see routing table).
- `DEFAULT_MODEL: str` — fallback model id.
- `MAX_TOKENS: int`.

### The 5 agents
| # | Agent name (key) | Role | Default model | Env override | API |
|---|---|---|---|---|---|
| 1 | `BankStatementIntelligenceAgent` | Normalize payer names (SWIFT truncation, DBA/aliases), parse invoice refs & remittance, flag payment attributes | `gpt-4o-mini` | `MODEL_BANK_AGENT` | Chat Completions |
| 2 | `ARLedgerAgent` | Build customer index, invoice aging, alias registry, legacy-invoice map, intercompany-netting table; flag disputes/holds | `gpt-4o-mini` | `MODEL_AR_AGENT` | Chat Completions |
| 3 | `ReconciliationAgent` | Pre-checks + 8-tier matching + exact arithmetic via **real Code Interpreter** | `gpt-4o` | `MODEL_RECON_AGENT` | **Assistants API** (code_interpreter) |
| 4 | `MismatchReasoningAgent` | For each exception: reasoning, RISK_TIER (CRITICAL/HIGH/MEDIUM/LOW), GL code, SLA, recommended action | `gpt-4o` | `MODEL_REASONING_AGENT` | Chat Completions |
| 5 | `CashPostingAgent` | Final GL routing, workqueue items, ERP-ready posting instructions for every txn | `gpt-4o` | `MODEL_POSTING_AGENT` | Chat Completions |

## 4. Reconciliation Agent (Agent 3) — the core business logic
Put ALL of this in the `PROMPT`. State the thresholds as literal constants the model must use:
- `AUTO_WRITEOFF_THRESHOLD = 25.00` (differences ≤ $25 auto write-off → GL 6020)
- `FUZZY_NAME_MATCH_THRESHOLD = 0.75`
- `DUPLICATE_WINDOW_DAYS = 30`
- `DISCOUNT_LATE_TOLERANCE_DAYS = 0`

**Pre-checks (run BEFORE any matching tier; they block or redirect a txn):**
`A COMPLIANCE_HOLD`, `B WRONG_ENTITY`, `C DISPUTED_INVOICE` (→ `DISPUTED_INVOICE_HOLD`),
`D POST_DATED_CHECK` (check_date > statement_date → `POST_DATED_HOLD`),
`E STALE_CHECK` (check_date < statement_date − 180d → `STALE_CHECK_RETURN`),
`F INTERCOMPANY_NET` (match to intercompany_netting table, not invoices),
`G PREPAYMENT` (→ `SUSPENSE_PREPAYMENT`), `H EDI_PENDING` (→ `HOLD_EDI_PENDING`).

**8-tier match hierarchy, applied in order after pre-checks:**
1 `EXACT`, 2 `LEGACY_REF`, 3 `ALIAS_MATCH` (fuzzy ≥ 0.75 + amount), 4 `REMITTANCE_REF`,
5 `DISCOUNT_EXACT`, 6 `MULTI_INVOICE` (sum of 2–4 invoices), 7 `CREDIT_NET`, 8 `FIFO`.

**Special statuses outside the tiers:** `BANK_FEE_WRITEOFF`, `OVERPAYMENT`,
`DUPLICATE_PAYMENT`, `INSTALLMENT`, `LATE_DISCOUNT`, `PARENT_SUBSIDIARY`,
`THIRD_PARTY_FACTORING`.

**Arithmetic rules (never approximate; show working so it's auditable):** multi-invoice must
equal the exact sum; discount = amount × (1 − pct/100); FX verify usd == foreign × rate within
$1; stale check by calendar days; intercompany net = our_receivable − our_payable.

**Output JSON:** `{ "agent": "ReconciliationAgent", "matches": [ {txn_id, match_status,
match_tier, confidence_pct, customer_resolved, matched_invoices:[{invoice_id, applied_amount,
remaining_open}], transaction_amount, total_applied, unapplied_amount, delta,
auto_writeoff_delta, exception:bool, exception_reason, pre_check_triggered} ],
"reconciliation_summary": { total_transactions, matched_exact, matched_with_exceptions,
compliance_holds, pre_check_blocks, unmatched, auto_writeoffs, auto_writeoff_total,
total_cash_received, total_applied, total_unapplied } }`. End with `NEXT: MismatchReasoningAgent`.

The domain models **35 edge cases grouped into 7 categories**: amount, identity/name,
multi-entity, timing/sequencing, remittance/reference, FX/international, compliance/legal.
Every exception carries a RISK_TIER.

## 5. Orchestrator (`backend/agents/cash_app.py`)
- `AGENT_ORDER` list drives the sequence. Build parallel dicts keyed by agent name for
  prompts, meta, `(env_key, default_model)`, and max_tokens (import them from each module).
- `_build_openai_client()`: read `AZURE_AI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`
  (default `2024-12-01-preview`). If `AZURE_API_KEY` is set, use key auth; otherwise use
  `DefaultAzureCredential` + `get_bearer_token_provider` (Service Principal in prod). Raise
  a clear error if endpoint is missing.
- `_extract_json(text)`: strip ```json fences, else take first `{`…last `}` and `json.loads`;
  return `None` on failure (callers emit `{"raw": text[:800]}` so a partial run is visible).
- `_user_content(agent_name)`: build **targeted** input per agent — pass only the fields that
  agent needs (don't dump the whole thread). Agent 3 receives Agent 1's normalized
  transactions + Agent 2's invoices/customer_index/legacy_map/compliance_flags/
  intercompany_netting. Agent 4 receives only the `exception` matches. Agent 5 receives
  matches + reconciliation_summary + exception analysis.
- **Determinism:** all Chat Completions calls use `temperature=0, seed=42, timeout=300`, with
  a 3-attempt retry loop (sleep 2s between). The Assistants run for Agent 3 uses
  `temperature=0`. (seed is best-effort on GPT-4o.)
- **`run_cash_application(bank_data, ar_data)`** is an async generator that yields event dicts.
  It routes on `USE_FIXTURES` (default `"true"`): true → `_run_demo_swarm`, false →
  `_run_live_swarm`.

### Agent 3 via Assistants API + Code Interpreter (`_run_recon_with_code_interpreter`)
Create an assistant with `tools=[{"type":"code_interpreter"}]`, create a thread, post the user
content, and `client.beta.threads.runs.stream(..., temperature=0)`. Stream two things to the
UI: text tokens (`thread.message.delta` → `agent_token` events) AND the Python the model writes
plus its execution output (`thread.run.step.delta` tool_calls → `code_input` / `code_output`
events). After the run, read the final assistant message as the JSON payload. **Always clean up**
the thread and assistant in a `finally`. If the Assistants API is unavailable, emit
`code_interpreter_unavailable` and **fall back** to a plain Chat Completions call for Agent 3.

### SSE event vocabulary (yielded by the swarm, forwarded by `/analyze`)
`agent_start` {agent,label,icon,color,model,tool}, `agent_token` {agent,token},
`code_input`/`code_output` {agent,code|output} (Agent 3 only), `agent_complete`
{agent,label,icon,color,output,response_chars,finish_reason,parse_ok}, `swarm_complete`
{results, final}, and `error` {agent?,message}.

### Demo swarm (`_run_demo_swarm`)
Replays a static `backend/data/cash_app_results.json` (keyed by agent name) with a fake
token-by-token animation (~4 chars per tick). **Deterministic.** If that file is missing, emit
a single `error` event and return. NOTE this mode ignores the selected dataset — it always
returns the same static result. (Live mode is the real path; keep both.)

## 6. FastAPI app (`backend/main.py`)
- Enable permissive CORS (`allow_origins=["*"]`).
- Optional Azure add-ons, each wrapped in try/except and **non-critical**:
  Application Insights via `configure_azure_monitor` when
  `APPLICATIONINSIGHTS_CONNECTION_STRING` is set; Blob Storage via `BlobServiceClient` +
  `DefaultAzureCredential` when `AZURE_STORAGE_ACCOUNT_URL` is set (container `cash-app-runs`).
- Endpoints:
  - `GET /health` → `{status, service, azure_blob_storage:bool, azure_app_insights:bool,
    use_fixtures:str, sample_count:int}`. (This only *reports* USE_FIXTURES; it does NOT gate
    `/analyze` — the real switch is in `cash_app.py`.)
  - `GET /samples` → list of each sample's `meta.json`.
  - `GET /demo-data?sample=NN` → `{bank_statement, open_ar, sample_id}`, loading
    `data/samples/sample_NN/`, falling back to the legacy fixture.
  - `POST /analyze` (body `{bank_data:dict, ar_data:dict}`) → `StreamingResponse`,
    `media_type="text/event-stream"`, headers `Cache-Control: no-cache`,
    `X-Accel-Buffering: no`. Generate a `run_id` (uuid4); upload inputs to blob immediately;
    for each swarm event tag it with `run_id`, archive agent_events and the final results to
    blob on `swarm_complete`, forward each event as `data: {json}\n\n`; on `swarm_complete`
    also persist. Run a **keepalive pump** via an `asyncio.Queue` that emits `: keepalive\n\n`
    every 10s (beats the Railway proxy timeout); end the stream with `data: [DONE]\n\n`.

## 7. Sample data (`backend/data/samples/`)
Ten curated scenarios `sample_01`…`sample_10`, each a folder with `bank_statement.json`,
`open_ar.json`, `meta.json`. Themes: 01 clean batch, 02 deductions, 03 compliance,
04 multi-entity (parent/subsidiary + factoring + intercompany), 05 FX, 06 timing,
07 remittance, 08 overpayments, 09 identity, 10 mixed. `meta.json` shape:
`{ "sample_id":"04", "label":"Multi-Entity - ...", "transactions":7, "invoices":8 }`.
`bank_statement.json` shape: `{ statement_date, bank, account, company, transactions:[
{txn_id, date, amount, currency, payment_type, payer_raw, bank_reference, remittance_text,
note} ] }`. `open_ar.json` mirrors it with customers, invoices (id, open_amount, dates,
aging), aliases, disputes/holds, legacy ids, and an intercompany-netting table. Include
`scripts/generate_samples.py` to regenerate them. **Make sample 04's totals internally
consistent** (multi-invoice + intercompany must reconcile).

## 8. Frontend (`frontend/app/page.js`) — single-page app
- One big client component file (~1300 lines is fine): all sub-components plus a `Home`
  container. **No client routing** — the app defines only `/`. The nav ("Overview / Bank
  Statement / Reconciliation / Exceptions / Cash Posting") are **tabs** driven by
  `activeTab` state, not routes. (So a 404 in prod = a Vercel deep-link on a non-`/` path;
  don't add extra routes — a catch-all rewrite is optional.)
- **API base:** read `NEXT_PUBLIC_API_URL` (points at the Railway backend on Vercel);
  `next.config.js` also rewrites `/api/:path*` → `${BACKEND_URL}/:path*` for local dev.
  On mount, fetch `/api/samples` to populate the dataset dropdown.
- **Flow:** "Load Dataset" (`GET /demo-data?sample=NN`) → "Run Cash Application"
  (`POST /analyze`). Consume the SSE stream with `fetch` + a `ReadableStream` reader
  (not `EventSource`, because it's a POST): accumulate `agentStates` (live streaming tokens
  per agent, incl. Agent 3's code_input/code_output) and `agentResults` (the parsed `output`
  from each `agent_complete`). Render live token animation while streaming.
- **Tab → component map:**
  - `pipeline` (Overview) → `CashAppSummaryBanner` + one `AgentOutputSection` per agent.
  - `bank` → `BankStatementTable`.
  - `results` → `ReconciliationResults`.
  - `exceptions` → `ExceptionAnalysis` (7 category cards, each with a count).
  - `posting` → `WorkQueue` (approve/reject/pending actions) + `PostingInstructions`
    (GL journal table).
- **`FLAG_BADGE` / `MATCH_STATUS_COLOR`** maps agent-emitted flag codes and match statuses to
  colored badges (35 edge cases across 7 groups; greens for matched/alias/legacy, blue for
  multi-invoice, etc.).
- **Prop hygiene (learned bug — do it right):** `AgentOutputSection` renders the Cash Posting
  card on the Overview tab, so it must receive `wqStatus` and `onWqAction` as **props** —
  never reference `Home`-scoped state/handlers directly inside a child component, or the
  Overview tab throws a client-side ReferenceError after Agent 5 completes.
- **Reconciliation summary tiles (learned bug — do it right):** the tiles must **sum to the
  total number of transactions.** Do NOT drive them off the agent's summary fields
  (`matched_exact` counts only exact `MATCHED` rows and silently drops multi-invoice /
  intercompany txns). Instead derive counts from the actual `matches` rows so they always add
  up and self-correct against LLM miscounts. Buckets, each row in exactly one:
  - **Compliance Holds** = statuses in {COMPLIANCE_HOLD, WRONG_ENTITY, DISPUTED_INVOICE_HOLD,
    POST_DATED_HOLD, STALE_CHECK_RETURN, HOLD_EDI_PENDING}
  - **Exceptions** = `exception === true` or status `UNMATCHED` (and not a hold)
  - **Applied** = everything else (exact, multi-invoice, intercompany, FIFO, discount, …)
  Render four tiles: `Total Received` ($), `Applied (X/Y)`, `Exceptions`, `Compliance Holds`.

## 9. Config files
- `frontend/package.json`: next 14.2.5, react 18, tailwind/postcss/autoprefixer dev deps;
  scripts dev/build/start.
- `backend/Dockerfile`: `python:3.11-slim`, install requirements, `ENV USE_FIXTURES=true`,
  `EXPOSE 8080`, `CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}`.
- `backend/railway.toml`: dockerfile builder; `healthcheckPath="/health"`.
- `backend/.env.example`: `AZURE_AI_ENDPOINT`, `AZURE_API_KEY`, `AZURE_OPENAI_API_VERSION`,
  `USE_FIXTURES=true`, commented model overrides + optional storage/telemetry vars.

## 10. Local run + acceptance
```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "USE_FIXTURES=false" > .env   # + Azure creds, OR true with a cash_app_results.json present
uvicorn main:app --port 8001 --reload
# frontend
cd frontend && npm install
NEXT_PUBLIC_API_URL=http://localhost:8001 npm run dev   # http://localhost:3000
```
**Acceptance checks:**
1. `curl localhost:8001/health` returns the health JSON with correct `sample_count` and
   `use_fixtures`.
2. `GET /samples` lists 10 samples; `GET /demo-data?sample=04` returns 7 txns / 8 invoices.
3. Running sample 04 streams tokens live, shows Agent 3 writing + executing Python
   (`code_input`/`code_output`), and completes all 5 agents.
4. On the Reconciliation tab, the summary tiles **sum to 7** (e.g. Applied (7/7) · 0
   Exceptions · 0 Compliance Holds) — multi-invoice and intercompany txns are counted.
5. Clicking **Overview** after the run does NOT throw (props threaded correctly).
6. `cd frontend && npx --no-install next build` compiles clean.

Deliver the complete repo with all files above, sensible prompts for all 5 agents, and at
least samples 01 and 04 fully populated and internally consistent.
