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

import json
from typing import Any

import pytest

from scripts.calibration_report import (
    DEFAULT_BS_THRESHOLD,
    DEFAULT_ECE_THRESHOLD,
    DEFAULT_MCE_THRESHOLD,
    DEFAULT_N_MIN,
    Observation,
    SCORE_AXES,
    base_rate,
    brier_score,
    compute_calibration_report,
    compute_corpus_calibration_report,
    expected_calibration_error,
    maximum_calibration_error,
    reliability_buckets,
    sharpness,
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
    assert DEFAULT_MCE_THRESHOLD == 0.25


# ---------------------------------------------------------------------------
# MCE / base rate / sharpness math
# ---------------------------------------------------------------------------


def test_mce_is_max_bucket_error_when_one_bucket_is_off():
    # 200 rows: 100 at p=0.1 with y=0 (perfect for that bucket), 100 at p=0.9 with y=0
    # (massively off — calibration error for 0.9 bucket = 0.9, MCE = 0.9).
    rows = [_row(0.1, 0) for _ in range(100)] + [_row(0.9, 0) for _ in range(100)]
    parsed = [Observation.from_raw(r) for r in rows]
    parsed = [o for o in parsed if o is not None]
    mce = maximum_calibration_error(parsed, n_buckets=10)
    assert mce == pytest.approx(0.9, abs=1e-9)


def test_base_rate_and_sharpness_known_case():
    parsed = [Observation(p=0.2, y=0), Observation(p=0.8, y=1)]
    assert base_rate(parsed) == pytest.approx(0.5, abs=1e-9)
    # mean(p)=0.5; var = ((0.2-0.5)^2 + (0.8-0.5)^2)/2 = 0.09; sharpness=0.3
    assert sharpness(parsed) == pytest.approx(0.3, abs=1e-9)


def test_report_includes_mce_base_rate_sharpness():
    rows = [_row(0.0, 0) for _ in range(100)] + [_row(1.0, 1) for _ in range(100)]
    report = compute_calibration_report(rows, n_min=200)
    assert report["mce"] == 0.0
    assert report["base_rate"] == 0.5
    assert report["sharpness"] == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Corpus-driven gate
# ---------------------------------------------------------------------------


def _corpus_envelope(records):
    return {
        "script": "curate_calibration_corpus.py",
        "generated_at_utc": "2026-05-26T00:00:00+00:00",
        "sources_used": ["test"],
        "metrics": {},
        "records": records,
    }


def _crec(p: float, y: int, *, source: str = "manual_trade",
          source_record_id: str | None = None, mock: bool = False) -> dict[str, Any]:
    return {
        "record_id": source_record_id or f"r{p}_{y}",
        "source": source,
        "source_record_id": source_record_id or f"sr{p}_{y}",
        "asset_or_market": "T",
        "signal_timestamp_utc": "2026-01-01T00:00:00+00:00",
        "outcome_timestamp_utc": "2026-01-02T00:00:00+00:00",
        "horizon_days": 1.0,
        "score_snapshot": {"model_probability": p},
        "outcome_label": y,
        "outcome_definition": "test",
        "provenance": {"mock_fallback": mock, "fallback_used": False},
    }


def test_corpus_predictive_claim_false_when_n_real_below_min(tmp_path):
    recs = [_crec(0.0, 0, source_record_id=f"a{i}") for i in range(50)] + \
           [_crec(1.0, 1, source_record_id=f"b{i}") for i in range(50)]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_corpus_envelope(recs)), encoding="utf-8")
    report = compute_corpus_calibration_report(path, n_min=200)
    assert report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False
    assert report["n_real"] == 100


def test_corpus_predictive_claim_true_only_when_all_thresholds_pass(tmp_path):
    # Perfect calibration at scale.
    recs = [_crec(0.0, 0, source_record_id=f"a{i}") for i in range(100)] + \
           [_crec(1.0, 1, source_record_id=f"b{i}") for i in range(100)]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_corpus_envelope(recs)), encoding="utf-8")
    report = compute_corpus_calibration_report(path, n_min=200)
    assert report["calibration_status"] == "MEASURED_PASS"
    assert report["predictive_claim_allowed"] is True
    assert report["brier_score"] == 0.0
    assert report["ece"] == 0.0
    assert report["mce"] == 0.0


