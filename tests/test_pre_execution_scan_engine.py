from datetime import datetime, timezone

from scripts.pipeline_health_report import build_pre_execution_scan_summary
from scripts.pre_execution_scan_engine import (
    BoardControlState,
    PreExecutionArchetype,
    PreExecutionDecision,
    PreExecutionScanConfig,
    PreExecutionScanEngine,
    PreExecutionScanInput,
    PressureState,
    ScanReadiness,
    SurpriseBand,
    TurnDecision,
    build_pre_execution_scan_report,
    clamp01,
    compute_board_control,
    compute_execution_timing_score,
    compute_gates,
    compute_hidden_preconditions_score,
    compute_mini_map_quality,
    compute_optionality,
    compute_pre_scan_quality,
    compute_pressure_awareness,
    compute_scan_frequency_effect,
    compute_scan_recency_score,
    compute_surprise_risk,
    compute_turn_safety,
    normalize_weights,
    safe_div,
    weighted_geometric_score,
)


def make_input(**overrides: object) -> PreExecutionScanInput:
    payload = {
        "signal_id": "SIGNAL_001",
        "timestamp": datetime(2026, 5, 7, tzinfo=timezone.utc),
        "raw_signal_strength": 0.78,
        "signal_confidence": 0.76,
        "validation_score": 0.78,
        "durability_score": 0.82,
        "execution_readiness_score": 0.80,
        "scan_count": 5,
        "scan_frequency_per_minute": 6.0,
        "scan_recency_seconds": 8.0,
        "scan_accuracy_score": 0.86,
        "context_freshness_score": 0.88,
        "information_decay_rate": 0.20,
        "known_actor_count": 9,
        "estimated_total_actor_count": 10,
        "teammate_alignment_score": 0.80,
        "opponent_pressure_score": 0.55,
        "exit_lane_count": 4,
        "safe_exit_lane_count": 3,
        "collision_risk_score": 0.20,
        "spatial_coverage_score": 0.82,
        "pressure_magnitude": 0.55,
        "pressure_closing_speed": 0.40,
        "pressure_angle_risk": 0.30,
        "pressure_direction_confidence": 0.78,
        "trap_risk_score": 0.30,
        "critical_zones_total": 4,
        "critical_zones_controlled": 3,
        "critical_zones_exposed": 1,
        "containment_strength_score": 0.72,
        "safe_action_count": 3,
        "total_action_count": 4,
        "best_action_quality_score": 0.82,
        "fallback_quality_score": 0.74,
        "recycle_quality_score": 0.76,
        "policy_veto": False,
        "chaos_veto": False,
        "shock_event": False,
        "heat_risk_score": 0.25,
        "volatility_score": 0.28,
        "contradiction_score": 0.10,
        "time_to_execution_seconds": 15.0,
        "execution_half_life_seconds": 45.0,
        "notes": [],
    }
    payload.update(overrides)
    return PreExecutionScanInput(**payload)


def test_clamp01_bounds() -> None:
    assert clamp01(-1.0) == 0.0
    assert clamp01(0.5) == 0.5
    assert clamp01(2.0) == 1.0


def test_safe_div_zero_default() -> None:
    assert safe_div(1.0, 0.0, default=0.7) == 0.7


def test_weighted_geometric_score_bounds() -> None:
    score = weighted_geometric_score({"a": 0.8, "b": 0.9}, {"a": 1.0, "b": 1.0})
    assert 0.0 <= score <= 1.0


def test_scan_frequency_effect_increases_with_frequency() -> None:
    assert compute_scan_frequency_effect(6.0) > compute_scan_frequency_effect(1.0)


def test_scan_recency_score_decreases_with_staleness() -> None:
    config = PreExecutionScanConfig()
    assert compute_scan_recency_score(5.0, config.max_scan_recency_seconds) > compute_scan_recency_score(
        40.0, config.max_scan_recency_seconds
    )


def test_pre_scan_quality_high_when_scans_fresh_and_accurate() -> None:
    score, _ = compute_pre_scan_quality(make_input(), PreExecutionScanConfig())
    assert score > 0.75


def test_pre_scan_quality_low_when_stale_and_inaccurate() -> None:
    score, _ = compute_pre_scan_quality(
        make_input(scan_frequency_per_minute=0.5, scan_recency_seconds=60.0, scan_accuracy_score=0.2, context_freshness_score=0.2),
        PreExecutionScanConfig(),
    )
    assert score < 0.35


