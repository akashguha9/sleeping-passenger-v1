from __future__ import annotations

from scripts.chess_archetype_decision_layer import (
    ChessArchetype,
    DecisionState,
    evaluate_chess_signal,
    generate_chess_archetype_report,
    write_chess_archetype_report,
)
from scripts.pipeline_health_report import build_pipeline_health_report


def _base_signal() -> dict:
    return {
        "signal_id": "BASE",
        "detection_score": 0.8,
        "signal_strength": 0.8,
        "evidence_depth": 0.8,
        "volatility": 0.25,
        "contradiction_level": 0.2,
        "timing_window": 0.8,
        "liquidity_risk": 0.2,
        "operator_readiness": 0.8,
        "external_confirmation": 0.8,
        "hidden_risk_score": 0.2,
        "control_score": 0.75,
        "chaos_score": 0.25,
        "collapse_risk": 0.2,
        "operator_confusion": 0.2,
        "policy_risk": 0.0,
        "structural_edge": 0.8,
        "narrative_heat": 0.3,
        "performance_after_stress": 0.78,
        "performance_before_stress": 0.8,
        "stress_survival": 0.8,
        "counterplay_reduction": 0.75,
        "persistence": 0.78,
        "confirmation_depth": 0.8,
        "maintenance_cost": 0.2,
        "execution_survivability": 0.8,
        "initiative": 0.7,
        "feasibility": 0.8,
        "asymmetry": 0.75,
        "residual_risk": 0.2,
        "minimum_validation": 0.75,
        "momentum_spike": 0.7,
        "risk_cap": 1.0,
        "freshness": 0.8,
        "repricing_lag": 0.7,
        "crowd_saturation": 0.2,
        "anomaly": 0.2,
        "narrative_instability": 0.25,
        "sentiment_divergence": 0.2,
        "volume_shock": 0.2,
        "opponent_overload_potential": 0.4,
        "self_collapse_risk": 0.2,
        "option_margin": 0.3,
        "analysis_depth": 0.8,
        "error_suppression": 0.8,
        "complexity_cost": 0.25,
        "information_gain": 0.7,
        "optionality_loss": 0.2,
        "shock_event_score": 0.2,
        "event_certainty": 0.2,
        "repricing_probability": 0.2,
        "structural_impact": 0.2,
        "preparation": 0.75,
        "target_weakness": 0.7,
        "exposure_cost": 0.2,
        "review_depth": 0.8,
        "method_update": 0.8,
        "cognitive_load": 0.3,
        "time_pressure": 0.4,
        "ambiguity": 0.2,
        "crowding": 0.2,
        "incentive_conflict": 0.2,
        "battlefield_choice": 0.8,
        "opponent_strength_neutralization": 0.75,
        "adaptive_speed": 0.75,
        "style_flexibility": 0.75,
        "style_drift": 0.15,
        "low_error_rate": 0.8,
        "execution_quality": 0.8,
        "exit_quality": 0.8,
        "counterplay": 0.2,
        "friction_cost": 0.2,
        "operator_misfit": 0.1,
        "drawdown": 0.1,
        "uncertainty": 0.2,
        "operator_stress": 0.2,
        "entry_defined": True,
        "sizing_defined": True,
        "invalidation_defined": True,
        "exit_defined": True,
        "review_defined": True,
        "policy_veto": False,
        "can_deploy_capital": False,
        "risk_cap_passed": True,
        "source": "synthetic",
    }


def test_policy_veto_always_overrides_every_archetype() -> None:
    signal = _base_signal() | {"policy_veto": True}
    result = evaluate_chess_signal(signal, policy={"allow_new_risk": False})
    assert result["decision"] == DecisionState.VETO.value
    assert result["vetoes"]["policy_veto"] is True


def test_tal_chaos_can_generate_but_cannot_execute_directly() -> None:
    signal = _base_signal() | {
        "anomaly": 0.9,
        "narrative_instability": 0.9,
        "sentiment_divergence": 0.8,
        "volume_shock": 0.8,
        "opponent_overload_potential": 0.85,
        "self_collapse_risk": 0.55,
        "entry_defined": False,
        "sizing_defined": False,
        "invalidation_defined": False,
        "exit_defined": False,
    }
    result = evaluate_chess_signal(signal)
    assert result["chaos_hypothesis"]["raw_hypothesis"] is True
    assert result["decision"] != DecisionState.EXECUTE.value


def test_morphy_fast_track_requires_minimum_validation_and_risk_cap() -> None:
    signal = _base_signal() | {"minimum_validation": 0.4, "risk_cap_passed": False, "momentum_spike": 0.95}
    result = evaluate_chess_signal(signal)
    assert result["tempo_advantage"]["fast_track_candidate"] is False


def test_steinitz_gate_blocks_unsupported_aggression() -> None:
    signal = _base_signal() | {"structural_edge": 0.35, "evidence_depth": 0.4, "narrative_heat": 0.95}
    result = evaluate_chess_signal(signal)
    assert result["positional_gate"]["positional_justification_passed"] is False
    assert result["decision"] in {DecisionState.VALIDATE.value, DecisionState.WAIT.value}


