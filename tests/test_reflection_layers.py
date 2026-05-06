from __future__ import annotations

from scripts.asset_durability_filter import build_asset_durability_report
from scripts.busquets_pre_execution_audit import evaluate_busquets_pre_execution_audit
from scripts.execution_integrity_audit import evaluate_execution_integrity_audit
from scripts.narrative_operator_wisdom_filter import (
    evaluate_narrative_operator_wisdom_filter,
)
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline


def _valid_busquets_context() -> dict:
    return {
        "signal_validated": True,
        "commitment_detected": True,
        "space_created": True,
        "timing_quality": 0.9,
        "space_quality": 0.85,
        "risk_clearance": True,
        "chaos_veto_active": False,
        "execution_packet": {
            "entry": {"ticker": "RTX"},
            "size": {"position_sizing_cap": "QUARTER_UNIT"},
            "invalidation": {"remaining_blockers": []},
            "exit_logic": {"recommended_action": "REVIEW_FOR_ENTRY"},
        },
        "execution_packet_locked": True,
        "policy_state": "REVIEW_READY",
    }


def test_busquets_chaos_veto_returns_hard_veto() -> None:
    payload = _valid_busquets_context()
    payload["chaos_veto_active"] = True
    result = evaluate_busquets_pre_execution_audit(payload)
    assert result["busquets_state"] == "HARD_VETO"
    assert result["allowed_to_execute"] is False


def test_busquets_missing_required_field_fails_safe() -> None:
    payload = _valid_busquets_context()
    payload.pop("execution_packet")
    result = evaluate_busquets_pre_execution_audit(payload)
    assert result["busquets_state"] in {"WAIT", "NO_TRADE"}
    assert "missing_required_fields" in result["failed_gates"]


def test_busquets_valid_signal_without_commitment_returns_wait() -> None:
    payload = _valid_busquets_context()
    payload["commitment_detected"] = False
    result = evaluate_busquets_pre_execution_audit(payload)
    assert result["busquets_state"] == "WAIT"


def test_busquets_commitment_without_space_returns_wait() -> None:
    payload = _valid_busquets_context()
    payload["space_created"] = False
    result = evaluate_busquets_pre_execution_audit(payload)
    assert result["busquets_state"] in {"WAIT", "NO_TRADE"}


def test_busquets_all_gates_pass_returns_pass() -> None:
    result = evaluate_busquets_pre_execution_audit(_valid_busquets_context())
    assert result["busquets_state"] == "PASS"
    assert result["allowed_to_execute"] is True


def test_busquets_unlocked_execution_packet_blocks_pass() -> None:
    payload = _valid_busquets_context()
    payload["execution_packet_locked"] = False
    result = evaluate_busquets_pre_execution_audit(payload)
    assert result["busquets_state"] == "WAIT"
    assert result["allowed_to_execute"] is False


def test_execution_integrity_visible_reopen_returns_broken_execution() -> None:
    result = evaluate_execution_integrity_audit({"visible_reopen": True})
    assert result["execution_integrity_state"] == "BROKEN_EXECUTION"


def test_execution_integrity_high_hesitation_blocks_execution() -> None:
    result = evaluate_execution_integrity_audit(
        {
            "rhythm_integrity_score": 0.8,
            "pattern_fidelity_score": 0.8,
            "operator_uncertainty_score": 1.0,
            "delay_cost": 1.0,
        }
    )
    assert result["execution_integrity_state"] == "BROKEN_EXECUTION"


def test_execution_integrity_hidden_adaptation_zero_delay_is_allowed() -> None:
    result = evaluate_execution_integrity_audit(
        {
            "rhythm_integrity_score": 0.9,
            "pattern_fidelity_score": 0.85,
            "hidden_adaptation_detected": True,
            "concealment_score": 0.9,
            "delay_cost": 0.0,
            "policy_aligned": True,
            "execution_packet_valid": True,
        }
    )
    assert result["execution_integrity_state"] == "ADAPTIVE_EXECUTION_ALLOWED"
    assert result["allowed_to_execute"] is True


def test_execution_integrity_hidden_adaptation_without_policy_alignment_blocks() -> None:
    result = evaluate_execution_integrity_audit(
        {
            "rhythm_integrity_score": 0.9,
            "pattern_fidelity_score": 0.85,
            "hidden_adaptation_detected": True,
            "concealment_score": 0.9,
            "delay_cost": 0.0,
            "policy_aligned": False,
            "execution_packet_valid": True,
        }
    )
    assert result["execution_integrity_state"] == "HARD_VETO"
    assert result["allowed_to_execute"] is False


def test_execution_integrity_clean_locked_packet_returns_locked_execution() -> None:
    result = evaluate_execution_integrity_audit(
        {
            "rhythm_integrity_score": 0.9,
            "pattern_fidelity_score": 0.9,
            "operator_uncertainty_score": 0.1,
            "delay_cost": 0.0,
        }
    )
    assert result["execution_integrity_state"] == "LOCKED_EXECUTION"


def test_narrative_low_evidence_high_confidence_creates_high_hallucination_risk() -> None:
    result = evaluate_narrative_operator_wisdom_filter(
        {
            "evidence_strength": 0.1,
            "narrative_confidence": 0.9,
            "emotional_resonance": 0.8,
            "falsifiable": True,
            "operator_state": "NEUTRAL",
            "cross_state_validated": False,
        }
    )
    assert result["hallucination_risk"] >= 0.7
    assert result["narrative_signal_class"] == "NARRATIVE_CONSTRUCTED_SIGNAL"


