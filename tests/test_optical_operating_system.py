from __future__ import annotations

from scripts.optical_operating_system import (
    classify_aperture_state,
    classify_opacity_state,
    evaluate_optical_operating_system,
    evaluate_shutter_controller,
    transition_lens_mode,
)
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.snapshot_logger import build_snapshot_row


def _base_optical_context() -> dict:
    return {
        "timestamp": "2026-05-06T16:00:00+00:00",
        "run_id": "run-optical-001",
        "asset": "RTX",
        "ticker": "RTX",
        "signal_id": "SIG_OPTICAL_001",
        "detection_strength": 0.85,
        "validation_quality": 0.82,
        "durability_score": 0.8,
        "execution_survivability": 0.76,
        "source_quality": 0.8,
        "signal_strength": 0.84,
        "evidence_strength": 0.82,
        "narrative_confidence": 0.4,
        "opportunity_half_life": 0.2,
        "validation_time": 0.5,
        "information_gain": 0.25,
        "delay_cost": 0.15,
        "current_lens_mode": "MACRO",
        "momentum_score": 0.78,
        "persistence": 0.7,
        "convergence": 0.8,
        "volatility": 0.2,
        "risk_score": 0.2,
        "regime_stress": 0.2,
        "candidate_count": 2,
        "active_blockers": [],
        "chaos_veto_active": False,
        "shock_override_active": False,
        "policy_clear": True,
        "policy_state": "REVIEW_READY",
        "risk_clear": True,
        "signal_valid": True,
        "minimum_validation_passed": True,
        "urgency_spike": False,
        "confidence_surge": False,
        "cognitive_load": 0.2,
        "requested_lens_change": False,
        "operator_state": "CALM",
        "operator_state_fit": 0.92,
        "lens_lock_active": False,
        "data_integrity_failure": False,
    }


def test_opacity_state_classification_blackout_under_policy_and_chaos() -> None:
    state, score = classify_opacity_state(
        chaos_score=1.0,
        policy_state="RESTRICTED",
        validation_quality=0.2,
        operator_state_fit=0.2,
        regime_stress=1.0,
    )
    assert state == "BLACKOUT"
    assert score >= 0.85


def test_aperture_state_classification_respects_candidate_width() -> None:
    state, width, depth = classify_aperture_state(candidate_count=7, emergency_mode=False)
    assert state == "WIDE"
    assert width > 0.9
    assert depth < 0.5


def test_shutter_controller_act_wait_abort_logic() -> None:
    act_state, _ = evaluate_shutter_controller(
        opportunity_half_life=0.2,
        validation_time=0.6,
        information_gain=0.2,
        delay_cost=0.3,
        minimum_validation_passed=True,
        risk_clear=True,
        policy_clear=True,
        chaos_clear=True,
        operator_safe=True,
    )
    wait_state, _ = evaluate_shutter_controller(
        opportunity_half_life=0.7,
        validation_time=0.2,
        information_gain=0.7,
        delay_cost=0.2,
        minimum_validation_passed=False,
        risk_clear=True,
        policy_clear=True,
        chaos_clear=True,
        operator_safe=True,
    )
    abort_state, _ = evaluate_shutter_controller(
        opportunity_half_life=0.2,
        validation_time=0.6,
        information_gain=0.7,
        delay_cost=0.2,
        minimum_validation_passed=True,
        risk_clear=False,
        policy_clear=True,
        chaos_clear=True,
        operator_safe=True,
    )

    assert act_state == "ACT_NOW"
    assert wait_state == "WAIT"
    assert abort_state == "ABORT"


def test_mirror_mode_risk_rules_block_warped_distortion() -> None:
    payload = _base_optical_context()
    payload["chaos_veto_active"] = True
    result = evaluate_optical_operating_system(payload)
    assert result["mirror_mode"] == "WARPED"
    assert result["action_allowed"] is False
    assert "mirror_warped" in result["failed_gates"]


