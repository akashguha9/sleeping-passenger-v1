"""Calibration gate tests — EMS/EQS/DS/LS/EFS/APS advisory scoring.

Identity Collapse + First-Day Operator sprint, Phase 8.

This is the NEW Phase-8 calibration test that exercises the
``scripts.calibration_report`` Brier/ECE helper.  The pre-existing
``tests/test_calibration_gate.py`` covers the older Sprint-10F outcome
readiness gate; both are kept.

Properties under test
---------------------
* With N < 200, ``predictive_claim_allowed`` is always False and the
  status is ``INSUFFICIENT_EVIDENCE``.
* Brier and ECE are computed correctly on known inputs.
* Invalid ``p_i`` outside [0,1] is clipped with no claim of validity.
* Invalid ``y_i`` values are rejected and counted.
* Missing outcomes / unavailable persistence yields
  ``INSUFFICIENT_EVIDENCE``.
* Every report carries the advisory safety stamps.
* The report's ``score_axes`` lists exactly the six canonical axes.
"""
from __future__ import annotations

from typing import Any

import pytest

from scripts.calibration_report import (
    DEFAULT_BS_THRESHOLD,
    DEFAULT_ECE_THRESHOLD,
    DEFAULT_N_MIN,
    Observation,
    SCORE_AXES,
    brier_score,
    compute_calibration_report,
    expected_calibration_error,
    reliability_buckets,
)


def _row(p: float, y: int, axis: str = "all") -> dict[str, Any]:
    return {"p": p, "y": y, "score_axis": axis}


# ---------------------------------------------------------------------------
# Static contract tests
# ---------------------------------------------------------------------------


def test_score_axes_are_exactly_canonical_six():
    assert SCORE_AXES == ("EMS", "EQS", "DS", "LS", "EFS", "APS")


def test_advisory_stamps_present_on_report():
    report = compute_calibration_report([])
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["canonical_store"] == "sqlite"
    assert report["jsonl_is_canonical"] is False


def test_empty_input_yields_insufficient_evidence():
    report = compute_calibration_report([])
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False
    assert report["brier_score"] is None
    assert report["ece"] is None


def test_none_input_when_persistence_missing_returns_insufficient_evidence():
    report = compute_calibration_report(observations=None)
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Sample-size gate
# ---------------------------------------------------------------------------


def test_below_n_min_blocks_predictive_claim():
    rows = [_row(0.0, 0) for _ in range(100)] + [_row(1.0, 1) for _ in range(99)]
    report = compute_calibration_report(rows, n_min=200)
    assert report["n"] == 199
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False


def test_at_n_min_with_perfect_calibration_allows_claim():
    rows = [_row(0.0, 0) for _ in range(100)] + [_row(1.0, 1) for _ in range(100)]
    report = compute_calibration_report(rows, n_min=200)
    assert report["n"] == 200
    assert report["calibration_status"] == "MEASURED"
    assert report["brier_score"] == 0.0
    assert report["ece"] == 0.0
    assert report["predictive_claim_allowed"] is True


def test_measured_but_thresholds_violated_blocks_claim():
    rows = [_row(0.5, 1) for _ in range(200)]
    report = compute_calibration_report(rows, n_min=200)
    assert report["n"] == 200
    assert report["calibration_status"] == "MEASURED"
    assert report["brier_score"] == 0.25
    assert report["ece"] == 0.5
    assert report["predictive_claim_allowed"] is False
    assert "calibration thresholds not met" in report["warning"]


# ---------------------------------------------------------------------------
# Math: Brier
# ---------------------------------------------------------------------------


def test_brier_score_perfect_predictions():
    obs = [Observation(p=0.0, y=0), Observation(p=1.0, y=1)]
    assert brier_score(obs) == 0.0


def test_brier_score_worst_case():
    obs = [Observation(p=0.0, y=1), Observation(p=1.0, y=0)]
    assert brier_score(obs) == 1.0


def test_brier_score_half_probability_balanced():
    obs = [Observation(p=0.5, y=0), Observation(p=0.5, y=1)]
    assert brier_score(obs) == 0.25


# ---------------------------------------------------------------------------
# Math: ECE + buckets
# ---------------------------------------------------------------------------


def test_ece_zero_when_perfectly_calibrated():
    rows = [_row(0.1, 0) for _ in range(9)] + [_row(0.1, 1) for _ in range(1)]
    rows += [_row(0.9, 0) for _ in range(1)] + [_row(0.9, 1) for _ in range(9)]
    parsed = [Observation.from_raw(r) for r in rows]
    parsed = [o for o in parsed if o is not None]
    ece = expected_calibration_error(parsed, n_buckets=10)
    assert ece == pytest.approx(0.0, abs=1e-9)


def test_buckets_partition_probabilities_correctly():
    rows = [_row(i / 100.0, 0) for i in range(101)]
    obs = [Observation.from_raw(r) for r in rows]
    obs = [o for o in obs if o is not None]
    buckets = reliability_buckets(obs, n_buckets=10)
    assert len(buckets) == 10
    assert all(b["count"] >= 1 for b in buckets)


# ---------------------------------------------------------------------------
# Input hygiene
# ---------------------------------------------------------------------------


def test_invalid_p_outside_range_is_clipped():
    rows = [{"p": 1.5, "y": 1}, {"p": -0.5, "y": 0}]
    report = compute_calibration_report(rows, n_min=1)
    assert report["n"] == 2
    assert report["brier_score"] == 0.0
    assert report["rejected_input_count"] == 0


def test_invalid_y_value_rejected():
    rows = [{"p": 0.5, "y": "yes"}, {"p": 0.5, "y": 2}, {"p": 0.5, "y": 1}]
    report = compute_calibration_report(rows, n_min=1)
    assert report["n"] == 1
    assert report["rejected_input_count"] == 2


def test_nan_or_inf_p_rejected():
    rows = [{"p": float("nan"), "y": 1}, {"p": float("inf"), "y": 0}, {"p": 0.5, "y": 1}]
    report = compute_calibration_report(rows, n_min=1)
    assert report["n"] == 1
    assert report["rejected_input_count"] == 2


def test_axis_label_recognised():
    rows = [{"p": 0.5, "y": 1, "score_axis": "APS"} for _ in range(200)]
    report = compute_calibration_report(rows, n_min=200)
    assert "APS" in report["per_axis_report"]
    assert report["per_axis_report"]["APS"]["n"] == 200


# ---------------------------------------------------------------------------
# JSON output contract — exhaustive shape
# ---------------------------------------------------------------------------


def test_report_keys_match_sprint_contract():
    report = compute_calibration_report([])
    for key in (
        "script",
        "generated_at_utc",
        "advisory_status",
        "execution_gate",
        "broker_api_called",
        "ai_execution_count",
        "n",
        "n_min",
        "calibration_status",
        "predictive_claim_allowed",
        "brier_score",
        "ece",
        "bucket_report",
        "score_axes",
        "warning",
    ):
        assert key in report, f"calibration report missing required key: {key}"


def test_defaults_match_spec():
    assert DEFAULT_N_MIN == 200
    assert DEFAULT_BS_THRESHOLD == 0.25
    assert DEFAULT_ECE_THRESHOLD == 0.10
