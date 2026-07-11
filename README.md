# sleeping-passenger-v1

> A **local, single-user advisory signal journal**. It pulls public-data
> signals into a SQLite store, surfaces them in a Next.js dashboard, and lets
> a human reflect, log a manual trade, and reconcile the outcome.

## Python version

This project requires **Python >= 3.12**. The test suite and several runtime
modules use PEP 701 f-strings (backslashes inside f-string expressions), which
are a `SyntaxError` on 3.11 and earlier. CI runs on Python 3.13.

## Who this is for

One person — you — running this on your own laptop to enforce trade-journal
discipline. It is not a hosted product, not multi-user, and not a broker.

## What this MVP does

- Ingests public signals (Polymarket, GDELT, SEC EDGAR, NewsAPI, Etherscan,
  Yahoo OHLCV, Grok/xAI) into a local SQLite database — all read-only.
- Surfaces them in a Next.js dashboard with derived next-human-action hints.
- Lets you reflect on a signal, log a manual trade you placed yourself, and
  reconcile the outcome later.
- Maintains a Moltbook — a self-correction journal of mistakes / biases /
  rule updates.
- Exports every journal stream as CSV for offline analysis.

## What this MVP does NOT do

- Does **not** place buy/sell orders on any exchange or broker.
- Does **not** connect to any broker API.
- Does **not** execute trades automatically or semi-automatically.
- Does **not** ever set `ai_execution_count > 0`. That value is immutable.
- Does **not** store broker credentials.

The advisory contract is stamped on every record:
`advisory_status=ADVISORY_ONLY`, `execution_mode=HUMAN_ONLY`,
`execution_gate=LOCKED`, `broker_api_called=false`, `ai_execution_count=0`.

## Canonical workflow

1. **Ingest** live signals (or use seeded data).
2. **Review** the Signal Inbox — filter, sort, drill into details.
3. **Reflect** — write a thesis or note on a signal.
4. **Decide** — mark `watchlist`, `human_review`, or `rejected`.
5. **Log** a manual trade you placed yourself (record-keeping only).
6. **Reconcile** the trade with the actual outcome.
7. **Learn** — log a Moltbook entry capturing the mistake/bias/rule update.

## Safety posture

This system is designed to be **incapable** of placing trades. The refusal
is enforced at four layers (UI badges, FastAPI route absence, persistence
stamps, AST-level test that no `/execute|/buy|/sell|/order|/broker` route
exists). See `scripts/api_server.py` and `tests/test_api_server.py` for the
exact enforcement.

## Quick start

See **[SETUP.md](SETUP.md)** for the full setup. Short version:

```powershell
# backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt; pip install -r requirements-dev.txt
python scripts\api_server.py

# frontend (new terminal)
cd frontend; npm install; npm run dev
```

Open http://localhost:3000.

## Documentation map

| Doc | Purpose |
|---|---|
| [SHOWCASE.md](SHOWCASE.md) | One-stop product showcase (problem, workflow, safety, demo) |
| [SETUP.md](SETUP.md) | Install, env vars, start/stop, troubleshooting |
| [DEMO.md](DEMO.md) | 5-minute scripted walkthrough |
| [TESTING.md](TESTING.md) | What is and isn't tested, how to run |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Current status and the path to production |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System / workflow / safety / persistence / refresh diagrams |
| [docs/MARKET_TITRATION_ENGINE.md](docs/MARKET_TITRATION_ENGINE.md) | Pre-alpha titration layer: evidence decay, readiness vs recognition, titration states |
| [docs/AI_OUTPUT_VALIDATION.md](docs/AI_OUTPUT_VALIDATION.md) | AI payload schema, malformed handling, safety overrides |
| [docs/LIVE_SIGNALS_REFRESH_MODEL.md](docs/LIVE_SIGNALS_REFRESH_MODEL.md) | 6-hour refresh model and source-health contract |
| [docs/LIVE_SIGNALS_SCHEDULING.md](docs/LIVE_SIGNALS_SCHEDULING.md) | Windows Task Scheduler / cron recipes |
| [docs/LEGAL_PRIVACY_NOTES.md](docs/LEGAL_PRIVACY_NOTES.md) | Advisory-only, no-financial-advice, source ToS posture |
| [docs/SOURCE_TOS_CHECKLIST.md](docs/SOURCE_TOS_CHECKLIST.md) | Per-source ToS verification checklist |
| [docs/PRODUCT_DIRECTION_DECISION.md](docs/PRODUCT_DIRECTION_DECISION.md) | Local-showcase vs private-beta vs public-prod decision |
| [docs/PRIVATE_BETA_AUTH_DESIGN.md](docs/PRIVATE_BETA_AUTH_DESIGN.md) | Multi-user auth and isolation design (not yet implemented) |
| [docs/POSTGRES_MIGRATION_PLAN.md](docs/POSTGRES_MIGRATION_PLAN.md) | SQLite → Postgres migration plan |
| [docs/HOSTED_DEPLOYMENT_PLAN.md](docs/HOSTED_DEPLOYMENT_PLAN.md) | Hosting options comparison and rollout checklist |
| [docs/MONITORING_AND_INCIDENTS.md](docs/MONITORING_AND_INCIDENTS.md) | Alerts, incident response, P0/P1 triage |
| [docs/FINAL_ACCEPTANCE_CHECKLIST.md](docs/FINAL_ACCEPTANCE_CHECKLIST.md) | Local setup, safety, data, frontend, tests, deployment acceptance |
| [docs/FINAL_SCORECARD.md](docs/FINAL_SCORECARD.md) | Honest before/after readiness scorecard |
| [docs/SCRIPT_INVENTORY.md](docs/SCRIPT_INVENTORY.md) | Active vs. research scripts |

### Framework and diagnostic roadmap

These are internal framework documents. They are documentation and metadata
only — no live calls, no DB writes, no execution permission. The MVP
remains advisory-only.

| Doc | Purpose |
|---|---|
| [docs/REFLECTION_FRAMEWORKS.md](docs/REFLECTION_FRAMEWORKS.md) | Sober engineering translation of biological / physical / probabilistic metaphors into diagnostic principles |
| [docs/FRAMEWORK_COMPONENT_MAP.md](docs/FRAMEWORK_COMPONENT_MAP.md) | Maps each reflection concept to a professional name, repo layer, priority, and test strategy |
| [docs/DIAGNOSTIC_FRAMEWORK_ROADMAP.md](docs/DIAGNOSTIC_FRAMEWORK_ROADMAP.md) | Sequenced roadmap for future diagnostics (sensitivity, distribution shift, toxic quarantine, continuity mode) — none implemented yet |
| [docs/SIGNAL_REACTOR_MODEL.md](docs/SIGNAL_REACTOR_MODEL.md) | Doctrine for the Signal Reactor + Adaptive Routing model — translation table, master formula, banned theatrical names, safety invariants |
| [docs/SIGNAL_REACTOR_USAGE.md](docs/SIGNAL_REACTOR_USAGE.md) | How to read the advisory payload from `scripts/signal_reactor.py --example --json`, what each reactor state means, why "review candidate" is not execution |

