"""Narrative radar (prediction-market shock) and narrative tracker tests."""

from __future__ import annotations

import pytest

from src.simulator.narrative_radar import (
    SHOCK_RADAR_THRESHOLD,
    score_narrative_shock,
)
from src.simulator.narrative_tracker import dirty_air_score, track_narrative


def _shock(**overrides):
    base = dict(
        market_name="AI grid bill passes 2026",
        probability_before=0.27,
        probability_after=0.54,
        velocity=0.8,
        market_importance=0.9,
        market_liquidity=0.7,
        cross_source_confirmation=0.8,
    )
    base.update(overrides)
    return score_narrative_shock(**base)


def test_case_study_ai_grid_shock_crosses_radar_threshold() -> None:
    shock = _shock()
    assert shock.probability_delta == pytest.approx(0.27)
    assert shock.narrative_shock_score >= SHOCK_RADAR_THRESHOLD
    assert shock.direction == "rising"
    assert "RADAR_NOT_TRADE" in shock.reason_codes


def test_zero_liquidity_kills_shock_score() -> None:
    shock = _shock(market_liquidity=0.0)
    assert shock.narrative_shock_score == 0.0
    assert "THIN_PREDICTION_MARKET" in shock.reason_codes
    assert "BELOW_RADAR_THRESHOLD" in shock.reason_codes


def test_falling_probability_has_negative_delta_and_direction() -> None:
    shock = _shock(probability_before=0.6, probability_after=0.3)
    assert shock.probability_delta < 0
    assert shock.direction == "falling"
    assert shock.narrative_shock_score > 0  # magnitude still scored


def test_shock_is_serializable() -> None:
    payload = _shock(affected_themes=["grid equipment"]).to_dict()
    assert payload["affected_themes"] == ["grid equipment"]
    assert isinstance(payload["narrative_shock_score"], float)


def test_dirty_air_case_study_37_articles_2_origins() -> None:
    # Case study 6: 37 articles, 2 independent origins -> 0.946.
    assert dirty_air_score(2, 37) == pytest.approx(1 - 2 / 37)


def test_dirty_air_zero_when_all_origins_independent() -> None:
    assert dirty_air_score(10, 10) == 0.0


def test_dirty_air_origins_capped_at_mentions() -> None:
    assert dirty_air_score(50, 10) == 0.0


def test_copied_articles_trigger_dirty_air_warning() -> None:
    status = track_narrative(
        narrative="hype loop",
        mention_count=37,
        origin_count=2,
        independent_origin_count=2,
        source_quality=0.5,
        narrative_velocity=0.3,
        narrative_acceleration=0.0,
    )
    assert status.dirty_air_score > 0.9
    assert "DIRTY_AIR_WARNING" in status.reason_codes


def test_contradiction_pressure_breaks_narrative() -> None:
    status = track_narrative(
        narrative="broken story",
        mention_count=20,
        origin_count=10,
        independent_origin_count=8,
        source_quality=0.7,
        narrative_velocity=0.5,
        narrative_acceleration=0.2,
        contradiction_count=10,
    )
    assert status.narrative_state == "broken"
    assert "CONTRADICTION_PRESSURE" in status.reason_codes


def test_narrative_lifecycle_states() -> None:
    ignored = track_narrative(
        narrative="n", mention_count=1, origin_count=1,
        independent_origin_count=1, source_quality=0.5,
        narrative_velocity=0.0, narrative_acceleration=0.0,
    )
    assert ignored.narrative_state == "ignored"

    early = track_narrative(
        narrative="n", mention_count=5, origin_count=4,
        independent_origin_count=4, source_quality=0.6,
        narrative_velocity=0.1, narrative_acceleration=0.0,
    )
    assert early.narrative_state == "early_stir"

    accelerating = track_narrative(
        narrative="n", mention_count=40, origin_count=20,
        independent_origin_count=18, source_quality=0.7,
        narrative_velocity=0.4, narrative_acceleration=0.2,
    )
    assert accelerating.narrative_state == "accelerating"

    crowded = track_narrative(
        narrative="n", mention_count=200, origin_count=120,
        independent_origin_count=110, source_quality=0.7,
        narrative_velocity=0.1, narrative_acceleration=0.0,
    )
    assert crowded.narrative_state == "crowded"

    overheated = track_narrative(
        narrative="n", mention_count=300, origin_count=12,
        independent_origin_count=10, source_quality=0.4,
        narrative_velocity=0.8, narrative_acceleration=0.3,
    )
    assert overheated.narrative_state == "overheated"

    decaying = track_narrative(
        narrative="n", mention_count=50, origin_count=20,
        independent_origin_count=15, source_quality=0.6,
        narrative_velocity=-0.3, narrative_acceleration=-0.1,
    )
    assert decaying.narrative_state == "decaying"
