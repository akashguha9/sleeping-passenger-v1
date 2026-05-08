# Pipeline V5.7 Core

This repo is a **research/demo MVP** local decision shell for inspecting seeded signal state, blocker state, action posture, and transition readiness. It is **not a live trading system**, **not financial advice**, **not deployable**, and **not decision-ready**.

> **Honest stance:** every diagnostic in this repo runs against seeded fixtures. Seeded/demo data is never external truth. Capital deployment, investment advice, and automated execution are explicitly forbidden by the canonical action-permission contract until external truth, calibration, and position reconciliation gates are passed.

## Canonical Truth → Decision → Action-Permission Spine

The repo carries a typed canonical contract (added in `scripts/runtime_contracts.py` and used by the health report):

```
truth origin → evidence ledger → validation status → calibration honesty
            → state/veto logic → position reconciliation
            → canonical action permission → decision ledger → health report honesty
```

Key invariants enforced by tests:

- `SEEDED` and `DEMO` truth origins are never counted as external truth.
- `external_signal_count == 0` ⇒ `canonical_action_permission = BLOCK_CAPITAL`.
- `position_integrity_state == DIVERGED` ⇒ blocks capital.
- `policy_state == RESTRICTED` ⇒ blocks capital unless demo/research only.
- Active chaos veto ⇒ block capital or quarantine.
- Missing calibration ⇒ no decision-ready claim.
- Disabled contextual interpretation ⇒ confidence downgrade warning.
- Forbidden state-machine transitions (e.g. `MIURA → GALLARDO` without `HURACAN` validation, `DIABLO → DEPLOY`, `JAIL → DEPLOY`, `HURACAN → DEPLOY` without validation floor) raise `StateMachineError`.

The health report summary now exposes:

```
canonical_action_permission=...
veto_reasons=[...]
truth_origin_breakdown=...
external_truth_status=...
evidence_ledger_status=...
decision_ledger_status=...
calibration_status=...
allowed_use=...
forbidden_use=...
canonical_position_integrity_state=...
```

In the seeded MVP runtime, the honest output is:

```
canonical_action_permission=BLOCK_CAPITAL
veto_reasons=[NO_EXTERNAL_TRUTH, SEEDED_TRUTH_ONLY, POSITION_DIVERGED,
              POLICY_RESTRICTED, CHAOS_VETO, CALIBRATION_MISSING,
              INTERPRETATION_DISABLED, JAIL_MODE_ACTIVE]
allowed_use=demo/research diagnostics only
forbidden_use=capital deployment; investment advice; automated execution
calibration_status=DEMO_ONLY
truth_origin_breakdown=SEEDED=<real_count>
evidence_ledger_status=SEEDED_ONLY
decision_ledger_status=NO_WRITE_MODE | <N>_RECORDS_PERSISTED | PERSIST_FAILED:...
```

## Canonical Permission is Now Enforced (not just reported)

The second hackathon wave wired the canonical action-permission resolver
into `scripts/action_engine.py`. Whenever the canonical permission is
`BLOCK_CAPITAL`, `QUARANTINE`, `DEMO_ONLY`, or `RESEARCH_ONLY`:

- Every per-ticker `action` field is downgraded to `ADVISORY_ONLY`.
- The legacy decision is preserved on the same row as
  `raw_action_signal` (`EXIT_NOW`, `REDUCE`, `HOLD`, `MONITOR`,
  `BLOCK_ENTRY`, `REVIEW_FOR_ENTRY`).
- The row carries `execution_status=DIAGNOSTIC_ONLY`,
  `action_executable=False`, `canonical_block_capital=True`,
  `allowed_use`, `forbidden_use`, and a `canonical_advisory_note`.
- The action report top-level surfaces
  `canonical_action_permission`, `canonical_veto_reasons`,
  `execution_status`, `allowed_use`, and `forbidden_use`.
- `tests/test_pipeline_canonical_consistency.py` fails if the action
  report ever contradicts the health-report canonical block.

## Decision Ledger Persistence

`build_pipeline_health_report` now constructs a `DecisionLedger` per
run, builds one `DecisionRecord` (with veto reasons and the evidence
snapshot hash), and persists JSONL to `runtime/decision_ledger.jsonl`
when `--no-write` is not passed.