The historical reference content (operator-control layer, perception-control
layer, phase 1/2 ingestion runbooks, chart-structure API, etc.) is preserved
below for context. Treat it as internal reference, not as the canonical
description of what the MVP does today.

---

# Pipeline V5.7 Core — historical reference

This repo is a local decision shell for inspecting seeded signal state, blocker state, action posture, and transition readiness. It is not a live trading system.

## Verified Now

- Local diagnostics run from checked-in Moltbook data and local signal ledger files.
- Runtime artifacts are stamped with a shared `run_id`, `source_mode`, `operating_mode`, `truth_origin`, `commit_hash`, and `config_fingerprint`.
- Execution remains governance-first and human-in-the-loop:
  - action reports now carry first-principles / competence / structured-learning advisory fields
  - paper entry sync stays suggestion-only unless explicit human approval is supplied
  - operator overrides can be logged with explicit first-principles reasoning
- The main repo-scoped test suite passes from `tests/`.
- The system can classify its current operating mode from local runtime state and environment flags.
- A first local paper-execution slice now exists:
  - decision ledger
  - paper order ledger
  - paper fill ledger
  - open paper positions ledger
  - paper close ledger
- A first Yahoo-assisted paper-retirement loop now exists:
  - external market mark artifact
  - bounded paper-trade retirement report
  - post-trade feedback ledger
  - model-upgrade summary artifact

## Not Yet Live

- No live quote adapter is wired.
- No live execution path is wired.
- No broker-backed or market-backed paper fill path exists.
- No broker-truth or venue-truth reconciliation loop exists.
- Yahoo Finance observation does not count as broker execution or economic proof.
- Local logic quality should not be confused with live readiness.

## Current Operating Stance

- Default mode is `seeded`.
- Default truth origin is `seeded`.
- Quote-provider handling is placeholder-only unless explicitly replaced later.
- External connectivity is optional and currently absent from the verified path.
- Optional read-only external ingestion is now available for Polymarket and Blockscout via explicit sync commands. It remains advisory and paper-safe.
- A real Polymarket Gamma-origin signal only enters the full decision pipeline through `python scripts\run_diagnostics_pipeline.py --summary --include-external-data`. Standalone report CLIs remain seed-neutral unless the current run explicitly carries external data through.
- A read-only Grok intelligence layer is now available for structured interpretation and signal ranking. It writes one stamped runtime artifact and remains execution-blind.

## Operator Control Layer

The repo now includes an additive operator-control slice designed for truthful manual governance.

- `runtime/operator_state.json`: optional manual operator state. No internal state is inferred if you do not log it.
- `runtime/signal_gate_summary.json`: hard admission gate summary over current signal rows.
- `logs/signal_kill_log.jsonl`: persistent rejected-signal log with explicit rejection dimensions and reasons.
- `runtime/active_work_block.json` and `logs/operator_block_events.jsonl`: manual/event-based selection, execution, context-switch, and closure logging.
- `runtime/operator_phase_balance.json` and `runtime/operator_phase_report.json`: transparent proxy scores for Phase 1/2/3 using logged drift, closure, gate behavior, tests, and artifact coverage.
- `config/structural_cover_map.json`: explicit mapping from exposed operator asymmetries to structural controls.
- Operator-control reports expose `manual_operator_state`; the health report keeps its separate derived `operator_pressure_state` label clearly marked as non-psychological.

Mode honesty is preserved:

- The operator-control layer is manual or event-driven unless an explicit runtime source exists.
- Timeliness is derived only from repo-visible signal identifiers when available.
- Closure is evaluated only from logged evidence. In the current repo default, any one of `output_exists`, `validation_exists`, or `report_exists` is enough, or the operator can explicitly mark a manual close.
- Phase scores are transparent proxy blends, not psychological truth claims.

## Perception Control Layer

The repo now includes a perception-control layer between signal refinement context and downstream action selection.

- `runtime/perception_control_report.json`: stamped runtime artifact for deprivation, injection, and high-constraint evaluation over current signal rows.
- `config/perception_control_config.json`: explicit thresholds and weights for suppression, surfacing, and survival checks.
- Deprivation suppresses low-value exposure before downstream ranking.
- Injection computes timing-aware `signal_lux`, `resurfacing_priority`, and `spectrum_class` so visibility is deliberate rather than generic.
- High-constraint evaluation applies structured promotion pressure before a candidate is surfaced as a stronger downstream review input.
- The layer is advisory and paper-safe. It does not imply live execution or autonomous trading authority.

## Repo Layout

- `scripts/`: runtime logic, diagnostics, adapters, and reports
- `moltbook/`: seeded local inputs
- `config/`: runtime configuration
- `tests/`: repo-scoped verification only
- `docs/`, `architecture/`, `scorecards/`, `prompts/`: supporting reference material and historical artifacts

## Repo-Scoped Verification

```powershell
python -m pytest -q tests
python scripts\repo_operating_mode.py --summary
python scripts\pipeline_health_report.py --summary --no-write
python scripts\experience_mode_report.py --summary
python scripts\environment_fit_report.py --summary
python scripts\complexity_ladder_controller.py --summary
python scripts\perception_control.py --summary
python scripts\governance_status.py --summary
python scripts\governance_feedback_report.py --summary
python scripts\closure_deficit_monitor.py --summary
python scripts\archetype_profile.py --summary
python scripts\artifact_coherence_check.py --summary
python scripts\operator_control.py report --summary
python scripts\paper_execution.py sync --summary
python scripts\operator_override_ledger.py --ticker RTX --override-action MONITOR --why-this-move "waiting for manual review" --trigger "review-ready candidate" --invalidation "cancel if validation weakens" --regime "review_ready" --why-now "blockers cleared this run" --summary
python scripts\yahoo_market_data_adapter.py --tickers RTX,ZIM --summary
python scripts\polymarket_gamma_adapter.py --summary
python scripts\polymarket_data_adapter.py --summary
python scripts\polymarket_clob_adapter.py --summary
python scripts\blockscout_adapter.py --summary
python scripts\external_data_runtime_sync.py --summary
python scripts\grok_xai_adapter.py --summary
python scripts\paper_trade_retirement.py --summary
python scripts\paper_reconciliation.py --summary
python scripts\run_diagnostics_pipeline.py --summary --no-write
python scripts\run_diagnostics_pipeline.py --summary --include-external-data
```

