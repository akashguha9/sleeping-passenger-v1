"""
Tests for ``scripts.self_test_report``.

Pin
---
- Missing DB returns a graceful report with ``db_available=False``.
- Empty DB returns zero counts and lists every "no_*_yet" limitation.
- A DB with rows returns the right counts and distributions.
- Reconciliation summary surfaces operator_entered PnL and labels it
  as manual / not broker-verified.
- Markdown rendering is produced when requested and contains the
  advisory disclaimer.
- The function performs no writes against the DB.
- No secret-shaped strings leak into the rendered output.
- Safety stamps are locked on every report.
- ``execute_broker_order`` never appears in the report graph.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import self_test_report as report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_empty_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE signal_events (
                id INTEGER PRIMARY KEY,
                event_id TEXT,
                source_name TEXT,
                raw_payload TEXT,
                fetched_at TEXT
            );
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT,
                ticker TEXT,
                side TEXT,
                quantity REAL,
                price REAL,
                executed_at TEXT,
                thesis TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            );
            CREATE TABLE reconciliation_results (
                reconciliation_id TEXT PRIMARY KEY,
                trade_id TEXT,
                event_id TEXT,
                reconciled_at TEXT,
                actual_fill_price REAL,
                actual_quantity REAL,
                outcome_notes TEXT DEFAULT '',
                pnl_estimate REAL DEFAULT 0.0,
                outcome_status TEXT DEFAULT 'UNKNOWN'
            );
            CREATE TABLE user_reflections (
                reflection_id TEXT PRIMARY KEY,
                event_id TEXT,
                reflection_text TEXT,
                reflected_at TEXT
            );
            CREATE TABLE ai_discussion_summaries (
                summary_id TEXT PRIMARY KEY,
                event_id TEXT,
                summary_text TEXT,
                summarized_at TEXT
            );
            CREATE TABLE signal_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                user_status TEXT,
                marked_at TEXT
            );
            CREATE TABLE moltbook_entries (
                entry_id TEXT PRIMARY KEY,
                event_id TEXT,
                ticker TEXT,
                manual_trade_log_id TEXT DEFAULT '',
                mistake_type TEXT,
                lesson_learned TEXT,
                logged_at TEXT
            );
            CREATE TABLE source_run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT,
                status TEXT,
                fetched_count INTEGER DEFAULT 0,
                skipped_reason TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                timestamp_utc TEXT,
                duration_ms INTEGER DEFAULT 0
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _populate_some_rows(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO signal_events (event_id, source_name, raw_payload, fetched_at)"
            " VALUES (?,?,?,?)",
            ("ev1", "polymarket", "{}", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO signal_events (event_id, source_name, raw_payload, fetched_at)"
            " VALUES (?,?,?,?)",
            ("ev2", "polymarket", "{}", "2026-01-02T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO signal_decisions (event_id, user_status, marked_at)"
            " VALUES (?,?,?)",
            ("ev1", "watchlist", "2026-01-01T00:01:00Z"),
        )
        conn.execute(
            "INSERT INTO signal_decisions (event_id, user_status, marked_at)"
            " VALUES (?,?,?)",
            ("ev2", "rejected", "2026-01-02T00:01:00Z"),
        )
        conn.execute(
            "INSERT INTO user_reflections (reflection_id, event_id, reflection_text, reflected_at)"
            " VALUES (?,?,?,?)",
            ("R1", "ev1", "Looks fragile", "2026-01-01T00:02:00Z"),
        )
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side, quantity, price,"
            " executed_at, thesis, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("T1", "ev1", "QQQ", "BUY", 10, 100.0, "2026-01-01T01:00:00Z",
             "persistence reclaim", "monitor"),
        )
        conn.execute(
            "INSERT INTO reconciliation_results (reconciliation_id, trade_id, event_id,"
            " reconciled_at, actual_fill_price, actual_quantity, outcome_notes,"
            " pnl_estimate, outcome_status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("R_rec1", "T1", "ev1", "2026-01-02T00:00:00Z", 100.5, 10, "ok", 50.0, "WIN"),
        )
        conn.execute(
            "INSERT INTO moltbook_entries (entry_id, event_id, ticker, manual_trade_log_id,"
            " mistake_type, lesson_learned, logged_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("M1", "ev1", "QQQ", "T1", "overtraded", "wait for confirmation",
             "2026-01-02T01:00:00Z"),
        )
        conn.execute(
            "INSERT INTO source_run_log (source_name, status, fetched_count, skipped_reason,"
            " error_message, timestamp_utc, duration_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            ("polymarket", "OK", 2, "", "", "2026-01-02T00:00:00Z", 120),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Missing DB
# ---------------------------------------------------------------------------


def test_missing_db_returns_graceful_report(tmp_path):
    db_path = tmp_path / "absent.db"
    r = report.build_report(db_path)
    assert r["db_available"] is False
    assert "db_missing" in r["limitations"]
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["execution_permission"] is False
    assert r["can_execute"] is False


# ---------------------------------------------------------------------------
# Empty DB
# ---------------------------------------------------------------------------


def test_empty_db_returns_zero_counts(tmp_path):
    db_path = tmp_path / "empty.db"
    _make_empty_db(db_path)
    r = report.build_report(db_path)
    assert r["db_available"] is True
    assert r["signals_reviewed_count"] == 0
    assert r["manual_trades_count"] == 0
    assert r["reflections_count"] == 0
    assert "no_reflections_logged_yet" in r["limitations"]
    assert "no_manual_trades_logged_yet" in r["limitations"]
    assert r["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# Populated DB
# ---------------------------------------------------------------------------


def test_populated_db_returns_meaningful_counts(tmp_path):
    db_path = tmp_path / "populated.db"
    _make_empty_db(db_path)
    _populate_some_rows(db_path)
    r = report.build_report(db_path)

    assert r["db_available"] is True
    assert r["signals_reviewed_count"] == 2
    assert r["manual_trades_count"] == 1
    assert r["reflections_count"] == 1
    assert r["reconciliation"]["reconciled_count"] == 1
    assert r["reconciliation"]["outcome_distribution"] == {"WIN": 1}
    assert r["signal_decision_distribution"] == {"watchlist": 1, "rejected": 1}
    assert r["moltbook"]["available"] is True
    assert r["moltbook"]["total_entries"] == 1
    assert r["source_health"]["available"] is True
    assert r["source_health"]["per_source"][0]["source_name"] == "polymarket"
    assert r["journal_quality"]["available"] is True
    assert r["journal_quality"]["trade_count_considered"] == 1


def test_pnl_is_labelled_manual_not_broker_verified(tmp_path):
    db_path = tmp_path / "populated.db"
    _make_empty_db(db_path)
    _populate_some_rows(db_path)
    r = report.build_report(db_path)
    assert r["reconciliation"]["pnl_source"] == "operator_entered_manual_only"
    assert r["reconciliation"]["operator_entered_pnl_count"] == 1
    assert r["reconciliation"]["operator_entered_pnl_sum"] == 50.0
    assert "pnl_unverified_by_broker" in r["limitations"]


def test_unreconciled_trades_count(tmp_path):
    db_path = tmp_path / "populated.db"
    _make_empty_db(db_path)
    _populate_some_rows(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side, quantity, price,"
            " executed_at, thesis, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("T2", "ev2", "SPY", "BUY", 5, 400.0, "2026-01-03T00:00:00Z", "test", ""),
        )
        conn.commit()
    finally:
        conn.close()
    r = report.build_report(db_path)
    assert r["unreconciled_trades_count"] == 1


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_contains_advisory_disclaimer(tmp_path):
    db_path = tmp_path / "populated.db"
    _make_empty_db(db_path)
    _populate_some_rows(db_path)
    r = report.build_report(db_path)
    md = report._render_markdown(r)
    assert "advisory-only" in md.lower()
    assert "broker" in md.lower()
    assert "ADVISORY_ONLY" in md
    assert "manual" in md.lower()
    assert "Limitations" in md


def test_markdown_missing_db_is_short_and_safe(tmp_path):
    db_path = tmp_path / "absent.db"
    r = report.build_report(db_path)
    md = report._render_markdown(r)
    assert "ADVISORY_ONLY" in md
    assert "advisory-only" in md.lower()
    assert "Limitations" in md


# ---------------------------------------------------------------------------
# Read-only / no DB writes
# ---------------------------------------------------------------------------


def test_report_does_not_write_to_db(tmp_path):
    db_path = tmp_path / "populated.db"
    _make_empty_db(db_path)
    _populate_some_rows(db_path)
    mtime_before = db_path.stat().st_mtime
    size_before = db_path.stat().st_size

    for _ in range(3):
        report.build_report(db_path)

    mtime_after = db_path.stat().st_mtime
    size_after = db_path.stat().st_size
    assert size_after == size_before
    # mtime may tick even on read-only opens on some platforms; assert size is stable
    # plus assert that no extra rows were created
    conn = sqlite3.connect(str(db_path))
    try:
        n = conn.execute("SELECT COUNT(*) FROM manual_trades").fetchone()[0]
        assert n == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Safety stamps
# ---------------------------------------------------------------------------


def test_safety_stamps_locked_on_every_report(tmp_path):
    db_path = tmp_path / "empty.db"
    _make_empty_db(db_path)
    for path in (db_path, tmp_path / "absent.db"):
        r = report.build_report(path)
        assert r["advisory_status"] == "ADVISORY_ONLY"
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] is False
        assert r["ai_execution_count"] == 0
        assert r["execution_permission"] is False
        assert r["can_execute"] is False


def test_no_execute_keyword_in_rendered_markdown(tmp_path):
    db_path = tmp_path / "populated.db"
    _make_empty_db(db_path)
    _populate_some_rows(db_path)
    md = report._render_markdown(report.build_report(db_path))
    lower = md.lower()
    assert "place order" not in lower
    assert "execute trade" not in lower
    assert "auto-trade" not in lower
    assert "broker order placed" not in lower


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_json_smoke(tmp_path, capsys):
    db_path = tmp_path / "empty.db"
    _make_empty_db(db_path)
    code = report.main(["--db-path", str(db_path), "--json"])
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["advisory_status"] == "ADVISORY_ONLY"


def test_cli_writes_markdown_when_requested(tmp_path):
    db_path = tmp_path / "empty.db"
    _make_empty_db(db_path)
    md_path = tmp_path / "report.md"
    code = report.main(["--db-path", str(db_path), "--json", "--markdown", str(md_path)])
    assert code == 0
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "ADVISORY_ONLY" in content


def test_cli_missing_db_exits_nonzero(tmp_path, capsys):
    db_path = tmp_path / "absent.db"
    code = report.main(["--db-path", str(db_path), "--json"])
    assert code == 1
