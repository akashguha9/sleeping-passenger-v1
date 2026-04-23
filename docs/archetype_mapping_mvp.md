# Archetype Mapping MVP

This repo now treats the reflection archetypes as additive paper-mode modules, not as examples or persona lore.

## Why This Exists

- The current MVP already has real signal, decision, paper-execution, reconciliation, and governance layers.
- The missing layer was a stable way to classify *what kind of edge* a current action represents.
- The new archetype layer does that with repo-visible proxies only. It does not invent live execution, broker truth, or unlogged branch trees.

## Current Mapping

- `Fischer -> Signal Purity Engine`
  - Source: `signal_refinery.signal_admission_gate` and `validation_engine`
  - Role today: scoring-critical advisory for purity/coherence
- `Kasparov -> Pressure Scenario Expander`
  - Source: `pipeline_health_report.gate_resolution_preview`, transition packets, queue persistence
  - Role today: advisory only
- `Carlsen -> Error Extraction Tracker`
  - Source: `paper_reconciliation`, `repeatability_tracker`, closure coverage
  - Role today: advisory only
- `Messi -> Optionality Preserver`
  - Source: watchlist pre-entry states plus deterministic `GSCE_CLEAR` / `ALL_CLEAR` previews
  - Role today: advisory only
- `Cristiano -> Objective Function Engine`
  - Source: `action_engine`, `execution_governance`, launch state, action reasons
  - Role today: scoring-critical advisory view
- `Neuer -> Geometry Controller`
  - Source: `signal_refinery.thermal_battery_manager`
  - Role today: advisory only
- `Neymar -> Entropy Opportunity Tagger`
  - Source: `visibility_timing_context` and validation-row context
  - Role today: advisory only
- `Hazard -> Friction Detector`
  - Source: blocker cost, FPEG gaps, override pressure, packet conflicts, unfinished closures
  - Role today: advisory only
- `Meta -> Archetype Weighting Layer`
  - Source: current regime flags from friction, transition pressure, entry readiness, and evidence sparsity
- `Meta Diagnostic -> Closure Deficit Monitor`
  - Source: paper decision ledger, paper close ledger, reconciliation history/summary, operator closure logging

## Real Outputs Today

- Registry config: `config/archetype_registry.json`
- Registry loader: `scripts/archetype_registry.py`
- Closure-gap report: `scripts/closure_deficit_monitor.py`
- Archetype report: `scripts/archetype_profile.py`
- Runtime artifacts:
  - `runtime/closure_deficit_report.json`
  - `runtime/archetype_profile_report.json`
- Health integration:
  - `pipeline_health_report` now includes `governance_feedback`, `closure_deficit`, and `archetype_profile`

## Truth Boundaries

- The archetype layer is advisory.
- It does not modify `action_engine` routing.
- It does not auto-approve paper entries.
- It does not claim live fills, live slippage, broker reconciliation, or full scenario-tree intelligence.
- Optionality is approximated from existing watchlist states and deterministic gate-clear simulations.
- Closure sufficiency is constrained by the current paper lineage and reconciliation sample size.

## Future Work

- Add explicit approval timestamps if approval-latency friction needs to be measured directly.
- Add richer per-signal branch logging if true optionality accounting is required.
- Add non-deterministic fill/mark lineage only after a real execution-truth source exists.
