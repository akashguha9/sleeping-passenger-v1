from __future__ import annotations

from scripts.extreme_state import (
    DO_NOT_DEPLOY,
    HIGH_EFFICIENCY_EDGE,
    NON_CONVERTING_EQUILIBRIUM,
    REPEATABLE_EDGE,
    SILENT_CHAOS,
    STRUCTURAL_ADVANTAGE_EDGE,
    VALID_BUT_NON_EXECUTABLE,
    evaluate_extreme_state_signal,
)
from scripts.extreme_state.extreme_state_report import build_extreme_state_report
from scripts.extreme_state.termination_gate import compute_loop_risk


def _base_signal() -> dict:
    return {
        "signal_id": "SIG_X",
        "symbol": "EDGE",
        "policy_state": "READY",
        "signal_strength_score": 0.75,
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
        "persistence_score": 0.60,
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


def test_roddick_case_maps_to_high_efficiency_edge():
    signal = _base_signal()
    signal.update(
        {
            "structure_score": 0.55,
            "sequence_quality": 0.95,
            "timing_precision": 0.94,
            "transfer_efficiency": 0.92,
            "contact_quality": 0.93,
            "access_score": 0.52,
            "angle_score": 0.50,
            "timing_access_score": 0.54,
            "constraint_reduction_score": 0.50,
            "successful_repetitions": 2,
            "total_attempts": 5,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state == HIGH_EFFICIENCY_EDGE


def test_karlovic_case_maps_to_structural_advantage_edge():
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


def test_isner_case_maps_to_repeatable_edge():
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
    assert result.extreme_state == REPEATABLE_EDGE
    assert result.decision["action"] in {"PROMOTE", "WAIT"}


def test_isner_mahut_loop_detected_as_silent_or_non_converting():
    signal = _base_signal()
    signal.update(
        {
            "signal_validity_score": 0.80,
            "persistence_score": 0.92,
            "stability_score": 0.90,
            "trigger_presence_score": 0.10,
            "conversion_trigger_score": 0.12,
            "timing_window_score": 0.14,
            "opponent_weakness_score": 0.10,
            "opponent_counter_signal_strength": 0.78,
            "exit_clarity_score": 0.12,
            "duration_zscore_normalized": 0.95,
            "transition_count": 0,
            "transition_rate": 0.05,
            "cost_increase_score": 0.80,
            "visible_volatility_score": 0.10,
            "time_cost": 0.60,
            "mental_cost": 0.60,
            "opportunity_cost": 0.75,
            "risk_cost": 0.55,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state in {SILENT_CHAOS, NON_CONVERTING_EQUILIBRIUM}
    assert result.decision["action"] in {"TERMINATE", "DOWNGRADE"}


def test_valid_signal_can_still_be_non_executable():
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
    assert result.decision["action"] == "DOWNGRADE"


def test_policy_veto_forces_do_not_deploy():
    signal = _base_signal()
    signal["policy_state"] = "RESTRICTED"
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state == DO_NOT_DEPLOY
    assert result.flags["policy_veto"] is True
    assert result.flags["can_execute"] is False


def test_silent_chaos_triggers_even_with_low_visible_volatility():
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
    assert result.extreme_state == SILENT_CHAOS


def test_persistence_without_state_change_is_not_progress():
    signal = _base_signal()
    signal.update({"persistence_score": 0.90, "transition_rate": 0.05})
    result = evaluate_extreme_state_signal(signal)
    assert result.scores["progress_score"] < 0.10


def test_exit_clarity_reduces_loop_risk():
    low = compute_loop_risk(0.9, 0.2, 0.2, 0.8)
    high = compute_loop_risk(0.9, 0.2, 0.8, 0.8)
    assert high < low


def test_opponent_symmetry_downgrades_when_counter_signal_matches():
    signal = _base_signal()
    signal.update(
        {
            "signal_validity_score": 0.76,
            "signal_strength_score": 0.82,
            "opponent_counter_signal_strength": 0.80,
            "trigger_presence_score": 0.20,
            "conversion_trigger_score": 0.20,
            "timing_window_score": 0.20,
            "opponent_weakness_score": 0.20,
            "exit_clarity_score": 0.32,
            "transition_rate": 0.12,
            "persistence_score": 0.84,
            "stability_score": 0.82,
        }
    )
    result = evaluate_extreme_state_signal(signal)
    assert result.extreme_state in {NON_CONVERTING_EQUILIBRIUM, VALID_BUT_NON_EXECUTABLE}
    assert result.decision["action"] == "DOWNGRADE"


def test_partial_input_does_not_crash_and_emits_warnings():
    result = evaluate_extreme_state_signal({"signal_id": "PARTIAL", "symbol": "P"})
    assert result.signal_id == "PARTIAL"
    assert result.warnings


def test_extreme_state_report_contains_required_top_level_keys(scratch_path):
    report = build_extreme_state_report(
        [_base_signal()],
        runtime_state={"execution_policy": {"policy_state": "READY"}},
        output_path=scratch_path / "extreme_state_report.json",
        write_runtime=True,
    )
    assert report["report_path"].endswith("extreme_state_report.json")
    assert "run_id" in report
    assert "scores" in report
    assert "signals" in report
    assert "extreme_state_logic" in report
