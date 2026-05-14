# SCRIPT INVENTORY

> Brutal note: **script count is not product maturity**. `scripts/` contains
> ~160 Python files, but only a small fraction are reachable from the FastAPI
> routes and Next.js frontend that make up the actual product. The rest is
> research scaffolding, historical experiments, or one-off CLIs.
>
> **Nothing has been moved or deleted as part of this inventory.** This file
> is a map. Use it to know what to look at first and what to ignore.

## Methodology

A script is classified as **active runtime** if it is:
- Imported (transitively) from `scripts/api_server.py`, or
- Invoked from a documented runbook in `README.md`, `SETUP.md`, or `DEMO.md`,
  or
- Imported from `scripts/signal_inbox_api.py`, `scripts/signal_inbox_bridge.py`,
  `scripts/persistence.py`, `scripts/runtime_common.py`,
  `scripts/runtime_config.py`, or
- Imported from a live source runner (`scripts/run_live_sources_*.py`,
  `scripts/live_source_runner*.py`).

Everything else is classified as **research / not verified** until proven
otherwise. That is intentional and conservative.

---

## Active — API + UI surface

Reachable from the FastAPI server and required for the canonical workflow.

| Script | Role |
|---|---|
| `scripts/api_server.py` | FastAPI app. Mounts every UI-facing route. |
| `scripts/runtime_config.py` | Env-driven config (CORS, host/port, token gate, DB path). |
| `scripts/runtime_common.py` | Shared paths, timestamps, atomic writers, run-id stamping. |
| `scripts/persistence.py` | SQLite schema + CRUD for all journal tables. |
| `scripts/signal_inbox_api.py` | Inbox / reflection / manual-trade / reconcile / moltbook ops. |
| `scripts/signal_inbox_bridge.py` | Promotes fresh `signal_events` rows into inbox candidates. |
| `scripts/moltbook_api.py` | Moltbook entry list/log. |
| `scripts/moltbook_loader.py` | Loads/normalizes seeded moltbook fixtures. |
| `scripts/gsheet_export.py` | CSV serializers for the `/exports/*.csv` routes. |
| `scripts/source_health_summary.py` | Per-source health classifier (pure logic, no FastAPI dep). |
| `scripts/chart_structure_api_context.py` | `/chart-structure` handler logic. |
| `scripts/chart_structure_engine.py` | OHLCV → candle anatomy / trend / volatility report. |
| `scripts/chart_symbol_bootstrap.py` | On-demand OHLCV backfill for missing symbols. |
| `scripts/symbol_normalizer.py` | Symbol → canonical mapping for the securities route. |
| `scripts/global_signal_fabric.py` | Legacy fabric report used as inbox fallback. |

## Active — live ingestion

Pulled by the live-source runners. Each adapter is read-only.

| Script | Source |
|---|---|
| `scripts/run_live_sources_phase1.py` | Phase 1 orchestrator (Polymarket / GDELT / SEC EDGAR). |
| `scripts/run_live_sources_phase2.py` | Phase 2 orchestrator (NewsAPI / Event Registry / Etherscan / others). |
| `scripts/live_source_runner.py` | Phase 1 runner internals. |
| `scripts/live_source_runner_phase2.py` | Phase 2 runner internals. |
| `scripts/live_signal_filters.py` | Domain gating (politics / finance / geopolitics / economy only). |
| `scripts/polymarket_gamma_adapter.py` | Polymarket Gamma. |
| `scripts/polymarket_data_adapter.py` | Polymarket Data. |
| `scripts/polymarket_clob_adapter.py` | Polymarket CLOB (public read only). |
| `scripts/blockscout_adapter.py` | Blockscout (chain explorer). |
| `scripts/grok_xai_adapter.py` | xAI/Grok interpretation layer. |
| `scripts/yahoo_market_data_adapter.py` | Yahoo OHLCV (yfinance). |
| `scripts/market_data_adapter.py` | OHLCV provider abstraction. |
| `scripts/external_data_runtime_sync.py` | Optional advisory external-data sync. |

