# Dead-Code & Maintainability Audit — sleeping-passenger-v1

> READ-ONLY map. Nothing here is deleted automatically. Every entry is a **candidate for human review**, not a deletion instruction.

- Scripts scanned: **406**
- Unreferenced candidates: **90**
- Modules without obvious tests: **165**
- Metaphor/archetype-named modules: **34**
- Legacy/quarantine files: **3**

## Runtime-artifact patterns (keep untracked)

```
runtime/
runtime/*.db
logs/
*.db
data/daily_payload_backup_*/
data/daily_payload/*.json
tests/_tmp_runtime/
```

## Unreferenced module candidates

Not imported by any other script or test (excludes CLI entry points). Review before any action — some may be reflective/CLI tools.

- `activation_trigger_tracker`
- `ai_integration_readiness`
- `apply_cockpit_hot_path_indexes`
- `apply_uso_removal`
- `asymmetry_survival_scorer`
- `backfill_manual_trade_log_provenance`
- `backtest_signals`
- `belief_backtest`
- `branch_payload`
- `bruce_lee_signal_discipline_report`
- `build_dataset`
- `bulk_log_manual_trades`
- `calibration_corpus_status`
- `competence_exploitation_engine`
- `composite_edge_score`
- `consensus_formation_detector`
- `continuity_mode`
- `cycle_clarity_chaos_intensity`
- `daily_signal_readiness`
- `db_hygiene_report`
- `db_integrity_audit`
- `db_integrity_check`
- `dead_code_inventory`
- `dead_diagnostic_audit`
- `defensive_alpha_report`
- `demographic_engine`
- `diagnostics_snapshot_warmer`
- `environment_quality_score`
- `error_contracts`
- `execution_conversion_tracker`
- `execution_quality_scorer`
- `expectation_divergence_signal`
- `export_paper_trade_template`
- `export_paper_trades`
- `external_tool_integration_layer`
- `extreme_state_logic`
- `fault_injection_probe`
- `fetch_polymarket`
- `game_state_control_engine`
- `import_paper_trades`
- `improv_layer`
- `kalshi_live_smoke`
- `kalshi_market_data_adapter`
- `kronos_price_path_evidence`
- `late_adoption_lockout`
- `live_provider_compliance_trace`
- `local_security_audit`
- `micro_timing_layer`
- `milk_test_polymarket_history`
- `milk_test_uso_removal`
- `narrative_archetype_router`
- `narrative_distortion_index`
- `narrative_drift_monitor`
- `narrative_inertia_score`
- `narrative_inflation_index`
- `narrative_structure_divergence`
- `operator_demo_value`
- `pendentive_engine`
- `performance_baseline`
- `performance_probe`
- … and 30 more

## Modules without obvious test coverage

- `activation_trigger_tracker`
- `ai_integration_readiness`
- `ai_report_ingestion`
- `apply_cockpit_hot_path_indexes`
- `apply_uso_removal`
- `architecture_fitness`
- `asymmetry_survival_scorer`
- `backend_api_quality`
- `backfill_manual_trade_log_provenance`
- `backfill_ohlcv_history`
- `backtest_signals`
- `belief_backtest`
- `branch_payload`
- `broken_windows_report`
- `bruce_lee_decision_quality_index`
- `bruce_lee_signal_discipline_report`
- `build_dataset`
- `bulk_log_manual_trades`
- `business_value_report`
- `calibration_corpus_status`
- `candidate_memory_decay_v2`
- `closed_loop_learning_audit`
- `cockpit_concurrency_stress_probe`
- `cockpit_hot_path_query_audit`
- `competence_exploitation_engine`
- `complex_systems_sqlite_bridge`
- `compliance_preflight`
- `compliance_readiness`
- `compliance_registers`
- `composite_edge_score`
- `config`
- `config_contract`
- `consensus_formation_detector`
- `continuity_mode`
- `cycle_clarity_chaos_intensity`
- `daily_discovery_config`
- `daily_signal_readiness`
- `data_void_engine`
- `db_hygiene_report`
- `db_integrity_audit`
- `db_integrity_check`
- `dead_code_inventory`
- `dead_diagnostic_audit`
- `defensive_alpha_report`
- `demographic_engine`
- `diablo_narrative_veto`
- `diagnostics_service`
- `diagnostics_snapshot_cache`
- `diagnostics_snapshot_key`
- `diagnostics_snapshot_warmer`
- `diagnostics_tail_metrics`
- `economy_of_motion_audit`
- `environment_quality_score`
- `error_contracts`
- `execution_conversion_tracker`
- `execution_quality_scorer`
- `expectation_divergence_signal`
- `export_paper_trade_template`
- `export_paper_trades`
- `external_evidence_operator_readiness`
- … and 105 more

## Metaphor / archetype-named modules (rename candidates)

- `archetype_profile`
- `archetype_registry`
- `baines_engine`
- `bruce_lee_decision_quality_index`
- `bruce_lee_signal_discipline_report`
- `busquets_pre_execution_audit`
- `chess_archetype_decision_layer`
- `external_evidence_moltbook_calibration`
- `football_portfolio_archetype_engine`
- `kante_real_provider_canary`
- `kronos_price_path_evidence`
- `moltbook_adjustment`
- `moltbook_api`
- `moltbook_cleanup_fake_seed`
- `moltbook_dedupe_cleanup`
- `moltbook_feedback`
- `moltbook_learning_backfill`
- `moltbook_learning_bridge`
- `moltbook_loader`
- `moltbook_reconciliation_bridge`
- `moltbook_visibility`
- `narrative_archetype_router`
- `reactor_calibration_report`
- `reactor_canonical_inputs`
- `reactor_snapshot_attach`
- `run_tennis_archetype_diagnostics`
- `signal_buoyancy_engine`
- `signal_field_geometry`
- `signal_geometry_persistence`
- `signal_geometry_reflection`
- `signal_metabolism`
- `signal_reactor`
- `tennis_archetype_execution`
- `tribev2_adapter`

## Legacy / quarantine files

- `scripts/_legacy_layers/README.md`
- `scripts/_quarantine/README.md`
- `scripts/_quarantine/source_signaling_discount.py.broken`

## Quarantine plan (safe, human-driven)

1. Confirm a candidate is truly unused (grep + run full suite).
2. Move — do not delete — to `scripts/_quarantine/` in a dedicated PR.
3. Run the full test suite; if green, keep quarantined one release.
4. Delete only after a release with no regression and explicit sign-off.
