"""Replay harness invariants: precision@k, Brier, calibration, safety."""

from __future__ import annotations

import json

import pytest

from src.alpha.replay import (
    brier_score,
    bucketed_calibration_error,
    classify_outcome,
    demo_replay_dataset,
    evaluate_replay,
    precision_at_k,
)


def _record(score: float, outcome: bool | None, **extra) -> dict:
    observed = {
        "price_return": None,
        "drawdown": None,
        "fundamental_confirmation": outcome,
        "narrative_persistence": None,
        "filing_confirmation": None,
    }
    return {
        "signal_id": f"S{score:.0f}",
        "opportunity_score": score,
        "verdict": "deep_research",
        "observed_outcome": observed,
        **extra,
    }


def test_classify_outcome_buckets() -> None:
    assert classify_outcome(_record(50, True)) == "confirmed"
    assert classify_outcome(_record(50, False)) == "refuted"
    assert classify_outcome(_record(50, None)) == "unresolved"
    assert classify_outcome({"observed_outcome": {"price_return": 0.05}}) == "confirmed"
    assert classify_outcome({"observed_outcome": {"price_return": -0.05}}) == "refuted"
    assert classify_outcome({}) == "unresolved"


def test_precision_at_k() -> None:
    records = [
        _record(90, True),
        _record(80, False),
        _record(70, True),
        _record(20, False),
    ]
    assert precision_at_k(records, 2) == pytest.approx(0.5)
    assert precision_at_k(records, 3) == pytest.approx(2 / 3)
    assert precision_at_k([], 5) is None
    assert precision_at_k(records, 0) is None


def test_unresolved_records_count_against_precision() -> None:
    records = [_record(90, None), _record(80, True)]
    assert precision_at_k(records, 2) == pytest.approx(0.5)


def test_brier_score_math() -> None:
    # Brier = (p − y)^2 averaged.
    assert brier_score([(1.0, 1), (0.0, 0)]) == pytest.approx(0.0)
    assert brier_score([(0.5, 1)]) == pytest.approx(0.25)
    assert brier_score([(0.8, 0)]) == pytest.approx(0.64)
    assert brier_score([]) is None


def test_bucketed_calibration_error() -> None:
    pairs = [(0.1, 0), (0.1, 0), (0.9, 1), (0.9, 0)]
    rows = bucketed_calibration_error(pairs, bucket_count=5)
    assert len(rows) == 5
    low = rows[0]
    assert low["count"] == 2
    assert low["abs_error"] == pytest.approx(0.1)
    high = rows[4]
    assert high["count"] == 2
    assert high["empirical_frequency"] == pytest.approx(0.5)
    assert high["abs_error"] == pytest.approx(0.4)
    empty = rows[2]
    assert empty["count"] == 0 and empty["abs_error"] is None


def test_evaluate_replay_full_report_on_demo_fixture() -> None:
    report = evaluate_replay(demo_replay_dataset(), k=2)
    assert report["record_count"] == 3
    assert report["outcome_counts"] == {
        "confirmed": 1,
        "refuted": 1,
        "unresolved": 1,
    }
    assert 0.0 <= report["precision_at_k"] <= 1.0
    assert 0.0 <= report["brier_score"] <= 1.0
    assert report["hit_rate_by_verdict"]["deep_research"]["hit_rate"] == 1.0
    assert report["average_score_by_outcome_bucket"]["confirmed"] == pytest.approx(62.0)
    # The meme record was trap-flagged and refuted: a true positive flag.
    assert report["trap_flag_false_positive_rate"] == 0.0
    assert report["narrative_decay_error"] is not None


def test_empty_dataset_is_safe() -> None:
    report = evaluate_replay([])
    assert report["record_count"] == 0
    assert report["precision_at_k"] is None
    assert report["brier_score"] is None
    assert report["trap_flag_false_positive_rate"] is None
    assert "replay_records" in report["missing_inputs"]
    assert report["calibration_support"] == 0.0


def test_calibration_support_grows_with_resolved_probabilities() -> None:
    few = evaluate_replay(demo_replay_dataset())
    many_records = [
        dict(_record(60, True), event_probability=0.6) for _ in range(60)
    ]
    many = evaluate_replay(many_records)
    assert many["calibration_support"] == 100.0
    assert few["calibration_support"] < many["calibration_support"]


def test_replay_is_deterministic_and_json_safe() -> None:
    first = json.dumps(evaluate_replay(demo_replay_dataset(), k=2), sort_keys=True)
    second = json.dumps(evaluate_replay(demo_replay_dataset(), k=2), sort_keys=True)
    assert first == second


def test_replay_never_implies_returns() -> None:
    report = evaluate_replay(demo_replay_dataset())
    text = json.dumps(report).lower()
    assert "not performance results" in text
    for forbidden in ("guaranteed", "profit you will", "expected return"):
        assert forbidden not in text
    assert "Advisory-only" in report["disclaimer"]


def test_demo_dataset_is_clearly_synthetic() -> None:
    for record in demo_replay_dataset():
        assert record["source"] == "manual_stub"
        assert record["signal_id"].startswith("DEMO_")
