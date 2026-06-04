# Core Module Boundary

Boundary clarity for the backend, enforced by `scripts/core_module_boundary.py`
and `tests/test_core_module_boundary.py`. This is classification, not
refactoring — no files are moved.

## Buckets
- **CORE** — load-bearing engines + infrastructure (the manifest set:
  leverage_governance, score_calibration, calibration_recommendations,
  score_output_contract, pre_real_money_preflight, diablo_narrative_veto,
  event_prior_detector, moltbook_feedback, signal_inbox_api, persistence,
  api_server, advisory_contract, outcome_evidence(+extractor),
  securities_master_coverage, signal_refinery/reactor, chronology_store, …).
- **SUPPORT** — tooling/adapters/reports/diagnostics by naming family, plus
  anything in CORE's import closure (if CORE depends on it, it is support).
- **EXPERIMENTAL** — archetype/mythology layers, NOT load-bearing (chess /
  tennis / football / Bruce-Lee / JKD / optical_operating_system, …).
- **ARCHIVED** — `archived_experimental/` (tribev2, quarantine), never imported.

## Import hygiene
A CORE module may import CORE or SUPPORT, **never** EXPERIMENTAL or ARCHIVED.
`core_import_violations()` enforces this; current violations: **none** (I = 1).

## Metrics
```
K  = (N_core + N_support + N_experimental) / N_total      (classified fraction)
H  = max(0, 1 - N_unknown/N_total)                        (boundary clarity)
I  = 1 iff no CORE imports EXPERIMENTAL/ARCHIVED
CH = 10 · (0.60·H + 0.40·I)                               (code hygiene)
```
Current: ~368 modules, 23 CORE, ~276 SUPPORT, 15 EXPERIMENTAL, ~54 UNKNOWN →
H ≈ 0.85, I = 1, **CH ≈ 9.1**.

## New-module rule
A new script must be CORE/EXPERIMENTAL, match a SUPPORT naming family, or be
added to `ACCEPTED_UNKNOWN_BASELINE` with intent. Otherwise
`test_no_new_unclassified_modules` fails — forcing an explicit decision.

Run: `python scripts/core_module_boundary.py`
