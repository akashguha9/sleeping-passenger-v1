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

## Operator Control Layer

The repo now includes an additive operator-control slice designed for truthful manual governance.

- `runtime/operator_state.json`: optional manual operator state. No internal state is inferred if you do not log it.
- `runtime/signal_gate_summary.json`: hard admission gate summary over current signal rows.
- `logs/signal_kill_log.jsonl`: persistent rejected-signal log with explicit rejection dimensions and reasons.
- `runtime/active_work_block.json` and `logs/operator_block_events.jsonl`: manual/event-based selection, execution, context-switch, and closure logging.
- `runtime/operator_phase_balance.json` and `runtime/operator_phase_report.json`: transparent proxy scores for Phase 1/2/3 using logged drift, closure, gate behavior, tests, and artifact coverage.
- `config/structural_cover_map.json`: explicit mapping from exposed operator asymmetries to structural controls.

Mode honesty is preserved:

- The operator-control layer is manual or event-driven unless an explicit runtime source exists.
- Timeliness is derived only from repo-visible signal identifiers when available.
- Closure is evaluated only from logged evidence such as `output_exists`, `validation_exists`, and `report_exists`.
- Phase scores are transparent proxy blends, not psychological truth claims.

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
python scripts\governance_status.py --summary
python scripts\governance_feedback_report.py --summary
python scripts\artifact_coherence_check.py --summary
python scripts\operator_control.py report --summary
python scripts\paper_execution.py sync --summary
python scripts\operator_override_ledger.py --ticker RTX --override-action MONITOR --why-this-move "waiting for manual review" --trigger "review-ready candidate" --invalidation "cancel if validation weakens" --regime "review_ready" --why-now "blockers cleared this run" --summary
python scripts\yahoo_market_data_adapter.py --tickers RTX,ZIM --summary
python scripts\paper_trade_retirement.py --summary
python scripts\paper_reconciliation.py --summary
python scripts\run_diagnostics_pipeline.py --summary --no-write
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
python scripts\operator_control.py close-block --output-exists --validation-exists
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
