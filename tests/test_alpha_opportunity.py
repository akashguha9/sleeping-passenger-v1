"""Module I — opportunity aggregation invariants."""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.opportunity import (
    ADVISORY_VERDICTS,
    POSITIVE_COMPONENTS,
    RISK_COMPONENTS,
    aggregate_opportunity_score,
)

_STRONG = {key: 90.0 for key in POSITIVE_COMPONENTS} | {
    key: 10.0 for key in RISK_COMPONENTS
}
_WEAK = {key: 10.0 for key in POSITIVE_COMPONENTS} | {
    key: 90.0 for key in RISK_COMPONENTS
}


def test_score_is_bounded_for_extremes() -> None:
    for components in (_STRONG, _WEAK, {}, None):
        result = aggregate_opportunity_score(components)
        assert 0.0 <= result["opportunity_score"] <= 100.0
        assert result["advisory_verdict"] in ADVISORY_VERDICTS


def test_strong_components_beat_weak_components() -> None:
    strong = aggregate_opportunity_score(_STRONG)
    weak = aggregate_opportunity_score(_WEAK)
    assert strong["opportunity_score"] > weak["opportunity_score"]
    assert strong["advisory_verdict"] == "core_candidate"
    # Weak positives drowning in casino distortion are a trap, not noise.
    assert weak["advisory_verdict"] == "avoid_trap"


def test_dead_signal_with_low_risk_is_ignore() -> None:
    dead = {key: 10.0 for key in POSITIVE_COMPONENTS} | {
        key: 10.0 for key in RISK_COMPONENTS
    }
    result = aggregate_opportunity_score(dead)
    assert result["advisory_verdict"] == "ignore"


def test_one_dead_positive_factor_sinks_the_score() -> None:
    dead_proof = dict(_STRONG, embedded_proof=0.0)
    result = aggregate_opportunity_score(dead_proof)
    assert result["opportunity_score"] == 0.0


def test_missing_components_default_neutral_and_are_reported() -> None:
    result = aggregate_opportunity_score({"narrative_velocity": 80.0})
    assert "narrative_velocity" not in result["missing_inputs"]
    assert "food_chain" in result["missing_inputs"]
    assert len(result["missing_inputs"]) == 10


def test_high_casino_distortion_with_weak_proof_is_avoid_trap() -> None:
    components = dict(_STRONG, casino_distortion=90.0, embedded_proof=20.0)
    result = aggregate_opportunity_score(components)
    assert result["advisory_verdict"] == "avoid_trap"


def test_short_half_life_forces_event_trade_only() -> None:
    result = aggregate_opportunity_score(_STRONG, half_life_days=3.0)
    assert result["advisory_verdict"] == "event_trade_only"


def test_risks_lower_the_score() -> None:
    low_risk = aggregate_opportunity_score(_STRONG)
    high_risk = aggregate_opportunity_score(
        dict(_STRONG, valuation_risk=95.0, regulatory_risk=95.0)
    )
    assert high_risk["opportunity_score"] < low_risk["opportunity_score"]


def test_drivers_and_disclaimer_present() -> None:
    result = aggregate_opportunity_score(_STRONG)
    assert len(result["top_positive_drivers"]) == 3
    assert len(result["top_negative_drivers"]) == 3
    assert result["disclaimer"] == ADVISORY_DISCLAIMER
    assert "guaranteed" not in str(result).lower()
