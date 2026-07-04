"""Objective 5 — decision-time model_probability snapshot tests.

Proves the plumbing can grow ``n_valid_p`` while the calibration gate stays
honestly locked (no predictive claim below N>=200 / without outcomes).
"""
from __future__ import annotations

from scripts.decision_probability_snapshot import (
    MODEL_VERSION,
    SCORING_VERSION,
    build_decision_snapshot,
    calibration_corpus_status,
    count_valid_p,
    record_decision_probability,
)

_AXES = {"EMS": 0.2, "EQS": 0.7, "DS": 0.6, "LS": 0.5, "EFS": 0.3, "APS": 0.6}


def test_decision_snapshot_persists_model_probability(tmp_path):
    db = tmp_path / "dps.db"
    assert count_valid_p(db) == 0
    snap = record_decision_probability(
        db_path=db, signal_id="SIG1", axes=_AXES,
        trade_id="T1", ticker="RELIANCE.NS", country="India",
        prediction_horizon_days=3.0,
    )
    assert snap["model_probability"] is not None
    assert count_valid_p(db) == 1


def test_model_probability_between_zero_and_one(tmp_path):
    snap = build_decision_snapshot(signal_id="SIG2", axes=_AXES)
    assert 0.0 <= snap["model_probability"] <= 1.0


def test_decision_snapshot_includes_scoring_version(tmp_path):
    snap = build_decision_snapshot(signal_id="SIG3", axes=_AXES)
    assert snap["scoring_version"] == SCORING_VERSION
    assert snap["model_version"] == MODEL_VERSION


def test_decision_snapshot_includes_prediction_horizon(tmp_path):
    snap = build_decision_snapshot(
        signal_id="SIG4", axes=_AXES, prediction_horizon_days=7.0,
    )
    assert snap["prediction_horizon_days"] == 7.0
    assert snap["target_event_definition"]


def test_calibration_corpus_counts_valid_p_after_decision(tmp_path):
    db = tmp_path / "dps.db"
    before = calibration_corpus_status(db)["n_valid_p"]
    record_decision_probability(db_path=db, signal_id="A", axes=_AXES)
    record_decision_probability(db_path=db, signal_id="B", axes=_AXES)
    after = calibration_corpus_status(db)["n_valid_p"]
    assert after == before + 2


def test_no_score_vector_records_null_probability_with_reason(tmp_path):
    # We never fabricate a probability when no score vector exists.
    db = tmp_path / "dps.db"
    snap = record_decision_probability(db_path=db, signal_id="EMPTY", axes=None)
    assert snap["model_probability"] is None
    assert snap["model_probability_reason"] == "NO_SCORE_VECTOR_AT_DECISION"
    # It must NOT count toward n_valid_p.
    assert count_valid_p(db) == 0


def test_uncalibrated_status_remains_until_gate_thresholds_met(tmp_path):
    db = tmp_path / "dps.db"
    for i in range(10):
        record_decision_probability(db_path=db, signal_id=f"S{i}", axes=_AXES)
    status = calibration_corpus_status(db)
    assert status["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert status["predictive_claim_allowed"] is False


def test_predictive_claim_allowed_false_when_n_below_200(tmp_path):
    db = tmp_path / "dps.db"
    record_decision_probability(db_path=db, signal_id="ONE", axes=_AXES)
    status = calibration_corpus_status(db)
    assert status["n_valid_p"] < 200
    assert status["predictive_claim_allowed"] is False


def test_decision_snapshot_carries_advisory_stamps(tmp_path):
    snap = build_decision_snapshot(signal_id="SAFE", axes=_AXES)
    assert snap["advisory_status"] == "ADVISORY_ONLY"
    assert snap["execution_gate"] == "LOCKED"
    assert snap["broker_api_called"] is False
    assert snap["ai_execution_count"] == 0
    assert snap["human_execution_required"] is True
