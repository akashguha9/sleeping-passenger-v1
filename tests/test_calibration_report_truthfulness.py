"""Calibration report truthfulness contract — proof_loop_hardening_sprint.

Pins the high-level invariants the calibration gate must satisfy.  These
are leakage controls: the gate must never claim more than the evidence
supports, and must never return a measurable metric when no data exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.calibration_report import (
    compute_calibration_report,
    compute_corpus_calibration_report,
)


pytestmark = [
    pytest.mark.calibration,
    pytest.mark.safety_floor,
]


def _write_corpus(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "corpus.json"
    envelope = {
        "script": "test",
        "generated_at_utc": "2026-05-27T00:00:00+00:00",
        "records": records,
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


def _real_record(p: float, y: int, rid: str = "r0") -> dict:
    return {
        "record_id": rid,
        "source": "manual_trade",
        "source_record_id": rid,
        "asset_or_market": "TEST",
        "signal_timestamp_utc": "2026-05-01T00:00:00+00:00",
        "outcome_timestamp_utc": "2026-05-08T00:00:00+00:00",
        "horizon_days": 7.0,
        "score_snapshot": {"model_probability": float(p)},
        "outcome_label": int(y),
        "outcome_definition": "test_event",
        "provenance": {"mock_fallback": False, "fallback_used": False},
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def _fixture_record(p: float, y: int, rid: str) -> dict:
    rec = _real_record(p, y, rid)
    rec["source"] = "fixture_test_only"
    return rec


def test_no_observations_reports_insufficient_evidence_and_nulls():
    """Empty input → INSUFFICIENT_EVIDENCE, no fabricated metrics."""
    report = compute_calibration_report(observations=[])
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False
    assert report["brier_score"] is None
    assert report["ece"] is None
    assert report["mce"] is None


def test_persistence_unavailable_reports_insufficient_evidence():
    """No persistence helper available → INSUFFICIENT_EVIDENCE, not a crash."""
    report = compute_calibration_report(observations=None)
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False
    assert report["brier_score"] is None


def test_corpus_with_only_fixtures_is_insufficient_evidence(tmp_path):
    fixtures = [_fixture_record(0.7, 1, f"fix{i}") for i in range(30)]
    corpus_path = _write_corpus(tmp_path, fixtures)
    report = compute_corpus_calibration_report(corpus_path)
    assert report["n_real"] == 0
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False


def test_corpus_with_few_real_rows_below_n_min_blocks_predictive_claim(tmp_path):
    # 25 perfectly-calibrated real rows is still below the 200 floor.
    records = []
    for i in range(25):
        p, y = (1.0, 1) if i % 2 == 0 else (0.0, 0)
        records.append(_real_record(p, y, f"r{i}"))
    corpus_path = _write_corpus(tmp_path, records)
    report = compute_corpus_calibration_report(corpus_path)
    assert report["n_real"] == 25
    assert report["predictive_claim_allowed"] is False
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"


def test_corpus_at_n_min_with_perfect_metrics_unlocks_measured_pass(tmp_path):
    records = []
    for i in range(200):
        p, y = (1.0, 1) if i % 2 == 0 else (0.0, 0)
        records.append(_real_record(p, y, f"r{i}"))
    corpus_path = _write_corpus(tmp_path, records)
    report = compute_corpus_calibration_report(corpus_path)
    assert report["n_real"] == 200
    assert report["calibration_status"] == "MEASURED_PASS"
    assert report["predictive_claim_allowed"] is True
    assert report["brier_score"] == pytest.approx(0.0)
    assert report["ece"] == pytest.approx(0.0)


def test_missing_corpus_path_does_not_crash_and_reports_insufficient(tmp_path):
    nonexistent = tmp_path / "absent.json"
    report = compute_corpus_calibration_report(nonexistent)
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False
    assert report["n_real"] == 0


def test_advisory_safety_stamps_present_in_every_report():
    report = compute_calibration_report(observations=[])
    for k in (
        "advisory_status",
        "execution_gate",
        "broker_api_called",
        "ai_execution_count",
    ):
        assert k in report
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0


def test_predictive_claim_never_true_when_n_real_below_threshold(tmp_path):
    # Adversarial: synthesise rows that would pass Brier/ECE/MCE in
    # isolation but stop at N_real = 199.  The gate must still block.
    records = []
    for i in range(199):
        p, y = (1.0, 1) if i % 2 == 0 else (0.0, 0)
        records.append(_real_record(p, y, f"r{i}"))
    corpus_path = _write_corpus(tmp_path, records)
    report = compute_corpus_calibration_report(corpus_path)
    assert report["predictive_claim_allowed"] is False
