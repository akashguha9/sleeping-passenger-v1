"""Tests for the SQLite hardening pragmas applied to every connection.

What we pin down:
  * busy_timeout is applied to every fresh connection.
  * journal_mode WAL is applied unless explicitly overridden.
  * synchronous and foreign_keys pragmas are set.
  * get_db_status exposes pragma state without leaking absolute paths.
  * Backup script can still produce a valid copy after WAL is enabled
    (covered indirectly: import + apply pragmas + read pragma state).

These tests use ``tmp_path`` so they never touch ``runtime/mvp_local.db``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import persistence as p


def test_busy_timeout_pragma_is_applied(tmp_path):
    db = tmp_path / "hardening.db"
    p.init_schema(db)
    conn = p._get_conn(db)
    try:
        row = conn.execute("PRAGMA busy_timeout").fetchone()
        # row is a sqlite3.Row; access by index works for single-value pragmas
        timeout = row[0] if row is not None else None
    finally:
        conn.close()
    # Default is 5000ms; should be > 0 either way
    assert isinstance(timeout, int)
    assert timeout >= 1000


def test_wal_journal_mode_default(tmp_path, monkeypatch):
    """Default journal mode is WAL.  WAL produces -wal/-shm sidecars."""
    monkeypatch.delenv("MVP_SQLITE_JOURNAL_MODE", raising=False)
    db = tmp_path / "wal.db"
    p.init_schema(db)
    conn = p._get_conn(db)
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        mode = row[0] if row is not None else None
    finally:
        conn.close()
    assert isinstance(mode, str)
    assert mode.lower() == "wal"


def test_journal_mode_overridable(tmp_path, monkeypatch):
    """MVP_SQLITE_JOURNAL_MODE=DELETE switches back to rollback journal."""
    monkeypatch.setenv("MVP_SQLITE_JOURNAL_MODE", "DELETE")
    db = tmp_path / "delete_mode.db"
    p.init_schema(db)
    conn = p._get_conn(db)
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        mode = row[0] if row is not None else None
    finally:
        conn.close()
    assert isinstance(mode, str)
    assert mode.lower() == "delete"


def test_foreign_keys_enabled(tmp_path):
    db = tmp_path / "fk.db"
    p.init_schema(db)
    conn = p._get_conn(db)
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        fk = row[0] if row is not None else None
    finally:
        conn.close()
    assert fk == 1


def test_get_db_status_exposes_pragmas(tmp_path):
    db = tmp_path / "status.db"
    p.init_schema(db)
    status = p.get_db_status(db_path=db)
    assert "pragmas" in status
    pragmas = status["pragmas"]
    assert pragmas["busy_timeout_ms"] is not None
    assert isinstance(pragmas["busy_timeout_ms"], int)
    assert pragmas["journal_mode"] is not None
    # Default WAL flag should be true
    assert status["wal_enabled"] is True
    # Safety stamps preserved
    assert status["advisory_status"] == "ADVISORY_ONLY"
    assert status["ai_execution_count"] == 0
    assert status["broker_api_called"] is False


def test_get_db_status_db_path_does_not_leak_home(tmp_path):
    """The display path must NOT contain the user's home dir; falls back to
    just the filename when the DB lives outside the repo (e.g. tmp_path)."""
    db = tmp_path / "leak_check.db"
    p.init_schema(db)
    status = p.get_db_status(db_path=db)
    display = status["db_path"]
    # tmp_path is outside repo; should be the bare filename
    assert display == db.name
    # Should not be an absolute Windows or POSIX path
    assert ":\\" not in display
    assert not display.startswith("/")


def test_pragmas_do_not_break_init_or_writes(tmp_path):
    """Schema init + a normal insert still work after WAL pragmas applied."""
    db = tmp_path / "smoke.db"
    p.init_schema(db)
    p.insert_signal_decision("EVT_SMOKE", "watchlist", "2026-01-01T00:00:00Z", db_path=db)
    latest = p.get_latest_signal_decision("EVT_SMOKE", db_path=db)
    assert latest is not None
    assert latest["user_status"] == "watchlist"
    assert latest["advisory_status"] == "ADVISORY_ONLY"


def test_backup_still_works_with_wal(tmp_path):
    """After WAL is enabled, sqlite3.Connection.backup() still produces a valid copy."""
    from scripts.backup_db import perform_backup

    db = tmp_path / "wal_backup.db"
    p.init_schema(db)
    p.insert_signal_decision("EVT_BK", "watchlist", "2026-01-01T00:00:00Z", db_path=db)

    backup_dir = tmp_path / "backups"
    result = perform_backup(db_path=db, backup_dir=backup_dir)
    assert result["ok"] is True
    assert Path(result["backup_path"]).exists()
    # advisory stamps preserved by backup script
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