Persistence helpers used by the above:
`scripts/snapshot_logger.py`, `scripts/external_data_common.py`,
`scripts/external_observation_lane.py`.

## Active — paper / reconciliation (optional, gated)

Only runs when `PIPELINE_ENABLE_PAPER_EXECUTION=true` AND
`PIPELINE_ENABLE_LIVE_EXECUTION=false`.

| Script | Role |
|---|---|
| `scripts/paper_execution.py` | Paper order/fill ledger maintenance. |
| `scripts/paper_reconciliation.py` | Mark-to-Yahoo reconciliation against paper positions. |
| `scripts/paper_trade_retirement.py` | Bounded paper-trade retirement loop. |

## Test support

Tests in `tests/` either exercise the active runtime above or exercise
research engines below. The `conftest.py` and `tests/fixtures/` set up a
deterministic snapshot seed.

## Framework metadata helper (documentation companion, not runtime)

| Script | Role |
|---|---|
| `scripts/reflection_frameworks.py` | Metadata-only companion to `docs/REFLECTION_FRAMEWORKS.md`. No live calls. No DB writes. No filesystem writes. Not imported by `api_server.py` or `persistence.py`. Exposes the framework component inventory, banned theatrical terms, priority/status enums, a deterministic validator, and a metadata scorecard. Every component blob carries the canonical advisory-only safety stamps (`advisory_status=ADVISORY_ONLY`, `execution_gate=LOCKED`, `broker_api_called=false`, `ai_execution_count=0`, `execution_permission=false`, `can_execute=false`). Covered by `tests/test_reflection_frameworks.py`. |

## Signal Reactor diagnostics (pure helpers, advisory-only, no runtime wiring yet)

Added in the *Signal Reactor + Adaptive Routing Model Upgrade* sprint.
Each module is pure (no DB writes, no live APIs, no broker imports),
deterministic, and stamped with the canonical advisory-only safety
contract on every output. Not imported by `api_server.py` or the
inbox API yet — wiring is the next sprint.

| Script | Role |
|---|---|
| `scripts/signal_field_geometry.py` | Classifies a single trace and the geometry of a small cluster (direction, phase alignment, resonance, damping, spike/echo/fan-out/compressing/chaotic). Tests: `tests/test_signal_field_geometry.py`. |
| `scripts/echo_risk_engine.py` | Separates independent confirmation from repetition; emits `echo_risk_score`, `confirmation_quality`, AI-echo guard. Tests: `tests/test_echo_risk_engine.py`. |
| `scripts/signal_decay_waste.py` | Half-life decay per signal type, stale/duplicate/contradicted/failed-thesis classes, waste-load summary. Tests: `tests/test_signal_decay_waste.py`. |
| `scripts/fission_branch_mapper.py` | Maps an explosive event into branch-energy scores; emits `branch_clarity_score` and `recommendation` (`map_only`, `watch_branches`, …). Tests: `tests/test_fission_branch_mapper.py`. |
| `scripts/fusion_thesis_engine.py` | Combines weak independent signals into a thesis only when independence + density + containment + durability all clear. Tests: `tests/test_fusion_thesis_engine.py`. |
| `scripts/operator_control_rods.py` | Operator-heat, containment-capacity, meltdown-risk, control-rod insertion, gallardo block. Distinct from `scripts/operator_control.py` (work-block / state ledger). Tests: `tests/test_operator_control_rods.py`. |
| `scripts/adaptive_signal_router.py` | Nutrient value + terrain penalty + route weight + route state (`reinforce`/`watch`/`decay`/`prune`/`quarantine`). Tests: `tests/test_adaptive_signal_router.py`. |
| `scripts/signal_reactor.py` | Pure orchestrator that calls every helper above and emits one advisory payload (`signal_reactor_state`, `decision_grade_energy`, `allowed_actions.broker_execute=false` always). CLI: `python scripts/signal_reactor.py --example --json`. Tests: `tests/test_signal_reactor.py`, `tests/test_signal_reactor_safety_invariants.py`. |