## Paper Path

The paper layer is now executable but still local-first and deterministic.

- Default current runtime sync records decision candidates only.
- Even with paper execution enabled, `paper_execution.py sync` does not open new paper entries unless you pass explicit human approval with `--approve-review-for-entry`.
- New paper orders and fills are created only when `PIPELINE_ENABLE_PAPER_EXECUTION=true`.
- Live execution remains blocked; the paper path refuses to run if live execution is enabled.
- Deterministic fill prices are used unless you supply manual `TICKER=PRICE` overrides.

Example PowerShell flow:

```powershell
python scripts\paper_execution.py sync --summary
$env:PIPELINE_ENABLE_PAPER_EXECUTION='true'
$env:PIPELINE_ENABLE_LIVE_EXECUTION='false'
python scripts\paper_execution.py sync --simulate-all-clear --summary
python scripts\paper_execution.py sync --simulate-all-clear --approve-review-for-entry --fill-price RTX=101.5 --fill-price ZIM=44.25 --summary
python scripts\operator_override_ledger.py --ticker RTX --override-action MONITOR --why-this-move "waiting for manual review" --trigger "review-ready candidate" --invalidation "cancel if validation weakens" --regime "review_ready" --why-now "blockers cleared this run" --summary
python scripts\governance_feedback_report.py --summary
python scripts\paper_execution.py close --position-id PAPER_POSITION_ID --exit-price 104.0 --close-reason TARGET_REACHED --summary
python scripts\yahoo_market_data_adapter.py --tickers RTX,ZIM,TLT --summary
python scripts\paper_trade_retirement.py --summary
python scripts\paper_reconciliation.py --summary
```

## Live Signal Ingestion Runbook

All live signals are ADVISORY_ONLY. No execution. No broker API. No order placement.

### Phase 1 — Polymarket, GDELT, SEC EDGAR

**Dry-run Polymarket (fetch only, no SQLite write):**
```powershell
python scripts\run_live_sources_phase1.py --source polymarket --dry-run
python scripts\run_live_sources_phase1.py --source polymarket --dry-run --json
```

**Write Polymarket signals to SQLite:**
```powershell
python scripts\run_live_sources_phase1.py --source polymarket --write
```

**Run all Phase 1 sources:**
```powershell
python scripts\run_live_sources_phase1.py --dry-run
python scripts\run_live_sources_phase1.py --write
```

SEC EDGAR requires `$env:SEC_USER_AGENT = "YourName your@email.com"`.

### Phase 2 — NewsAPI, Event Registry, Etherscan

**Dry-run NewsAPI:**
```powershell
$env:NEWS_API_KEY = "your-key"
python scripts\run_live_sources_phase2.py --source newsapi --dry-run --json
```

**Write NewsAPI signals to SQLite:**
```powershell
python scripts\run_live_sources_phase2.py --source newsapi --write
```

**Dry-run Event Registry:**
```powershell
$env:EVENT_REGISTRY_API_KEY = "your-key"
python scripts\run_live_sources_phase2.py --source event_registry --dry-run --json
```

**Write Event Registry signals to SQLite:**
```powershell
python scripts\run_live_sources_phase2.py --source event_registry --write
```

**Dry-run Etherscan (fetch public transactions for an address, no SQLite write):**
```powershell
$env:ETHERSCAN_API_KEY = "your-key"
python scripts\run_live_sources_phase2.py --source etherscan --address 0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae --dry-run --json
```

**Write Etherscan signals to SQLite:**
```powershell
$env:ETHERSCAN_API_KEY = "your-key"
python scripts\run_live_sources_phase2.py --source etherscan --address 0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae --write
```

**Etherscan with optional parameters:**
```powershell
python scripts\run_live_sources_phase2.py --source etherscan --address 0x... --max-transactions 10 --chain ethereum --dry-run
```

Etherscan is read-only. It fetches public transaction data only. No private keys, no wallet signing, no transaction broadcasting. Missing `ETHERSCAN_API_KEY` or `--address` skips cleanly with a logged reason.

Missing API keys skip cleanly with a logged reason — no crash.

### View signals via API

**Start the backend:**
```powershell
python scripts\api_server.py
```

**Query all signals:**
```
GET http://localhost:8000/live-signals
GET http://localhost:8000/live-signals?source=polymarket
GET http://localhost:8000/live-signals?source=gdelt
GET http://localhost:8000/live-signals?source=sec_edgar
GET http://localhost:8000/live-signals?source=newsapi
GET http://localhost:8000/live-signals?source=event_registry
GET http://localhost:8000/live-signals?source=etherscan
```

## Phase D.3 — Chart Structure API (Backend, Advisory-Only)

The `GET /chart-structure` endpoint exposes the chart structure engine as an advisory-only signal context. It reads OHLCV candles from the SQLite `signal_events` table (populated by `market_data` ingestion) and returns a full chart structure report. No orders are placed. No broker API is called.

All responses carry:
- `advisory_status = ADVISORY_ONLY`
- `execution_gate = LOCKED`
- `human_review_required = true`
- `ai_execution_count = 0`
- `broker_api_called = false`
- `broker_order_id = NONE`

### Prerequisite: ingest market data

```powershell
python scripts\run_live_sources_phase2.py --source market_data --write
```

### Request examples

**Chart structure for a symbol (basic):**
```
GET http://localhost:8000/chart-structure?symbol=AAPL
```

**Chart structure with a limit on how many recent events to scan:**
```
GET http://localhost:8000/chart-structure?symbol=AAPL&limit=50
```

**Chart structure linked to a specific signal event:**
```
GET http://localhost:8000/chart-structure?symbol=AAPL&source_event_id=EVT_market_data_AAPL_20260101
```

### Response shape

```json
{
  "symbol": "AAPL",
  "source_event_id": null,
  "candle_count": 5,
  "advisory_status": "ADVISORY_ONLY",
  "execution_gate": "LOCKED",
  "human_review_required": true,
  "ai_execution_count": 0,
  "broker_api_called": false,
  "broker_order_id": "NONE",
  "report": {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "human_review_required": true,
    "ai_execution_count": 0,
    "broker_api_called": false,
    "broker_order_id": "NONE",
    "summary": { ... },
    "candle_anatomy": { ... },
    "trend": { ... },
    "volatility": { ... },
    "support_resistance": { ... },
    "context": { "chart_state": "TRENDING_UP", ... },
    "advisory": {
      "advisory_summary": "Chart structure shows an upward trend. Human review required.",
      "suggested_next_step": "WATCH_ONLY"
    }
  }
}
```

