"""
Tests for the Moltbook learning backfill script.

The backfill scans existing reconciled trades and creates the Moltbook
learning entry that would have been written by the live bridge — for
STOP_HIT (XOM, CVX, TSM), PARTIAL_TP_HIT (ANET), PARTIAL_TP_LOGGED
(ASML), and CLOSED (GLD).  Idempotent.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import scripts.persistence as persistence
import scripts.moltbook_learning_backfill as backfill


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "backfill.db"
    persistence.init_schema(db)
    return db


def _insert_trade(
    db: Path,
    *,
    trade_id: str,
    ticker: str,
    event_id: str,
    side: str = "BUY",
    quantity: float = 1.0,
    price: float = 100.0,
    thesis: str = "Real operator thesis for the trade.",
    created_via: str = "manual_trade_log",
    executed_at: str = "2026-05-19T18:00:00+00:00",
) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO manual_trades"
            " (trade_id, event_id, ticker, side, quantity, price, executed_at,"
            "  thesis, created_via) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade_id, event_id, ticker, side, quantity, price, executed_at,
             thesis, created_via),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_reconciliation(
    db: Path,
    *,
    rec_id: str,
    trade_id: str,
    event_id: str,
    outcome_status: str,
    pnl_estimate: float,
    actual_fill_price: float = 0.0,
    actual_quantity: float = 1.0,
    extras: dict | None = None,
    reconciled_at: str = "2026-05-20T09:00:00+00:00",
) -> None:
    notes = "Advisory-only close reconciliation. No broker call by MVP."
    if extras is not None:
        notes += f"\n[reconciliation_extras={json.dumps(extras)}]"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO reconciliation_results"
            " (reconciliation_id, trade_id, event_id, reconciled_at,"
            "  actual_fill_price, actual_quantity, outcome_notes, pnl_estimate,"
            "  outcome_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rec_id, trade_id, event_id, reconciled_at, actual_fill_price,
             actual_quantity, notes, pnl_estimate, outcome_status),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db = _make_db(tmp_path)
    # XOM stop hit
    _insert_trade(db, trade_id="MT_XOM", ticker="XOM",
                  event_id="USER_XOM_LONG", price=105.0, quantity=10.0)
    _insert_reconciliation(
        db, rec_id="REC_XOM", trade_id="MT_XOM",
        event_id="USER_XOM_LONG", outcome_status="LOSS",
        pnl_estimate=-65.0, actual_fill_price=98.5, actual_quantity=10.0,
        extras={
            "post_trade_outcome": "STOPPED_OUT", "stop_loss_hit": True,
            "entry_price": 105.0, "actual_exit_price": 98.5,
            "exit_quantity": 10.0, "realized_pnl": -65.0,
            "stop_loss_price": 98.5,
        },
    )
    # CVX stop hit (bad-process)
    _insert_trade(db, trade_id="MT_CVX", ticker="CVX",
                  event_id="USER_CVX_LONG", price=150.0, quantity=5.0)
    _insert_reconciliation(
        db, rec_id="REC_CVX", trade_id="MT_CVX",
        event_id="USER_CVX_LONG", outcome_status="LOSS",
        pnl_estimate=-50.0, actual_fill_price=140.0, actual_quantity=5.0,
        extras={
            "post_trade_outcome": "STOPPED_OUT", "stop_loss_hit": True,
            "entry_price": 150.0, "actual_exit_price": 140.0,
            "exit_quantity": 5.0, "realized_pnl": -50.0,
            "mistake_tags": "oversized,fomo",
        },
    )
    # ANET partial TP hit
    _insert_trade(db, trade_id="MT_ANET", ticker="ANET",
                  event_id="USER_ANET_LONG", price=380.0, quantity=10.0)
    _insert_reconciliation(
        db, rec_id="REC_ANET", trade_id="MT_ANET",
        event_id="USER_ANET_LONG", outcome_status="UNKNOWN",
        pnl_estimate=280.0, actual_fill_price=420.0, actual_quantity=7.0,
        extras={
            "post_trade_outcome": "PARTIAL_TP",
            "entry_price": 380.0, "actual_exit_price": 420.0,
            "exit_quantity": 7.0, "realized_pnl": 280.0,
            "partial_take_profit_price": 420.0,
            "partial_take_profit_quantity": 7.0,
            "runner_quantity": 3.0,
        },
    )
    # ASML partial TP logged (plan only, no fill yet)
    _insert_trade(db, trade_id="MT_ASML", ticker="ASML",
                  event_id="USER_ASML_LONG", price=900.0, quantity=4.0)
    _insert_reconciliation(
        db, rec_id="REC_ASML", trade_id="MT_ASML",
        event_id="USER_ASML_LONG", outcome_status="UNKNOWN",
        pnl_estimate=0.0, actual_fill_price=0.0, actual_quantity=0.0,
        extras={
            "post_trade_outcome": "PARTIAL_TP",
            "entry_price": 900.0, "actual_exit_price": 0.0,
            "exit_quantity": 0.0, "realized_pnl": 0.0,
            "partial_take_profit_price": 980.0,
            "partial_take_profit_quantity": 2.8,
        },
    )
    # GLD closed (manual exit loss)
    _insert_trade(db, trade_id="MT_GLD", ticker="GLD",
                  event_id="USER_GLD_LONG", price=418.07, quantity=0.1114)
    _insert_reconciliation(
        db, rec_id="REC_GLD", trade_id="MT_GLD",
        event_id="USER_GLD_LONG", outcome_status="LOSS",
        pnl_estimate=-0.7319, actual_fill_price=411.5, actual_quantity=0.1114,
        extras={
            "post_trade_outcome": "MANUAL_EXIT",
            "entry_price": 418.07, "actual_exit_price": 411.5,
            "exit_quantity": 0.1114, "realized_pnl": -0.7319,
        },
    )
    # TSM closed (legacy LOSS status — derives to CLOSED_LOSS event)
    _insert_trade(db, trade_id="MT_TSM", ticker="TSM",
                  event_id="USER_TSM_LONG", price=393.26, quantity=2.0)
    _insert_reconciliation(
        db, rec_id="REC_TSM", trade_id="MT_TSM",
        event_id="USER_TSM_LONG", outcome_status="LOSS",
        pnl_estimate=-39.32, actual_fill_price=373.6, actual_quantity=2.0,
        extras={
            "post_trade_outcome": "CLOSED_LOSS",
            "entry_price": 393.26, "actual_exit_price": 373.6,
            "exit_quantity": 2.0, "realized_pnl": -39.32,
        },
    )
    return db


def test_backfill_dry_run_writes_nothing(seeded_db):
    report = backfill.backfill(seeded_db, write=False)
    assert report["candidates"] == 6
    assert report["created"] == 0
    assert report["updated"] == 0
    assert persistence.get_moltbook_entries(db_path=seeded_db) == []


def test_backfill_write_creates_one_entry_per_reconciliation(seeded_db):
    report = backfill.backfill(seeded_db, write=True)
    assert report["candidates"] == 6
    assert report["created"] == 6
    rows = persistence.get_moltbook_entries(db_path=seeded_db)
    by_ticker = {r["ticker"]: r for r in rows}
    assert set(by_ticker) == {"XOM", "CVX", "ANET", "ASML", "GLD", "TSM"}
    assert by_ticker["XOM"]["event_type"] == "STOP_LOSS_HIT"
    assert by_ticker["CVX"]["event_type"] == "STOP_LOSS_HIT"
    assert by_ticker["CVX"]["outcome_quality"] == "BAD_PROCESS_LOSS"
    assert by_ticker["ANET"]["event_type"] == "PARTIAL_TP_HIT"
    assert by_ticker["ASML"]["event_type"] == "PARTIAL_TP_LOGGED"
    assert by_ticker["GLD"]["event_type"] == "CLOSED"
    assert by_ticker["TSM"]["event_type"] == "CLOSED"


def test_backfill_is_idempotent(seeded_db):
    first = backfill.backfill(seeded_db, write=True)
    second = backfill.backfill(seeded_db, write=True)
    assert first["created"] == 6
    assert second["created"] == 0
    assert second["updated"] == 6
    rows = persistence.get_moltbook_entries(db_path=seeded_db)
    # Same 6 tickers, no duplicates.
    assert {r["ticker"] for r in rows} == {"XOM", "CVX", "ANET", "ASML", "GLD", "TSM"}
    assert len(rows) == 6


def test_backfill_subset_by_ticker(seeded_db):
    report = backfill.backfill(seeded_db, write=True, only_tickers=["XOM", "CVX"])
    assert report["created"] == 2
    rows = persistence.get_moltbook_entries(db_path=seeded_db)
    assert {r["ticker"] for r in rows} == {"XOM", "CVX"}


def test_backfill_safety_stamps(seeded_db):
    report = backfill.backfill(seeded_db, write=True)
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
