from __future__ import annotations

import json

from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.run_tennis_archetype_diagnostics import run_tennis_archetype_diagnostics
from scripts.tennis_archetype_execution import (
    ExecutionStyle,
    RecommendedAction,
    apply_tennis_execution_gates,
    classify_execution_style,
    generate_tennis_archetype_report,
)


def _base_signal() -> dict:
    return {
        "signal_id": "BASE",
        "detection_score": 0.8,
        "output_quality": 0.8,
        "energy_cost": 0.2,
        "timing_quality": 0.8,
        "error_control": 0.8,
        "performance_after_stress": 0.75,
        "performance_before_stress": 0.8,
        "signal_strength": 0.8,
        "stress_survival": 0.75,
        "repeatability": 0.75,
        "volatility_tolerance": 0.75,
        "recovery_speed": 0.75,
        "pressure_absorbed": 0.75,
        "timing": 0.8,
        "pattern_dependence": 0.4,
        "disruption_timing": 0.4,
        "opponent_adjustment_lag": 0.4,
        "initial_shock": 0.4,
        "reaction_delay": 0.4,
        "timing_window": 0.4,
        "minimum_validation": 0.7,
        "weapon_strength": 0.6,
        "access_frequency": 0.6,
        "pressure_access": 0.6,
        "dominant_variable": 0.6,
        "momentum": 0.5,
        "discipline_score": 0.8,
        "chaos_score": 0.3,
        "unpredictability": 0.3,
        "executability": 0.7,
        "control": 0.8,
        "emotional_instability": 0.2,
        "decision_impact": 0.7,
        "raw_skill": 0.8,
        "velocity": 0.5,
        "confidence": 0.8,
        "external_energy": 0.4,
        "aesthetic_appeal": 0.3,
        "structural_reliability": 0.8,
        "upside": 0.7,
        "variance_penalty": 0.3,
        "low_repeatability": 0.2,
        "chaos_exposure": 0.3,
        "validation_score": 0.75,
        "durability_score": 0.75,
        "execution_survivability": 0.75,
        "heat_score": 0.3,
        "risk_guard_score": 0.3,
        "policy_veto": False,
        "can_deploy_capital": False,
        "risk_cap_active": True,
        "entry_defined": True,
        "invalidation_defined": True,
        "sizing_defined": True,
        "exit_defined": True,
        "review_defined": True,
        "pattern_shock": False,
        "source": "synthetic",
    }


def test_federer_like_signal_maps_to_frictionless_control_and_gallardo() -> None:
    signal = _base_signal() | {
        "signal_id": "FEDERER",
        "output_quality": 0.95,
        "energy_cost": 0.1,
        "timing_quality": 0.92,
        "error_control": 0.95,
        "validation_score": 0.85,
        "minimum_validation": 0.85,
        "durability_score": 0.8,
        "execution_survivability": 0.85,
    }
    classified = classify_execution_style(signal)
    gated = apply_tennis_execution_gates(signal)
    assert classified["execution_style"] == ExecutionStyle.FRICTIONLESS_CONTROL.value
    assert gated["bull_state"] == "GALLARDO"


def test_nadal_like_signal_maps_to_pressure_durability_and_murcielago() -> None:
    signal = _base_signal() | {
        "signal_id": "NADAL",
        "signal_strength": 0.9,
        "stress_survival": 0.95,
        "repeatability": 0.9,
        "performance_after_stress": 0.92,
        "performance_before_stress": 0.94,
        "durability_score": 0.9,
        "entry_defined": False,
        "invalidation_defined": False,
        "sizing_defined": False,
        "exit_defined": False,
    }
    classified = classify_execution_style(signal)
    gated = apply_tennis_execution_gates(signal)
    assert classified["execution_style"] == ExecutionStyle.PRESSURE_DURABILITY.value
    assert gated["bull_state"] == "MURCIELAGO"


def test_djokovic_like_signal_absorbs_chaos_but_diablo_if_chaos_too_high() -> None:
    signal = _base_signal() | {
        "signal_id": "DJOKOVIC",
        "volatility_tolerance": 0.95,
        "recovery_speed": 0.95,
        "pressure_absorbed": 0.95,
        "chaos_score": 0.9,
    }
    classified = classify_execution_style(signal)
    gated = apply_tennis_execution_gates(signal)
    assert classified["execution_style"] == ExecutionStyle.CHAOS_ABSORPTION.value
    assert gated["bull_state"] == "DIABLO"