The status surfaced in the health summary is **derived**, never a
hardcoded literal:

```
NO_WRITE_MODE          # --no-write was supplied
1_RECORDS_PERSISTED    # write succeeded
PERSIST_FAILED:OSError # I/O failure (does not crash the report)
```

## Real Evidence Ledger

`truth_origin_breakdown`, `evidence_ledger_status`, and
`external_signal_count` are now derived from a real `EvidenceLedger`
populated from `state["per_signal_attribution"]`. SEEDED records can
never be re-classified as external truth — the contract lives in
`scripts/evidence_ledger.py` and is enforced by tests.

## Replay-Labelled Scaffolding

A tiny labelled replay fixture lives at
`tests/fixtures/replay_with_labels/`:

```
tests/fixtures/replay_with_labels/sample_replay.json   # 12 labelled rows
tests/fixtures/replay_with_labels/sample_unlabeled.json # 3 unlabelled rows
```

`scripts/replay_runner.py` loads the fixture, routes records through
`ReplayTruthSource`, populates an `EvidenceLedger`, runs the canonical
permission resolver, computes per-baseline outcome metrics, and emits a
deterministic JSON summary. Replay-labelled records are typed as
`REPLAY_LABELED` (externally checkable, but **never live external
truth**). Capital deployment remains blocked.

## Baseline Strategies & FP/FN Accounting

- `scripts/baseline_strategies.py` provides three deterministic
  baselines: `AlwaysHoldBaseline`, `RandomChoiceBaseline(seed=0)`,
  `NaiveMomentumBaseline`. None of these are investment advice; they
  are deterministic references for replay comparison.
- `scripts/outcome_accounting.py` computes
  `true_positive` / `false_positive` / `true_negative` / `false_negative`,
  plus `precision`, `recall`, `false_positive_rate`,
  `false_negative_rate`. Zero denominators return `None` (never
  silently faked). Below 5 labelled samples the result is marked
  `insufficient_sample`.
- These metrics are explicitly labelled as **replay/sample metrics**.
  They never claim live predictive validity.

## Limitations (Seeded/Demo Mode)

- All numeric scores and thresholds are heuristic. None are calibrated against external outcome labels and none support a decision-ready claim.
- Position truth comes from the curated moltbook fixture; runtime paper positions diverge by default.
- External truth integration is **incomplete unless explicitly configured**. `ExternalTruthSourceStub` reports `NOT_CONFIGURED` and never pretends live data exists.
- Replay records without outcome labels do not validate outcomes.
- Replay records with outcome labels are externally checkable for the labelled slice, but they are not live external truth and cannot upgrade `canonical_action_permission` past `BLOCK_CAPITAL` while position state, calibration, and policy gates remain shut.
- Scientific validity is still bounded. Until a real
  `LIVE_EXTERNAL` adapter, an out-of-sample split, real calibration
  curves, and externally-derived outcome labels exist, all metrics are
  replay/sample diagnostics, not validity proofs.
- Tests assert these invariants directly so they cannot be silently weakened.

## Quickstart

```bash
# Compile
python -m compileall scripts tests

# Run the test suite (seeded; deterministic)
python -m pytest tests -q

# Honest health report (does not write runtime files)
python scripts/pipeline_health_report.py --summary --no-write

# Run the replay fixture through the canonical spine
python scripts/replay_runner.py --fixture tests/fixtures/replay_with_labels

# End-to-end consistency tests (action engine ↔ health report ↔ ledgers)
python -m pytest tests/test_pipeline_canonical_consistency.py -q
```

## Health Report Interpretation Guide

- `system_readiness_state=DO_NOT_DEPLOY` is the only honest value when `truth_origin=seeded` and `external_signal_count=0`.
- `canonical_action_permission` is the canonical decision; `can_deploy_capital` and `system_readiness_state` must remain consistent with it (the test suite enforces no contradiction).
- `veto_reasons` enumerates every active blocking gate. None of these can be "wished away" — they must be resolved by real structural state changes (external truth, calibration, reconciliation, etc.).
- `calibration_status=DEMO_ONLY` means scores must not be used to claim decision-readiness or to support capital permission.

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

## Offline-First Notes

- The verified path runs fully local.
- Do not treat placeholder adapters as live integrations.
- Keep external contact bounded and explicit if real data or execution is added later.
