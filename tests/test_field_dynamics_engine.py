from __future__ import annotations

from scripts.field_dynamics_engine import (
    ACTIONABLE_UNDER_POLICY,
    DIVERGENT,
    HIGHLY_COHERENT,
    MISALIGNED,
    NO_FIELD,
    NO_INTERACTION_DATA,
    NO_VECTOR,
    STRONG_FIELD,
    attach_field_dynamics,
    build_field_dynamics_report,
    compute_execution_vector,
    compute_field_interaction_matrix,
    compute_field_pressure_state,
    compute_trade_readiness,
    compute_valid_signal_rate,
)
from scripts.pipeline_health_report import (
    build_pipeline_health_report,
    format_pipeline_health_summary,
)
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline


def _strong_candidate() -> dict:
    return {
        "candidate_id": "SIG001",
        "asset_symbol": "UNG",
        "ticker": "UNG",
        "sentiment_score": 0.8,
        "price_move_pct": 0.75,
        "volume_move_ratio": 0.7,
        "event_prior_score": 0.72,
        "narrative_score": 0.7,
        "narrative_direction_score": 0.8,
        "liquidity_score": 0.8,
        "repeatability_score": 0.82,
        "persistence_score": 0.82,
        "durability_score": 0.76,
        "execution_survivability_score": 0.81,
        "timing_alignment_score": 0.78,
        "timing_window": 0.7,
        "momentum_score": 0.75,
        "minimum_validation_passed": True,
    }


def test_empty_input_returns_conservative_defaults() -> None:
    pressure = compute_field_pressure_state({})
    interaction = compute_field_interaction_matrix({})
    vector = compute_execution_vector({}, pressure, interaction)
    readiness = compute_trade_readiness(
        pressure,
        interaction,
        vector,
        policy_state={"policy_state": "RESTRICTED", "allow_new_risk": False, "chaos_veto": False},
    )
    assert pressure["classification"] == NO_FIELD
    assert interaction["classification"] == NO_INTERACTION_DATA
    assert vector["classification"] == NO_VECTOR
    assert readiness["valid_signal_rate"] == 0.0


def test_strong_pressure_but_divergent_interaction_stays_low_readiness() -> None:
    candidate = _strong_candidate() | {
        "price_move_pct": -0.75,
        "narrative_direction_score": 0.8,
        "liquidity_score": 0.15,
        "narrative_score": 0.1,
    }
    pressure = compute_field_pressure_state(candidate)
    interaction = compute_field_interaction_matrix(candidate)
    vector = compute_execution_vector(
        candidate | {"policy_permission": True, "chaos_veto": False},
        pressure,
        interaction,
    )
    readiness = compute_trade_readiness(
        pressure,
        interaction,
        vector,
        policy_state={"policy_state": "READY", "allow_new_risk": True, "chaos_veto": False},
    )
    assert pressure["classification"] == STRONG_FIELD
    assert interaction["classification"] == DIVERGENT
    assert vector["classification"] in {NO_VECTOR, MISALIGNED}
    assert readiness["trade_readiness"] < 0.2
    assert readiness["action_promotion_state"] == "BLOCKED_DIVERGENT_FIELD"


def test_strong_pressure_and_coherent_interaction_produce_actionable_under_policy() -> None:
    candidate = _strong_candidate()
    pressure = compute_field_pressure_state(candidate)
    interaction = compute_field_interaction_matrix(candidate)
    vector = compute_execution_vector(
        candidate | {"policy_permission": True, "chaos_veto": False},
        pressure,
        interaction,
    )
    readiness = compute_trade_readiness(
        pressure,
        interaction,
        vector,
        policy_state={"policy_state": "READY", "allow_new_risk": True, "chaos_veto": False},
    )
    assert pressure["classification"] == STRONG_FIELD
    assert interaction["classification"] in {HIGHLY_COHERENT, "COHERENT"}
    assert vector["classification"] == ACTIONABLE_UNDER_POLICY
    assert readiness["valid_signal_rate"] > 0.0


def test_policy_or_chaos_veto_preserves_block() -> None:
    candidate = _strong_candidate()
    attached = attach_field_dynamics(
        candidate,
        policy_state={"policy_state": "RESTRICTED", "allow_new_risk": False, "chaos_veto": True},
    )
    state = attached["gauss_maxwell_lorentz_state"]
    assert state["trade_readiness"] == 0.0
    assert state["final_permission_state"] == "BLOCKED_POLICY"


def test_missing_optional_fields_do_not_crash() -> None:
    report = build_field_dynamics_report(
        [{"ticker": "TLT"}],
        policy_state={"policy_state": "RESTRICTED", "allow_new_risk": False, "chaos_veto": False},
    )
    assert report["field_dynamics_engine_available"] is True
    assert report["field_dynamics_candidate_count"] == 1
    assert 0.0 <= report["valid_signal_rate"] <= 1.0


def test_valid_signal_rate_stays_bounded() -> None:
    pressure = {"pressure_score": 0.9}
    interaction = {"interaction_coherence": 0.9}
    vector = {"execution_clarity": 0.95}
    assert 0.0 <= compute_valid_signal_rate(pressure, interaction, vector) <= 1.0


def test_health_report_surfaces_dashboard_without_breaking_existing_summary() -> None:
    health = build_pipeline_health_report(write_runtime=False)
    summary = format_pipeline_health_summary(health)
    assert "gauss_maxwell_lorentz_state" in health
    assert "gauss_maxwell_lorentz_dashboard" in health
    assert "field_dynamics_engine_state=" in summary
    assert "valid_signal_rate=" in summary
    assert "field_dynamics_report_path=" in summary
    assert health["scm"]["scm_state"] == "LOW_CONVERSION"
    assert health["policy"]["policy_state"] == "RESTRICTED"


def test_run_diagnostics_pipeline_includes_field_dynamics() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    for key in (
        "gauss_maxwell_lorentz_state",
        "gauss_maxwell_lorentz_dashboard",
        "field_dynamics_engine_available",
        "field_dynamics_engine_state",
        "valid_signal_rate",
        "trade_readiness",
        "field_dynamics_report_path",
    ):
        assert key in report
