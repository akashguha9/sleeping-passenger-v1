# Legacy / metaphor layer inventory (non-canonical)

> **Read this before touching any module in this list.**
>
> The scripts named below are **historical / research / metaphor layers**.
> They are preserved in place because moving them would break existing
> tests and import paths.  They are **not** part of the canonical
> first-day operator workflow described in the main `README.md`.
>
> If you are a first-day operator, ignore this file.  These modules do
> not need to be run for the MVP to function.

## Inventory

The following modules live under `scripts/` but are classified as
**legacy / research / metaphor**.  They remain importable so existing
tests pass, but they are not surfaced in the canonical workflow.

| Module | Category | Notes |
|---|---|---|
| `scripts/archetype_profile.py` | archetype | Profile of archetype distribution. |
| `scripts/archetype_registry.py` | archetype | Registry of archetype state names. |
| `scripts/baines_engine.py` | metaphor (named) | Named-engine experiment. |
| `scripts/board_control_safety_layer.py` | metaphor | Board-control safety overlay. |
| `scripts/chess_archetype_decision_layer.py` | archetype | Chess-archetype decision overlay. |
| `scripts/contextual_interpretation_engine.py` | metaphor | Contextual interpretation overlay. |
| `scripts/extreme_state_logic.py` | metaphor | Extreme-state logic overlay. |
| `scripts/extreme_state_report.py` | metaphor | Extreme-state diagnostic report. |
| `scripts/false_negative_casino_monopoly_layer.py` | metaphor | Casino / monopoly framing. |
| `scripts/field_dynamics_engine.py` | metaphor | Field-dynamics engine. |
| `scripts/football_portfolio_archetype_engine.py` | archetype | Football-archetype overlay. |
| `scripts/hedge_trade_entry_common.py` | metaphor | Hedge-trade entry helper. |
| `scripts/hedge_trade_entry_playbook.py` | metaphor | Hedge-trade entry playbook. |
| `scripts/latent_signal_release_bull_layer.py` | metaphor | Latent-signal bull-state overlay. |
| `scripts/narrative_archetype_router.py` | archetype | Narrative-archetype routing. |
| `scripts/run_contextual_interpretation_demo.py` | metaphor | Demo runner. |
| `scripts/run_extreme_state_report.py` | metaphor | Diagnostic runner. |
| `scripts/run_tennis_archetype_diagnostics.py` | archetype | Tennis-archetype diagnostic runner. |
| `scripts/signal_metabolism.py` | metaphor | Signal-metabolism overlay. |
| `scripts/signal_refinery.py` | research | Signal-refinery research path (see `docs/legacy/SIGNAL_REFINERY_HISTORICAL_REFERENCE.md`). |
| `scripts/signal_surface_engine.py` | metaphor | Signal-surface overlay. |
| `scripts/structural_admission_layer.py` | metaphor | Structural-admission overlay. |
| `scripts/structural_design_engine.py` | metaphor | Structural-design overlay. |
| `scripts/structural_integrity_score.py` | metaphor | Structural-integrity score. |
| `scripts/tennis_archetype_execution.py` | archetype | Tennis-archetype execution overlay. |

## Inventory math

```
S_total                = 322   (top-level scripts/*.py)
S_legacy_inventoried   = 25    (modules listed above)
S_active               = 297
LegacyRatio            = 25 / 322  ≈  0.078
```

`LegacyRatio` is intentionally small.  We optimised for **correctness**,
not for moving the maximum possible number of files.  Modules above are
flagged as legacy without being physically moved, because:

* Several are imported by existing tests via absolute paths.
* Several are reachable from CI release-gate scripts.
* Physically moving them would create churn that has no proportionate
  truth-surface benefit.

If a future sprint wants to physically move them, the safe pattern is
`git mv` plus a compatibility wrapper at the original path that re-exports
the symbols (so import sites continue to work).

## Hard rules these legacy modules still obey

* They do **not** override the advisory-only safety contract.
* They do **not** call brokers, place orders, or execute trades.
* They are **not** predictive without calibration; see
  `docs/SCORING_STACK_VALIDATION.md`.
* They are **not** part of the canonical first-day operator workflow.

## What is NOT in the legacy list

The following layers are canonical and remain on the workflow even
though they share archetype-adjacent vocabulary:

* `scripts/advisory_contract.py` — canonical safety contract.
* `scripts/live_source_registry.py` — canonical source registry.
* `scripts/refresh_live_signals.py` — canonical 6-hour refresh.
* `scripts/watchdog_refresh_stale_sources.py` — canonical 30-min watchdog.
* `scripts/persistence.py` — canonical SQLite layer.
* `scripts/api_server.py` — canonical FastAPI surface.
* `scripts/calibration_report.py` — calibration gate (this sprint).
* `scripts/first_run_seed_free_sources.py` — first-day operator seed.
* `scripts/runtime_truth_purity_audit.py` — truth-purity gate.
* `scripts/moltbook_api.py`, `scripts/moltbook_reconciliation_bridge.py`
  — Moltbook learning loop.

## Verification

The inventory above is sanity-checked by
`tests/test_legacy_layers_inventory.py` (this sprint): every module
listed must exist on disk; every module that exists in the
metaphor-vocabulary glob must either be in the inventory or be in the
canonical allow-list.

## Stop expanding the mythology

This sprint's deliberate posture: do not add new metaphors, do not add
new archetypes, do not add new scoring names, do not add new execution
surfaces.  Defend the truth surface.
