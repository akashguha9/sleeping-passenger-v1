# Unknown Module Review

Review of the previously-UNKNOWN backend modules (boundary classifier). None
are imported by CORE, so none can break import isolation (I=1).

| module | imported_by_core | has_tests | recommendation | reason |
|--------|------------------|-----------|----------------|--------|
| action_doctrine_status | no | yes | KEEP_SUPPORT | tested support module |
| anti_staleness | no | yes | KEEP_SUPPORT | tested support module |
| backup_db | no | yes | KEEP_SUPPORT | tested support module |
| backup_local_state | no | yes | KEEP_SUPPORT | tested support module |
| belief_backtest | no | no | ARCHIVE_LATER | untested legacy backtest experiment; superseded by run_imported_backtest |
| branch_payload | no | no | ARCHIVE_LATER | untested legacy backtest experiment; superseded by run_imported_backtest |
| candidate_memory_decay_v2 | no | yes | KEEP_SUPPORT | tested support module |
| continuity_mode | no | yes | KEEP_SUPPORT | tested support module |
| cycle_clarity_chaos_intensity | no | no | MARK_EXPERIMENTAL | archetype/regime experiment, not load-bearing |
| daily_synthesis_pipeline | no | yes | KEEP_SUPPORT | tested support module |
| diagnostics_snapshot_cache | no | yes | KEEP_SUPPORT | tested support module |
| diagnostics_snapshot_key | no | yes | KEEP_SUPPORT | tested support module |
| diagnostics_snapshot_warmer | no | yes | KEEP_SUPPORT | tested support module |
| diagnostics_tail_metrics | no | yes | KEEP_SUPPORT | tested support module |
| error_contracts | no | yes | KEEP_SUPPORT | tested support module |
| expectation_divergence_signal | no | no | KEEP_SUPPORT | KEEP_SUPPORT |
| extreme_state_logic | no | yes | KEEP_SUPPORT | tested support module |
| five_model_independence | no | yes | KEEP_SUPPORT | tested support module |
| fresh_market_discovery | no | yes | KEEP_SUPPORT | tested support module |
| governance_status | no | yes | KEEP_SUPPORT | tested support module |
| governance_verdict | no | yes | KEEP_SUPPORT | tested support module |
| kalshi_live_smoke | no | no | KEEP_SUPPORT | KEEP_SUPPORT |
| late_adoption_lockout | no | no | KEEP_SUPPORT | KEEP_SUPPORT |
| live_provider_compliance_trace | no | no | KEEP_SUPPORT | KEEP_SUPPORT |
| live_signal_filters | no | yes | KEEP_SUPPORT | tested support module |
| live_source_runner_phase2 | no | yes | KEEP_SUPPORT | tested support module |
| local_mvp_smoke_test | no | yes | KEEP_SUPPORT | tested support module |
| market_data_freshness | no | yes | KEEP_SUPPORT | tested support module |
| minimum_daily_universe | no | yes | KEEP_SUPPORT | tested support module |
| model_disagreement | no | yes | KEEP_SUPPORT | tested support module |
| moltbook_cleanup_fake_seed | no | yes | KEEP_SUPPORT | tested support module |
| narrative_structure_divergence | no | no | KEEP_SUPPORT | KEEP_SUPPORT |
| operator_live_provider_refresh | no | yes | KEEP_SUPPORT | tested support module |
| paper_execution | no | yes | KEEP_SUPPORT | tested support module |
| paper_trade_retirement | no | yes | KEEP_SUPPORT | tested support module |
| perception_control | no | yes | KEEP_SUPPORT | tested support module |
| performance_baseline | no | yes | KEEP_SUPPORT | tested support module |
| persistence_global_securities | no | no | KEEP_SUPPORT | KEEP_SUPPORT |
| persistence_integrity | no | yes | KEEP_SUPPORT | tested support module |
| portfolio_truth_integrity | no | yes | KEEP_SUPPORT | tested support module |
| position_truth_resolver | no | yes | KEEP_SUPPORT | tested support module |
| prediction_market_embedding_providers | no | yes | KEEP_SUPPORT | tested support module |
| prediction_market_semantic_pairing | no | yes | KEEP_SUPPORT | tested support module |
| promotion_downgrade | no | yes | KEEP_SUPPORT | tested support module |
| provider_verification | no | yes | KEEP_SUPPORT | tested support module |
| repo_operating_mode | no | yes | KEEP_SUPPORT | tested support module |
| restore_db | no | yes | KEEP_SUPPORT | tested support module |
| restore_drill | no | yes | KEEP_SUPPORT | tested support module |
| signal_geometry_persistence | no | yes | KEEP_SUPPORT | tested support module |
| signal_index_query | no | yes | KEEP_SUPPORT | tested support module |
| survivorship_bias_corrector | no | no | KEEP_SUPPORT | KEEP_SUPPORT |
| tail_loss_governor | no | yes | KEEP_SUPPORT | tested support module |
| universe_coverage | no | yes | KEEP_SUPPORT | tested support module |
| why_today_enforcement | no | yes | KEEP_SUPPORT | tested support module |