def test_surprise_risk_decreases_with_scan_frequency() -> None:
    low, _ = compute_surprise_risk(make_input(scan_frequency_per_minute=1.0), PreExecutionScanConfig())
    high, _ = compute_surprise_risk(make_input(scan_frequency_per_minute=8.0), PreExecutionScanConfig())
    assert high < low


def test_surprise_risk_high_when_unknown_actor_coverage_high() -> None:
    risk, trace = compute_surprise_risk(
        make_input(
            known_actor_count=1,
            estimated_total_actor_count=10,
            scan_accuracy_score=0.4,
            context_freshness_score=0.4,
            scan_frequency_per_minute=0.5,
            scan_recency_seconds=40.0,
        ),
        PreExecutionScanConfig(),
    )
    assert risk > 0.50
    assert trace["unknown_variable_ratio"] > 0.5


def test_mini_map_quality_penalizes_collision_risk() -> None:
    low, _ = compute_mini_map_quality(make_input(collision_risk_score=0.8), PreExecutionScanConfig())
    high, _ = compute_mini_map_quality(make_input(collision_risk_score=0.1), PreExecutionScanConfig())
    assert high > low


def test_mini_map_quality_rewards_safe_exit_lanes() -> None:
    low, _ = compute_mini_map_quality(make_input(safe_exit_lane_count=1, exit_lane_count=4), PreExecutionScanConfig())
    high, _ = compute_mini_map_quality(make_input(safe_exit_lane_count=4, exit_lane_count=4), PreExecutionScanConfig())
    assert high > low


def test_pressure_awareness_penalizes_trap_risk() -> None:
    low, _ = compute_pressure_awareness(make_input(trap_risk_score=0.8), PreExecutionScanConfig())
    high, _ = compute_pressure_awareness(make_input(trap_risk_score=0.1), PreExecutionScanConfig())
    assert high > low


def test_board_control_controlled_state() -> None:
    score, state, _ = compute_board_control(
        make_input(
            critical_zones_total=4,
            critical_zones_controlled=4,
            critical_zones_exposed=0,
            containment_strength_score=0.80,
        ),
        PreExecutionScanConfig(),
    )
    assert score >= 0.75
    assert state == BoardControlState.CONTROLLED


def test_board_control_collapsing_state() -> None:
    score, state, _ = compute_board_control(
        make_input(critical_zones_total=4, critical_zones_controlled=0, critical_zones_exposed=4, containment_strength_score=0.1),
        PreExecutionScanConfig(),
    )
    assert score < 0.35
    assert state == BoardControlState.COLLAPSING


def test_optionality_score_rewards_safe_actions() -> None:
    low, _ = compute_optionality(make_input(safe_action_count=1, total_action_count=5), PreExecutionScanConfig())
    high, _ = compute_optionality(make_input(safe_action_count=4, total_action_count=5), PreExecutionScanConfig())
    assert high > low


def test_turn_allowed_when_pressure_low_and_optionality_high() -> None:
    config = PreExecutionScanConfig()
    scan_input = make_input(pressure_magnitude=0.20, trap_risk_score=0.10, collision_risk_score=0.10)
    mini_map, _ = compute_mini_map_quality(scan_input, config)
    board_score, _, _ = compute_board_control(scan_input, config)
    optionality, _ = compute_optionality(scan_input, config)
    pressure_awareness, _ = compute_pressure_awareness(scan_input, config)
    _, decision, _ = compute_turn_safety(
        scan_input,
        config,
        {
            "mini_map_quality_score": mini_map,
            "board_control_score": board_score,
            "optionality_score": optionality,
            "pressure_awareness_score": pressure_awareness,
        },
    )
    assert decision == TurnDecision.TURN_ALLOWED


def test_no_turn_when_trap_and_collision_high() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(trap_risk_score=0.8, collision_risk_score=0.8, safe_exit_lane_count=0)
    )
    assert report.turn_decision == TurnDecision.NO_TURN


def test_recycle_when_pressure_high_but_recycle_quality_good() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(pressure_magnitude=0.8, trap_risk_score=0.3, collision_risk_score=0.2, recycle_quality_score=0.8)
    )
    assert report.turn_decision == TurnDecision.RECYCLE


def test_categorizes_blind_scan_readiness() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(scan_frequency_per_minute=0.2, scan_recency_seconds=60.0, scan_accuracy_score=0.2, context_freshness_score=0.2)
    )
    assert report.scan_readiness == ScanReadiness.BLIND


def test_categorizes_high_awareness() -> None:
    report = PreExecutionScanEngine().evaluate(make_input())
    assert report.scan_readiness == ScanReadiness.HIGH_AWARENESS