def test_corpus_predictive_claim_false_when_mce_fails(tmp_path):
    # 100 records calibrated perfectly at p=0.1 + 100 records badly miscalibrated at p=0.9.
    # ECE will be ≈ 0.45 (also fails), so this also exercises ECE.  But the
    # MCE alone is 0.9 which trips the MCE threshold (0.25) in isolation.
    recs = [_crec(0.1, 0, source_record_id=f"a{i}") for i in range(100)] + \
           [_crec(0.9, 0, source_record_id=f"b{i}") for i in range(100)]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_corpus_envelope(recs)), encoding="utf-8")
    report = compute_corpus_calibration_report(path, n_min=200)
    assert report["calibration_status"] == "MEASURED_FAIL"
    assert report["mce"] > 0.25
    assert report["predictive_claim_allowed"] is False
    assert "MCE" in report["warning"] or "ECE" in report["warning"] or "Brier" in report["warning"]


def test_corpus_predictive_claim_false_when_brier_fails(tmp_path):
    # Brier = 0.25 — exactly at the threshold, so passes the ≤ check.  Bump it
    # by adding a perfect-loss row to drive Brier above 0.25.  We force ECE
    # below threshold by using a single bucket at p=0.5 with mixed outcomes
    # (predicted=0.5, observed=0.5 → ECE=0).  MCE also stays at 0 in that
    # bucket.  But Brier alone trips.
    recs = []
    for i in range(100):
        recs.append(_crec(0.5, 1, source_record_id=f"y{i}"))
        recs.append(_crec(0.5, 0, source_record_id=f"n{i}"))
    # Now BS = (0.5)^2 = 0.25 exactly.  Pad with two rows pushing BS past 0.25.
    recs.append(_crec(0.0, 1, source_record_id="bad1"))  # BS contribution 1.0
    recs.append(_crec(1.0, 0, source_record_id="bad2"))
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_corpus_envelope(recs)), encoding="utf-8")
    report = compute_corpus_calibration_report(path, n_min=200)
    assert report["brier_score"] > 0.25
    assert report["calibration_status"] == "MEASURED_FAIL"
    assert report["predictive_claim_allowed"] is False


def test_corpus_fixture_records_do_not_count_toward_n_real(tmp_path):
    real = [_crec(0.5, 1, source_record_id=f"r{i}") for i in range(10)]
    fixture = [
        dict(_crec(0.5, 1, source_record_id=f"f{i}"), source="fixture_test_only")
        for i in range(10)
    ]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_corpus_envelope(real + fixture)), encoding="utf-8")
    report = compute_corpus_calibration_report(path, n_min=200)
    assert report["n_total"] == 20
    assert report["n_fixture"] == 10
    assert report["n_real"] == 10
    assert report["evidence_status"] == "INSUFFICIENT_EVIDENCE"


def test_corpus_mock_fallback_records_excluded_from_n_real(tmp_path):
    real = [_crec(0.5, 1, source_record_id=f"r{i}") for i in range(5)]
    mocked = [_crec(0.5, 1, source_record_id=f"m{i}", mock=True) for i in range(5)]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_corpus_envelope(real + mocked)), encoding="utf-8")
    report = compute_corpus_calibration_report(path, n_min=200)
    assert report["n_total"] == 10
    assert report["n_mock"] == 5
    assert report["n_real"] == 5


def test_corpus_missing_file_yields_insufficient_evidence(tmp_path):
    path = tmp_path / "missing.json"
    report = compute_corpus_calibration_report(path, n_min=200)
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False
    assert "missing" in report["warning"].lower()


def test_corpus_carries_advisory_stamps_and_no_broker_language(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps(_corpus_envelope([])), encoding="utf-8")
    report = compute_corpus_calibration_report(path)
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    serialized = json.dumps(report).lower()
    for forbidden in ("/orders", "place_order", "broker_order_id\": \"y"):
        assert forbidden not in serialized


def test_corpus_report_thresholds_match_spec(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps(_corpus_envelope([])), encoding="utf-8")
    report = compute_corpus_calibration_report(path)
    th = report["thresholds"]
    assert th["n_min"] == 200
    assert th["brier_score_max"] == 0.25
    assert th["ece_max"] == 0.10
    assert th["mce_max"] == 0.25