def test_lens_transition_requires_macro_before_leica() -> None:
    payload = _base_optical_context()
    payload["current_lens_mode"] = "TELEPHOTO"
    payload["validation_quality"] = 0.9
    payload["source_quality"] = 0.9
    payload["execution_survivability"] = 0.9
    result = evaluate_optical_operating_system(payload)
    assert result["target_lens_mode"] == "LEICA"
    assert result["lens_mode"] == "MACRO"


def test_fisheye_cannot_execute() -> None:
    payload = _base_optical_context()
    payload["signal_strength"] = 0.1
    payload["detection_strength"] = 0.1
    result = evaluate_optical_operating_system(payload)
    assert result["lens_mode"] == "FISHEYE"
    assert result["action_allowed"] is False
    assert "fisheye_not_executable" in result["failed_gates"]


def test_operator_red_blocks_action() -> None:
    payload = _base_optical_context()
    payload["operator_state"] = "INTOXICATED"
    payload["operator_state_fit"] = 0.0
    result = evaluate_optical_operating_system(payload)
    assert result["operator_band"] == "RED"
    assert result["action_allowed"] is False
    assert result["blocking_reason"] == "operator_red"


def test_diablo_chaos_veto_blocks_new_risk() -> None:
    payload = _base_optical_context()
    payload["chaos_veto_active"] = True
    result = evaluate_optical_operating_system(payload)
    assert result["optical_bull_state"] == "DIABLO"
    assert result["final_recommendation"] == "BLOCK"


def test_islero_shock_forces_reclassification() -> None:
    payload = _base_optical_context()
    payload["shock_override_active"] = True
    result = evaluate_optical_operating_system(payload)
    assert result["optical_bull_state"] == "ISLERO"
    assert result["final_recommendation"] == "RECLASSIFY"


def test_huracan_fast_track_requires_minimum_validation() -> None:
    payload = _base_optical_context()
    payload["current_lens_mode"] = "STANDARD"
    payload["validation_quality"] = 0.4
    payload["minimum_validation_passed"] = False
    payload["momentum_score"] = 0.95
    result = evaluate_optical_operating_system(payload)
    assert result["fast_track_eligible"] is False
    assert result["optical_bull_state"] != "HURACAN"


def test_execution_lens_lock_blocks_mid_execution_switching() -> None:
    lens_mode, transition_state, blocked = transition_lens_mode(
        current_lens_mode="EXECUTION_LOCK",
        target_lens_mode="WIDE",
        lens_lock_active=True,
        hard_override=False,
    )
    assert lens_mode == "EXECUTION_LOCK"
    assert transition_state == "LOCKED_HOLD"
    assert blocked is True


def test_optical_state_logging_produces_expected_fields() -> None:
    result = evaluate_optical_operating_system(_base_optical_context())
    assert set(result["optical_state_log"]) >= {
        "timestamp",
        "run_id",
        "asset",
        "signal_id",
        "bull_archetype_state",
        "lens_mode",
        "mirror_mode",
        "opacity_state",
        "aperture_state",
        "shutter_state",
        "operator_state",
        "operator_state_fit",
        "valve_state",
        "macro_pass",
        "leica_clearance",
        "lens_lock",
        "action_allowed",
        "blocking_reason",
        "final_recommendation",
    }


def test_pipeline_report_surfaces_optical_fields_without_overriding_policy() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    for key in (
        "optical_operating_system",
        "optical_bull_state",
        "optical_lens_mode",
        "optical_mirror_mode",
        "optical_opacity_state",
        "optical_aperture_state",
        "optical_shutter_state",
        "optical_valve_state",
        "optical_lens_lock",
        "optical_action_allowed",
        "optical_final_recommendation",
        "optical_state_log",
    ):
        assert key in report
    assert report["policy"]["policy_state"] == "RESTRICTED"
    assert report["can_deploy_capital"] is False


def test_run_diagnostics_pipeline_and_snapshot_row_include_optical_logging() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    row = build_snapshot_row(runtime_state=None, health_report=report)
    assert row["optical_lens_mode"] == report["optical_lens_mode"]
    assert row["optical_final_recommendation"] == report["optical_final_recommendation"]
    assert row["optical_state_log"]["final_recommendation"] == report["optical_final_recommendation"]