If no OHLCV data is available for the symbol, `chart_state` is `INSUFFICIENT_DATA` and `report` is `null` — the endpoint never crashes.

### What it does not do

- Does not place orders
- Does not connect to any broker API
- Does not produce buy/sell/execute instructions
- Does not depend on TradingView, paid charting, or wallet APIs
- Does not require live internet (reads from local SQLite only)

### View signals in the frontend

1. Start the backend: `python scripts\api_server.py`
2. Start the frontend: `cd frontend && npm run dev`
3. Navigate to `/live-signals`
4. Use the source filter buttons: All Sources / Polymarket / GDELT / SEC EDGAR / NewsAPI / Event Registry / Etherscan
5. Use the search bar to filter by title, market ID, domain, publisher, etc.

All signals display `ADVISORY_ONLY`, `HUMAN_REVIEW_REQUIRED`, and `EXECUTION LOCKED` badges.

## Phase D.4 — Chart Structure Frontend Panel (Advisory-Only)

**Route:** `/chart-structure`

**Sidebar nav item:** Chart Structure (◫)

### What it does

- Renders an interactive symbol-lookup panel in the frontend
- Calls `GET /chart-structure?symbol=<symbol>&limit=<limit>` from the browser
- Displays: symbol, chart state, candle count, trend direction + strength, volatility regime, latest close, support/resistance proximity, confirmation score with reasons, advisory summary, suggested next step
- All execution invariants are always visible: `ADVISORY_ONLY`, `execution_gate=LOCKED`, `HUMAN_REVIEW_REQUIRED`, `AI_EXECUTION_COUNT=0`, `broker_api_called=false`, `broker_order_id=NONE`
- Handles empty / backend-offline / insufficient-data states with clear messaging

### What it does not do

- No buy button, sell button, execute button, place order button
- No auto-trade wording or broker order UI
- No broker API connection of any kind
- No order placement, wallet signing, or live execution

### Usage

1. Start the backend: `python scripts\api_server.py`
2. Ingest market data (required for candles): `python scripts\run_live_sources_phase2.py --source market_data --write`
3. Start the frontend: `cd frontend && npm run dev`
4. Navigate to `/chart-structure`
5. Enter a symbol such as `AAPL`, `BTC-USD`, or `RELIANCE.NS`
6. Set candle limit (default 100, max 500)
7. Click **Fetch**

### Safety banner

Every page load shows:

> **Chart structure is advisory-only. No execution. Human review required.**

All results carry `ADVISORY_ONLY`, `execution_gate=LOCKED`, and `HUMAN_REVIEW_REQUIRED` badges.

### New files

| File | Purpose |
|---|---|
| `frontend/src/app/chart-structure/page.tsx` | Chart Structure page |

### Modified files

| File | Change |
|---|---|
| `frontend/src/types/index.ts` | Added `ChartStructureResponse`, `ChartStructureReport`, and supporting types |
| `frontend/src/lib/apiClient.ts` | Added `getChartStructure(symbol, limit?, sourceEventId?)` |
| `frontend/src/components/layout/Sidebar.tsx` | Added Chart Structure nav item |

## Yahoo-Assisted Retirement Limits

- Yahoo Finance marks are external observation for paper workflows only.
- Successful Yahoo fetches can truthfully move a paper run into `hybrid` mode because external observation is present.
- Failed Yahoo fetches are persisted as failure states and do not imply hybrid readiness.
- Paper retirements remain paper-simulated closes using external marks, not broker fills.
- Small-sample feedback is recorded, but the repo still reports insufficient evidence for parameter changes unless enough retired trades accumulate.

## External Data Limits

- Polymarket Gamma, Data, and CLOB integrations are read-only observational adapters.
- Blockscout integration is read-only explorer/API ingestion and may have partial endpoint coverage depending on whether you point it at a per-instance explorer or the multichain PRO API.
- No order placement, wallet signing, live execution, or secret material is hardcoded.
- External-data success can move a run into `hybrid` mode because external observation is present, but that still does not imply execution readiness or venue truth.

## External Bridge Modes

- `seeded`: no external observation mode requested; SCM remains seeded.
- `hybrid_observation`: external observations are attached as read-only context, but no external candidates are admitted into SCM.
- `external_candidate_validation`: valid external observations are admitted as paper-safe SCM candidate rows.

## Signal Refinery MVP_1

This repo now includes an additive read-only public-data subsystem under `src/` for a geopolitical / narrative / prediction-market signal refinery MVP.

### Doctrine

- Detect widely.
- Classify intent early.
- Reject aggressively.
- Validate durable signals.
- Paper-trade before capital.
- Execute only after proof.

The edge is disciplined refusal, not speed.

### What It Does

- fetches public Polymarket market data through a read-only client with deterministic mock fallback
- scores markets for engineered attention versus durable evidence
- classifies each market into `IGNORE`, `WATCH`, `VALIDATE`, or `PAPER_TRADE`
- stores raw snapshots, processed scores, attention clusters, rejected signals, and paper trades in SQLite
- supports a paper-only dashboard and explanatory output layer

### What It Does Not Do

- live trading
- wallet or private-key handling
- authenticated order placement
- signed Polymarket orders
- broker integration
- capital deployment logic

This is a read-only signal-refinery MVP.
It does not provide financial advice.
It does not execute trades.
It does not handle wallets or private keys.
It uses public data to test signal classification and paper-trading logic.
Real capital should not be connected until the paper system is validated.

### Governing Formulas

`Signal Problem ≠ Truth vs Falsehood`

`Signal Problem = Durable Evidence vs Engineered Attention`

`Detected Signal ≠ Valid Signal ≠ Actionable Signal`

`AI Output = Explanation Layer`

`Pipeline Score = Decision Layer`

`MVP_1 = Public Data + Scoring + Dashboard + Paper Trade`

`Alpha = Refusal Quality + Validation Discipline + Execution Patience`

`False Claim ≠ Zero Value`

`False Claim = Low Truth Value + Possible Attention Value`

`Good MVP = Signal Refinery`

`Bad MVP = Premature Trading Bot`

`NetSignalValue = MarketMispricing × EvidenceQuality × Durability × Liquidity - EngagementManipulation - ExecutionFriction`

`ReadyForLive = PaperAccuracy > θa AND Drawdown < θd AND APIStability = True AND WalletSecurity = True`

`ReadyForLive` is roadmap only and is not implemented.

### Scoring Stack

