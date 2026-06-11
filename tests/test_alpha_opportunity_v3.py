"""Opportunity v3: probability source ladder and calibration-adjusted confidence."""

from __future__ import annotations

import pytest

from src.alpha.opportunity import (
    POSITIVE_COMPONENTS,
    RISK_COMPONENTS,
    aggregate_opportunity_score_v2,
)

_BASE = {
    key: 70.0 for key in POSITIVE_COMPONENTS if key != "probability_confirmation"
} | {key: 20.0 for key in RISK_COMPONENTS}


def test_calibrated_probability_overrides_raw_proxy() -> None:
    result = aggregate_opportunity_score_v2(
        _BASE,
        event_probability_raw=0.9,
        event_probability_calibrated=0.6,
    )
    assert result["probability_source"] == "calibrated"
    assert result["score_components"]["probability_confirmation"] == pytest.approx(60.0)
    assert result["raw_event_probability"] == pytest.approx(0.9)
    assert result["calibrated_event_probability"] == pytest.approx(0.6)


def test_raw_proxy_used_with_warning_when_no_calibration() -> None:
    result = aggregate_opportunity_score_v2(_BASE, event_probability_raw=0.9)
    assert result["probability_source"] == "raw_proxy"
    assert result["score_components"]["probability_confirmation"] == pytest.approx(90.0)
    assert any(
        "raw_score_probability_proxy" in warning
        for warning in result["calibration_warnings"]
    )


def test_neutral_missing_stays_50() -> None:
    result = aggregate_opportunity_score_v2(_BASE)
    assert result["probability_source"] == "neutral_missing"
    assert result["score_components"]["probability_confirmation"] == 50.0
    assert "event_probability" in result["missing_inputs"]


def test_explicit_component_beats_derived_probability() -> None:
    result = aggregate_opportunity_score_v2(
        dict(_BASE, probability_confirmation=99.0),
        event_probability_raw=0.1,
        event_probability_calibrated=0.2,
    )
    assert result["probability_source"] == "component_supplied"
    assert result["score_components"]["probability_confirmation"] == 99.0


def test_confidence_rises_only_with_support_and_coverage() -> None:
    nothing = aggregate_opportunity_score_v2(_BASE)
    support_only = aggregate_opportunity_score_v2(_BASE, calibration_support=80.0)
    support_and_coverage = aggregate_opportunity_score_v2(
        _BASE, calibration_support=80.0, outcome_coverage=0.9
    )
    assert (
        nothing["calibration_adjusted_confidence"]
        < support_only["calibration_adjusted_confidence"]
    )
    # calibration_adjusted_confidence = base × (0.5 + 0.5·s/100) × max(0.25, cov)
    assert support_and_coverage["calibration_adjusted_confidence"] == pytest.approx(
        support_and_coverage["confidence"] * 0.9 * 0.9, rel=1e-6
    )


def test_low_coverage_suppresses_overconfidence() -> None:
    high = aggregate_opportunity_score_v2(
        _BASE, calibration_support=90.0, outcome_coverage=1.0
    )
    low = aggregate_opportunity_score_v2(
        _BASE, calibration_support=90.0, outcome_coverage=0.1
    )
    assert (
        low["calibration_adjusted_confidence"]
        < high["calibration_adjusted_confidence"]
    )
    assert any("low outcome coverage" in w for w in low["calibration_warnings"])
    # The floor keeps it bounded away from zero (max(0.25, coverage)).
    assert low["calibration_adjusted_confidence"] > 0.0


def test_severe_trap_flags_cap_verdict_despite_strong_calibration() -> None:
    components = dict(
        _BASE,
        narrative_velocity=90.0,
        embedded_proof=20.0,
        casino_distortion=85.0,
        food_chain=30.0,
    )
    result = aggregate_opportunity_score_v2(
        components,
        calibration_support=95.0,
        outcome_coverage=1.0,
        event_probability_calibrated=0.9,
    )
    assert result["advisory_verdict"] == "avoid_trap"


def test_probability_fields_bounded_and_output_complete() -> None:
    result = aggregate_opportunity_score_v2(
        _BASE,
        event_probability_raw=7.0,  # clamps to 1.0
        event_probability_calibrated=-3.0,  # clamps to 0.0
        calibration_support=50.0,
        outcome_coverage=0.5,
    )
    assert result["raw_event_probability"] == 1.0
    assert result["calibrated_event_probability"] == 0.0
    assert result["outcome_coverage"] == pytest.approx(50.0)
    for key in (
        "probability_source",
        "calibration_support",
        "calibration_warnings",
        "calibration_adjusted_confidence",
    ):
        assert key in result
    assert 0.0 <= result["calibration_adjusted_confidence"] <= 100.0
