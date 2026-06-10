"""Module F — classic benchmark layer invariants."""

from __future__ import annotations

import pytest

from src.alpha.classic_benchmark import (
    CLASSIC_BENCHMARKS,
    classic_for_sector,
    compare_to_classic,
)


def test_candidate_above_margin_beats_classic() -> None:
    result = compare_to_classic("vanilla", candidate_score=80.0, benchmark_score=60.0)
    assert result["verdict"] == "beats_classic"
    assert result["benchmark_edge"] == pytest.approx(20.0)


def test_candidate_below_margin_fails_classic() -> None:
    result = compare_to_classic("vanilla", candidate_score=40.0, benchmark_score=60.0)
    assert result["verdict"] == "fails_classic"


def test_edge_within_margin_is_inconclusive() -> None:
    result = compare_to_classic("margherita", candidate_score=62.0, benchmark_score=60.0)
    assert result["verdict"] == "inconclusive"


def test_custom_margin_is_respected() -> None:
    result = compare_to_classic(
        "fcf", candidate_score=62.0, benchmark_score=60.0, inconclusive_margin=1.0
    )
    assert result["verdict"] == "beats_classic"


def test_scores_are_clamped() -> None:
    result = compare_to_classic("vanilla", candidate_score=500.0, benchmark_score=-50.0)
    assert result["candidate_score"] == 100.0
    assert result["benchmark_score"] == 0.0


def test_sector_registry_includes_framework_classics() -> None:
    assert classic_for_sector("ice_cream") == "vanilla"
    assert classic_for_sector("pizza") == "margherita"
    assert classic_for_sector("stocks") == "free_cash_flow"
    assert classic_for_sector("nonexistent_sector") is None
    assert "payments" in CLASSIC_BENCHMARKS
