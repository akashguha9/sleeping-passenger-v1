"""Narrative snapshot adapter: velocity math, diversity, safety."""

from __future__ import annotations

import pytest

from src.alpha.adapters.narrative_snapshot_adapter import (
    compute_mention_velocity,
    summarize_narrative_snapshots,
)

_AS_OF = "2026-06-01T00:00:00"


def _row(day: str, mentions: int, source: str = "newspaper", **extra) -> dict:
    return {
        "theme": "residential plumbing",
        "source": source,
        "timestamp": f"2026-05-{day}T00:00:00",
        "mention_count": mentions,
        "sentiment_score": extra.pop("sentiment", 0.3),
        "source_quality": extra.pop("quality", 60),
        **extra,
    }


def test_mention_velocity_formula() -> None:
    assert compute_mention_velocity(30, 10) == pytest.approx(2.0)
    assert compute_mention_velocity(10, 10) == pytest.approx(0.0)
    assert compute_mention_velocity(5, 0) == pytest.approx(5.0)  # max(1, prev)


def test_rising_mentions_increase_score() -> None:
    rising = summarize_narrative_snapshots(
        [_row("20", 5), _row("29", 40)], as_of=_AS_OF
    )
    flat = summarize_narrative_snapshots(
        [_row("20", 20), _row("29", 20)], as_of=_AS_OF
    )
    assert rising["narrative_velocity_score"] > flat["narrative_velocity_score"]
    assert rising["mention_velocity"] > 0


def test_flat_mentions_are_velocity_neutral() -> None:
    result = summarize_narrative_snapshots(
        [_row("20", 20), _row("29", 20)], as_of=_AS_OF
    )
    assert result["mention_velocity"] == pytest.approx(0.0)
    assert result["velocity_score"] == pytest.approx(50.0)


def test_source_diversity_increases_confidence() -> None:
    single = summarize_narrative_snapshots(
        [_row("29", 40, source="reddit")], as_of=_AS_OF
    )
    diverse = summarize_narrative_snapshots(
        [
            _row("29", 10, source="reddit"),
            _row("29", 10, source="newspaper"),
            _row("29", 10, source="youtube"),
            _row("29", 10, source="x"),
        ],
        as_of=_AS_OF,
    )
    assert diverse["confidence"] > single["confidence"]
    assert diverse["unique_sources"] == 4


def test_single_source_hype_has_low_confidence_despite_volume() -> None:
    hype = summarize_narrative_snapshots(
        [_row("29", 100000, source="x")], as_of=_AS_OF
    )
    assert hype["confidence"] < 25.0


def test_missing_previous_window_is_safe_and_reported() -> None:
    result = summarize_narrative_snapshots([_row("29", 40)], as_of=_AS_OF)
    assert "previous_window_mentions" in result["missing_inputs"]
    assert 0.0 <= result["narrative_velocity_score"] <= 100.0


def test_empty_rows_are_safe() -> None:
    result = summarize_narrative_snapshots([], as_of=_AS_OF)
    assert "current_window_rows" in result["missing_inputs"]
    assert result["narrative_velocity_score"] >= 0.0


def test_bad_timestamps_are_ignored_not_fatal() -> None:
    result = summarize_narrative_snapshots(
        [{"timestamp": "not a date", "mention_count": 5}, _row("29", 10)],
        as_of=_AS_OF,
    )
    assert result["current_window_mentions"] == 10


def test_invalid_as_of_raises_value_error() -> None:
    with pytest.raises(ValueError):
        summarize_narrative_snapshots([], as_of="whenever")


def test_score_bounded_under_extreme_spikes() -> None:
    result = summarize_narrative_snapshots(
        [_row("20", 1), _row("29", 10_000_000, sentiment=1.0, quality=100)],
        as_of=_AS_OF,
    )
    assert 0.0 <= result["narrative_velocity_score"] <= 100.0


def test_adapter_makes_no_network_calls() -> None:
    import src.alpha.adapters.narrative_snapshot_adapter as adapter

    source = open(adapter.__file__).read()
    for fragment in ("requests.", "urllib", "httpx", "socket"):
        assert fragment not in source