- `EMS = 0.20*EmotionalIntensity + 0.15*HeadlineExtremity + 0.15*NarrativeRecycling + 0.15*ViralitySpike + 0.15*CuriosityGap - 0.10*EvidenceDensity - 0.10*SourceCredibility`
- `EQS = 0.25*PrimarySourceWeight + 0.20*SourceCredibility + 0.20*ConfirmationCountNorm + 0.15*RecencyScore + 0.10*CrossSourceDiversity - 0.10*ContradictionPenalty`
- `DS = 0.25*Persistence + 0.25*StressSurvival + 0.20*CrossSourceConfirmation + 0.15*TimeStability + 0.15*ContradictionResistance`
- `LS = 0.35*LiquidityNorm + 0.30*VolumeNorm + 0.20*OrderBookDepthNorm - 0.15*SpreadPenalty`
- `EFS = 0.25*SpreadPenalty + 0.25*LowLiquidityPenalty + 0.20*VolatilityPenalty + 0.20*TimingRisk + 0.10*APIUncertaintyPenalty`
- `ModelProbability = clip(0.50 + 0.25*(EQS-0.50) + 0.20*(DS-0.50) - 0.15*EMS - 0.10*EFS, 0.01, 0.99)`
- `APS = 0.30*EQS + 0.25*DS + 0.20*LS + 0.15*MarketMispricingEstimate - 0.20*EMS - 0.15*EFS`

### State Classification

- `IGNORE`: high manipulation / low evidence, or friction too high
- `WATCH`: early but incomplete
- `VALIDATE`: promising and durable enough for deeper review
- `PAPER_TRADE`: strongest paper-only candidates with sufficient evidence, durability, liquidity, and manageable friction

### Storage and Dashboard

- SQLite path: `data/processed/signal_refinery.sqlite`
- Streamlit app: `src/dashboard/streamlit_app.py`
- Run ingestion: `python scripts\run_ingestion.py --summary`
- Run scoring: `python scripts\run_scoring.py --summary`
- Run paper trading: `python scripts\run_paper_trading.py --summary`
- Run dashboard helper: `python scripts\run_dashboard.py`
- `unavailable`: external mode was requested, but zero valid observations survived provider/data-quality checks; the system fails closed.

All bridge modes remain advisory and paper-safe. They do not enable capital deployment or broker execution.

## Grok Intelligence Limits

- Grok is an intelligence-extraction layer, not an execution layer.
- It can interpret payloads and rank current candidates, but it does not approve trades or alter governance.
- It requires explicit `XAI_API_KEY`, `XAI_API_BASE_URL`, and `XAI_MODEL` configuration.
- If the API call fails or the returned payload is not valid structured JSON, the repo persists that failure state explicitly in `runtime/grok_xai_report.json`.

## Reconciliation Layer

The repo now writes a cumulative paper reconciliation history and summary.

- `logs/paper_reconciliation_history.jsonl` accumulates one reconciled row per closed paper trade.
- `runtime/paper_reconciliation_summary.json` tracks cumulative expectancy, win/loss, and data-gap metrics.
- `runtime/paper_reconciliation_report.json` reports the latest reconciliation pass and merge counts.
- This measures paper lineage quality and paper expectancy. It is still not economic proof of a live system.

## Experience Ladder

The repo now has a first additive experience/readiness report for trainer/utility/jet-style surfaces.

- `runtime/experience_mode_report.json` summarizes trainer-mode metadata, visibility/lineage legibility, readiness scaffolding, degraded-mode flags, and premium-surface eligibility.
- `runtime/complexity_ladder_controller.json` interprets that report into advisory surface exposure flags for trainer, utility, and premium operator views.
- `runtime/environment_fit_report.json` adds advisory environment-fit, robustness-vs-precision, locality, dependency-fragility, and anti-overcustomization summaries.
- That report now also includes a `truth_boundary_summary` block separating observed repo evidence, heuristic inference, placeholders, and items that still need real data or live APIs for full validation.
- The current tree should still be interpreted as trainer / early-utility phase.
- These experience/complexity reports are advisory only. They do not change decisioning or execution behavior.

## Manual Operator Control Commands

Examples:

```powershell
python scripts\operator_control.py state --active-objective "ship operator control MVP" --active-task "wire phase report" --operator-mode focused --baseline-score 0.42 --current-score 0.58 --peak-score 0.73 --note "manual-only input"
python scripts\operator_control.py start-block --objective "ship operator control MVP" --success-metric "tests green" --time-boundary "90m" --active-task "wire gate" --non-goal "rewrite paper flow" --block-type coding
python scripts\operator_control.py log-event --event-type execution_started
python scripts\operator_control.py log-event --event-type context_switch --reason "checked adjacent module before closing"
python scripts\operator_control.py close-block --output-exists
python scripts\operator_control.py report --summary
```

## Known Coherence Gap

- `runtime/signal_vocoder_report.json` is a legacy unmanaged artifact in the current tree.
- It does not carry the repo's current runtime metadata contract.
- Do not treat it as proof that all runtime outputs are coherent until its producer is either patched or retired.

## Environment Template

Copy `.env.example` into your local environment management flow if you want to test paper/live-prepared mode flags later. The checked-in verified path does not require secrets.

## Local Advisory MVP — SQLite Persistence (Step 3)

The local advisory MVP persists signal events, reflections, AI summaries, decisions, manual trades, reconciliations, and Moltbook entries in a local SQLite database.

**DB path:** `runtime/mvp_local.db` (auto-created; `runtime/` is gitignored)

### Start the advisory API server

```powershell
python -m pip install fastapi uvicorn
python -m uvicorn scripts.api_server:app --reload
# or
python scripts/api_server.py
```

### New endpoints (Step 3)

| Endpoint | Description |
|---|---|
| `GET /manual-trades` | List all persisted manual trade records |
| `GET /source-health` | Fabric health snapshot (also logs to source_health table) |
| `GET /db/status` | Table row counts and DB file info |

### DB tables

`signal_decisions`, `user_reflections`, `ai_discussion_summaries`, `manual_trades`, `reconciliation_results`, `moltbook_entries`, `source_health`, `export_logs`

### Reset the local DB

```powershell
# Delete the DB — it will be auto-recreated on next API call
Remove-Item runtime\mvp_local.db -ErrorAction SilentlyContinue
```

### Run the advisory MVP frontend

```powershell
cd frontend
npm install
npm run dev
# open http://localhost:3000
```

### Run persistence tests

```powershell
python -m pytest tests/test_persistence.py -v
```

### Advisory safety rules (never change)

- `advisory_status = "ADVISORY_ONLY"` on every record
- `execution_mode = "HUMAN_ONLY"` on every trade record
- `ai_execution_count = 0` always
- `broker_api_called = False` always
- `broker_order_id = "NONE"` always (unless human-entered external reference)
- No buy/sell/execute endpoint exists. No broker API. No order placement.

