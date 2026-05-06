from __future__ import annotations

from scripts.pipeline_health_report import build_pipeline_health_report, format_pipeline_health_summary
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.signal_metabolism import (
    apply_high_intensity_guard,
    build_signal_metabolism_report,
    classify_bull_archetype,
    classify_signal_route,
    classify_signal_stage,
    compute_regime_factor,
    evaluate_signal_metabolism,
    score_psychological_chemistry,
    split_virality_vs_validity,
)


def _base_signal() -> dict:
    return {
        "candidate_id": "SIG_001",
        "signal_id": "SIG_2026_05_01_001",
        "asset_symbol": "TLT",
        "ticker": "TLT",
        "source_name": "twitter social post",
        "headline": "BREAKING bullish upgrade now!!!",
        "text": "BREAKING bullish squeeze now now!!!",
        "source_quality_score": 0.25,
        "confirmation_count": 0,
        "repost_count": 4,
        "narrative_mentions": 1,
        "engagement_proxy": 0.9,
        "engagement_velocity": 0.8,
        "price_move_pct": 0.15,
        "volume_move_ratio": 0.10,
        "signal_detected_at": "2026-05-01T12:00:00+00:00",
        "as_of": "2026-05-01T13:00:00+00:00",
        "repeatability_score": 0.45,
        "momentum_score": 0.4,
    }


def test_route_classifier_social_returns_fast_latency_and_lower_reliability() -> None:
    result = classify_signal_route({"source_name": "twitter social post"})
    assert result["signal_route"] == "social"
    assert result["route_latency_profile"] == "fast"
    assert result["route_reliability_prior"] == 0.35


def test_route_classifier_filing_returns_higher_reliability() -> None:
    result = classify_signal_route({"headline": "8-K filing posted", "source_quality_score": 0.9})
    assert result["signal_route"] == "filing"
    assert result["route_reliability_prior"] == 0.8


def test_route_classifier_unknown_safely_defaults() -> None:
    result = classify_signal_route({})
    assert result["signal_route"] == "unknown"
    assert result["route_reliability_prior"] == 0.3


def test_stage_classifier_raw_signal_returns_raw() -> None:
    result = classify_signal_stage({"headline": "new signal"})
    assert result["signal_stage"] == "RAW"


def test_stage_classifier_amplified_or_narrative_when_reposted_and_confirmed() -> None:
    result = classify_signal_stage({"repost_count": 3, "confirmation_count": 2})
    assert result["signal_stage"] in {"AMPLIFIED", "NARRATIVE"}


def test_stage_classifier_price_and_volume_confirmation_returns_priced_risk() -> None:
    result = classify_signal_stage(
        {"narrative_saturation": 0.8},
        market_context={"price_move_pct": 0.9, "volume_move_ratio": 0.9},
    )
    assert result["signal_stage"] == "PRICED"
    assert result["priced_risk"] >= 0.7


def test_psychological_chemistry_viral_post_has_high_intensity_low_truth() -> None:
    result = score_psychological_chemistry(_base_signal())
    assert result["intensity_score"] >= 0.5
    assert result["truth_score"] < result["virality_score"]
    assert result["validity_gap"] > 0


def test_psychological_chemistry_evidence_backed_post_has_higher_truth_and_stability() -> None:
    signal = _base_signal() | {
        "headline": "company filing confirms guidance",
        "source_name": "sec filing",
        "source_quality_score": 0.9,
        "confirmation_count": 3,
        "engagement_proxy": 0.2,
        "price_confirmation_score": 0.8,
    }
    result = score_psychological_chemistry(signal)
    assert result["truth_score"] >= 0.7
    assert result["evidence_stability_score"] >= 0.7


def test_psychological_chemistry_neutral_signal_remains_low_intensity() -> None:
    result = score_psychological_chemistry({"headline": "routine update", "text": "routine update"})
    assert result["intensity_score"] < 0.4


def test_virality_vs_validity_high_virality_low_truth_requires_validation() -> None:
    result = split_virality_vs_validity(virality_score=0.9, truth_score=0.2)
    assert result["attention_truth_state"] == "high_attention_low_truth"
    assert result["require_validation"] is True


def test_regime_override_chaos_or_policy_veto_forces_no_new_risk() -> None:
    result = compute_regime_factor(
        {
            "policy_state": "RESTRICTED",
            "friction_band": "HIGH_FRICTION",
            "chaos_flag": True,
            "allow_new_risk": False,
            "can_deploy_capital": False,
            "existing_blockers": ["REALM_BIS"],
        }
    )
    assert result["no_new_risk_due_to_regime"] is True
    assert result["regime_state"] == "CHAOS_LOCKED"


def test_regime_normal_allows_scoring() -> None:
    result = compute_regime_factor(
        {
            "policy_state": "READY",
            "friction_band": "LOW_FRICTION",
            "chaos_flag": False,
            "allow_new_risk": True,
            "can_deploy_capital": True,
        }
    )
    assert result["no_new_risk_due_to_regime"] is False
    assert result["regime_factor"] > 0.5


def test_high_intensity_guard_blocks_or_delays_for_high_intensity_low_stability() -> None:
    result = apply_high_intensity_guard(
        intensity_score=0.95,
        stability_score=0.20,
        truth_score=0.2,
        no_new_risk_due_to_regime=False,
    )
    assert result["guard_action"] in {"block", "delay"}
    assert result["guard_multiplier"] < 1.0


