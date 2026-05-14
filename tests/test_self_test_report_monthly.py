"""Tests for self_test_report's monthly-window mode + process quality + queue embed.

Pin
---
- --days filters period_payload counts to only trades/recons in the window.
- --period monthly works the same as --days 30.
- include_reconciliation_queue embeds the queue summary in the report.
- process_quality summary appears when reconciled trades exist.
- Advisory safety stamps locked.
- No DB writes.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path

import pytest

from scripts import self_test_report as report


def _create_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE signal_events (
                id INTEGER PRIMARY KEY, event_id TEXT, source_name TEXT,
                raw_payload TEXT, fetched_at TEXT
            );
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT, ticker TEXT, side TEXT, quantity REAL, price REAL,
                executed_at TEXT, thesis TEXT DEFAULT '', notes TEXT DEFAULT '',
                invalidation_level TEXT DEFAULT '',
                expected_horizon TEXT DEFAULT '',
                risk_reason TEXT DEFAULT '',
                entry_reason TEXT DEFAULT '',
                exit_plan TEXT DEFAULT '',
                confidence_before REAL,
                emotional_state TEXT DEFAULT '',
                mistake_tags TEXT DEFAULT '',
                lesson TEXT DEFAULT ''
            );
            CREATE TABLE reconciliation_results (
                reconciliation_id TEXT PRIMARY KEY,
                trade_id TEXT, event_id TEXT,
                reconciled_at TEXT, actual_fill_price REAL, actual_quantity REAL,
                outcome_notes TEXT DEFAULT '', pnl_estimate REAL DEFAULT 0.0,
                outcome_status TEXT DEFAULT 'UNKNOWN',
                outcome_quality TEXT DEFAULT '',
                process_error TEXT DEFAULT '',
                process_error_notes TEXT DEFAULT ''
            );
            CREATE TABLE user_reflections (
                reflection_id TEXT PRIMARY KEY, event_id TEXT,
                reflection_text TEXT, reflected_at TEXT
            );
            CREATE TABLE ai_discussion_summaries (
                summary_id TEXT PRIMARY KEY, event_id TEXT,
                summary_text TEXT, summarized_at TEXT
            );
            CREATE TABLE signal_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT, user_status TEXT, marked_at TEXT
            );
            CREATE TABLE moltbook_entries (
                entry_id TEXT PRIMARY KEY, event_id TEXT, ticker TEXT,
                manual_trade_log_id TEXT DEFAULT '', mistake_type TEXT,
                lesson_learned TEXT, logged_at TEXT
            );
            CREATE TABLE source_run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT, status TEXT, fetched_count INTEGER DEFAULT 0,
                skipped_reason TEXT DEFAULT '', error_message TEXT DEFAULT '',
                timestamp_utc TEXT, duration_ms INTEGER DEFAULT 0
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_trade(
    db_path: Path, trade_id: str, executed_at: str, *, ticker: str = "QQQ",
    thesis: str = "ok", invalidation: str = "X", horizon: str = "1w",
    risk: str = "1R", entry: str = "retest", exit_plan: str = "scale out",
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side, quantity, price,"
            " executed_at, thesis, invalidation_level, expected_horizon,"
            " risk_reason, entry_reason, exit_plan)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (trade_id, f"EV_{trade_id}", ticker, "BUY", 10, 100.0,
             executed_at, thesis, invalidation, horizon, risk, entry, exit_plan),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_recon(
    db_path: Path, trade_id: str, reconciled_at: str, outcome: str = "WIN",
    process_error: str = "",
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO reconciliation_results (reconciliation_id, trade_id, event_id,"
            " reconciled_at, actual_fill_price, actual_quantity, outcome_notes,"
            " pnl_estimate, outcome_status, outcome_quality, process_error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"R_{trade_id}", trade_id, f"EV_{trade_id}", reconciled_at,
             100.0, 10, "ok", 50.0, outcome, "", process_error),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Period window
# ---------------------------------------------------------------------------


def test_days_window_filters_period_counts(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    # In window
    _insert_trade(db, "T_IN", executed_at="2026-05-10T00:00:00Z")
    _insert_recon(db, "T_IN", reconciled_at="2026-05-11T00:00:00Z")
    # Out of window
    _insert_trade(db, "T_OLD", executed_at="2026-01-01T00:00:00Z")
    _insert_recon(db, "T_OLD", reconciled_at="2026-01-02T00:00:00Z")
    now = _dt.datetime(2026, 5, 14, tzinfo=_dt.timezone.utc)
    r = report.build_report(db, days=30, now=now)
    assert "period" in r
    p = r["period"]
    assert p["trades_logged_in_period"] == 1
    assert p["reconciled_in_period"] == 1
    assert p["days"] == 30
    # Whole-DB counters unchanged.
    assert r["manual_trades_count"] == 2
    assert r["reconciliation"]["reconciled_count"] == 2


def test_period_monthly_alias(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    _insert_trade(db, "T1", executed_at="2026-05-10T00:00:00Z")
    now = _dt.datetime(2026, 5, 14, tzinfo=_dt.timezone.utc)
    r = report.build_report(db, period="monthly", now=now)
    assert r["period"]["days"] == 30
    assert r["period"]["trades_logged_in_period"] == 1


def test_no_period_means_no_period_block(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    _insert_trade(db, "T1", executed_at="2026-05-10T00:00:00Z")
    r = report.build_report(db)
    assert "period" not in r


# ---------------------------------------------------------------------------
# Reconciliation queue embed
# ---------------------------------------------------------------------------


def test_include_reconciliation_queue(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    _insert_trade(db, "T1", executed_at="2026-05-10T00:00:00Z")
    r = report.build_report(db, include_reconciliation_queue=True)
    assert "reconciliation_queue" in r
    summary = r["reconciliation_queue"]["summary"]
    assert summary["unreconciled_count"] == 1
    # Embedded items list is bounded by the helper's limit=50.
    assert len(r["reconciliation_queue"]["items"]) == 1


# ---------------------------------------------------------------------------
# Process quality
# ---------------------------------------------------------------------------


def test_process_quality_summary_when_reconciled(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    _insert_trade(db, "T_WIN", executed_at="2026-05-10T00:00:00Z")
    _insert_recon(db, "T_WIN", "2026-05-11T00:00:00Z", outcome="WIN")
    _insert_trade(db, "T_LOSS", executed_at="2026-05-10T00:00:00Z")
    _insert_recon(db, "T_LOSS", "2026-05-11T00:00:00Z", outcome="LOSS")
    r = report.build_report(db)
    pq = r["process_quality"]
    assert pq["available"] is True
    assert pq["trade_count"] == 2
    assert pq["classified_count"] == 2


def test_process_quality_unavailable_without_recon_table(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    # Drop reconciliation_results to simulate older DB.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("DROP TABLE reconciliation_results")
        conn.commit()
    finally:
        conn.close()
    r = report.build_report(db)
    assert r["process_quality"]["available"] is False


# ---------------------------------------------------------------------------
# Safety stamps locked across new shapes
# ---------------------------------------------------------------------------


def test_safety_stamps_locked_with_period_and_queue(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    _insert_trade(db, "T1", executed_at="2026-05-10T00:00:00Z")
    now = _dt.datetime(2026, 5, 14, tzinfo=_dt.timezone.utc)
    r = report.build_report(
        db, days=30, include_reconciliation_queue=True, now=now,
    )
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] is False
    assert r["ai_execution_count"] == 0
    assert r["execution_permission"] is False
    assert r["can_execute"] is False


def test_no_db_writes_in_period_mode(tmp_path):
    db = tmp_path / "p.db"
    _create_schema(db)
    _insert_trade(db, "T1", executed_at="2026-05-10T00:00:00Z")
    size = db.stat().st_size
    mtime = db.stat().st_mtime
    report.build_report(db, days=30, include_reconciliation_queue=True)
    assert db.stat().st_size == size
    assert db.stat().st_mtime == mtime
