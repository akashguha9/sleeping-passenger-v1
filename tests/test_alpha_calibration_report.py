"""Reliability diagram data: bins, Brier, expected calibration error."""

from __future__ import annotations

import pytest

from src.alpha.calibration_report import (
    reliability_diagram,
    reliability_from_replay_records,
)


def test_empty_dataset_is_safe() -> None:
    report = reliability_diagram([])
    assert report["sample_size"] == 0
    assert report["brier_score"] is None
    assert report["expected_calibration_error"] is None
    assert len(report["bins"]) == 5
    for row in report["bins"]:
        assert row["count"] == 0
        assert row["mean_predicted_probability"] is None
        assert row["calibration_error"] is None


def test_perfect_calibration_near_zero_error() -> None:
    # 10 predictions at 0.3 with 3 wins; 10 at 0.7 with 7 wins.
    pairs = [(0.3, 1)] * 3 + [(0.3, 0)] * 7 + [(0.7, 1)] * 7 + [(0.7, 0)] * 3
    report = reliability_diagram(pairs)
    assert report["expected_calibration_error"] == pytest.approx(0.0, abs=1e-9)


def test_overconfident_predictions_produce_positive_error() -> None:
    pairs = [(0.9, 1)] * 5 + [(0.9, 0)] * 5  # claims 90%, delivers 50%
    report = reliability_diagram(pairs)
    assert report["expected_calibration_error"] == pytest.approx(0.4)
    assert report["brier_score"] > 0.2


def test_bins_are_deterministic_and_bounded() -> None:
    pairs = [(0.05, 0), (0.45, 1), (0.99, 1)]
    first = reliability_diagram(pairs)
    second = reliability_diagram(pairs)
    assert first == second
    counts = [row["count"] for row in first["bins"]]
    assert counts == [1, 0, 1, 0, 1]
    for row in first["bins"]:
        if row["mean_predicted_probability"] is not None:
            assert 0.0 <= row["mean_predicted_probability"] <= 1.0
            assert 0.0 <= row["empirical_frequency"] <= 1.0


def test_out_of_range_probabilities_are_clamped() -> None:
    report = reliability_diagram([(5.0, 1), (-2.0, 0)])
    assert report["sample_size"] == 2
    assert report["bins"][0]["count"] == 1
    assert report["bins"][4]["count"] == 1


def test_reliability_from_replay_records_uses_resolved_only() -> None:
    records = [
        {
            "event_probability": 0.8,
            "observed_outcome": {"fundamental_confirmation": True},
        },
        {
            "event_probability": 0.6,
            "observed_outcome": {"fundamental_confirmation": None},
        },
        {"observed_outcome": {"fundamental_confirmation": True}},  # no probability
    ]
    report = reliability_from_replay_records(records)
    assert report["discovered_records"] == 3
    assert report["resolved_count"] == 1
