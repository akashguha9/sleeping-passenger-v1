"""F9 + F12 regression: schema migrations fail loud; identifiers allowlisted.

F9: ``_additive_migrations`` swallowed ``sqlite3.OperationalError`` per
column — a failed ALTER left code assuming a column that doesn't exist,
surfacing later as a cryptic "no such column" at insert time.

Contract: a failed ALTER raises RuntimeError naming every failed
migration, and each successful ALTER is verified against table_info.

F12: dynamic ``PRAGMA table_info({table})`` / ``ALTER TABLE {table}``
interpolation now asserts identifiers against an allowlist regex so a
future refactor can never feed hostile names into the f-strings.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import persistence


def test_failed_alter_raises_with_details(tmp_path, monkeypatch):
    db = tmp_path / "mig.db"
    # Create a minimal manual_trades missing the leverage column so the
    # additive migration has work to do.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE manual_trades (trade_id TEXT PRIMARY KEY,"
        " event_id TEXT, ticker TEXT, side TEXT, quantity TEXT,"
        " price TEXT, executed_at TEXT)"
    )
    conn.commit()

    real_execute = sqlite3.Connection.execute

    class _Boom(sqlite3.OperationalError):
        pass

    def failing_execute(self, sql, *args, **kwargs):
        if isinstance(sql, str) and sql.strip().upper().startswith("ALTER TABLE"):
            raise _Boom("disk I/O error")
        return real_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(sqlite3.Connection, "execute", failing_execute)
    with pytest.raises(RuntimeError) as exc:
        persistence._additive_migrations(conn)
    msg = str(exc.value)
    assert "manual_trades" in msg
    assert "leverage" in msg
    monkeypatch.undo()
    conn.close()


def test_successful_migration_still_works(tmp_path):
    db = tmp_path / "ok.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE manual_trades (trade_id TEXT PRIMARY KEY,"
        " event_id TEXT, ticker TEXT, side TEXT, quantity TEXT,"
        " price TEXT, executed_at TEXT)"
    )
    conn.commit()
    persistence._additive_migrations(conn)  # must not raise
    cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
    assert "leverage" in cols
    assert "trade_mode" in cols
    conn.close()


def test_identifier_allowlist_rejects_hostile_names():
    with pytest.raises(ValueError):
        persistence._safe_identifier("manual_trades; DROP TABLE x--")
    with pytest.raises(ValueError):
        persistence._safe_identifier("")
    assert persistence._safe_identifier("manual_trades") == "manual_trades"
    assert persistence._safe_identifier("leverage_ceiling") == "leverage_ceiling"
