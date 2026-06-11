"""Reliability-diagram data: how honest are the probabilities, per bucket.

    Brier = (p − y)^2
    calibration_error_bucket =
        |mean(predicted_probability_bucket) − empirical_frequency_bucket|
    expected_calibration_error =
        Σ_bucket weight_bucket × calibration_error_bucket

Deterministic, bounded, fixture-friendly: probabilities are clamped to
[0, 1], empty buckets report ``None`` (not fake zeros), and an empty
dataset produces a complete, safe report.
"""

from __future__ import annotations

from typing import Any

from src.alpha.replay import classify_outcome
from src.utils.math_utils import clamp01

DEFAULT_BIN_COUNT = 5


def reliability_diagram(
    probability_pairs: list[tuple[float, float]] | None,
    *,
    bin_count: int = DEFAULT_BIN_COUNT,
) -> dict[str, Any]:
    """Build reliability bins from (predicted probability, outcome) pairs."""
    pairs = [
        (clamp01(float(p)), 1.0 if y else 0.0) for p, y in (probability_pairs or [])
    ]
    bins: list[list[tuple[float, float]]] = [[] for _ in range(bin_count)]
    for probability, outcome in pairs:
        index = min(bin_count - 1, int(probability * bin_count))
        bins[index].append((probability, outcome))

    rows: list[dict[str, Any]] = []
    expected_calibration_error = 0.0 if pairs else None
    for index, bucket in enumerate(bins):
        bin_min = index / bin_count
        bin_max = (index + 1) / bin_count
        if not bucket:
            rows.append(
                {
                    "bin_min": bin_min,
                    "bin_max": bin_max,
                    "count": 0,
                    "mean_predicted_probability": None,
                    "empirical_frequency": None,
                    "calibration_error": None,
                }
            )
            continue
        mean_predicted = sum(p for p, _ in bucket) / len(bucket)
        empirical = sum(y for _, y in bucket) / len(bucket)
        error = abs(mean_predicted - empirical)
        rows.append(
            {
                "bin_min": bin_min,
                "bin_max": bin_max,
                "count": len(bucket),
                "mean_predicted_probability": mean_predicted,
                "empirical_frequency": empirical,
                "calibration_error": error,
            }
        )
        expected_calibration_error += (len(bucket) / len(pairs)) * error

    brier = (
        sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None
    )
    return {
        "bins": rows,
        "brier_score": brier,
        "expected_calibration_error": expected_calibration_error,
        "sample_size": len(pairs),
        "resolved_count": len(pairs),
    }


def reliability_from_replay_records(
    replay_records: list[dict[str, Any]] | None,
    *,
    bin_count: int = DEFAULT_BIN_COUNT,
    probability_field: str = "event_probability",
) -> dict[str, Any]:
    """Reliability data straight from replay records (resolved only)."""
    pairs: list[tuple[float, float]] = []
    discovered = 0
    for record in replay_records or []:
        discovered += 1
        probability = record.get(probability_field)
        if probability is None:
            continue
        outcome = classify_outcome(record)
        if outcome == "unresolved":
            continue
        pairs.append((float(probability), 1.0 if outcome == "confirmed" else 0.0))
    report = reliability_diagram(pairs, bin_count=bin_count)
    report["discovered_records"] = discovered
    return report