def test_over_scanning_when_scan_high_but_timing_decays() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(
            scan_count=9,
            scan_frequency_per_minute=7.0,
            execution_half_life_seconds=10.0,
            time_to_execution_seconds=20.0,
            information_decay_rate=0.8,
        )
    )
    assert report.scan_readiness == ScanReadiness.OVER_SCANNING


def test_pressure_state_chaos_on_chaos_veto() -> None:
    report = PreExecutionScanEngine().evaluate(make_input(chaos_veto=True))
    assert report.pressure_state == PressureState.CHAOS


def test_surprise_band_critical() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(known_actor_count=0, estimated_total_actor_count=12, scan_accuracy_score=0.1, context_freshness_score=0.1, scan_recency_seconds=60.0, scan_frequency_per_minute=0.1)
    )
    assert report.surprise_band == SurpriseBand.CRITICAL


def test_action_permission_false_on_policy_veto() -> None:
    report = PreExecutionScanEngine().evaluate(make_input(policy_veto=True))
    assert report.action_permission is False


def test_action_permission_false_on_chaos_veto() -> None:
    report = PreExecutionScanEngine().evaluate(make_input(chaos_veto=True))
    assert report.action_permission is False


def test_action_permission_false_on_shock_event() -> None:
    report = PreExecutionScanEngine().evaluate(make_input(shock_event=True))
    assert report.action_permission is False


def test_action_permission_false_when_scan_quality_below_floor() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(scan_frequency_per_minute=0.2, scan_recency_seconds=60.0, scan_accuracy_score=0.2, context_freshness_score=0.2)
    )
    assert report.action_permission is False


def test_action_permission_false_when_board_control_below_floor() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(critical_zones_controlled=0, critical_zones_exposed=4, containment_strength_score=0.1)
    )
    assert report.action_permission is False


def test_action_permission_false_when_optionality_below_floor() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(safe_action_count=0, total_action_count=4, best_action_quality_score=0.2, fallback_quality_score=0.2, recycle_quality_score=0.2)
    )
    assert report.action_permission is False


def test_action_permission_true_for_clean_mapped_signal() -> None:
    report = PreExecutionScanEngine().evaluate(make_input())
    assert report.action_permission is True


def test_miura_mapping_when_raw_signal_high_but_scan_low() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(raw_signal_strength=0.9, validation_score=0.4, scan_frequency_per_minute=0.4, scan_recency_seconds=55.0, scan_accuracy_score=0.2, context_freshness_score=0.2)
    )
    assert report.pre_execution_archetype == PreExecutionArchetype.MIURA_BLIND_RAW_SIGNAL
    assert report.action_permission is False


def test_murcielago_mapping_under_pressure_with_good_scan() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(execution_readiness_score=0.55, pressure_magnitude=0.62, trap_risk_score=0.35, raw_signal_strength=0.70)
    )
    assert report.pre_execution_archetype == PreExecutionArchetype.MURCIELAGO_MAPPED_UNDER_PRESSURE


def test_aventador_mapping_when_prepared_but_not_execution_ready() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(execution_readiness_score=0.62, pressure_magnitude=0.30, raw_signal_strength=0.70)
    )
    assert report.pre_execution_archetype == PreExecutionArchetype.AVENTADOR_PREPARED_ACTIONABLE


def test_gallardo_mapping_when_all_gates_pass() -> None:
    report = PreExecutionScanEngine().evaluate(make_input())
    assert report.pre_execution_archetype == PreExecutionArchetype.GALLARDO_CLEAN_EXECUTION_READY


def test_diablo_mapping_on_chaos() -> None:
    report = PreExecutionScanEngine().evaluate(make_input(chaos_veto=True))
    assert report.pre_execution_archetype == PreExecutionArchetype.DIABLO_CHAOS_NO_TURN


def test_islero_mapping_on_shock() -> None:
    report = PreExecutionScanEngine().evaluate(make_input(shock_event=True))
    assert report.pre_execution_archetype == PreExecutionArchetype.ISLERO_SHOCK_REMAP


def test_huracan_fast_track_requires_scan_floor() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(raw_signal_strength=0.95, validation_score=0.72, durability_score=0.70, execution_readiness_score=0.70, time_to_execution_seconds=8.0, execution_half_life_seconds=20.0)
    )
    assert report.pre_execution_archetype == PreExecutionArchetype.HURACAN_FAST_TRACK_WITH_SCAN_FLOOR


def test_huracan_fast_track_cannot_bypass_policy_veto() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(raw_signal_strength=0.95, validation_score=0.72, durability_score=0.70, execution_readiness_score=0.70, time_to_execution_seconds=8.0, execution_half_life_seconds=20.0, policy_veto=True)
    )
    assert report.pre_execution_archetype != PreExecutionArchetype.HURACAN_FAST_TRACK_WITH_SCAN_FLOOR
    assert report.action_permission is False


