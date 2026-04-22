# Validated Signal Refinery Upgrade

## Purpose
This upgrade remaps the MVP away from crude signal throughput and toward earliest validated signal, controlled review readiness, thermal discipline, repeatability, and maintenance.

## Active Runtime Mapping
- `scripts/signal_conversion_monitor.py`
  Raw seeded signal state. Still the crude feed and policy seed.
- `scripts/signal_refinery.py`
  New refinery layer. Converts crude runtime state into:
  - horsepower monitor
  - validation / traction engine
  - launch control
  - thermal + battery manager
  - repeatability tracker
  - maintenance + wear log
  - time-to-valid-signal KPI
- `scripts/action_engine.py`
  Still emits deterministic operator actions. Now accepts optional launch-control gating from the refinery.
- `scripts/snapshot_logger.py`
  Snapshot memory now persists refinery metrics alongside existing SCM / policy / transition fields.
- `scripts/trend_engine.py`
  Trend report now tracks validation quality, decision-grade signal count, thermal headroom, and time-to-valid-signal.
- `scripts/pipeline_health_report.py`
  Health report now embeds the refinery artifact and includes the new test slice.
- `scripts/run_diagnostics_pipeline.py`
  Orchestrates the refinery in the live diagnostics path instead of leaving it as a sidecar.

## New Runtime Artifact
- `runtime/signal_refinery_report.json`

## New Config
- `config/signal_refinery_config.json`

## What Is Real
- Horsepower metrics are computed from the seeded signal ledger.
- Validation scores are deterministic heuristics based on existing repo evidence:
  - CE score
  - conversion / pre-entry state
  - blocker clearance
  - persistence proxy
  - crowding proxy
  - source-quality proxy
- Thermal state is real relative to current seeded open positions and Moltbook close history.
- Repeatability metrics are real relative to the four curated Moltbook closes.
- Time-to-valid-signal exists, but only as a heuristic based on signal-id date because the repo still lacks live event and ingestion clocks.

## What Is Still Heuristic
- Cross-source confirmation is neutral until ETIL / external feeds are wired.
- Crowding / repricing is a placeholder derived from review persistence and existing exposure, not live market microstructure.
- Time-to-valid-signal uses `signal_id` dates plus current run time, not true observation timestamps.
- Launch control can mark names `REVIEW_READY` while deployment stays blocked by thermal state. This is intentional: the current repo is still review-first, not auto-execution-ready.

## Current Design Intent
- Horsepower is treated as feed output, not edge.
- Validation is the primary decision filter.
- Launch control only promotes sufficiently validated, still-early candidates.
- Thermal discipline blocks deployability before the repo can hurt capital.
- Repeatability is evaluated from accumulated closes, not isolated wins.
- Maintenance turns every realized trade into model upkeep and failure attribution.

## Operator Use
- Read-only pipeline check:
  - `python scripts\run_diagnostics_pipeline.py --summary --include-tests --no-write`
- Full JSON refinery output:
  - `python scripts\signal_refinery.py`
- Full diagnostics artifact write:
  - `python scripts\run_diagnostics_pipeline.py --summary`

## Current Constraints
- No live ingestion in the active path.
- No real market confirmation adapter in the active path.
- No broker or fill lifecycle.
- No true chronology / observation scheduler in production yet.
- This remains a decision-grade prototype, not an execution-ready live system.
