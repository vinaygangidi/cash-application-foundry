# Cash Application Foundry

Sequential 5-agent Azure AI Foundry swarm for AR cash application; FastAPI backend, Next.js dashboard.

![Language](https://img.shields.io/badge/language-Python-blue?style=flat-square)
![Last Commit](https://img.shields.io/github/last-commit/vinaygangidi/cash-application-foundry?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)

**Live demo:** https://cash-application-foundry.vercel.app
**Full documentation:** https://vinaygangidi.github.io/cash-application-foundry/

Built for Microsoft Build AI Hackathon 2026 (theme: Agent Swarms).

## What This Does

Automates accounts receivable cash application — matching incoming bank deposits to open
invoices — using five Azure OpenAI agents in a sequential hand-off. The hard part of AR
reconciliation is not pattern matching but judgment: whether a $250 shortfall is a
legitimate freight deduction or an unauthorized short pay, whether a payment from an
unfamiliar name is a factoring relationship, whether an invoice under legal dispute
should be posted at all.

Each agent handles one stage and passes structured JSON to the next. Agent 3 runs its
arithmetic in a real Python sandbox rather than generating numbers, so allocation math is
executed instead of predicted.

## How It Works

```
Bank statement + AR ledger
        │
        ▼
1. BankStatementIntelligenceAgent   normalize payer names, fix SWIFT truncation, flag suspicious items
        ▼
2. ARLedgerAgent                    build customer index, aging, alias registry, compliance flags
        ▼
3. ReconciliationAgent              8-tier matching hierarchy, arithmetic in a Code Interpreter sandbox
        ▼
4. MismatchReasoningAgent           reason over exceptions only; assign risk tier, GL code, action
        ▼
5. CashPostingAgent                 emit GL posting instructions and workqueue items
        ▼
GL postings + exception workqueue
```

Orchestration is hand-rolled in `backend/agents/cash_app.py` — no CrewAI, LangGraph, or
Semantic Kernel. Agents 1, 2, 4, and 5 use streaming Chat Completions with
`temperature=0` and `seed=42`, retried three times with 2-second backoff. Agent 3 uses the
Azure OpenAI Assistants API with the `code_interpreter` tool, falling back to Chat
Completions if Assistants is unavailable.

Every stage streams to the browser over Server-Sent Events, with a 10-second keepalive to
prevent proxy timeouts.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Status, plus the current `use_fixtures` value |
| `GET` | `/samples` | List the 10 sample datasets |
| `GET` | `/demo-data?sample=NN` | Load one sample's bank statement and AR ledger |
| `POST` | `/analyze` | Run the swarm, streaming SSE |

## Quickstart

> **Demo mode does not work on a fresh clone.** `USE_FIXTURES` defaults to `true`, which
> replays `backend/data/cash_app_results.json` — a file that is **not tracked in this
> repository**. Without it you get
> `{"event":"error","message":"Demo data file not found."}`. Either supply that file or
> run live Azure mode as shown in step 3.

1. Start the backend:
   ```bash
   git clone https://github.com/vinaygangidi/cash-application-foundry.git
   cd cash-application-foundry/backend

   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure Azure credentials in `backend/.env`:
   ```bash
   cp .env.example .env
   # Set AZURE_AI_ENDPOINT and AZURE_API_KEY
   ```

3. Run in live Azure mode:
   ```bash
   USE_FIXTURES=false uvicorn main:app --port 8001 --reload
   ```

4. Start the UI in a second terminal:
   ```bash
   cd ../frontend
   npm install
   npm run dev
   ```

5. Open http://localhost:3000, click **Load Demo Data**, then **Run Cash Application**.

The frontend reaches the backend through a Next.js rewrite configured by `BACKEND_URL`
(default `http://localhost:8001`), so no frontend environment variable is needed for local
use.

### Registering agents in Azure AI Foundry

`backend/scripts/register_agents.py` registers the five agents as Foundry resources. It
needs three variables that `.env.example` does not document: `AZURE_SUBSCRIPTION_ID`,
`AZURE_RESOURCE_GROUP`, and `AZURE_PROJECT_NAME`.

## Configuration

| Name | Required | Default | Description |
|---|---|---|---|
| `AZURE_AI_ENDPOINT` | Yes | none | Azure AI Foundry endpoint. Raises `EnvironmentError` if unset in live mode |
| `AZURE_API_KEY` | No | `""` | API key. When empty, falls back to `DefaultAzureCredential` |
| `AZURE_OPENAI_API_VERSION` | No | `2024-12-01-preview` | Azure OpenAI API version |
| `USE_FIXTURES` | No | `true` | `true` replays demo JSON (see the warning above); `false` calls Azure |
| `MODEL_BANK_AGENT` | No | `gpt-4o-mini` | Model for agent 1 |
| `MODEL_AR_AGENT` | No | `gpt-4o-mini` | Model for agent 2 |
| `MODEL_RECON_AGENT` | No | `gpt-4o` | Model for agent 3 |
| `MODEL_REASONING_AGENT` | No | `gpt-4o` | Model for agent 4 |
| `MODEL_POSTING_AGENT` | No | `gpt-4o` | Model for agent 5 |
| `AZURE_STORAGE_ACCOUNT_URL` | No | `""` | Blob endpoint for the run audit trail, via `DefaultAzureCredential`. The original demo storage account has been deleted; point this at a new one to re-enable |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | `""` | Enables Azure Monitor if set. The original demo instance has been deleted; provision a new one to re-enable |
| `AZURE_SUBSCRIPTION_ID` | Script only | `""` | Required by `register_agents.py` |
| `AZURE_RESOURCE_GROUP` | Script only | `""` | Required by `register_agents.py` |
| `AZURE_PROJECT_NAME` | Script only | `""` | Required by `register_agents.py` |
| `BACKEND_URL` | No | `http://localhost:8001` | Frontend rewrite target for `/api/*` |

The `MODEL_*` defaults above are what the agent modules use at runtime.
`backend/scripts/register_agents.py` declares different defaults for three of them
(`gpt-5.4-mini` for agents 1 and 2, `gpt-5` for agent 4), so registration and execution can
disagree unless you set the variables explicitly.

## Limitations

- **Demo mode is broken on a fresh clone.** `backend/data/cash_app_results.json` is
  required by the default `USE_FIXTURES=true` path and is not tracked in git. This is the
  first thing a reader hits.
- **No deterministic matching or policy layer.** Matching, exception reasoning, and posting
  decisions are all model output. Agent 3 executes its arithmetic in a Code Interpreter
  sandbox, but nothing in the backend independently verifies an allocation before it is
  presented as an auto-post candidate. A sibling project,
  [ledger-sense](https://github.com/vinaygangidi/ledger-sense), implements the
  deterministic-guardrail approach for comparison.
- **No tests.** No test suite and no CI. `.github/` contains only `copilot-instructions.md`.
- **Azure demo resources have been decommissioned.** The Application Insights instance and
  the Blob Storage account used during the hackathon no longer exist. The integration code
  remains in place, so telemetry and the Blob audit trail come back by provisioning new
  resources and setting `APPLICATIONINSIGHTS_CONNECTION_STRING` and
  `AZURE_STORAGE_ACCOUNT_URL`.
- **Audit-trail failures are silent, which matters once it is reconnected.** Application
  Insights initialization and every Blob Storage write are wrapped in bare
  `except Exception: pass`, and `/health` reports only whether the client object was
  constructed — not whether uploads succeed. A misconfigured audit trail is therefore
  indistinguishable from an intentionally unconfigured one. Worth adding an explicit
  health signal before relying on this for traceability.
- **CORS is wide open.** `allow_origins=["*"]` with all methods and headers.
- **No field allowlist on model payloads.** Agent-selected slices of the full bank and AR
  JSON are sent to Azure OpenAI. Bank account numbers, routing numbers, or tax IDs present
  in input data are not stripped, and no test asserts otherwise.
- **No authentication.** Any caller who can reach the API can run the swarm.
- **Sample data is smaller than the headline numbers suggest.** Ten samples hold 81
  transactions in total, the largest being 9. Earlier versions of this README described "35
  transactions in under 60 seconds" and a "91 percent auto-post rate" on a 35-transaction
  run; no fixture in the repository contains 35 transactions, and those figures are not
  reproducible from this code.
- **`LICENSE` was missing** despite the README asserting MIT. Added.
- **Duplicate of a sibling repository.** `cash-app-foundry-iq` is an independent init of the
  same project (unrelated git history) and holds files this one lacks, including
  `backend/agents/foundry_client.py`, deploy configs, and the demo results JSON.
- **Timings are illustrative.** Per-agent durations previously quoted in this README were
  from one observed run, not benchmarks, and depend on model, region, and payload size.

## Documentation

| Document | Contents |
|---|---|
| [docs/how-it-works.md](docs/how-it-works.md) | Business explanation, worked examples, ERP integration |
| [docs/QUICK_VISUAL_GUIDE.md](docs/QUICK_VISUAL_GUIDE.md) | Diagrams, data flow, edge-case catalog |
| [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) | Architecture, Azure integration, security model, roadmap |
| [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) | Azure setup, Railway and Vercel deployment, troubleshooting |

## License

MIT — see [LICENSE](LICENSE).
