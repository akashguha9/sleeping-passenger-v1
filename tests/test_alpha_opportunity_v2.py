"""Evidence-weighted opportunity aggregation (v2) invariants."""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.opportunity import (
    POSITIVE_COMPONENTS,
    RISK_COMPONENTS,
    TRAP_FLAGS,
    aggregate_opportunity_score_v2,
)

_STRONG = {key: 85.0 for key in POSITIVE_COMPONENTS} | {
    key: 15.0 for key in RISK_COMPONENTS
}


def _v2(components=None, **kwargs):
    return aggregate_opportunity_score_v2(components, **kwargs)


def test_all_outputs_bounded() -> None:
    for components in (_STRONG, {}, None, {key: 0.0 for key in _STRONG}):
        result = _v2(components)
        assert 0.0 <= result["opportunity_score"] <= 100.0
        assert 0.0 <= result["confidence"] <= 100.0
        assert 0.0 <= result["evidence_quality_score"] <= 100.0
        assert 0.0 <= result["evidence_gap_risk"] <= 100.0
        assert 0.0 <= result["filing_risk_disclosure_score"] <= 100.0


def test_hard_evidence_increases_confidence() -> None:
    weak = _v2(_STRONG, evidence_quality=10.0)
    strong = _v2(_STRONG, evidence_quality=95.0)
    assert strong["confidence"] > weak["confidence"]
    assert strong["evidence_gap_risk"] < weak["evidence_gap_risk"]


def test_risk_disclosure_decreases_score() -> None:
    clean = _v2(_STRONG, filing_risk_disclosure_score=0.0)
    risky = _v2(_STRONG, filing_risk_disclosure_score=90.0)
    assert risky["opportunity_score"] < clean["opportunity_score"]
    assert "risk_disclosure_overhang" in risky["trap_flags"]


def test_high_casino_low_food_chain_is_trap() -> None:
    components = dict(_STRONG, casino_distortion=85.0, food_chain=25.0)
    result = _v2(components)
    assert "high_casino_low_food_chain" in result["trap_flags"]
    assert result["advisory_verdict"] == "avoid_trap"


def test_high_narrative_low_proof_is_trap() -> None:
    components = dict(_STRONG, narrative_velocity=90.0, embedded_proof=20.0)
    result = _v2(components)
    assert "high_narrative_low_proof" in result["trap_flags"]
    assert result["advisory_verdict"] == "avoid_trap"


def test_strong_residual_utility_weak_narrative_stays_conservative() -> None:
    # The "boring but real" shape: must NOT come out as a hype buy.
    components = {
        "narrative_velocity": 20.0,
        "probability_confirmation": 50.0,
        "embedded_proof": 75.0,
        "node_strength": 70.0,
        "half_life": 90.0,
        "residual_utility": 85.0,
        "food_chain": 80.0,
        "valuation_risk": 30.0,
        "regulatory_risk": 25.0,
        "commoditization_risk": 35.0,
        "casino_distortion": 10.0,
    }
    result = _v2(components, filing_risk_disclosure_score=20.0)
    assert result["advisory_verdict"] in (
        "watchlist",
        "deep_research",
        "small_position_candidate",
    )
    assert "high_narrative_low_proof" not in result["trap_flags"]


def test_short_half_life_high_valuation_trap() -> None:
    components = dict(_STRONG, half_life=20.0, valuation_risk=80.0)
    result = _v2(components, half_life_days=10.0)
    assert "short_half_life_high_valuation" in result["trap_flags"]
    assert result["advisory_verdict"] == "event_trade_only"


def test_strong_theme_weak_node_capture_trap() -> None:
    components = dict(_STRONG, residual_utility=80.0, node_strength=20.0)
    assert "strong_theme_weak_node_capture" in _v2(components)["trap_flags"]


def test_edge_without_liquidity_trap() -> None:
    result = _v2(_STRONG, probability_edge=0.25, liquidity_score=10.0)
    assert "high_probability_edge_low_liquidity" in result["trap_flags"]
    no_flag = _v2(_STRONG, probability_edge=0.25, liquidity_score=80.0)
    assert "high_probability_edge_low_liquidity" not in no_flag["trap_flags"]


def test_filing_claim_without_hard_evidence_trap() -> None:
    result = _v2(_STRONG, evidence_quality=10.0, filing_claims_present=True)
    assert "filing_claim_without_hard_evidence" in result["trap_flags"]


def test_overconcentration_trap() -> None:
    result = _v2(_STRONG, portfolio_overlap_risk=85.0)
    assert "overconcentrated_portfolio_exposure" in result["trap_flags"]


def test_missing_proof_caps_verdict_at_deep_research() -> None:
    # With hot narrative the engine goes further and calls the trap.
    hyped = _v2(dict(_STRONG, embedded_proof=20.0), evidence_quality=20.0)
    assert hyped["advisory_verdict"] == "avoid_trap"
    # With moderate narrative, weak proof still caps at deep_research.
    components = dict(_STRONG, embedded_proof=20.0, narrative_velocity=50.0)
    result = _v2(components, evidence_quality=20.0)
    assert result["advisory_verdict"] in ("ignore", "watchlist", "deep_research")


def test_missing_inputs_populate_why_not_higher() -> None:
    result = _v2({"narrative_velocity": 80.0})
    assert result["missing_inputs"]
    assert any("missing input" in reason for reason in result["why_not_higher"])
    # Sparse inputs cap the verdict at watchlist.
    assert result["advisory_verdict"] in ("ignore", "watchlist")


def test_why_not_lower_lists_strengths() -> None:
    result = _v2(_STRONG, evidence_quality=85.0)
    assert any("is strong" in reason for reason in result["why_not_lower"])
    assert any("hard evidence" in reason for reason in result["why_not_lower"])


def test_no_calibration_support_is_admitted() -> None:
    result = _v2(_STRONG)
    assert result["confidence_components"]["calibration_support"] == 0.0
    assert any("calibration" in reason for reason in result["why_not_higher"])


def test_uncalibrated_engine_caps_verdict_at_deep_research() -> None:
    # Even a maximally strong signal may not become a position candidate
    # until the replay harness provides outcome-backed calibration.
    uncalibrated = _v2(_STRONG)
    assert uncalibrated["advisory_verdict"] in (
        "ignore",
        "watchlist",
        "deep_research",
    )
    calibrated = _v2(_STRONG, calibration_support=80.0)
    assert calibrated["advisory_verdict"] in (
        "small_position_candidate",
        "core_candidate",
    )
    assert calibrated["confidence"] > uncalibrated["confidence"]


def test_trap_flags_are_from_known_registry_and_disclaimer_present() -> None:
    components = dict(_STRONG, casino_distortion=90.0, food_chain=10.0, embedded_proof=10.0)
    result = _v2(
        components,
        filing_risk_disclosure_score=90.0,
        portfolio_overlap_risk=90.0,
        probability_edge=0.3,
        liquidity_score=5.0,
        filing_claims_present=True,
        evidence_quality=5.0,
    )
    assert result["trap_flags"]
    for flag in result["trap_flags"]:
        assert flag in TRAP_FLAGS
    assert result["disclaimer"] == ADVISORY_DISCLAIMER
    assert "guaranteed" not in str(result).lower()
