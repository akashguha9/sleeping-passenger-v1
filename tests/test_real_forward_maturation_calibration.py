"""Real-Forward Outcome Maturation Sprint — Phase 4 calibration tests.

Verifies the exact Brier / ECE / LogLoss math on the real-forward corpus, that
the first pairs never unlock a predictive claim below N=200, and that the
historical-proxy corpus is excluded from the real-forward metrics.

    Brier   = (1/N) Σ (p_i - y_i)^2
    LogLoss = -(1/N) Σ [y ln(p_clip) + (1-y) ln(1-p_clip)],  p_clip in [1e-15, 1-1e-15]
    ECE     = Σ_b (n_b/N) |acc(b) - conf(b)|
    CalibrationAllowed = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)
"""
from __future__ import annotations

import math
import sqlite3

import pytest

from scripts import persistence
from scripts.real_calibration_evidence import (
    build_calibration_evidence,
    compute_corpus_metrics,
    extract_datasets,
)
from scripts.decision_probability_snapshot import persist_decision_snapshot, TABLE
from scripts.outcome_labeling_flow import _ensure_outcome_columns


def _seed_pair(db, sid, p, y, *, kind="real_forward", excluded=0):
    snap = {
        "snapshot_id": sid, "signal_id": sid, "timestamp_utc": "2026-05-10T00:00:00Z",
        "ticker": "AAPL", "prediction_horizon_days": 5.0,
        "target_event_definition": "forward_return_ge_threshold",
        "model_probability": p, "model_probability_reason": "OK",
        "score_vector": {}, "model_version": "m", "scoring_version": "s",
    }
    persist_decision_snapshot(snap, db)
    conn = sqlite3.connect(str(db))
    try:
        _ensure_outcome_columns(conn)
        conn.execute(
            f"UPDATE {TABLE} SET outcome_label=?, is_real_outcome=1, outcome_kind=?,"
            f" horizon_elapsed=1, excluded_from_calibration=? WHERE snapshot_id=?",
            (y, kind, excluded, sid),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    persistence.init_schema(p)
    return p


def test_metrics_null_when_n_zero():
    m = compute_corpus_metrics([])
    assert m["n"] == 0
    assert m["brier"] is None
    assert m["ece"] is None
    assert m["log_loss"] is None
    assert m["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert m["predictive_claim_allowed"] is False


def test_metrics_compute_when_n_positive():
    m = compute_corpus_metrics([{"p": 0.6, "y": 1}, {"p": 0.4, "y": 0}])
    assert m["n"] == 2
    assert m["brier"] is not None
    assert m["predictive_claim_allowed"] is False  # N < 200


def test_first_pairs_do_not_unlock_predictive_claim(db):
    # Even a perfectly-calibrated tiny corpus cannot pass N>=200.
    _seed_pair(db, "s1", 0.99, 1)
    _seed_pair(db, "s2", 0.01, 0)
    ev = build_calibration_evidence(db)
    assert ev["n_real_forward"] == 2
    assert ev["predictive_claim_allowed"] is False


def test_n_below_200_status_detail_first_pairs(db):
    _seed_pair(db, "s1", 0.6, 1)
    ev = build_calibration_evidence(db)
    assert ev["status_detail"] == "FIRST_REAL_FORWARD_PAIRS_ATTACHED_BUT_BELOW_GATE"
    # N=0 reports the distinct "no pairs yet" detail.
    ev0 = build_calibration_evidence(tmp := db.parent / "empty.db")
    persistence.init_schema(tmp)
    assert build_calibration_evidence(tmp)["status_detail"] == "NO_REAL_FORWARD_PAIRS"


def test_brier_formula_exact():
    data = [{"p": 0.7, "y": 1}, {"p": 0.3, "y": 0}, {"p": 0.8, "y": 0}]
    expected = ((0.7 - 1) ** 2 + (0.3 - 0) ** 2 + (0.8 - 0) ** 2) / 3
    m = compute_corpus_metrics(data)
    assert m["brier"] == pytest.approx(expected, abs=1e-6)


def test_ece_formula_exact():
    # Two points in one 0.1-wide bin [0.6,0.7): conf=(0.6+0.65)/2, acc=(1+0)/2.
    data = [{"p": 0.6, "y": 1}, {"p": 0.65, "y": 0}]
    conf = (0.6 + 0.65) / 2
    acc = 0.5
    expected = abs(acc - conf)  # single occupied bin, n_b/N = 1
    m = compute_corpus_metrics(data, n_buckets=10)
    assert m["ece"] == pytest.approx(expected, abs=1e-6)


def test_logloss_clipping_exact():
    # Both points are confidently wrong: p=1.0/y=0 clips to 1-1e-15 so its loss
    # is -ln(1e-15); p=0.0/y=1 clips to 1e-15 so its loss is also -ln(1e-15).
    # Clipping keeps the loss finite (no infinity).
    data = [{"p": 1.0, "y": 0}, {"p": 0.0, "y": 1}]
    expected = -math.log(1e-15)  # mean of two identical clipped losses (~34.54)
    m = compute_corpus_metrics(data)
    assert math.isfinite(m["log_loss"])  # clipping prevents -inf
    assert m["log_loss"] == pytest.approx(expected, abs=1e-2)


def test_historical_proxy_excluded_from_real_forward_metrics(db):
    _seed_pair(db, "rf1", 0.6, 1, kind="real_forward")
    _seed_pair(db, "hp1", 0.5, 0, kind="historical_proxy")
    _seed_pair(db, "hp2", 0.5, 1, kind="historical_proxy")
    datasets = extract_datasets(db)
    assert len(datasets["real_forward"]) == 1
    assert len(datasets["historical_proxy"]) == 2
    ev = build_calibration_evidence(db)
    assert ev["n_real_forward"] == 1
    assert ev["n_historical_proxy"] == 2
