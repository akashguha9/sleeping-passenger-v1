"""Close the Outcome Loop Sprint — Phase 3 tests.

Brier / ECE / LogLoss are computed honestly over the REAL-FORWARD corpus, the
calibration gate requires all three of (N>=200, Brier<=0.25, ECE<=0.10), and the
historical-proxy corpus can NEVER unlock a predictive claim.  Excluded outcomes
are never counted.  Metrics are persisted to the evidence JSON.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts import persistence
from scripts.decision_probability_snapshot import (
    build_decision_snapshot,
    persist_decision_snapshot,
)
from scripts.outcome_labeling_flow import REAL_FORWARD, HISTORICAL_PROXY, attach_outcome
from scripts.snapshot_calibration_bridge import compute_brier_ece
from scripts.real_calibration_evidence import (
    build_calibration_evidence,
    compute_corpus_metrics,
    extract_datasets,
    write_evidence,
)

_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.45, "LS": 0.5, "EFS": 0.5, "APS": 0.5}


def _seed_pair(
    db: Path,
    sid: str,
    p: float,
    y: int,
    *,
    kind: str = REAL_FORWARD,
    is_real: bool = True,
) -> str:
    """Persist a snapshot with an explicit probability then attach outcome y."""
    snap = build_decision_snapshot(signal_id=sid, axes=_AXES, ticker="SPY",
                                   prediction_horizon_days=5.0,
                                   timestamp_utc="2026-01-05T00:00:00Z")
    # Override the model_probability to the exact p we want to test the math on.
    snap["model_probability"] = float(p)
    persist_decision_snapshot(snap, db)
    # build_decision_snapshot computes p from axes; force the stored value.
    import sqlite3
    from scripts.decision_probability_snapshot import TABLE
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(f"UPDATE {TABLE} SET model_probability=? WHERE snapshot_id=?",
                     (float(p), snap["snapshot_id"]))
        conn.commit()
    finally:
        conn.close()
    attach_outcome(db, snap["snapshot_id"], int(y), outcome_kind=kind,
                   is_real_outcome=is_real, horizon_elapsed=True,
                   now_utc="2026-05-31T00:00:00Z")
    return snap["snapshot_id"]


# --- 1. Brier from real-forward pairs ------------------------------------- #

def test_brier_computed_from_real_forward_pairs(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_pair(db, "A", 0.0, 0)
    _seed_pair(db, "B", 1.0, 1)
    ev = build_calibration_evidence(db)
    assert ev["n_real_forward"] == 2
    # Perfect predictions -> Brier 0.
    assert ev["brier_real_forward"] == pytest.approx(0.0, abs=1e-9)


# --- 2. ECE from real-forward pairs --------------------------------------- #

def test_ece_computed_from_real_forward_pairs(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_pair(db, "A", 0.0, 0)
    _seed_pair(db, "B", 1.0, 1)
    ev = build_calibration_evidence(db)
    assert ev["ece_real_forward"] == pytest.approx(0.0, abs=1e-9)


# --- 3. LogLoss computed and clipped -------------------------------------- #

def test_logloss_computed_and_clipped(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    # p=1.0 with y=0 would be -ln(0)=inf without clipping; clipping keeps it finite.
    _seed_pair(db, "A", 1.0, 0)
    _seed_pair(db, "B", 0.0, 1)
    ev = build_calibration_evidence(db)
    ll = ev["logloss_real_forward"]
    assert ll is not None and math.isfinite(ll)
    # With 1e-15 clipping each term is ~ -ln(1e-15) ≈ 34.54.
    assert ll > 30.0


# --- 4. N<200 keeps the predictive claim locked --------------------------- #

def test_n_below_200_keeps_predictive_claim_locked(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_pair(db, "A", 0.0, 0)
    _seed_pair(db, "B", 1.0, 1)
    ev = build_calibration_evidence(db)
    # Below N=200 the status is a locked tier (TOO_FEW_OUTCOMES /
    # INSUFFICIENT_EVIDENCE) and the predictive claim must stay locked.
    assert ev["calibration_status"] != "MEASURED"
    assert ev["predictive_claim_allowed"] is False


# --- 5. Gate requires N AND Brier AND ECE all pass ------------------------ #

def test_gate_requires_n_brier_and_ece_all_pass():
    # 200 perfectly-calibrated pairs -> all three thresholds clear -> unlocked.
    perfect = ([{"p": 1.0, "y": 1}] * 100) + ([{"p": 0.0, "y": 0}] * 100)
    m_perfect = compute_corpus_metrics(perfect)
    assert m_perfect["n"] == 200
    assert m_perfect["predictive_claim_allowed"] is True

    # 200 pairs but badly miscalibrated -> Brier/ECE fail -> stays locked.
    bad = ([{"p": 1.0, "y": 0}] * 100) + ([{"p": 0.0, "y": 1}] * 100)
    m_bad = compute_corpus_metrics(bad)
    assert m_bad["n"] == 200
    assert m_bad["brier"] > 0.25
    assert m_bad["predictive_claim_allowed"] is False

    # Fewer than 200 perfect pairs -> sample-size floor keeps it locked.
    small = ([{"p": 1.0, "y": 1}] * 10) + ([{"p": 0.0, "y": 0}] * 10)
    assert compute_corpus_metrics(small)["predictive_claim_allowed"] is False


# --- 6. Historical proxy can never unlock the gate ------------------------ #

def test_historical_proxy_cannot_unlock_gate(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    # 250 perfectly-calibrated PROXY pairs — would clear the math, but proxy
    # never gates.
    for i in range(125):
        _seed_pair(db, f"P1_{i}", 1.0, 1, kind=HISTORICAL_PROXY)
        _seed_pair(db, f"P0_{i}", 0.0, 0, kind=HISTORICAL_PROXY)
    ev = build_calibration_evidence(db)
    assert ev["n_historical_proxy"] == 250
    assert ev["n_real_forward"] == 0
    assert ev["predictive_claim_allowed"] is False
    assert ev["calibration_status"] == "INSUFFICIENT_EVIDENCE"


# --- 7. Excluded outcomes are not counted --------------------------------- #

def test_excluded_outcomes_not_counted(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    # A snapshot with NO probability -> attach marks it excluded_from_calibration.
    snap = build_decision_snapshot(signal_id="NOP", axes={}, ticker="SPY",
                                   prediction_horizon_days=5.0,
                                   timestamp_utc="2026-01-05T00:00:00Z")
    persist_decision_snapshot(snap, db)
    res = attach_outcome(db, snap["snapshot_id"], 1, outcome_kind=REAL_FORWARD,
                         is_real_outcome=True, horizon_elapsed=True)
    assert res["excluded_from_calibration"] is True
    assert extract_datasets(db)["real_forward"] == []
    assert build_calibration_evidence(db)["n_real_forward"] == 0


# --- 8. Metrics written to the evidence JSON ------------------------------ #

def test_real_forward_metrics_written_to_evidence_json(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_pair(db, "A", 0.0, 0)
    _seed_pair(db, "B", 1.0, 1)
    ev = build_calibration_evidence(db)
    out = tmp_path / "calibration_evidence.json"
    write_evidence(ev, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    for key in ("n_real_forward", "brier_real_forward", "ece_real_forward",
                "logloss_real_forward", "calibration_status",
                "predictive_claim_allowed"):
        assert key in loaded
    assert loaded["predictive_claim_allowed"] is False
    assert loaded["execution_gate"] == "LOCKED"


# --- direct clipping unit ------------------------------------------------- #

def test_compute_brier_ece_clips_logloss_directly():
    m = compute_brier_ece([{"p": 1.0, "y": 0}, {"p": 0.0, "y": 1}])
    assert math.isfinite(m["log_loss"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