## Offline-First Notes

- The verified path runs fully local.
- Do not treat placeholder adapters as live integrations.
- Keep external contact bounded and explicit if real data or execution is added later.

## Frontend — Signal Intelligence Cockpit

A Next.js frontend scaffold lives in `frontend/`. It is an advisory-only intelligence dashboard — no broker connection, no execution UI, no API keys.

### Requirements

- Node.js 18+ and npm

### Install and run

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000` in your browser.

### Build for production

```powershell
cd frontend
npm run build
npm run start
```

### Pages

| Route | Description |
|---|---|
| `/` | Dashboard — fabric state, status breakdown, top signals |
| `/signal-inbox` | Filterable signal list with state badges |
| `/signal-inbox/[id]` | Signal detail, score panel, evidence timeline, reflection |
| `/reflection-desk` | Human reflections and AI advisory context per signal |
| `/moltbook` | Self-correction and mistake-learning entries |
| `/manual-trade-log` | Record trades placed manually (HUMAN_ONLY) |
| `/reconciliation` | Match logged trades to actual outcomes |
| `/exports` | Download JSON/CSV exports of all advisory data |
| `/settings` | System constants and safety information |

### Safety rules enforced in the UI

- No Buy, Sell, Execute, or Auto-trade buttons exist anywhere in the UI.
- All trade actions are labelled **Log Manual Trade**.
- All signal actions carry **ADVISORY_ONLY** and **HUMAN_REVIEW_REQUIRED**.
- All trade-related UI carries **HUMAN_ONLY**.
- AI execution count displays `0` on every page and in every response shape.
- A persistent top banner states: **"This system does not place trades."**
- `EXECUTION_GATE: LOCKED` is shown in the header on every page.

### Data

Step 1 uses mock data in `frontend/src/lib/mockData.ts` that mirrors the FastAPI response shapes from `scripts/signal_inbox_api.py` and `scripts/moltbook_api.py`. Live backend connection is Step 2.

---

## Serious Local MVP Runbook

> **This MVP is advisory-only. It does not place trades. It has no broker execution path.**
>
> `advisory_status = ADVISORY_ONLY` | `execution_mode = HUMAN_ONLY` | `ai_execution_count = 0` | `broker_api_called = False`

### Prerequisites

```powershell
python -m pip install fastapi uvicorn requests
cd frontend
npm install
cd ..
```

### Start the full local stack

Open **three separate terminals** in the repo root.

**Terminal 1 — FastAPI advisory server**

```powershell
python -m uvicorn scripts.api_server:app --reload
# Server starts at http://localhost:8000
# Docs: http://localhost:8000/docs
```

**Terminal 2 — Next.js frontend**

```powershell
cd frontend
npm run dev -- -p 3000
# Dashboard at http://localhost:3000
# Note: port 3000 is required -- the sleepingpassenger proxy forwards port 80 -> 3000.
# If port 3000 is busy, stop the existing Next.js process first.
```

**Terminal 3 — Phase 1 live source ingestion**

```powershell
# Dry-run first (fetch only — no DB write):
python scripts/run_live_sources_phase1.py --dry-run --json

# Write run (fetch and persist to SQLite):
python scripts/run_live_sources_phase1.py --write
```

**Terminal 4 — Phase 2 live source ingestion (NewsAPI)**

Requires `NEWS_API_KEY` environment variable. Skips cleanly if unset.

```powershell
# Dry-run — fetch and normalize, no DB write:
python scripts/run_live_sources_phase2.py --source newsapi --dry-run --json

# Write run — fetch, normalize, and persist to SQLite:
python scripts/run_live_sources_phase2.py --source newsapi --write

# Custom query:
python scripts/run_live_sources_phase2.py --source newsapi --dry-run --query "AI semiconductors"
```

All NewsAPI signals are `ADVISORY_ONLY`, `HUMAN_REVIEW_REQUIRED`, `execution_gate=LOCKED`,
`ai_execution_count=0`, `broker_api_called=false`.

### Browser

| URL | Description |
|---|---|
| `http://localhost:3000` | Dashboard — fabric state, status breakdown, top signals |
| `http://localhost:3000/live-signals` | Live signal events from Phase 1 + Phase 2 sources |
| `http://localhost:3000/signal-inbox` | Filterable signal inbox |
| `http://localhost:3000/reflection-desk` | Human reflections and AI advisory context |
| `http://localhost:3000/manual-trade-log` | Record trades placed manually (HUMAN_ONLY) |
| `http://localhost:3000/moltbook` | Mistake-learning entries |
| `http://localhost:3000/reconciliation` | Match logged trades to actual outcomes |
| `http://localhost:3000/exports` | Download JSON/CSV exports |

### Run the smoke test

```powershell
# Quick local verification (mocks Phase 1 runner):
python scripts/local_mvp_smoke_test.py --skip-live-source

# Full check including Phase 1 dry-run (requires internet for Polymarket / GDELT):
python scripts/local_mvp_smoke_test.py

# JSON report:
python scripts/local_mvp_smoke_test.py --json
```

### Run the full test suite

```powershell
python -m pytest tests -q
python -m pytest tests/test_local_mvp_smoke_test.py -v
python -m pytest tests/test_persistence.py -v
```

### Compile-check all scripts and tests

```powershell
python -m compileall scripts tests
```

### Reset the local DB

```powershell
# Wipe the SQLite DB — auto-recreated on next API call or source run
Remove-Item runtime\mvp_local.db -ErrorAction SilentlyContinue
```

### Phase C Integrated Source Matrix

All sources are `execution_permission = ADVISORY_ONLY`. No auto-trading path exists for any source.