def test_huracan_fast_track_cannot_bypass_chaos_veto() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(raw_signal_strength=0.95, validation_score=0.72, durability_score=0.70, execution_readiness_score=0.70, time_to_execution_seconds=8.0, execution_half_life_seconds=20.0, chaos_veto=True)
    )
    assert report.pre_execution_archetype != PreExecutionArchetype.HURACAN_FAST_TRACK_WITH_SCAN_FLOOR
    assert report.action_permission is False


def test_report_contains_formula_trace() -> None:
    report = PreExecutionScanEngine().evaluate(make_input())
    required_keys = {
        "scan_frequency_effect",
        "scan_recency_score",
        "known_actor_coverage",
        "unknown_variable_ratio",
        "information_staleness",
        "raw_surprise_risk",
        "adjusted_surprise_risk",
        "actor_coverage",
        "exit_lane_quality",
        "collision_safety",
        "mini_map_weighted_score",
        "mini_map_geometric_score",
        "pressure_speed",
        "awareness_speed",
        "failure_risk",
        "critical_square_coverage",
        "exposure_ratio",
        "board_control_score",
        "safe_action_ratio",
        "optionality_score",
        "telemetry_freshness_score",
        "hidden_preconditions_score",
        "execution_ceiling",
        "weighted_geometric_final_raw",
        "final_pre_execution_score",
        "unsafe_action_risk",
        "murcielago_fit",
        "gallardo_fit",
    }
    assert required_keys.issubset(report.formula_trace.keys())


def test_report_contains_transition_log() -> None:
    report = PreExecutionScanEngine().evaluate(make_input())
    assert report.transition_log


def test_report_contains_recommended_next_steps() -> None:
    report = PreExecutionScanEngine().evaluate(make_input(chaos_veto=True))
    assert report.recommended_next_steps


def test_unsafe_action_risk_high_when_detection_outruns_context() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(raw_signal_strength=0.95, validation_score=0.20, scan_frequency_per_minute=0.4, scan_accuracy_score=0.2, context_freshness_score=0.2)
    )
    assert report.formula_trace["unsafe_action_risk"] > 0.25


def test_final_score_capped_by_hidden_preconditions() -> None:
    report = PreExecutionScanEngine().evaluate(
        make_input(raw_signal_strength=0.95, execution_readiness_score=0.95, scan_frequency_per_minute=0.5, scan_accuracy_score=0.3, context_freshness_score=0.3, known_actor_count=2, estimated_total_actor_count=10)
    )
    assert report.final_pre_execution_score <= report.formula_trace["execution_ceiling"] + 0.05 + 1e-9


def test_experts_see_preconditions_principle_via_hidden_preconditions_score() -> None:
    report = PreExecutionScanEngine().evaluate(make_input())
    assert report.hidden_preconditions_score >= 0.70


def test_pipeline_health_report_integration_if_integrated() -> None:
    report = build_pre_execution_scan_report(
        [{"ticker": "RTX", "truth_probability": 0.8, "signal_strength_score": 0.7}],
        runtime_state={"policy_state": "RESTRICTED"},
        write_runtime=False,
    )
    summary = build_pre_execution_scan_summary(report)
    assert summary["pre_execution_scan_state"]
    assert "pre_execution_score" in summary


def test_normalize_weights_normalizes_safely() -> None:
    weights = normalize_weights({"a": 2.0, "b": 1.0})
    assert round(sum(weights.values()), 10) == 1.0


def test_compute_gates_respects_action_floors() -> None:
    scan_input = make_input()
    gates = compute_gates(
        scan_input,
        {
            "pre_scan_quality_score": 0.8,
            "surprise_risk_score": 0.2,
            "board_control_score": 0.8,
            "optionality_score": 0.8,
            "execution_timing_score": 0.8,
        },
        PreExecutionScanConfig(),
    )
    assert gates["scan_gate_pass"] is True
    assert gates["board_control_gate_pass"] is True


def test_hidden_preconditions_score_is_multiplicative() -> None:
    score, trace = compute_hidden_preconditions_score(
        {
            "pre_scan_quality_score": 0.9,
            "mini_map_quality_score": 0.9,
            "board_control_score": 0.9,
            "optionality_score": 0.9,
            "pressure_awareness_score": 0.2,
            "execution_readiness_score": 0.9,
        },
        PreExecutionScanConfig(),
    )
    assert score < 0.9
    assert trace["execution_ceiling"] <= 0.9
