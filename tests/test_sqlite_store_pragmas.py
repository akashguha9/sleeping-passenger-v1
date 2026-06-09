"""F7 regression: the Streamlit SQLiteStore applies the safety pragmas.

Audit finding F7: ``src/storage/sqlite_store.py`` held one eternal
connection with zero pragmas — no busy_timeout (dashboard reads raced API
writes straight into ``database is locked``), no WAL, no foreign keys.
Also F7b: ``persistence._apply_pragmas`` swallowed pragma failures with
``except sqlite3.Error: pass`` — invisible loss of FK enforcement.

Contract:
* SQLiteStore's connection has busy_timeout > 0, journal_mode=WAL (or the
  configured mode), and foreign_keys=ON;
* a concurrent writer holding the DB does not instantly fail a store read;
* pragma application failures are logged at ERROR, never silently dropped.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from src.storage.sqlite_store import SQLiteStore


def test_store_applies_pragmas(tmp_path: Path):
    store = SQLiteStore(tmp_path / "store.db")
    conn = store.connection
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).upper()
    assert mode in {"WAL", "MEMORY"}  # MEMORY only for :memory: fixtures


def test_concurrent_write_does_not_instantly_lock_reads(tmp_path: Path):
    db = tmp_path / "busy.db"
    store = SQLiteStore(db)

    # Writer thread holds an exclusive transaction briefly.
    started = threading.Event()

    def writer():
        wconn = sqlite3.connect(str(db))
        wconn.execute("BEGIN IMMEDIATE")
        wconn.execute(
            "CREATE TABLE IF NOT EXISTS _busy_probe (x INTEGER)"
        )
        started.set()
        time.sleep(0.5)
        wconn.commit()
        wconn.close()

    t = threading.Thread(target=writer)
    t.start()
    started.wait(timeout=5)
    # WAL mode: reads proceed under a concurrent writer; without the F7
    # pragmas this raised "database is locked" immediately.
    snapshots = store.read_latest_market_snapshots()
    assert isinstance(snapshots, list)
    t.join()


def test_persistence_pragma_failure_is_logged(monkeypatch, caplog, tmp_path):
    from scripts import persistence

    class _FailingConn:
        def execute(self, sql, *a, **k):
            raise sqlite3.OperationalError("pragma refused")

    with caplog.at_level(logging.ERROR, logger="scripts.persistence"):
        persistence._apply_pragmas(_FailingConn())  # must not raise
    assert any("pragma" in r.message.lower() for r in caplog.records)
