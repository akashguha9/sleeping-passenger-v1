"""SEC-S5/S8 regression: trade-data artifacts are owner-only from creation.

Default umask left the journal DB, JSONL logs, backups, restores,
migration reports, and the rotating API log world-readable (0o644).
Every artifact writer now applies chmod 0o600 (POSIX; on Windows/NTFS
Python's chmod only toggles read-only — the documented icacls command
covers shared machines).
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from scripts import persistence
from scripts.backup_db import perform_backup, perform_restore
from scripts.runtime_common import append_jsonl, restrict_file_permissions

_POSIX = os.name == "posix"

pytestmark = pytest.mark.skipif(
    not _POSIX, reason="permission-bit assertions are POSIX-only"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_helper_restricts_to_owner_only(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("data")
    os.chmod(f, 0o644)
    assert restrict_file_permissions(f) is True
    assert _mode(f) == 0o600


def test_jsonl_journal_is_owner_only_on_create(tmp_path):
    log = tmp_path / "mt.jsonl"
    append_jsonl(log, {"trade_id": "MT_PERM", "thesis": "secret-ish"}, stamp=False)
    assert _mode(log) == 0o600
    # subsequent appends keep working
    append_jsonl(log, {"trade_id": "MT_PERM2"}, stamp=False)
    assert _mode(log) == 0o600


def test_new_db_is_owner_only(tmp_path):
    db = tmp_path / "perm.db"
    persistence.init_schema(db)
    assert _mode(db) == 0o600


def test_backup_and_restore_outputs_are_owner_only(tmp_path):
    db = tmp_path / "live.db"
    persistence.init_schema(db)
    backup = perform_backup(db, tmp_path / "backups", label="perm")
    assert backup["ok"] is True
    assert _mode(Path(backup["backup_path"])) == 0o600

    restored = tmp_path / "restored.db"
    result = perform_restore(Path(backup["backup_path"]), restored)
    assert result["ok"] is True
    assert _mode(restored) == 0o600


def test_migration_report_and_backup_are_owner_only(tmp_path):
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE manual_trades (trade_id TEXT PRIMARY KEY, event_id TEXT,"
        " ticker TEXT, side TEXT, quantity REAL NOT NULL, price REAL NOT NULL,"
        " executed_at TEXT);"
        "CREATE TABLE reconciliation_results (reconciliation_id TEXT PRIMARY KEY,"
        " trade_id TEXT, event_id TEXT, reconciled_at TEXT,"
        " actual_fill_price REAL NOT NULL, actual_quantity REAL NOT NULL,"
        " outcome_notes TEXT DEFAULT '', pnl_estimate REAL DEFAULT 0,"
        " outcome_status TEXT DEFAULT 'UNKNOWN');"
    )
    conn.execute(
        "INSERT INTO manual_trades (trade_id, event_id, ticker, side, quantity,"
        " price, executed_at) VALUES ('MT_P','E','A','BUY',1,2,'2026-01-01')"
    )
    conn.commit()
    conn.close()
    persistence.init_schema(db)  # triggers F3 rebuild + backup + report
    backups = list((tmp_path / "backups").glob("*.pre-f3-money.*.db"))
    reports = list((tmp_path / "backups").glob("f3_money_migration_report_*.json"))
    assert backups and reports
    assert _mode(backups[0]) == 0o600
    assert _mode(reports[0]) == 0o600


def test_rotating_log_file_is_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_LOG_DIR", str(tmp_path))
    import importlib

    from src.utils import logging_utils

    importlib.reload(logging_utils)
    logger = logging_utils.get_logger("perm_probe_logger")
    logger.error("probe")
    log_file = tmp_path / "api_server.log"
    assert log_file.exists()
    assert _mode(log_file) == 0o600
    importlib.reload(logging_utils)
