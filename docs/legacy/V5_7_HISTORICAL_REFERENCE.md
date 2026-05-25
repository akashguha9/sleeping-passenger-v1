# Pipeline V5.7 — Historical Reference (legacy, non-canonical)

> **This document is preserved for historical context only.**  The content
> below was once part of the top-level README.  It is **not** the canonical
> description of what the MVP does today.  See the main `README.md` and
> `docs/ARCHITECTURE.md` for the current canonical workflow.
>
> The advisory-only safety contract still applies to every artifact below:
> `advisory_status="ADVISORY_ONLY"`, `execution_gate="LOCKED"`,
> `broker_api_called=false`, `ai_execution_count=0`.

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
