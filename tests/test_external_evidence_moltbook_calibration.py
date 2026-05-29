"""External-evidence Moltbook calibration — outcome math + weight proofs.

Proves the post-outcome learning loop: closed trades link to their persisted
evidence snapshots, learning math is correct, weights stay conservative, the
loop is idempotent, and NOTHING affects real-money sizing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.external_evidence_persistence as eep
import scripts.external_evidence_moltbook_calibration as cal

GEN_AT = "2026-05-22T10:00:00+00:00"
RUN_DATE = "2026-05-22"

_NEW_MODULES = (eep, cal)


# --------------------------------------------------------------------- helpers
def _persist_snapshot(
    db: Path,
    *,
    signal_id="SIG1",
    ticker="AAPL",
    source_name="kronos",
    evidence_type="CANDLESTICK_FORECAST",
    route_decision="WATCH",
    status="ACCEPTED_EVIDENCE_ONLY",
    score_delta=0.12,
    alignment=1.0,
    confidence_calibrated=0.6,
    forecast_return_pct=5.0,
):
    item = {
        "source_name": source_name,
        "evidence_type": evidence_type,
        "status": status,
        "route_decision": route_decision,
        "execution_permission": "WATCH_ONLY",
        "score_delta": score_delta,
        "alignment_score": alignment,
        "reliability_weight": 0.8,
        "router_safety_multiplier": 0.25,
        "evidence_quality_multiplier": 0.7,
        "proof_status": "ACCEPTED_EVIDENCE_ONLY",
        "reason": "test",
        "payload_summary": {
            "KRONOS_STATUS": "SUPPORTIVE",
            "KRONOS_MODE": "stub_safe",
            "KRONOS_FORECAST_RETURN_PCT": forecast_return_pct,
            "KRONOS_CONFIDENCE_CALIBRATED": confidence_calibrated,
            "KRONOS_DOWNSIDE_PATH_RISK": 0.1,
        },
    }
    bundle = {
        "external_evidence_enabled": True,
        "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
        "external_evidence_items": [item],
        "generated_at_utc": GEN_AT,
    }
    return eep.persist_external_evidence_bundle(
        bundle,
        {"daily_run_id": RUN_DATE, "signal_id": signal_id, "ticker": ticker},
        db_path=db,
    )


def _trade(
    *,
    trade_id="T1",
    signal_id="SIG1",
    ticker="AAPL",
    entry_price=100.0,
    exit_price=110.0,
    closed=True,
    status=None,
    event_type="TP_HIT",
    exit_ts="2026-05-25T10:00:00+00:00",
):
    t = {
        "trade_id": trade_id,
        "signal_id": signal_id,
        "ticker": ticker,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "exit_timestamp_utc": exit_ts,
        "outcome_event_type": event_type,
    }
    if status is not None:
        t["status"] = status
    else:
        t["closed"] = closed
    return t


def _outcomes(db: Path):
    conn = eep._open(db)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM external_evidence_outcomes"
        )]
    finally:
        conn.close()


def _buckets(db: Path):
    conn = eep._open(db)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM external_evidence_calibration_buckets"
        )]
    finally:
        conn.close()


# ----------------------------------------------------------------------- test 8
def test_record_external_evidence_outcome_only_for_closed_trade(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _persist_snapshot(db, signal_id="SIG_OPEN")
    # Open trade → no learning.
    open_res = cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="SIG_OPEN", closed=False, status="OPEN"), db_path=db
    )
    assert open_res["status"] == cal.STATUS_NOT_FINAL
    assert open_res["records_created"] == 0

    # Closed trade with matching snapshot → RECORDED.
    closed_res = cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="SIG_OPEN", status="CLOSED"), db_path=db
    )
    assert closed_res["status"] == cal.STATUS_RECORDED
    assert closed_res["records_created"] == 1


# ----------------------------------------------------------------------- test 9
def test_external_evidence_outcome_math(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _persist_snapshot(db, signal_id="SIGM", forecast_return_pct=5.0, alignment=1.0)
    res = cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="SIGM", entry_price=100.0, exit_price=110.0), db_path=db
    )
    assert res["status"] == cal.STATUS_RECORDED
    rows = _outcomes(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["realized_return_pct"] == pytest.approx(10.0)
    assert row["actual_direction"] == "UP"
    assert row["forecast_direction"] == "UP"
    assert row["direction_correct"] == 1
    # |5 - 10| = 5
    assert row["forecast_error_pct"] == pytest.approx(5.0)


# ---------------------------------------------------------------------- test 10
def test_external_evidence_false_confidence_detection(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    # Positive evidence, calibrated confidence >= 0.50, but a losing outcome.
    _persist_snapshot(
        db,
        signal_id="SIGF",
        score_delta=0.3,
        confidence_calibrated=0.6,
        forecast_return_pct=2.0,
    )
    cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="SIGF", entry_price=100.0, exit_price=90.0), db_path=db
    )
    row = _outcomes(db)[0]
    assert row["false_confidence"] == 1
    assert row["evidence_harmed"] == 1


# ---------------------------------------------------------------------- test 11
def test_risk_reducer_helped_detection(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    # Negative evidence ahead of a loss → risk reducer helped.
    _persist_snapshot(
        db,
        signal_id="SIGR",
        score_delta=-0.4,
        alignment=-1.0,
        forecast_return_pct=-2.0,
        confidence_calibrated=0.55,
    )
    cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="SIGR", entry_price=100.0, exit_price=90.0), db_path=db
    )
    row = _outcomes(db)[0]
    assert row["risk_reducer_helped"] == 1
    assert row["evidence_helped"] == 1
    assert row["false_confidence"] == 0


# ---------------------------------------------------------------------- test 12
def test_calibration_bucket_small_sample_haircut() -> None:
    w = cal.compute_bucket_weights(n=10, h=8, x=0, f=0)
    assert w["sample_multiplier"] == 0.50
    # Conservatively capped: advisory_weight never exceeds raw_reliability.
    assert w["advisory_weight"] <= w["raw_reliability"]
    assert w["advisory_weight"] <= 1.25
    assert w["real_money_weight_allowed"] == 0
    assert w["real_money_sizing_impact"] == "PROHIBITED"


# ---------------------------------------------------------------------- test 13
def test_calibration_bucket_after_50_samples() -> None:
    w = cal.compute_bucket_weights(n=50, h=40, x=2, f=1)
    assert w["sample_multiplier"] == 1.00
    # Even at full sample multiplier, real-money influence stays off.
    assert w["real_money_weight_allowed"] == 0
    assert w["real_money_sizing_impact"] == "PROHIBITED"


# ---------------------------------------------------------------------- test 14
def test_outcome_learning_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _persist_snapshot(db, signal_id="SIGI")
    trade = _trade(signal_id="SIGI", status="CLOSED")
    r1 = cal.record_external_evidence_outcome_for_trade(trade, db_path=db)
    r2 = cal.record_external_evidence_outcome_for_trade(trade, db_path=db)
    assert r1["records_created"] == 1
    assert r2["records_created"] == 0
    assert len(_outcomes(db)) == 1


# ---------------------------------------------------------------------- test 15
def test_no_learning_for_unmatched_evidence(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    # No snapshot for this signal/ticker.
    res = cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="NOPE", ticker="ZZZZ", status="CLOSED"), db_path=db
    )
    assert res["status"] == cal.STATUS_NO_MATCH
    assert res["records_created"] == 0
    assert len(_outcomes(db)) == 0


# ----------------------------------------------------- insufficient-data guard
def test_record_insufficient_outcome_data(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _persist_snapshot(db, signal_id="SIGD")
    res = cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="SIGD", entry_price=None, exit_price=None, status="CLOSED"),
        db_path=db,
    )
    assert res["status"] == cal.STATUS_INSUFFICIENT


# ---------------------------------------------------------------------- test 19
def test_external_evidence_calibration_no_real_money_sizing(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _persist_snapshot(db, signal_id="SIGRM")
    res = cal.record_external_evidence_outcome_for_trade(
        _trade(signal_id="SIGRM", status="CLOSED"), db_path=db
    )
    assert res["real_money_sizing_impact"] == "PROHIBITED"
    for row in _outcomes(db):
        assert row["real_money_sizing_impact"] == "PROHIBITED"
    for b in _buckets(db):
        assert b["real_money_sizing_impact"] == "PROHIBITED"
        assert b["real_money_weight_allowed"] == 0


# ---------------------------------------------------------------------- test 20
def test_external_evidence_no_execution_language() -> None:
    import pathlib

    forbidden = (
        "place_order(",
        "submit_order(",
        "execute_trade(",
        "broker_execute",
        "auto_execute",
        "import alpaca",
        "import ib_insync",
        "import ccxt",
    )
    for mod in _NEW_MODULES:
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in src, (mod.__name__, token)
        # The advisory invariant must be present in source.
        assert "real_money_sizing_impact" in src