def test_narrative_non_falsifiable_signal_rejected() -> None:
    result = evaluate_narrative_operator_wisdom_filter(
        {
            "evidence_strength": 0.8,
            "narrative_confidence": 0.2,
            "falsifiable": False,
            "operator_state": "CALM",
            "cross_state_validated": True,
        }
    )
    assert result["wisdom_state"] == "REJECT"


def test_narrative_volatile_operator_revokes_action_authority() -> None:
    for state in ("EUPHORIC", "INTOXICATED", "FATIGUED"):
        result = evaluate_narrative_operator_wisdom_filter(
            {
                "evidence_strength": 0.8,
                "narrative_confidence": 0.2,
                "falsifiable": True,
                "operator_state": state,
                "cross_state_validated": True,
            }
        )
        assert result["action_authority"] == "REVOKED"


def test_narrative_passing_state_tag_does_not_authorize_action() -> None:
    result = evaluate_narrative_operator_wisdom_filter(
        {
            "evidence_strength": 0.8,
            "narrative_confidence": 0.3,
            "falsifiable": True,
            "operator_state": "CALM",
            "cross_state_validated": True,
            "passing_state_tag": True,
        }
    )
    assert result["wisdom_state"] == "HOLD"
    assert result["allowed_to_execute"] is False


def test_narrative_cross_state_unvalidated_remains_observe_only() -> None:
    result = evaluate_narrative_operator_wisdom_filter(
        {
            "evidence_strength": 0.8,
            "narrative_confidence": 0.2,
            "falsifiable": True,
            "operator_state": "CALM",
            "cross_state_validated": False,
        }
    )
    assert result["wisdom_state"] == "OBSERVE_ONLY"
    assert "CROSS_STATE_UNVALIDATED" in result["tags"]


def test_asset_durability_high_quality_inputs_produce_high_score() -> None:
    result = build_asset_durability_report(
        {
            "durability": 0.9,
            "recovery": 0.9,
            "adaptation": 0.9,
            "liquidity": 0.9,
            "low_fragility": 0.9,
            "performance_before_stress": 1.0,
            "performance_after_stress": 1.05,
            "simple_mechanism": 0.9,
            "universal_need": 0.9,
            "repeat_demand": 0.9,
        }
    )
    assert result["hundred_wash_score"] >= 0.85


def test_asset_durability_high_complexity_lowers_adjusted_score() -> None:
    clean = build_asset_durability_report(
        {
            "durability": 0.7,
            "recovery": 0.7,
            "adaptation": 0.7,
            "liquidity": 0.7,
            "low_fragility": 0.7,
        }
    )
    complex_asset = build_asset_durability_report(
        {
            "durability": 0.7,
            "recovery": 0.7,
            "adaptation": 0.7,
            "liquidity": 0.7,
            "low_fragility": 0.7,
            "unrelated_business_lines": 1.0,
            "single_founder_dependency": 1.0,
            "single_regulation_dependency": 1.0,
            "single_liquidity_dependency": 1.0,
            "single_narrative_dependency": 1.0,
            "unclear_core_mechanism": 1.0,
        }
    )
    assert complex_asset["adjusted_score"] < clean["adjusted_score"]


def test_asset_durability_positive_adaptation_detected() -> None:
    result = build_asset_durability_report(
        {
            "durability": 0.7,
            "recovery": 0.7,
            "adaptation": 0.7,
            "liquidity": 0.7,
            "low_fragility": 0.7,
            "performance_before_stress": 1.0,
            "performance_after_stress": 1.2,
        }
    )
    assert result["positive_adaptation_score"] > 0.0


def test_asset_durability_paracetamol_score_rewards_simple_recurrent_need() -> None:
    result = build_asset_durability_report(
        {
            "durability": 0.5,
            "recovery": 0.5,
            "adaptation": 0.5,
            "liquidity": 0.5,
            "low_fragility": 0.9,
            "simple_mechanism": 1.0,
            "universal_need": 1.0,
            "repeat_demand": 1.0,
        }
    )
    assert result["paracetamol_score"] >= 0.85


def test_asset_durability_brand_distortion_rises_when_price_exceeds_value() -> None:
    result = build_asset_durability_report(
        {
            "durability": 0.6,
            "recovery": 0.6,
            "adaptation": 0.6,
            "liquidity": 0.6,
            "low_fragility": 0.6,
            "market_price": 10.0,
            "fundamental_durability_value": 2.0,
        }
    )
    assert result["brand_distortion_score"] > 0.5


def test_integration_diagnostics_pipeline_runs_and_surfaces_new_fields() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    for key in (
        "busquets_audit_state",
        "busquets_allowed_to_execute",
        "busquets_audit_score",
        "execution_integrity_state",
        "execution_integrity_score",
        "hesitation_leak_score",
        "mid_execution_reopen_detected",
        "narrative_signal_class",
        "hallucination_risk",
        "operator_state",
        "operator_stability_score",
        "action_authority",
        "hundred_wash_score",
        "paracetamol_score",
        "durability_class",
        "positive_adaptation_score",
    ):
        assert key in report


def test_integration_hard_veto_prevents_allowed_to_execute() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    assert report["allowed_to_execute"] is False
    assert report["busquets_allowed_to_execute"] is False


def test_integration_policy_veto_outranks_new_modules() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    assert report["policy"]["policy_state"] == "RESTRICTED"
    assert report["busquets_audit_state"] == "HARD_VETO"
    assert report["allowed_to_execute"] is False
