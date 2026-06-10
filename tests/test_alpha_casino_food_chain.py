"""Module A — casino vs food-chain classifier invariants."""

from __future__ import annotations

from src.alpha.casino_food_chain import classify_casino_food_chain

_HYPE = {
    "mention_velocity": 1.0,
    "sentiment_intensity": 1.0,
    "volume_spike": 1.0,
    "options_activity": 1.0,
    "influencer_density": 1.0,
    "headline_intensity": 1.0,
}
_QUIET = {key: 0.0 for key in _HYPE}
_STRONG_ECONOMICS = {
    "revenue_quality": 1.0,
    "fcf_quality": 1.0,
    "gross_margin_quality": 1.0,
    "demand_recurrence": 1.0,
    "pricing_power": 1.0,
    "balance_sheet_strength": 1.0,
    "leverage_risk": 0.0,
    "commoditization_risk": 0.0,
}
_WEAK_ECONOMICS = {
    "revenue_quality": 0.0,
    "fcf_quality": 0.0,
    "gross_margin_quality": 0.0,
    "demand_recurrence": 0.0,
    "pricing_power": 0.0,
    "balance_sheet_strength": 0.0,
    "leverage_risk": 1.0,
    "commoditization_risk": 1.0,
}


def test_scores_are_bounded_0_100() -> None:
    for casino, food in [
        (_HYPE, _STRONG_ECONOMICS),
        (_QUIET, _WEAK_ECONOMICS),
        (None, None),
    ]:
        result = classify_casino_food_chain(casino, food)
        assert 0.0 <= result["casino_score"] <= 100.0
        assert 0.0 <= result["food_chain_score"] <= 100.0


def test_hype_without_economics_is_casino_heavy() -> None:
    result = classify_casino_food_chain(_HYPE, _WEAK_ECONOMICS)
    assert result["classification"] == "casino_heavy"
    assert result["casino_food_chain_gap"] > 0


def test_economics_without_hype_is_food_chain_heavy() -> None:
    result = classify_casino_food_chain(_QUIET, _STRONG_ECONOMICS)
    assert result["classification"] == "food_chain_heavy"
    assert result["casino_food_chain_gap"] < 0


def test_no_signal_anywhere_is_weak_signal() -> None:
    result = classify_casino_food_chain(_QUIET, _WEAK_ECONOMICS)
    assert result["classification"] == "weak_signal"


def test_missing_inputs_default_to_neutral_without_crash() -> None:
    result = classify_casino_food_chain(None, None)
    assert result["casino_score"] == 50.0
    assert result["food_chain_score"] == 50.0
    assert result["classification"] == "balanced"
    assert len(result["missing_inputs"]) == 14


def test_partial_inputs_report_only_the_missing_keys() -> None:
    result = classify_casino_food_chain({"mention_velocity": 0.9}, None)
    assert "casino.mention_velocity" not in result["missing_inputs"]
    assert "casino.volume_spike" in result["missing_inputs"]


def test_leverage_risk_lowers_food_chain_score() -> None:
    low_leverage = classify_casino_food_chain(None, {"leverage_risk": 0.0})
    high_leverage = classify_casino_food_chain(None, {"leverage_risk": 1.0})
    assert high_leverage["food_chain_score"] < low_leverage["food_chain_score"]


def test_out_of_range_inputs_are_clamped() -> None:
    result = classify_casino_food_chain({"mention_velocity": 99.0}, None)
    assert result["casino_score"] <= 100.0


def test_explanation_is_present() -> None:
    result = classify_casino_food_chain(_HYPE, _STRONG_ECONOMICS)
    assert result["explanation"]