| Source | Phase | Env var (if any) | Status | CLI dry-run | CLI write | Frontend filter | Persistence |
|---|---|---|---|---|---|---|---|
| `polymarket` | 1 | — | Active | `run_live_sources_phase1.py --source polymarket --dry-run --json` | `--write` | Polymarket | signal_events / source_run_log |
| `gdelt` | 1 | — | Active | `run_live_sources_phase1.py --source gdelt --dry-run --json` | `--write` | GDELT | signal_events / source_run_log |
| `sec_edgar` | 1 | `SEC_USER_AGENT` | Skips cleanly if unset | `run_live_sources_phase1.py --source sec_edgar --dry-run --json` | `--write` | SEC EDGAR | signal_events / source_run_log |
| `newsapi` | 2 | `NEWS_API_KEY` | Skips cleanly if unset | `run_live_sources_phase2.py --source newsapi --dry-run --json` | `--write` | NewsAPI | signal_events / source_run_log |
| `event_registry` | 2 | `EVENT_REGISTRY_API_KEY` | Skips cleanly if unset | `run_live_sources_phase2.py --source event_registry --dry-run --json` | `--write` | Event Registry | signal_events / source_run_log |
| `etherscan` | 2 | `ETHERSCAN_API_KEY` | Skips cleanly if unset or no address | `run_live_sources_phase2.py --source etherscan --dry-run --json` | `--write` | Etherscan | signal_events / source_run_log |
| `grok_xai` | 2 | `XAI_API_KEY` | Skips cleanly if unset | `run_live_sources_phase2.py --source grok_xai --dry-run --json` | `--write` | Grok/xAI | signal_events / source_run_log |
| `market_data` | 2 | — (yfinance) | Active | `run_live_sources_phase2.py --source market_data --dry-run --json` | `--write` | Market Data | signal_events / source_run_log |
| `india` | 2 | — | Active (NSE/RBI/SEBI public) | `run_live_sources_phase2.py --source india --dry-run --json` | `--write` | India | signal_events / source_run_log |
| `global_filings` | 2 | — (ASX active; others placeholder) | ASX active, rest skip cleanly | `run_live_sources_phase2.py --source global_filings --dry-run --json` | `--write` | Global Filings | signal_events / source_run_log |
| `asia_disclosure` | 2 | — (all placeholder) | All skip cleanly | `run_live_sources_phase2.py --source asia_disclosure --dry-run --json` | `--write` | Asia Disclosure | signal_events / source_run_log |

All 11 sources set `advisory_status = ADVISORY_ONLY`, `execution_gate = LOCKED`,
`human_review_required = True`, `ai_execution_count = 0`, and `broker_api_called = False` on
every normalized record. `broker_order_id = NONE` on global_filings and asia_disclosure records.

Run the static integration audit at any time:

```powershell
python scripts/phase_c_final_audit.py --verbose
```

### Advisory safety rules (permanent — never change)

- No Buy, Sell, Execute, or Auto-trade button or endpoint exists anywhere.
- `execution_mode = HUMAN_ONLY` on every trade record.
- `advisory_status = ADVISORY_ONLY` on every record.
- `ai_execution_count = 0` always.
- `broker_api_called = False` always.
- `broker_order_id = NONE` always.
- `execution_gate = LOCKED` on every signal event.
- No `.env` contains broker credentials. No broker API is imported.

## Local Auto-Start, 5-Minute Refresh, and sleepingpassenger URL

These Windows helper scripts auto-start the full local advisory MVP stack at logon, refresh live signals every 5 minutes, and serve the frontend at `http://sleepingpassenger`.

**Local-only setup.** This uses a Windows hosts-file alias pointing `sleepingpassenger` at `127.0.0.1`. It does not configure public DNS, cloud hosting, or internet access.

### One-time setup

**1. Add local host aliases (requires Administrator):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1
```

Adds to `C:\Windows\System32\drivers\etc\hosts`:

```
127.0.0.1 sleepingpassenger
127.0.0.1 sleepingpassenger.local
```

**2. Register startup task (runs at logon):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\register_mvp_startup_task.ps1
```

Registers Windows Scheduled Task `PipelineV57LocalMVP` to launch `start_mvp_stack.ps1` at user logon with highest privileges (required for the port-80 proxy).

### Manual run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start_mvp_stack.ps1
```

Opens four separate PowerShell windows:

| Window | Command | URL |
|---|---|---|
| Backend | `python -m uvicorn scripts.api_server:app --reload` | `http://localhost:8000` |
| Frontend | `npm run dev -- -p 3000` (in `frontend/`, port pinned) | `http://localhost:3000` |
| Poller | `poll_live_sources.ps1` | runs every 300 s |
| Proxy | `start_sleepingpassenger_proxy.ps1` | port 80 → port 3000 |

### URLs

| URL | Notes |
|---|---|
| `http://sleepingpassenger` | Requires host alias + port-80 proxy (Administrator) |
| `http://sleepingpassenger.local` | Requires host alias + port-80 proxy (Administrator) |
| `http://localhost:3000` | Direct frontend — always available, no proxy needed |
| `http://localhost:8000` | Backend API |
| `http://localhost:8000/docs` | API docs (Swagger UI) |

Backend remains `http://localhost:8000` in all cases.

### Stop / unregister

```powershell
# Unregister the startup task:
powershell -ExecutionPolicy Bypass -File scripts\windows\unregister_mvp_startup_task.ps1

# Remove host aliases (requires Administrator):
powershell -ExecutionPolicy Bypass -File scripts\windows\remove_sleepingpassenger_host_alias.ps1
```

### Logs

All logs write to `runtime/logs/` (gitignored):

| File | Content |
|---|---|
| `runtime/logs/live_source_poller.log` | Timestamped poller runs (polymarket, gdelt, market_data) |
| `runtime/logs/sleepingpassenger_proxy.log` | Reverse proxy activity and errors |

### Port 80 and Administrator privileges

The reverse proxy (`local_frontend_reverse_proxy.py`) binds port 80 so the frontend is reachable at `http://sleepingpassenger` without a port number. On Windows, port 80 requires Administrator or a `netsh` port-sharing rule. If the proxy cannot bind, it prints a clear message and you can use `http://localhost:3000` instead.

The startup task runs with highest privileges so the proxy can bind port 80 at logon.

### Scripts added

| Script | Purpose |
|---|---|
| `scripts/windows/start_mvp_stack.ps1` | Launch all four processes |
| `scripts/windows/poll_live_sources.ps1` | 300-second advisory signal poller |
| `scripts/windows/register_mvp_startup_task.ps1` | Register logon auto-start task |
| `scripts/windows/unregister_mvp_startup_task.ps1` | Remove logon auto-start task |
| `scripts/windows/add_sleepingpassenger_host_alias.ps1` | Add hosts-file aliases |
| `scripts/windows/remove_sleepingpassenger_host_alias.ps1` | Remove hosts-file aliases |
| `scripts/windows/start_sleepingpassenger_proxy.ps1` | Start port-80 reverse proxy |
| `scripts/windows/local_frontend_reverse_proxy.py` | Python HTTP reverse proxy (stdlib only) |

### Safety invariant

The poller runs only these advisory/read-only commands — no broker API, no order placement:

```powershell
python scripts\run_live_sources_phase1.py --source polymarket --write
python scripts\run_live_sources_phase1.py --source gdelt --write
python scripts\run_live_sources_phase2.py --source market_data --write
python scripts\update_ohlcv_latest.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --interval 1d --lookback-days 10 --write
```

`advisory_status = ADVISORY_ONLY` on every ingested record.

---

