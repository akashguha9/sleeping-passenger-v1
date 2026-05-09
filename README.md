# Pipeline V5.7 Core

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
pip install fastapi uvicorn
uvicorn scripts.api_server:app --reload
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
