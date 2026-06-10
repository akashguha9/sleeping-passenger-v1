"""Module C — half-life decay math invariants."""

from __future__ import annotations

import math

import pytest

from src.alpha.half_life import (
    SIGNAL_HALF_LIFE_DAYS,
    decay_signal_strength,
    estimate_half_life,
    half_life_to_lambda,
)


def test_strength_at_t_zero_equals_initial() -> None:
    result = decay_signal_strength(0.8, 0.0, 30.0)
    assert result["current_strength"] == pytest.approx(0.8)


def test_strength_at_half_life_is_half_initial() -> None:
    result = decay_signal_strength(1.0, 30.0, 30.0)
    assert result["current_strength"] == pytest.approx(0.5, rel=1e-9)


def test_strength_at_two_half_lives_is_quarter() -> None:
    result = decay_signal_strength(100.0, 60.0, 30.0)
    assert result["current_strength"] == pytest.approx(25.0, rel=1e-9)


def test_longer_half_life_decays_slower() -> None:
    fast = decay_signal_strength(1.0, 10.0, 2.0)
    slow = decay_signal_strength(1.0, 10.0, 365.0)
    assert slow["current_strength"] > fast["current_strength"]


def test_lambda_matches_ln2_over_half_life() -> None:
    assert half_life_to_lambda(30.0) == pytest.approx(math.log(2.0) / 30.0)


def test_invalid_half_life_raises() -> None:
    with pytest.raises(ValueError):
        decay_signal_strength(1.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        decay_signal_strength(1.0, -1.0, 30.0)


def test_estimate_half_life_neutral_inputs_keep_baseline() -> None:
    result = estimate_half_life("viral_social_post")
    assert result["half_life_days"] == pytest.approx(
        SIGNAL_HALF_LIFE_DAYS["viral_social_post"]
    )
    assert result["missing_inputs"] == []


def test_estimate_half_life_strong_inputs_stretch_baseline() -> None:
    strong = estimate_half_life(
        "new_contract", source_quality=1.0, proof_strength=1.0, recurrence=1.0
    )
    weak = estimate_half_life(
        "new_contract", source_quality=0.0, proof_strength=0.0, recurrence=0.0
    )
    base = SIGNAL_HALF_LIFE_DAYS["new_contract"]
    assert strong["half_life_days"] == pytest.approx(base * 1.5)
    assert weak["half_life_days"] == pytest.approx(base * 0.5)


def test_estimate_half_life_unknown_type_falls_back_without_crash() -> None:
    result = estimate_half_life("mystery_signal")
    assert result["half_life_days"] > 0
    assert any("mystery_signal" in note for note in result["missing_inputs"])


def test_category_ordering_viral_shortest_necessity_longest() -> None:
    assert (
        SIGNAL_HALF_LIFE_DAYS["viral_social_post"]
        < SIGNAL_HALF_LIFE_DAYS["newspaper_article"]
        < SIGNAL_HALF_LIFE_DAYS["earnings_surprise"]
        < SIGNAL_HALF_LIFE_DAYS["new_contract"]
        < SIGNAL_HALF_LIFE_DAYS["regulatory_approval"]
        < SIGNAL_HALF_LIFE_DAYS["infrastructure_cycle"]
        < SIGNAL_HALF_LIFE_DAYS["human_necessity"]
    )