def test_roddick_first_strike_cannot_fast_track_without_validation_floor() -> None:
    signal = _base_signal() | {
        "signal_id": "RODDICK",
        "initial_shock": 0.95,
        "reaction_delay": 0.9,
        "timing_window": 0.9,
        "minimum_validation": 0.4,
        "validation_score": 0.4,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["execution_style"] == ExecutionStyle.FIRST_STRIKE.value
    assert gated["gates"]["fast_track_allowed"] is False


def test_alcaraz_hybrid_fast_tracks_only_with_momentum_and_validation() -> None:
    signal = _base_signal() | {
        "signal_id": "ALCARAZ",
        "momentum": 0.9,
        "minimum_validation": 0.8,
        "discipline_score": 0.9,
        "velocity": 0.9,
        "external_energy": 0.8,
        "entry_defined": False,
        "invalidation_defined": False,
        "sizing_defined": False,
        "exit_defined": False,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["execution_style"] == ExecutionStyle.HYBRID_FAST_TRACK.value
    assert gated["gates"]["fast_track_allowed"] is True
    assert gated["bull_state"] == "HURACAN"


def test_bublik_controlled_chaos_allowed_only_below_veto_with_control() -> None:
    signal = _base_signal() | {
        "signal_id": "BUBLIK",
        "unpredictability": 0.9,
        "executability": 0.85,
        "control": 0.85,
        "chaos_score": 0.68,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["execution_style"] == ExecutionStyle.CONTROLLED_CHAOS.value
    assert gated["bull_state"] != "DIABLO"


def test_safin_signal_gets_emotional_volatility_penalty_and_may_be_blocked() -> None:
    signal = _base_signal() | {
        "signal_id": "SAFIN",
        "emotional_instability": 0.95,
        "decision_impact": 0.9,
        "validation_score": 0.5,
        "minimum_validation": 0.5,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["scores"]["emotional_volatility_penalty"] >= 0.65
    assert gated["bull_state"] == "DIABLO"


def test_tsitsipas_beauty_without_reliability_is_aesthetic_trap() -> None:
    signal = _base_signal() | {
        "signal_id": "TSITSIPAS",
        "aesthetic_appeal": 0.95,
        "structural_reliability": 0.35,
        "durability_score": 0.35,
        "validation_score": 0.5,
        "minimum_validation": 0.5,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["execution_style"] == ExecutionStyle.AESTHETIC_RAW_SIGNAL.value
    assert gated["scores"]["aesthetic_trap_risk"] > 0.3


def test_verdasco_signal_gets_high_variance_risk() -> None:
    signal = _base_signal() | {
        "signal_id": "VERDASCO",
        "variance_penalty": 0.95,
        "low_repeatability": 0.9,
        "chaos_exposure": 0.85,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["execution_style"] == ExecutionStyle.HIGH_VARIANCE_SHOTMAKING.value
    assert gated["scores"]["high_variance_risk"] >= 0.6


def test_nishikori_signal_gets_repeatable_precision_classification() -> None:
    signal = _base_signal() | {
        "signal_id": "NISHIKORI",
        "timing": 0.95,
        "repeatability": 0.95,
        "error_control": 0.95,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["execution_style"] == ExecutionStyle.REPEATABLE_PRECISION.value


def test_policy_veto_always_overrides_every_other_gate() -> None:
    signal = _base_signal() | {
        "signal_id": "POLICY",
        "policy_veto": True,
        "momentum": 0.95,
        "minimum_validation": 0.95,
    }
    gated = apply_tennis_execution_gates(signal, policy={"allow_new_risk": False})
    assert gated["bull_state"] == "DIABLO"
    assert gated["recommended_action"] == RecommendedAction.BLOCK_NO_NEW_RISK.value


def test_detected_signal_never_equals_executable_without_validation() -> None:
    signal = _base_signal() | {
        "signal_id": "RAW",
        "detection_score": 0.95,
        "validation_score": 0.3,
        "minimum_validation": 0.3,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["bull_state"] == "MIURA"


def test_miura_raw_signal_cannot_become_gallardo_directly() -> None:
    signal = _base_signal() | {
        "signal_id": "MIURA",
        "validation_score": 0.4,
        "minimum_validation": 0.4,
        "entry_defined": True,
        "invalidation_defined": True,
        "sizing_defined": True,
        "exit_defined": True,
        "review_defined": True,
    }
    gated = apply_tennis_execution_gates(signal)
    assert gated["bull_state"] != "GALLARDO"


def test_report_json_contains_required_keys() -> None:
    report = generate_tennis_archetype_report([_base_signal()])
    assert {
        "total_signals",
        "distribution_by_execution_style",
        "distribution_by_player_archetype",
        "distribution_by_bull_state",
        "chaos_veto_count",
        "fast_track_candidate_count",
        "aesthetic_trap_count",
        "high_variance_count",
        "durability_pass_count",
        "execution_ready_simulation_only_count",
        "top_5_execution_ready_simulation_only",
        "top_5_blocked_by_chaos",
        "top_5_aesthetic_traps",
        "top_5_first_strike_candidates",
        "top_5_repeatable_precision_candidates",
    }.issubset(report.keys())


def test_cli_runner_generates_summary_payload() -> None:
    report = run_tennis_archetype_diagnostics(write_runtime=False)
    assert report["total_signals"] >= 1
    assert report["report_path"].endswith("tennis_archetype_report.json")


def test_pipeline_health_report_includes_tennis_fields() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    assert "tennis_archetype_state" in report
    assert "tennis_dominant_execution_style" in report
