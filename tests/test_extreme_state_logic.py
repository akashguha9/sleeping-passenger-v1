from __future__ import annotations

from scripts.extreme_state import (
    DO_NOT_DEPLOY,
    HIGH_EFFICIENCY_EDGE,
    INFINITE_LOOP_RISK,
    NON_CONVERTING_EQUILIBRIUM,
    REPEATABLE_STRUCTURAL_EDGE,
    SILENT_CHAOS,
    STRUCTURAL_ADVANTAGE_EDGE,
    TERMINATION_REQUIRED,
    VALID_BUT_NON_EXECUTABLE,
    evaluate_extreme_state_signal,
)
from scripts.extreme_state.termination_gate import compute_loop_risk


def _base_signal() -> dict:
    return {
        "signal_id": "SIG_X",
        "symbol": "EDGE",
        "policy_state": "READY",
        "signal_strength_score": 0.76,
        "signal_validity_score": 0.72,
        "technique_score": 0.70,
        "structure_score": 0.60,
        "timing_score": 0.60,
        "sequence_quality": 0.60,
        "timing_precision": 0.60,
        "transfer_efficiency": 0.60,
        "contact_quality": 0.60,
        "access_score": 0.55,
        "angle_score": 0.55,
        "timing_access_score": 0.55,
        "constraint_reduction_score": 0.55,
        "successful_repetitions": 2,
        "total_attempts": 4,
        "stress_survival_score": 0.60,
        "trigger_presence_score": 0.60,
        "conversion_trigger_score": 0.60,
        "timing_window_score": 0.60,
        "opponent_weakness_score": 0.55,
        "opponent_counter_signal_strength": 0.30,
        "exit_clarity_score": 0.70,
        "stability_score": 0.55,
        "duration_zscore_normalized": 0.25,
        "transition_count": 1,
        "transition_rate": 0.60,
        "cost_increase_score": 0.20,
        "visible_volatility_score": 0.45,
        "time_cost": 0.20,
        "mental_cost": 0.20,
        "opportunity_cost": 0.20,
        "risk_cost": 0.20,
    }


def test_roddick_case_maps_to_high_efficiency_edge() -> None:
    signal = _base_signal()
    signal.update(
        {
            "structure_score": 0.52,
            "sequence_quality": 0.95,
            "timing_precision": 0.94,
            "transfer_efficiency": 0.92,
            "contact_quality": 0.93,
            "access_score": 0.48,
            "angle_score": 0.49,
            "timing_access_score": 0.50,
            "constraint_reduction_score": 0.49,
            "successful_repetitions": 2,
            "total_attempts": 5,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state == HIGH_EFFICIENCY_EDGE


def test_karlovic_case_maps_to_structural_advantage_edge() -> None:
    signal = _base_signal()
    signal.update(
        {
            "access_score": 0.90,
            "angle_score": 0.88,
            "timing_access_score": 0.82,
            "constraint_reduction_score": 0.86,
            "successful_repetitions": 1,
            "total_attempts": 3,
            "stress_survival_score": 0.50,
            "sequence_quality": 0.45,
            "timing_precision": 0.48,
            "transfer_efficiency": 0.40,
            "contact_quality": 0.44,
            "signal_validity_score": 0.55,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state == STRUCTURAL_ADVANTAGE_EDGE


def test_isner_case_maps_to_repeatable_structural_edge() -> None:
    signal = _base_signal()
    signal.update(
        {
            "access_score": 0.90,
            "angle_score": 0.88,
            "timing_access_score": 0.85,
            "constraint_reduction_score": 0.88,
            "successful_repetitions": 8,
            "total_attempts": 10,
            "stress_survival_score": 0.90,
            "signal_validity_score": 0.75,
            "conversion_trigger_score": 0.72,
            "trigger_presence_score": 0.72,
            "timing_window_score": 0.72,
            "opponent_weakness_score": 0.65,
            "exit_clarity_score": 0.78,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state == REPEATABLE_STRUCTURAL_EDGE
    assert result.decision["action"] in {"PROMOTE", "HOLD"}


def test_isner_mahut_loop_detected_as_infinite_loop_risk() -> None:
    signal = _base_signal()
    signal.update(
        {
            "signal_validity_score": 0.80,
            "stability_score": 0.92,
            "trigger_presence_score": 0.10,
            "conversion_trigger_score": 0.12,
            "timing_window_score": 0.14,
            "opponent_weakness_score": 0.10,
            "opponent_counter_signal_strength": 0.78,
            "exit_clarity_score": 0.12,
            "duration_zscore_normalized": 0.55,
            "transition_count": 0,
            "transition_rate": 0.05,
            "cost_increase_score": 0.38,
            "visible_volatility_score": 0.30,
            "time_cost": 0.42,
            "mental_cost": 0.40,
            "opportunity_cost": 0.45,
            "risk_cost": 0.40,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state in {INFINITE_LOOP_RISK, NON_CONVERTING_EQUILIBRIUM}
    assert result.decision["action"] in {"TERMINATE", "DOWNGRADE"}


def test_silent_chaos_triggers_terminate_even_with_low_visible_volatility() -> None:
    signal = _base_signal()
    signal.update(
        {
            "duration_zscore_normalized": 0.88,
            "transition_rate": 0.05,
            "transition_count": 0,
            "cost_increase_score": 0.72,
            "visible_volatility_score": 0.08,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.flags["silent_chaos_flag"] is True
    assert result.extreme_state in {SILENT_CHAOS, TERMINATION_REQUIRED}
    assert result.decision["action"] == "TERMINATE"


def test_valid_signal_can_still_be_non_executable() -> None:
    signal = _base_signal()
    signal.update(
        {
            "signal_validity_score": 0.86,
            "trigger_presence_score": 0.22,
            "conversion_trigger_score": 0.18,
            "timing_window_score": 0.20,
            "opponent_weakness_score": 0.18,
            "exit_clarity_score": 0.20,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state == VALID_BUT_NON_EXECUTABLE
    assert result.decision["action"] in {"HOLD", "DOWNGRADE"}


def test_termination_gate_fires_on_duration_without_transition() -> None:
    signal = _base_signal()
    signal.update(
        {
            "duration_zscore_normalized": 0.95,
            "transition_count": 0,
            "transition_rate": 0.0,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.flags["termination_required"] is True
    assert result.extreme_state in {TERMINATION_REQUIRED, SILENT_CHAOS}


def test_policy_veto_forces_do_not_deploy() -> None:
    signal = _base_signal()
    signal["policy_state"] = "RESTRICTED"
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state == DO_NOT_DEPLOY
    assert result.flags["policy_veto"] is True
    assert result.flags["executable"] is False


def test_exit_clarity_reduces_loop_risk() -> None:
    low_exit = compute_loop_risk(0.9, 0.8, 0.8)
    high_exit = compute_loop_risk(0.9, 0.2, 0.8)
    assert high_exit < low_exit


def test_partial_input_does_not_crash_and_emits_warnings() -> None:
    result = evaluate_extreme_state_signal({"signal_id": "PARTIAL", "symbol": "P"})
    assert result.signal_id == "PARTIAL"
    assert result.warnings
