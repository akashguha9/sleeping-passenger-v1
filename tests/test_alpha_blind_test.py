"""Blind-test differential: measured narrative contribution."""

from __future__ import annotations

from src.alpha.blind_test import BLIND_CLASSES, blind_test_differential
from src.alpha.opportunity import POSITIVE_COMPONENTS, RISK_COMPONENTS

_HYPE_DRIVEN = {
    "narrative_velocity": 95.0,
    "probability_confirmation": 55.0,
    "embedded_proof": 30.0,
    "node_strength": 35.0,
    "half_life": 30.0,
    "residual_utility": 30.0,
    "food_chain": 35.0,
    "valuation_risk": 60.0,
    "regulatory_risk": 30.0,
    "commoditization_risk": 40.0,
    "casino_distortion": 85.0,
}
_REALITY_DRIVEN = {
    "narrative_velocity": 30.0,
    "probability_confirmation": 55.0,
    "embedded_proof": 80.0,
    "node_strength": 70.0,
    "half_life": 90.0,
    "residual_utility": 85.0,
    "food_chain": 80.0,
    "valuation_risk": 30.0,
    "regulatory_risk": 25.0,
    "commoditization_risk": 35.0,
    "casino_distortion": 10.0,
}


def test_hype_driven_signal_is_story_carried() -> None:
    result = blind_test_differential(_HYPE_DRIVEN)
    # The story props the score up AND the signal fails blind testing.
    assert result["blind_class"] == "story_carried"
    assert result["narrative_contribution"] > 0
    assert result["survives_blind_test"] is False


def test_reality_driven_signal_survives_blind_test() -> None:
    result = blind_test_differential(_REALITY_DRIVEN)
    assert result["survives_blind_test"] is True
    # Quiet reality scores HIGHER blind: the missing story was a drag.
    assert result["blind_class"] == "narrative_understated"
    assert result["narrative_contribution"] < 0


def test_blind_pass_neutralizes_only_the_story_channel() -> None:
    result = blind_test_differential(_HYPE_DRIVEN)
    assert result["neutralized_inputs"] == {"narrative_velocity": 50.0}


def test_engine_structurally_bounds_narrative_influence() -> None:
    # The geometric mean bounds any single loud factor: even a 95-velocity
    # narrative cannot contribute more than a handful of points.
    result = blind_test_differential(_HYPE_DRIVEN)
    assert abs(result["narrative_contribution"]) < 15.0


def test_differential_is_deterministic_and_bounded() -> None:
    first = blind_test_differential(_HYPE_DRIVEN)
    second = blind_test_differential(_HYPE_DRIVEN)
    assert first == second
    assert -100.0 <= first["narrative_contribution"] <= 100.0
    assert first["blind_class"] in BLIND_CLASSES
    assert first["narrative_inflation"] == first["narrative_contribution"]


def test_neutral_signal_is_narrative_independent() -> None:
    result = blind_test_differential(
        {key: 50.0 for key in POSITIVE_COMPONENTS}
        | {key: 50.0 for key in RISK_COMPONENTS}
    )
    assert result["blind_class"] == "narrative_independent"
    assert result["narrative_contribution"] == 0.0


def test_empty_components_are_safe() -> None:
    result = blind_test_differential({})
    assert 0.0 <= result["blind_score"] <= 100.0
    assert result["blind_class"] in BLIND_CLASSES


def test_kwargs_flow_through_to_both_passes() -> None:
    gated = blind_test_differential(_REALITY_DRIVEN, calibration_support=80.0)
    assert gated["labelled_verdict"] in (
        "small_position_candidate",
        "core_candidate",
        "deep_research",
    )


def test_no_execution_language() -> None:
    text = str(blind_test_differential(_HYPE_DRIVEN)).lower()
    for forbidden in ("guaranteed", "buy now", "execute trade"):
        assert forbidden not in text


def test_full_component_coverage_stays_bounded() -> None:
    everything = {key: 100.0 for key in POSITIVE_COMPONENTS} | {
        key: 0.0 for key in RISK_COMPONENTS
    }
    result = blind_test_differential(everything)
    assert 0.0 <= result["labelled_score"] <= 100.0
    assert 0.0 <= result["blind_score"] <= 100.0
