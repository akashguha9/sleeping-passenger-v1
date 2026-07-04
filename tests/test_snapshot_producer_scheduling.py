"""Tests: the daily loop produces timestamp-locked predictions (Feed-the-Loop).

Pins the sprint's compounding contract:
* the scheduler's run_once carries the producer step (score -> decision batch);
* snapshots are locked (INSERT OR IGNORE on snapshot_id — no overwrite);
* a duplicate same-day scheduler run is idempotent (SKIPPED_ALREADY_RAN_TODAY);
* no future leakage: entry-price evidence timestamp <= decision timestamp;
* matureable snapshots are detected only after the horizon elapses.
"""
from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

from scripts import nbi_scheduler
from scripts.decision_probability_snapshot import (
    TABLE,
    ensure_forward_columns,
    ensure_schema,
    persist_decision_snapshot,
    stamp_forward_contract,
)
from scripts.forward_outcome_maturity_scanner import scan_forward_outcome_maturity


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    ensure_schema(conn)
    ensure_forward_columns(conn)
    conn.commit()
    conn.close()
    return db


def _snapshot(snapshot_id: str = "DPS_test_1", **over) -> dict:
    base = {
        "snapshot_id": snapshot_id,
        "signal_id": "sig_test_1",
        "trade_id": None,
        "timestamp_utc": "2026-07-04T10:00:00Z",
        "ticker": "SPY",
        "country": None,
        "signal_class": None,
        "market_regime": None,
        "prediction_horizon_days": 5.0,
        "target_event_definition": "forward_return_ge_threshold",
        "model_probability": 0.55,
        "model_probability_reason": "OK",
        "score_vector_json": "{}",
        "model_version": "advisory-logistic-v1",
        "scoring_version": "v1",
    }
    base.update(over)
    return base


def test_scheduler_run_once_carries_producer_step() -> None:
    src = inspect.getsource(nbi_scheduler.run_once)
    assert "run_daily_decision_batch" in src, (
        "the daily loop lost the snapshot producer — N stops compounding"
    )
    assert "score_real_signal_events" in src
    assert "SKIPPED_ALREADY_RAN_TODAY" in src, "same-day idempotency guard missing"
    assert "producer_ok" in src, "producer must participate in scheduler health"


def test_snapshots_cannot_be_overwritten(tmp_path: Path) -> None:
    db = _db(tmp_path)
    persist_decision_snapshot(_snapshot(model_probability=0.55), db)
    # Same snapshot_id with a DIFFERENT probability: must be ignored, never
    # overwrite the locked prediction.
    persist_decision_snapshot(_snapshot(model_probability=0.99), db)
    conn = sqlite3.connect(db)
    rows = conn.execute(
        f"SELECT model_probability FROM {TABLE} WHERE snapshot_id='DPS_test_1'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert abs(rows[0][0] - 0.55) < 1e-9, "locked prediction was rewritten!"


def test_same_day_scheduler_rerun_guard_counts_today(tmp_path: Path) -> None:
    """The producer's idempotency guard: snapshots already locked today."""
    db = _db(tmp_path)
    persist_decision_snapshot(
        _snapshot(timestamp_utc="2026-07-04T08:30:00Z"), db
    )
    conn = sqlite3.connect(str(db))
    already = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE substr(timestamp_utc,1,10)=?",
        ("2026-07-04",),
    ).fetchone()[0]
    conn.close()
    assert already == 1  # the exact query the scheduler guard uses fires


def test_maturity_scanner_detects_pending_then_due(tmp_path: Path) -> None:
    db = _db(tmp_path)
    persist_decision_snapshot(_snapshot(snapshot_id="DPS_x"), db)
    stamped = stamp_forward_contract(
        db, "DPS_x",
        entry_price=500.0,
        entry_price_timestamp_utc="2026-07-03T16:00:00Z",
        entry_price_source="real_ohlcv_signal_events",
    )
    assert stamped.get("forward_outcome_eligible") in (1, True)
    pending = scan_forward_outcome_maturity(
        db_path=db, now_utc="2026-07-05T00:00:00Z"
    )
    assert pending["n_pending_horizon"] == 1
    assert pending["n_due_forward"] == 0
    due = scan_forward_outcome_maturity(
        db_path=db, now_utc="2026-07-10T00:00:00Z"
    )
    assert due["n_due_forward"] == 1


def test_no_future_leakage_in_locked_contract(tmp_path: Path) -> None:
    """Entry-price evidence must never postdate the decision timestamp."""
    db = _db(tmp_path)
    persist_decision_snapshot(_snapshot(snapshot_id="DPS_leak"), db)
    stamped = stamp_forward_contract(
        db, "DPS_leak",
        entry_price=500.0,
        entry_price_timestamp_utc="2026-07-05T16:00:00Z",  # AFTER decision ts
        entry_price_source="real_ohlcv_signal_events",
    )
    assert not stamped.get("forward_outcome_eligible"), (
        "a snapshot whose entry evidence postdates its decision timestamp "
        "must never be forward-outcome-eligible (future leakage)"
    )
