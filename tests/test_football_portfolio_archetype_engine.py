from __future__ import annotations

from scripts.football_portfolio_archetype_engine import (
    CHAOS_ALLOCATION_BANDS,
    DEFAULT_ALLOCATION_BANDS,
    PRIMARY_ROLE_THRESHOLD,
    build_football_portfolio_allocation_recommendation,
    build_football_portfolio_archetype_report,
    classify_football_portfolio_candidate,
)
from scripts.pipeline_health_report import (
    build_pipeline_health_report,
    format_pipeline_health_summary,
)
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.snapshot_logger import build_snapshot_row


def _base_candidate() -> dict:
    return {
        "candidate_id": "TLT",
        "asset_symbol": "TLT",
        "asset_name": "TLT",
        "primary_role_score": 0.82,
        "secondary_output_score": 0.76,
        "output_percentile": 0.80,
        "price_percentile": 0.35,
        "multi_channel_output_score": 0.84,
        "repeatability_score": 0.82,
        "catalyst_score": 0.66,
        "attention_score": 0.25,
        "relative_cost_score": 0.40,
        "risk_adjusted_cost": 0.28,
        "defense_score": 0.62,
        "survival_score": 0.70,
        "catalyst_probability": 0.55,
        "impact_magnitude": 0.62,
        "structural_safety_score": 0.88,
        "system_dependency_score": 0.22,
        "structural_compromise_score": 0.16,
        "validated_output_score": 0.76,
        "policy_veto": False,
        "chaos_state": False,
        "heat_state": False,
    }


def test_baines_candidate_passes() -> None:
    candidate = _base_candidate()
    candidate.update({"catalyst_probability": 0.42, "impact_magnitude": 0.48})
    result = classify_football_portfolio_candidate(candidate)
    assert result["archetype_classification"] == "BAINES_EXPANSION"
    assert result["admission_decision"] == "VALIDATION_QUEUE"


def test_tarkowski_candidate_passes_in_normal_regime() -> None:
    candidate = _base_candidate()
    candidate.update(
        {
            "asset_symbol": "TIP",
            "candidate_id": "TIP",
            "defense_score": 0.92,
            "survival_score": 0.90,
            "system_dependency_score": 0.12,
            "secondary_output_score": 0.58,
            "multi_channel_output_score": 0.45,
            "catalyst_probability": 0.35,
            "impact_magnitude": 0.40,
            "attention_score": 0.18,
            "structural_compromise_score": 0.12,
        }
    )
    result = classify_football_portfolio_candidate(candidate)
    assert result["archetype_classification"] == "TARKOWSKI_CORE"
    assert result["admission_decision"] == "ADMIT_CORE"


def test_tarkowski_candidate_allowed_in_chaos_regime() -> None:
    candidate = _base_candidate()
    candidate.update(
        {
            "asset_symbol": "TIP",
            "candidate_id": "TIP",
            "chaos_state": True,
            "defense_score": 0.94,
            "survival_score": 0.91,
            "system_dependency_score": 0.10,
            "secondary_output_score": 0.50,
            "multi_channel_output_score": 0.40,
        }
    )
    result = classify_football_portfolio_candidate(candidate)
    assert result["archetype_classification"] == "TARKOWSKI_CORE"


def test_baines_candidate_blocked_in_chaos_regime() -> None:
    candidate = _base_candidate()
    candidate["chaos_state"] = True
    result = classify_football_portfolio_candidate(candidate)
    assert result["archetype_classification"] == "REJECT_CHAOS_REGIME"


def test_trent_candidate_classified_correctly() -> None:
    candidate = _base_candidate()
    candidate.update(
        {
            "asset_symbol": "RTX",
            "candidate_id": "RTX",
            "primary_role_score": 0.66,
            "secondary_output_score": 0.86,
            "system_dependency_score": 0.82,
            "defense_score": 0.54,
            "survival_score": 0.56,
            "multi_channel_output_score": 0.68,
            "structural_compromise_score": 0.30,
        }
    )
    result = classify_football_portfolio_candidate(candidate)
    assert result["archetype_classification"] == "TRENT_SYSTEM_DEPENDENT_RISK"
    assert result["admission_decision"] == "CAP_OR_REJECT"