## Research / not-verified

These scripts exist, have tests, and compile — but they are **not reached
from the FastAPI surface or the live-source runners**. They are the artifacts
of earlier experiments (archetype taxonomies, narrative analysis, signal
metabolism, "extreme state" logic, "perception control", "operator control",
etc.).

> If you are a new contributor, you can safely ignore everything below until
> you have a reason to touch it. None of it is required to demo the product.

A non-exhaustive sample (alphabetical, not all 130+ files):

- `scripts/archetype_profile.py`
- `scripts/archetype_registry.py`
- `scripts/artifact_coherence_check.py`
- `scripts/asymmetry_survival_scorer.py`
- `scripts/attention_proxy_engine.py`
- `scripts/baines_engine.py`
- `scripts/blocker_cost_engine.py`
- `scripts/board_control_safety_layer.py`
- `scripts/chess_archetype_decision_layer.py`
- `scripts/closure_deficit_monitor.py`
- `scripts/competence_exploitation_engine.py`
- `scripts/complexity_ladder_controller.py`
- `scripts/composite_edge_score.py`
- `scripts/consensus_formation_detector.py`
- `scripts/contextual_interpretation_engine.py`
- `scripts/cycle_clarity_chaos_intensity.py`
- `scripts/demographic_engine.py`
- `scripts/event_prior_detector.py`
- `scripts/execution_governance.py`
- `scripts/extreme_state_logic.py`
- `scripts/false_negative_casino_monopoly_layer.py`
- `scripts/field_dynamics_engine.py`
- `scripts/football_portfolio_archetype_engine.py`
- `scripts/game_state_control_engine.py`
- `scripts/governance_feedback_report.py`
- `scripts/governance_status.py`
- `scripts/hedge_trade_entry_playbook.py`
- `scripts/improv_layer.py`
- `scripts/integrity_diagnostics.py`
- `scripts/latent_signal_release_bull_layer.py`
- `scripts/narrative_archetype_router.py`
- `scripts/narrative_drift_monitor.py`
- `scripts/narrative_inertia_score.py`
- `scripts/narrative_inflation_index.py`
- `scripts/operator_control.py`
- `scripts/operator_override_ledger.py`
- `scripts/optical_operating_system.py`
- `scripts/pendentive_engine.py`
- `scripts/perception_control.py`
- `scripts/pre_execution_scan_engine.py`
- `scripts/regime_translation_tester.py`
- `scripts/signal_buoyancy_engine.py`
- `scripts/signal_distortion_index.py`
- `scripts/signal_lifecycle_tracker.py`
- `scripts/signal_metabolism.py`
- `scripts/signal_refinery.py`
- `scripts/silence_filter.py`
- `scripts/structural_admission_layer.py`
- `scripts/structural_design_engine.py`
- `scripts/structural_integrity_score.py`
- `scripts/tennis_archetype_execution.py`
- `scripts/tension_accumulation_tracker.py`
- `scripts/visibility_engine.py`
- ...and many more.

If you want to confirm a specific script is unreached, search:

```powershell
Select-String -Path scripts\api_server.py,scripts\signal_inbox_api.py,scripts\signal_inbox_bridge.py,scripts\moltbook_api.py,scripts\live_source_runner*.py,scripts\run_live_sources_*.py -Pattern "scriptname_without_dot_py"
```

## Future cleanup (not done in this sprint)

A safe move sequence — only if you confirm no test references the script by
its absolute path:

1. Create `research_scripts/` at repo root.
2. Move one script at a time. Run `python -m pytest tests -q`. If anything
   breaks, move it back.
3. Repeat for batches of related modules (archetype family, narrative family,
   operator family, etc.).

Mass deletion is **not recommended** — these modules took real effort and
some of them may be wired up via the runtime artifacts under `runtime/`.
Documentation (this file) is the safer first step.
