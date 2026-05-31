"""Tests — Real Evidence Sprint Phase 2: outcome labelling flow.

Proves the system can grow the REAL forward calibration corpus honestly:
  * a real resolved outcome attaches to a decision snapshot,
  * open trades and unelapsed horizons are rejected (never stored),
  * a missing decision-time probability is recorded but excluded with a reason,
  * historical-proxy pairs never count as real-forward calibration,
  * real-forward pairs increment only for valid (p, y),
  * advisory-only context survives,
  * stop-loss / target outcomes map to y in {0, 1},
  * exclusion reasons are reported.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import outcome_labeling_flow as flow
from scripts.decision_probability_snapshot import record_decision_probability


_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.5, "LS": 0.45, "EFS": 0.5, "APS": 0.5}


def _db(tmp_path: Path) -> Path:
    return tmp_path / "snap.db"


def _make_snapshot(db: Path, signal_id: str, *, with_p: bool = True) -> str:
    snap = record_decision_probability(
        db_path=db,
        signal_id=signal_id,
        axes=_AXES if with_p else None,
        ticker="RELIANCE.NS",
        country="India",
        prediction_horizon_days=10,
    )
    return snap["snapshot_id"]


# --- 1. attach a real outcome ---------------------------------------------
def test_attach_real_outcome_to_decision_snapshot(tmp_path):
    db = _db(tmp_path)
    sid = _make_snapshot(db, "sig-1")
    res = flow.attach_outcome(db, sid, 1, is_real_outcome=True)
    assert res["attached"] is True
    assert res["calibration_eligible"] is True
    assert res["excluded_from_calibration"] is False
    summary = flow.build_outcome_corpus_summary(db)
    assert summary["n_real_forward_pairs"] == 1
    assert summary["n_with_outcome"] == 1


# --- 2. open trade not eligible -------------------------------------------
def test_open_trade_not_calibration_eligible(tmp_path):
    db = _db(tmp_path)
    sid = _make_snapshot(db, "sig-open")
    res = flow.attach_outcome(db, sid, 1, trade_open=True)
    assert res["attached"] is False
    assert res["calibration_eligible"] is False
    assert res["reason"] == flow.REASON_OPEN_TRADE
    assert flow.build_outcome_corpus_summary(db)["n_real_forward_pairs"] == 0


# --- 3. unelapsed horizon not eligible ------------------------------------
def test_unelapsed_horizon_not_calibration_eligible(tmp_path):
    db = _db(tmp_path)
    sid = _make_snapshot(db, "sig-horizon")
    res = flow.attach_outcome(db, sid, 0, horizon_elapsed=False)
    assert res["attached"] is False
    assert res["reason"] == flow.REASON_HORIZON_NOT_ELAPSED
    assert flow.build_outcome_corpus_summary(db)["n_with_outcome"] == 0


# --- 4. missing probability excluded with reason --------------------------
def test_missing_probability_excluded_with_reason(tmp_path):
    db = _db(tmp_path)
    sid = _make_snapshot(db, "sig-nop", with_p=False)  # no axes -> p is None
    res = flow.attach_outcome(db, sid, 1, is_real_outcome=True)
    assert res["attached"] is True  # outcome recorded
    assert res["excluded_from_calibration"] is True
    assert res["calibration_eligible"] is False
    assert res["reason"] == flow.REASON_MISSING_PROBABILITY
    summary = flow.build_outcome_corpus_summary(db)
    assert summary["n_real_forward_pairs"] == 0
    assert summary["n_excluded"] == 1
    assert summary["exclusion_reasons"].get(flow.REASON_MISSING_PROBABILITY) == 1


# --- 5. historical proxy not counted as real forward ----------------------
def test_historical_proxy_not_counted_as_real_forward_calibration(tmp_path):
    db = _db(tmp_path)
    sid = _make_snapshot(db, "sig-proxy")
    res = flow.attach_outcome(
        db, sid, 1, is_real_outcome=True, outcome_kind=flow.HISTORICAL_PROXY
    )
    assert res["attached"] is True
    assert res["calibration_eligible"] is False  # proxy is never forward-eligible
    summary = flow.build_outcome_corpus_summary(db)
    assert summary["n_real_forward_pairs"] == 0
    assert summary["n_historical_proxy_pairs"] == 1
    assert summary["predictive_claim_allowed"] is False


# --- 6. real-forward pair count increments only for valid p and y ---------
def test_real_forward_pair_count_increments_only_for_valid_p_and_y(tmp_path):
    db = _db(tmp_path)
    good = _make_snapshot(db, "sig-good")
    nop = _make_snapshot(db, "sig-missing-p", with_p=False)
    flow.attach_outcome(db, good, 1, is_real_outcome=True)
    flow.attach_outcome(db, nop, 1, is_real_outcome=True)  # excluded, missing p
    # invalid label is rejected outright
    bad = flow.attach_outcome(db, good, 7, is_real_outcome=True)
    assert bad["reason"] == flow.REASON_INVALID_LABEL
    summary = flow.build_outcome_corpus_summary(db)
    assert summary["n_real_forward_pairs"] == 1
    assert summary["n_snapshots"] == 2


# --- 7. advisory-only context preserved -----------------------------------
def test_outcome_label_preserves_advisory_only_context(tmp_path):
    db = _db(tmp_path)
    sid = _make_snapshot(db, "sig-adv")
    res = flow.attach_outcome(db, sid, 0, is_real_outcome=True)
    assert res["advisory_status"] == "ADVISORY_ONLY"
    assert res["execution_gate"] == "LOCKED"
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0
    summary = flow.build_outcome_corpus_summary(db)
    assert summary["execution_gate"] == "LOCKED"


# --- 8/9. stop-loss / target mapping --------------------------------------
def test_stop_loss_outcome_maps_to_y_zero():
    assert flow.label_stop_loss_vs_target(stop_loss_hit=True, target_hit=False) == 0
    # via return formula: a loss below threshold -> 0
    assert flow.label_return_ge_threshold(100.0, 92.0, 0.05) == 0


def test_target_hit_outcome_maps_to_y_one():
    assert flow.label_stop_loss_vs_target(stop_loss_hit=False, target_hit=True) == 1
    assert flow.label_return_ge_threshold(100.0, 110.0, 0.05) == 1
    # ambiguous resolution is not labellable
    assert flow.label_stop_loss_vs_target(stop_loss_hit=True, target_hit=True) is None


# --- 10. exclusion reasons reported ---------------------------------------
def test_exclusion_reasons_are_reported(tmp_path):
    db = _db(tmp_path)
    s1 = _make_snapshot(db, "sig-x1", with_p=False)
    s2 = _make_snapshot(db, "sig-x2", with_p=False)
    flow.attach_outcome(db, s1, 1, is_real_outcome=True)
    flow.attach_outcome(db, s2, 0, is_real_outcome=True)
    summary = flow.build_outcome_corpus_summary(db)
    assert summary["n_excluded"] == 2
    assert summary["exclusion_reasons"][flow.REASON_MISSING_PROBABILITY] == 2


# --- bonus: fabricated outcomes are rejected ------------------------------
def test_fabricated_outcome_rejected(tmp_path):
    db = _db(tmp_path)
    sid = _make_snapshot(db, "sig-fake")
    res = flow.attach_outcome(db, sid, 1, is_real_outcome=False)
    assert res["attached"] is False
    assert res["reason"] == flow.REASON_NOT_REAL_OUTCOME


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