def test_high_intensity_guard_allows_when_stability_is_high() -> None:
    result = apply_high_intensity_guard(
        intensity_score=0.82,
        stability_score=0.85,
        truth_score=0.8,
        no_new_risk_due_to_regime=False,
    )
    assert result["guard_action"] in {"allow", "reduce_confidence"}


def test_bull_archetype_raw_detection_maps_to_miura() -> None:
    result = classify_bull_archetype(
        signal_stage="RAW",
        regime_state="NORMALIZING",
        no_new_risk_due_to_regime=False,
        truth_score=0.4,
        evidence_stability_score=0.4,
        repeatability_score=0.4,
        durability_score=0.4,
        execution_survivability_score=0.4,
        minimum_validation_passed=False,
    )
    assert result == "MIURA"


def test_bull_archetype_chaos_maps_to_diablo() -> None:
    result = classify_bull_archetype(
        signal_stage="AMPLIFIED",
        regime_state="CHAOS_LOCKED",
        no_new_risk_due_to_regime=True,
        truth_score=0.7,
        evidence_stability_score=0.7,
        repeatability_score=0.7,
        durability_score=0.7,
        execution_survivability_score=0.7,
        minimum_validation_passed=True,
    )
    assert result == "DIABLO"


def test_bull_archetype_validated_durable_maps_to_murcielago_or_aventador() -> None:
    result = classify_bull_archetype(
        signal_stage="NARRATIVE",
        regime_state="NORMALIZING",
        no_new_risk_due_to_regime=False,
        truth_score=0.72,
        evidence_stability_score=0.74,
        repeatability_score=0.72,
        durability_score=0.74,
        execution_survivability_score=0.60,
        minimum_validation_passed=True,
    )
    assert result in {"MURCIELAGO", "AVENTADOR"}


def test_bull_archetype_execution_ready_maps_to_gallardo() -> None:
    result = classify_bull_archetype(
        signal_stage="PRICED",
        regime_state="NORMALIZING",
        no_new_risk_due_to_regime=False,
        truth_score=0.82,
        evidence_stability_score=0.82,
        repeatability_score=0.82,
        durability_score=0.78,
        execution_survivability_score=0.82,
        minimum_validation_passed=True,
    )
    assert result == "GALLARDO"


def test_composite_score_remains_bounded_and_guard_reduces_score() -> None:
    guarded = evaluate_signal_metabolism(
        _base_signal(),
        regime_context={
            "policy_state": "RESTRICTED",
            "friction_band": "HIGH_FRICTION",
            "chaos_flag": True,
            "allow_new_risk": False,
            "can_deploy_capital": False,
            "existing_blockers": ["REALM_BIS"],
        },
        compatibility_context={"historical_success_rate": 0.6, "profile_similarity": 0.6},
    )
    calm = evaluate_signal_metabolism(
        _base_signal() | {"headline": "filing confirms upside", "source_name": "sec filing", "confirmation_count": 3},
        regime_context={
            "policy_state": "READY",
            "friction_band": "LOW_FRICTION",
            "chaos_flag": False,
            "allow_new_risk": True,
            "can_deploy_capital": True,
            "existing_blockers": [],
        },
        compatibility_context={"historical_success_rate": 0.8, "profile_similarity": 0.8},
    )
    assert 0.0 <= guarded["dynamic_signal_score"] <= 1.0
    assert 0.0 <= calm["dynamic_signal_score"] <= 1.0
    assert guarded["dynamic_signal_score"] <= calm["dynamic_signal_score"]


def test_missing_fields_do_not_crash() -> None:
    result = evaluate_signal_metabolism({})
    assert 0.0 <= result["dynamic_signal_score"] <= 1.0
    assert result["signal_stage"] in {"RAW", "UNKNOWN"}


def test_signal_metabolism_report_and_health_report_surface_fields() -> None:
    report = build_signal_metabolism_report(
        [_base_signal()],
        regime_context={
            "policy_state": "RESTRICTED",
            "friction_band": "HIGH_FRICTION",
            "chaos_flag": True,
            "allow_new_risk": False,
            "can_deploy_capital": False,
            "existing_blockers": ["REALM_BIS"],
        },
        compatibility_defaults={"historical_success_rate": 0.6, "profile_similarity": 0.6},
        run_id="abc123",
        generated_at="2026-05-07T00:00:00+00:00",
    )
    assert report["signal_metabolism_engine_available"] is True
    health = build_pipeline_health_report(write_runtime=False)
    summary = format_pipeline_health_summary(health)
    assert "signal_metabolism_engine_available" in health
    assert "signal_metabolism_engine_state=" in summary
    assert "signal_metabolism_report_path=" in summary
    assert health["can_deploy_capital"] is False
    assert health["policy"]["policy_state"] == "RESTRICTED"


def test_run_diagnostics_pipeline_includes_metabolism_fields() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    for key in (
        "signal_metabolism",
        "signal_metabolism_engine_available",
        "signal_metabolism_engine_state",
        "signal_metabolism_candidate_count",
        "signal_metabolism_guarded_count",
        "signal_metabolism_top_candidate",
        "signal_metabolism_report_path",
    ):
        assert key in report