def test_primary_role_failure_overrides_upside() -> None:
    candidate = _base_candidate()
    candidate.update(
        {
            "primary_role_score": PRIMARY_ROLE_THRESHOLD - 0.15,
            "secondary_output_score": 0.95,
            "system_dependency_score": 0.20,
        }
    )
    result = classify_football_portfolio_candidate(candidate)
    assert result["archetype_classification"] == "REJECT_PRIMARY_ROLE_FAILURE"


def test_structural_compromise_blocks_candidate() -> None:
    candidate = _base_candidate()
    candidate["structural_compromise_score"] = 0.72
    result = classify_football_portfolio_candidate(candidate)
    assert result["archetype_classification"] == "REJECT_PRIMARY_ROLE_FAILURE"
    assert result["rejection_reason"] == "structural_compromise_exceeded"


def test_policy_veto_overrides_all() -> None:
    candidate = _base_candidate()
    candidate["policy_veto"] = True
    result = classify_football_portfolio_candidate(candidate)
    assert result["admission_decision"] == "BLOCKED_POLICY_VETO"
    assert result["policy_veto_applied"] is True


def test_bpm_handles_zero_denominator_safely() -> None:
    candidate = _base_candidate()
    candidate["risk_adjusted_cost"] = 0.0
    result = classify_football_portfolio_candidate(candidate)
    assert 0.0 <= result["bpm_score"] <= 1.0


def test_allocation_recommendation_respects_chaos_and_policy() -> None:
    calm = build_football_portfolio_allocation_recommendation(
        policy_state="READY",
        chaos_state=False,
        candidates=[classify_football_portfolio_candidate(_base_candidate())],
    )
    chaos = build_football_portfolio_allocation_recommendation(
        policy_state="RESTRICTED",
        chaos_state=True,
        candidates=[classify_football_portfolio_candidate(_base_candidate())],
    )
    assert calm["allocation_bands"] == DEFAULT_ALLOCATION_BANDS
    assert chaos["allocation_bands"] == CHAOS_ALLOCATION_BANDS


def test_report_and_summary_include_football_archetype_section() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    summary = format_pipeline_health_summary(report)
    for key in (
        "football_portfolio_archetype_engine_available",
        "football_portfolio_archetype_engine_state",
        "football_baines_candidates_count",
        "football_tarkowski_candidates_count",
        "football_portfolio_mode",
        "football_allocation_recommendation",
        "football_portfolio_archetype_report_path",
    ):
        assert key in report or key in summary
    assert "football_portfolio_archetype_engine_state=" in summary
    assert "football_allocation_recommendation=" in summary


def test_health_report_and_snapshot_surface_football_archetype_fields() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    row = build_snapshot_row(runtime_state=None, health_report=report)
    assert "football_portfolio_archetypes" in report
    assert "football_portfolio_mode" in row
    assert report["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert report["can_deploy_capital"] is False
    assert report["football_policy_veto_applied"] is True


def test_aggregate_report_counts_rejections_and_tops() -> None:
    baines = _base_candidate()
    tarkowski = _base_candidate()
    tarkowski.update(
        {
            "candidate_id": "TIP",
            "asset_symbol": "TIP",
            "defense_score": 0.95,
            "survival_score": 0.94,
            "multi_channel_output_score": 0.40,
            "secondary_output_score": 0.50,
            "structural_compromise_score": 0.10,
        }
    )
    trent = _base_candidate()
    trent.update(
        {
            "candidate_id": "RTX",
            "asset_symbol": "RTX",
            "primary_role_score": 0.66,
            "secondary_output_score": 0.88,
            "system_dependency_score": 0.82,
            "defense_score": 0.52,
            "survival_score": 0.58,
            "structural_compromise_score": 0.28,
        }
    )
    report = build_football_portfolio_archetype_report(
        [baines, tarkowski, trent],
        policy_state="READY",
        chaos_state=False,
        run_id="abc123",
        generated_at="2026-05-06T00:00:00+00:00",
    )
    assert report["baines_candidates_count"] == 1
    assert report["tarkowski_candidates_count"] == 1
    assert report["trent_risk_count"] == 1
    assert report["top_baines_candidate"] == "TLT"
    assert report["top_tarkowski_candidate"] == "TIP"
