"""Phase 5 — forward fields persist; migration is additive and non-destructive."""
from __future__ import annotations

import sqlite3

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_market_bar,
    seed_score_vector,
)
from scripts.decision_probability_snapshot import (
    TABLE,
    ensure_forward_columns,
    ensure_schema,
    persist_decision_snapshot,
)
from scripts.forward_snapshot_contract import REASON_MISSING_ENTRY_PRICE
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_NOW = "2026-05-10T00:00:00Z"
_FORWARD_COLS = {
    "target_return_threshold", "target_source", "entry_price",
    "entry_price_timestamp_utc", "entry_price_source", "horizon_close_utc",
    "forward_outcome_eligible", "forward_outcome_unavailable_reason",
}


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _cols(db):
    conn = sqlite3.connect(str(db))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
    finally:
        conn.close()


def _run(db, events):
    return run_daily_decision_batch(db_path=db, events=events, now_iso=_NOW, write=True)


def test_forward_columns_added_idempotently(db):
    conn = sqlite3.connect(str(db))
    try:
        ensure_forward_columns(conn)
        ensure_forward_columns(conn)  # second call must not raise
    finally:
        conn.close()
    assert _FORWARD_COLS.issubset(_cols(db))


def test_existing_snapshots_remain_readable(db):
    # Persist a legacy-style snapshot (no forward fields), then migrate.
    conn = sqlite3.connect(str(db))
    try:
        ensure_schema(conn)
    finally:
        conn.close()
    persist_decision_snapshot(
        {
            "snapshot_id": "LEGACY_1", "signal_id": "sig", "timestamp_utc": _NOW,
            "model_probability": 0.5, "model_probability_reason": "OK",
            "score_vector": {}, "model_version": "m", "scoring_version": "s",
        },
        db,
    )
    conn = sqlite3.connect(str(db))
    try:
        ensure_forward_columns(conn)
    finally:
        conn.close()
    snap = read_snapshot(db, signal_id="sig")
    assert snap is not None
    assert snap["snapshot_id"] == "LEGACY_1"
    # Old snapshot stays ineligible (forward fields are NULL), never crashes.
    assert snap["forward_outcome_eligible"] is None
    assert snap["entry_price"] is None


def test_new_snapshot_persists_ticker_horizon_target_entry_price(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["ticker"] == "AAPL"
    assert snap["prediction_horizon_days"] == 5
    assert snap["target_event_definition"] == "forward_return_ge_threshold"
    assert snap["entry_price"] == 190.0


def test_forward_outcome_eligible_persisted_true_when_complete(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["forward_outcome_eligible"] == 1
    assert snap["forward_outcome_unavailable_reason"] is None


def test_forward_outcome_unavailable_reason_persisted_when_missing_entry(db):
    seed_score_vector(db, event_id="ev1", ticker="NVDA")  # no price bars
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["forward_outcome_eligible"] == 0
    assert snap["forward_outcome_unavailable_reason"] == REASON_MISSING_ENTRY_PRICE


def test_persistence_preserves_advisory_safety_stamps(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["advisory_status"] == "ADVISORY_ONLY"
    assert snap["execution_gate"] == "LOCKED"
    assert snap["human_execution_required"] == 1


def test_no_schema_destructive_migration(db):
    # Capture the full column set before, then run a batch (which migrates).
    before = _cols(db)
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    _run(db, [event_row("ev1", payload={})])
    after = _cols(db)
    # Migration is purely additive: every prior column survives.
    assert before.issubset(after)
    assert _FORWARD_COLS.issubset(after)