def test_petrosian_detector_catches_hidden_risk_before_promotion() -> None:
    signal = _base_signal() | {"liquidity_risk": 0.9, "friction_cost": 0.9, "operator_stress": 0.9}
    result = evaluate_chess_signal(signal)
    assert result["hidden_risk"]["passed"] is False
    assert result["vetoes"]["hidden_risk_veto"] is True


def test_karpov_durability_sits_before_kasparov_promotion() -> None:
    signal = _base_signal() | {
        "initiative": 0.95,
        "timing_window": 0.95,
        "performance_after_stress": 0.35,
        "stress_survival": 0.35,
        "persistence": 0.35,
    }
    result = evaluate_chess_signal(signal)
    assert result["durability_validation"]["admission_decision"] is False
    assert result["promotion"]["promoted"] is False


def test_caruana_precision_triggers_when_option_margins_are_thin() -> None:
    signal = _base_signal() | {"option_margin": 0.05}
    result = evaluate_chess_signal(signal)
    assert result["precision_validation"]["precision_required"] is True


def test_capablanca_simplification_triggers_when_complexity_exceeds_information_gain() -> None:
    signal = _base_signal() | {"complexity_cost": 0.9, "information_gain": 0.2, "operator_confusion": 0.65}
    result = evaluate_chess_signal(signal)
    assert result["simplification"]["simplify_now"] is True
    assert result["decision"] == DecisionState.SIMPLIFY.value


def test_fischer_shock_forces_state_reclassification() -> None:
    signal = _base_signal() | {"shock_event_score": 0.9, "event_certainty": 0.9, "repricing_probability": 0.9, "structural_impact": 0.9}
    result = evaluate_chess_signal(signal)
    assert result["forced_line"]["shock_detected"] is True
    assert result["final_state"] == "FORCED_LINE"


def test_ding_recovery_blocks_new_high_risk_action() -> None:
    signal = _base_signal() | {"drawdown": 0.9, "uncertainty": 0.9, "operator_stress": 0.9}
    result = evaluate_chess_signal(signal)
    assert result["recovery"]["recovery_mode_active"] is True
    assert result["decision"] == DecisionState.RECOVER.value


def test_carlsen_conversion_requires_execution_packet() -> None:
    signal = _base_signal() | {
        "entry_defined": False,
        "sizing_defined": False,
        "invalidation_defined": False,
        "exit_defined": False,
    }
    result = evaluate_chess_signal(signal)
    assert result["conversion"]["executable_signal"] is False
    assert result["decision"] != DecisionState.EXECUTE.value


def test_four_order_consequence_score_affects_final_decision() -> None:
    signal = _base_signal() | {"collapse_risk": 0.9, "maintenance_cost": 0.9, "policy_risk": 0.6, "operator_misfit": 0.8}
    result = evaluate_chess_signal(signal)
    assert result["scores"]["multi_order_consequence"] < 0.55
    assert result["decision"] != DecisionState.EXECUTE.value


def test_detection_does_not_equal_admission() -> None:
    signal = _base_signal() | {"detection_score": 0.95, "evidence_depth": 0.3, "minimum_validation": 0.3}
    result = evaluate_chess_signal(signal)
    assert result["decision"] != DecisionState.EXECUTE.value


def test_good_signal_but_bad_execution_becomes_wait_or_validate_not_execute() -> None:
    signal = _base_signal() | {"execution_quality": 0.25, "low_error_rate": 0.25, "exit_quality": 0.25}
    result = evaluate_chess_signal(signal)
    assert result["decision"] in {DecisionState.WATCH.value, DecisionState.VALIDATE.value, DecisionState.WAIT.value}


def test_chaos_veto_outranks_fast_track() -> None:
    signal = _base_signal() | {
        "momentum_spike": 0.95,
        "minimum_validation": 0.95,
        "risk_cap_passed": True,
        "chaos_score": 0.95,
        "control_score": 0.3,
    }
    result = evaluate_chess_signal(signal)
    assert result["tempo_advantage"]["fast_track_candidate"] is False
    assert result["decision"] == DecisionState.VETO.value


def test_adaptive_selector_does_not_over_switch_when_confidence_is_low() -> None:
    signal = _base_signal() | {"style_flexibility": 0.55, "style_drift": 0.7, "adaptive_speed": 0.56, "initiative": 0.57}
    result = evaluate_chess_signal(signal)
    assert result["adaptive_selector"]["style_drift_warning"] is True


def test_report_json_contains_required_keys() -> None:
    report = generate_chess_archetype_report([_base_signal()])
    assert {
        "total_signals_evaluated",
        "archetype_distribution",
        "veto_counts",
        "fast_track_candidates",
        "chaos_hypotheses_generated",
        "chaos_hypotheses_admitted",
        "durability_pass_rate",
        "precision_required_cases",
        "simplification_cases",
        "forced_line_reclassifications",
        "recovery_activations",
        "average_multi_order_consequence_score",
        "most_common_rejection_reason",
        "system_readiness_impact",
    }.issubset(report.keys())


def test_runtime_payload_contains_run_id() -> None:
    report = write_chess_archetype_report([_base_signal()], runtime_state={}, write_runtime=False)
    assert report["artifact"]["run_id"]


def test_pipeline_health_report_includes_chess_fields() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    assert report["chess_archetype_layer_available"] is True
    assert "chess_selected_archetype" in report
    assert "chess_report_path" in report
