"""Tests for ``scripts.db_integrity_check``.

Pin
---
- Missing DB returns ok=False with an operator action.
- Valid DB with full schema + backup -> ok=True.
- Missing journal columns -> FAIL.
- Corrupt file -> FAIL without raising.
- Backup openable check passes only on a real SQLite DB.
- Safety stamps locked.
- No DB writes (size/mtime unchanged).
- Stale backup (>7 days) triggers a WARN.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path

import pytest

from scripts import db_integrity_check as dic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_full_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT, ticker TEXT, side TEXT, quantity REAL, price REAL,
                executed_at TEXT, thesis TEXT, notes TEXT,
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
                process_error_notes TEXT DEFAULT '',
                mistake_tags TEXT DEFAULT '',
                lesson TEXT DEFAULT ''
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _create_min_schema_missing_columns(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT, ticker TEXT, side TEXT, quantity REAL, price REAL,
                executed_at TEXT
            );
            CREATE TABLE reconciliation_results (
                reconciliation_id TEXT PRIMARY KEY,
                trade_id TEXT, event_id TEXT, reconciled_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _write_backup(backup_dir: Path, label: str = "bk1") -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    bk = backup_dir / f"{label}.db"
    conn = sqlite3.connect(str(bk))
    try:
        conn.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY);")
        conn.commit()
    finally:
        conn.close()
    return bk


# ---------------------------------------------------------------------------
# Missing / corrupt DB
# ---------------------------------------------------------------------------


def test_missing_db_returns_fail(tmp_path):
    db = tmp_path / "absent.db"
    payload = dic.run_integrity_check(db, backup_dir=tmp_path / "backups")
    assert payload["ok"] is False
    assert "db_exists" in payload["failed_checks"]
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_permission"] is False


def test_corrupt_db_returns_fail_without_raising(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_bytes(b"this is not a sqlite database file at all")
    payload = dic.run_integrity_check(db, backup_dir=tmp_path / "backups")
    # Either db_openable fails or integrity_check fails; both are acceptable.
    assert payload["ok"] is False


# ---------------------------------------------------------------------------
# Valid DB
# ---------------------------------------------------------------------------


def test_full_schema_with_backup_passes(tmp_path):
    db = tmp_path / "full.db"
    _create_full_schema(db)
    bdir = tmp_path / "backups"
    _write_backup(bdir, "fresh")
    payload = dic.run_integrity_check(db, backup_dir=bdir)
    assert payload["ok"] is True, payload["check_results"]
    names = [c["name"] for c in payload["check_results"]]
    assert "manual_trades_journal_columns" in names
    assert "reconciliation_results_columns" in names
    assert "latest_backup_openable" in names
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["manual_trades_journal_columns"] == "PASS"
    assert statuses["reconciliation_results_columns"] == "PASS"
    assert statuses["latest_backup_openable"] == "PASS"


def test_missing_journal_columns_fails(tmp_path):
    db = tmp_path / "shallow.db"
    _create_min_schema_missing_columns(db)
    payload = dic.run_integrity_check(db, backup_dir=tmp_path / "backups")
    assert payload["ok"] is False
    assert "manual_trades_journal_columns" in payload["failed_checks"]
    assert "reconciliation_results_columns" in payload["failed_checks"]


def test_missing_required_table_fails(tmp_path):
    db = tmp_path / "no_tables.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    payload = dic.run_integrity_check(db, backup_dir=tmp_path / "backups")
    assert payload["ok"] is False
    assert "table:manual_trades" in payload["failed_checks"]
    assert "table:reconciliation_results" in payload["failed_checks"]


# ---------------------------------------------------------------------------
# Backup edge cases
# ---------------------------------------------------------------------------


def test_backup_dir_missing_is_warning_not_fail(tmp_path):
    db = tmp_path / "full.db"
    _create_full_schema(db)
    payload = dic.run_integrity_check(db, backup_dir=tmp_path / "absent_backups")
    # Backup absence is a warning, not a hard fail.
    assert "backup_dir_exists" in payload["warnings"]
    # Other checks still pass.
    assert "manual_trades_journal_columns" not in payload["failed_checks"]


def test_unopenable_backup_fails(tmp_path):
    db = tmp_path / "full.db"
    _create_full_schema(db)
    bdir = tmp_path / "backups"
    bdir.mkdir()
    junk = bdir / "junk.db"
    junk.write_bytes(b"not a sqlite file")
    payload = dic.run_integrity_check(db, backup_dir=bdir)
    assert "latest_backup_openable" in payload["failed_checks"]


def test_stale_backup_triggers_warning(tmp_path):
    db = tmp_path / "full.db"
    _create_full_schema(db)
    bdir = tmp_path / "backups"
    bk = _write_backup(bdir, "old")
    # Make the backup look 10 days old.
    old_time = (
        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=10)
    ).timestamp()
    import os
    os.utime(bk, (old_time, old_time))
    payload = dic.run_integrity_check(db, backup_dir=bdir)
    assert "backup_recency" in payload["warnings"]


# ---------------------------------------------------------------------------
# Read-only / safety
# ---------------------------------------------------------------------------


def test_no_db_writes(tmp_path):
    db = tmp_path / "full.db"
    _create_full_schema(db)
    size = db.stat().st_size
    mtime = db.stat().st_mtime
    dic.run_integrity_check(db, backup_dir=tmp_path / "backups")
    assert db.stat().st_size == size
    assert db.stat().st_mtime == mtime


def test_safety_stamps_locked(tmp_path):
    db = tmp_path / "full.db"
    _create_full_schema(db)
    payload = dic.run_integrity_check(db, backup_dir=tmp_path / "backups")
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_json(tmp_path, capsys):
    db = tmp_path / "full.db"
    _create_full_schema(db)
    bdir = tmp_path / "backups"
    _write_backup(bdir)
    rc = dic.main([
        "--db-path", str(db),
        "--backup-dir", str(bdir),
        "--json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "advisory_status" in out
    assert "ADVISORY_ONLY" in out


def test_cli_nonzero_on_missing_db(tmp_path):
    rc = dic.main(["--db-path", str(tmp_path / "absent.db")])
    assert rc != 0
