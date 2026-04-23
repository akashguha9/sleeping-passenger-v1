# Operator Control Architecture

This repo now carries a small additive operator-control layer.

The layer is intentionally narrow:

- It does not infer psychological truth.
- It does not claim live execution.
- It does not invent missing operator data.
- It only scores what is explicitly logged or transparently derived from repo-visible fields.

## What Exists

`A. Operator State Layer`

- `runtime/operator_state.json`
- Optional manual fields:
  - `active_objective`
  - `active_task`
  - `active_block_id`
  - `operator_mode`
  - `context_switch_count`
  - `unfinished_closures`
  - `baseline_score`
  - `current_score`
  - `peak_score`
  - `recent_scores`
  - `instability_reasons`
  - `notes`

`B. Signal Admission Gate`

- Implemented in [scripts/operator_control.py](/C:/Users/akash/pipeline-v5.7-core/scripts/operator_control.py) and surfaced from [scripts/signal_refinery.py](/C:/Users/akash/pipeline-v5.7-core/scripts/signal_refinery.py).
- Hard dimensions:
  - relevance
  - actionability
  - timeliness
- Base logic:
  - `admit = relevance * actionability * timeliness`
- The current gate uses repo-visible proxies only:
  - `ce_score` for relevance
  - explicit signal state / watchlist state for actionability
  - `signal_id` date parsing for timeliness

`C. Kill Log`

- `logs/signal_kill_log.jsonl`
- One row per rejected signal per run, deduped within the run.

`D. Drift / Context Switch Monitor`

- `logs/operator_block_events.jsonl`
- Supported manual events:
  - `selected`
  - `execution_started`
  - `context_switch`
  - `decision_reopened`
  - `abandoned`
  - `closed`
  - `closure_failed`

`E. Closure Threshold Engine`

- Closure is evidence-based, not inferred.
- Current rules live in `config/operator_control_config.json`.
- Examples:
  - `coding`: `output_exists AND validation_exists`
  - `research`: `output_exists AND report_exists`
  - `feature`: `output_exists AND validation_exists`

`F. Selection vs Execution Split`

- `runtime/active_work_block.json` stores the active block header.
- `logs/operator_block_events.jsonl` stores later execution and drift events.
- This makes mid-block switching visible instead of implicit.

`G. Phase Balance Dashboard`

- `runtime/operator_phase_balance.json`
- `runtime/operator_phase_report.json`
- Transparent proxies:
  - Phase 1: drift inverse, closure ratio, unfinished burden inverse
  - Phase 2: reject rate, average admitted `ce_score`
  - Phase 3: closure ratio, test status, artifact coverage

`H. Baseline vs Peak Tracker`

- Derived from manual `baseline_score`, `current_score`, `peak_score`, and optional `recent_scores`.
- If those fields are absent, the report says so.

`I. Structural Cover Mapper`

- `config/structural_cover_map.json`
- This is the explicit map from exposed weakness to structural control.

`J. Top-Down Constraint Header`

- Logged through `operator_control.py start-block`
- Stored in `runtime/active_work_block.json`
- Fields:
  - objective
  - success_metric
  - time_boundary
  - non_goals

## Pipeline Position

The repo is now closer to:

`operator_state`
`-> signal_admission_gate`
`-> signal_refinement`
`-> action_report`
`-> execution_governance`
`-> paper_or_live_pathway`
`-> reconciliation`
`-> feedback`
`-> operator_recalibration`

Narrative compression and operator recalibration are still mostly represented as report structure and manual review rather than a separate fully automated engine.

## Truth Boundaries

- The signal gate is real and executable.
- The kill log is real and persistent.
- Block drift and closure logging are real if you log events.
- Baseline/peak is manual unless you explicitly write scores.
- Phase balance scores are observable proxy blends, not deep truth claims.