## Phase E.3 — Real OHLCV History + Incremental Candle Updater

### OHLCV data modes

| Mode | Script | Data | Use |
|---|---|---|---|
| Demo seed (offline) | `scripts/seed_chart_ohlcv_history.py` | **Synthetic, NOT real market prices** | UI demo without internet |
| Real historical backfill | `scripts/backfill_ohlcv_history.py` | Real OHLCV via yfinance (free) | Full history for chart analysis |
| Incremental refresh | `scripts/update_ohlcv_latest.py` | Real recent candles via yfinance | 5-minute poller, keeps DB current |

> **Important:** `seed_chart_ohlcv_history.py` creates deterministic **synthetic** sample candles
> generated with a random number generator. They are **not real market prices** and must not be
> used for analysis or decision-making. Use `backfill_ohlcv_history.py` for real data.

### Commands

**Demo-only seed (synthetic, no internet required):**

```bash
python scripts/seed_chart_ohlcv_history.py --write
```

**Real historical backfill (requires yfinance + internet):**

```bash
# Install dependency if needed:
python -m pip install yfinance

# Backfill full history (may fetch several years per symbol):
python scripts/backfill_ohlcv_history.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --period max --interval 1d --write

# Dry-run (prints JSON, no DB write):
python scripts/backfill_ohlcv_history.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --period max --interval 1d
```

**Incremental update (safe to run every 5 minutes):**

```bash
python scripts/update_ohlcv_latest.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --interval 1d --lookback-days 10 --write
```

**Start full local stack:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start_mvp_stack.ps1
```

### Chart Structure data preference

The `/chart-structure` API endpoint:
1. Queries candles for the requested symbol directly (symbol-filtered DB query — no per-symbol cap)
2. Prefers **real backfill** candles (`ohlcv_*` event IDs) over demo seed (`seed_ohlcv_*`) for the same date
3. Returns up to `limit` (default 100) candles in chronological order
4. Falls back to seed candles for dates not covered by real data

### Event ID scheme

| Source | Event ID format | Example |
|---|---|---|
| Demo seed | `seed_ohlcv_{symbol}_{YYYY-MM-DD}` | `seed_ohlcv_aapl_2024-01-15` |
| Real backfill / incremental | `ohlcv_{symbol}_{interval}_{YYYY-MM-DD}` | `ohlcv_aapl_1d_2024-01-15` |

Both use `INSERT OR IGNORE` — re-running either script is fully idempotent.

### Dependency

yfinance is required for real data. The seed script has no external dependencies.

```bash
python -m pip install yfinance
```

### Safety invariant (unchanged)

All OHLCV records carry:

```
advisory_status    = ADVISORY_ONLY
execution_gate     = LOCKED
human_review_required = True
ai_execution_count = 0
broker_api_called  = False
broker_order_id    = NONE
```

No broker API is called. No orders are placed. No private keys are used.

---

## Phase E.5 — Silent local startup

Starts the full MVP stack in the background with no visible PowerShell windows.
All output is redirected to `runtime\logs\`.

### Scripts

| Script | Purpose |
|---|---|
| `scripts\windows\start_mvp_stack_silent.ps1` | Start backend, frontend, poller, proxy silently |
| `scripts\windows\stop_mvp_stack_silent.ps1` | Stop all MVP stack processes by command-line pattern |
| `scripts\windows\register_mvp_silent_startup_task.ps1` | Register Windows Scheduled Task at logon |
| `scripts\windows\unregister_mvp_silent_startup_task.ps1` | Remove the scheduled task |

### One-time setup

```powershell
# 1. Add sleepingpassenger host alias (run as Administrator, once):
powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1

# 2. Register silent auto-start task (run as Administrator for port 80):
powershell -ExecutionPolicy Bypass -File scripts\windows\register_mvp_silent_startup_task.ps1
```

### Manual start / stop

```powershell
# Start silently (idempotent — skips components already running):
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File scripts\windows\start_mvp_stack_silent.ps1

# Stop all MVP stack processes:
powershell -ExecutionPolicy Bypass -File scripts\windows\stop_mvp_stack_silent.ps1
```

### After startup

| URL | Notes |
|---|---|
| `http://sleepingpassenger` | Requires host alias + port-80 proxy (Administrator) |
| `http://localhost:3000` | Frontend direct |
| `http://localhost:8000/health` | Backend health check |

### Logs

All logs are written to `runtime\logs\`:

| File | Content |
|---|---|
| `silent_startup.log` | Startup progress and port-ready timestamps |
| `silent_stop.log` | Process stop events |
| `backend_stdout.log` / `backend_stderr.log` | uvicorn output |
| `frontend_stdout.log` / `frontend_stderr.log` | Next.js dev server output |
| `poller_stdout.log` / `poller_stderr.log` | poll_live_sources.ps1 output |
| `proxy_stdout.log` / `proxy_stderr.log` | sleepingpassenger proxy output |

### Safety invariant (unchanged)

Advisory only. No broker API is called. No orders are placed.

---

## Run local frontend as http://sleepingpassenger/

Simpler alternative to the reverse-proxy path above: bind Next.js dev server directly
to port 80 so `http://sleepingpassenger/` works without a separate proxy process.

Backend is unchanged — FastAPI continues to serve on `http://127.0.0.1:8000`. The
frontend reads it from `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local`.

### One-time hosts entry (Administrator PowerShell)

```powershell
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" -Value "`n127.0.0.1 sleepingpassenger"
ipconfig /flushdns
ping sleepingpassenger
```

### Start the backend (regular PowerShell)

```powershell
cd C:\Users\akash\sleeping-passenger-v1
python -m uvicorn scripts.api_server:app --host 127.0.0.1 --port 8000 --reload
```

### Start the frontend on port 80 (Administrator PowerShell)

Port 80 binding on Windows requires Administrator. Use either:

```powershell
cd C:\Users\akash\sleeping-passenger-v1\frontend
npm run dev:sleepingpassenger
```

Or the preflight helper (checks hosts entry and port 80 availability first):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start_sleepingpassenger_local.ps1
```

Then open:

```
http://sleepingpassenger/
```

### Verify

```powershell
ping sleepingpassenger
netstat -ano | findstr ":80"
```

### Fallback if port 80 is blocked

If Administrator is unavailable, port 80 is held by IIS/Skype/another service, or
the bind otherwise fails, use the standard dev script:

```powershell
cd C:\Users\akash\sleeping-passenger-v1\frontend
npm run dev
# open http://localhost:3000
```

The existing reverse-proxy path (`scripts\windows\start_sleepingpassenger_proxy.ps1`)
is also still available — it runs Next.js on 3000 and proxies 80 → 3000.
