from __future__ import annotations

from scripts.baines_engine import build_baines_engine_report, evaluate_baines_candidate
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.snapshot_logger import build_snapshot_row


def _base_candidate() -> dict:
    return {
        "asset_id": "BNS",
        "asset_class": "etf",
        "listed_role": "defender",
        "observed_function": "creator",
        "price_score": 0.3,
        "output_score": 0.92,
        "output_percentile": 0.92,
        "price_expectation_percentile": 0.28,
        "attention_score": 0.22,
        "payoff_channels": {
            "income": 0.82,
            "growth": 0.79,
            "hedging": 0.74,
        },
        "persistence_score": 0.92,
        "stability_score": 0.91,
        "historical_conversion_score": 0.82,
        "performance_before_stress": 1.0,
        "performance_after_stress": 0.86,
        "risk_adjusted_cost": 0.28,
        "volatility_penalty": 0.14,
        "liquidity_penalty": 0.10,
        "reality_gap_penalty": 0.08,
        "policy_veto": False,
        "chaos_veto": False,
    }


def test_baines_score_clamps_between_zero_and_one() -> None:
    candidate = _base_candidate()
    candidate["output_score"] = 5.0
    candidate["output_percentile"] = 5.0
    candidate["performance_after_stress"] = 5.0
    candidate["risk_adjusted_cost"] = 0.00001
    result = evaluate_baines_candidate(candidate)
    assert 0.0 <= result["baines_score"] <= 1.0


def test_policy_veto_overrides_everything() -> None:
    candidate = _base_candidate()
    candidate["policy_veto"] = True
    result = evaluate_baines_candidate(candidate)
    assert result["classification"] == "BAINES_VETOED_POLICY"
    assert result["recommended_next_state"] == "BLOCKED_BY_POLICY"


def test_chaos_veto_overrides_baines_promotion() -> None:
    candidate = _base_candidate()
    candidate["chaos_veto"] = True
    result = evaluate_baines_candidate(candidate)
    assert result["classification"] == "BAINES_VETOED_CHAOS"


def test_cheap_asset_with_no_output_is_rejected() -> None:
    candidate = _base_candidate()
    candidate.update(
        {
            "price_score": 0.1,
            "output_score": 0.05,
            "output_percentile": 0.05,
            "price_expectation_percentile": 0.05,
            "payoff_channels": {"income": 0.1},
            "persistence_score": 0.2,
            "stability_score": 0.2,
            "historical_conversion_score": 0.2,
            "performance_after_stress": 0.05,
            "volatility_penalty": 0.8,
            "liquidity_penalty": 0.7,
            "reality_gap_penalty": 0.9,
        }
    )
    result = evaluate_baines_candidate(candidate)
    assert result["classification"] == "BAINES_REJECTED"


def test_high_output_high_attention_asset_loses_discount() -> None:
    low_attention = evaluate_baines_candidate(_base_candidate())
    high_attention_candidate = _base_candidate()
    high_attention_candidate["attention_score"] = 0.92
    high_attention = evaluate_baines_candidate(high_attention_candidate)
    assert high_attention["attention_discount"] < low_attention["attention_discount"]
    assert high_attention["baines_score"] < low_attention["baines_score"]


def test_one_off_spike_low_repeatability_requires_validation() -> None:
    candidate = _base_candidate()
    candidate.update(
        {
            "persistence_score": 0.9,
            "stability_score": 0.9,
            "historical_conversion_score": 0.74,
            "performance_after_stress": 0.92,
            "volatility_penalty": 0.02,
            "liquidity_penalty": 0.02,
            "reality_gap_penalty": 0.02,
        }
    )
    result = evaluate_baines_candidate(candidate)
    assert result["repeatability_score"] < 0.60
    assert result["classification"] == "BAINES_VALIDATION_REQUIRED"


def test_multichannel_candidate_scores_higher_than_single_channel_candidate() -> None:
    multi = evaluate_baines_candidate(_base_candidate())
    single_candidate = _base_candidate()
    single_candidate["payoff_channels"] = {"income": 0.82}
    single = evaluate_baines_candidate(single_candidate)
    assert multi["multichannel_score"] > single["multichannel_score"]
    assert multi["baines_score"] > single["baines_score"]


def test_role_mismatch_raises_score() -> None:
    low_mismatch_candidate = _base_candidate()
    low_mismatch_candidate["price_expectation_percentile"] = 0.80
    low_mismatch = evaluate_baines_candidate(low_mismatch_candidate)
    high_mismatch = evaluate_baines_candidate(_base_candidate())
    assert high_mismatch["role_mismatch_score"] > low_mismatch["role_mismatch_score"]
    assert high_mismatch["baines_score"] > low_mismatch["baines_score"]


def test_bpm_handles_zero_risk_adjusted_cost_safely() -> None:
    candidate = _base_candidate()
    candidate["risk_adjusted_cost"] = 0.0
    result = evaluate_baines_candidate(candidate)
    assert 0.0 <= result["bpm_score"] <= 1.0


def test_empty_input_returns_clean_fallback() -> None:
    report = build_baines_engine_report([])
    assert report == {
        "baines_engine_available": True,
        "baines_engine_state": "EMPTY",
        "baines_candidates_detected": 0,
        "baines_durable_candidates": 0,
        "baines_policy_vetoed": 0,
        "baines_chaos_vetoed": 0,
        "top_baines_candidate": None,
        "top_baines_score": None,
        "outputs": [],
    }


def test_formula_trace_contains_required_keys() -> None:
    result = evaluate_baines_candidate(_base_candidate())
    assert result["formula_trace"].keys() == {
        "role_mismatch_score",
        "multichannel_score",
        "attention_discount",
        "repeatability_score",
        "durability_score",
        "bpm_score",
        "final_baines_score",
        "veto_logic",
    }


def test_durable_candidate_never_becomes_execution_instruction() -> None:
    result = evaluate_baines_candidate(_base_candidate())
    assert result["classification"] == "BAINES_DURABLE_CANDIDATE"
    assert "EXECUTE" not in result["recommended_next_state"]


def test_pipeline_and_snapshot_surface_baines_fields_without_overriding_safety() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    snapshot_row = build_snapshot_row(runtime_state=None, health_report=report)
    for key in (
        "baines_engine",
        "baines_engine_available",
        "baines_engine_state",
        "baines_candidates_detected",
        "baines_durable_candidates",
        "baines_policy_vetoed",
        "baines_chaos_vetoed",
        "top_baines_candidate",
        "top_baines_score",
    ):
        assert key in report
    assert "baines_engine_state" in snapshot_row
    assert report["can_deploy_capital"] is False
    assert report["allowed_to_execute"] is False
    assert report["baines_engine_available"] is True
    assert report["baines_engine_state"] == "VETOED"


def test_health_report_surfaces_baines_fields() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    assert report["baines_engine_available"] is True
    assert report["baines_engine_state"] == "VETOED"
    assert report["policy"]["policy_state"] == "RESTRICTED"
