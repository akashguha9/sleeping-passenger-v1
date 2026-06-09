"""F6 regression: silent INSERT OR IGNORE drops become visible.

Audit finding F6: pervasive ``INSERT OR IGNORE`` meant a constraint-violating
row vanished with no rowcount check and no log; the duplicate-fingerprint
SELECT-then-INSERT raced (TOCTOU) without ``BEGIN IMMEDIATE``.

Contract:
* insert helpers return whether the row was actually written and count
  ignored duplicates in a module counter surfaced via /health/full;
* a WARNING is logged on every ignored insert;
* upsert_duplicate_fingerprint runs its check-then-act inside
  ``BEGIN IMMEDIATE``.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from scripts import persistence


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "ignored.db"
    persistence.init_schema(p)
    return p


@pytest.fixture(autouse=True)
def _reset_counter():
    persistence._reset_ignored_insert_count()
    yield
    persistence._reset_ignored_insert_count()


def _trade(db: Path, trade_id: str = "MT_DUP") -> None:
    persistence.insert_manual_trade(
        trade_id, "EVT_D", "AAPL", "BUY", 1, 100,
        "2026-01-01T00:00:00Z", "t", "", "human", db_path=db,
    )


def test_duplicate_manual_trade_is_counted_and_logged(db, caplog):
    _trade(db)
    with caplog.at_level(logging.WARNING, logger="scripts.persistence"):
        _trade(db)  # same PK → OR IGNORE drop
    assert persistence.ignored_insert_count() == 1
    assert any("ignored duplicate" in r.message for r in caplog.records)


def test_duplicate_reconciliation_is_counted(db):
    persistence.insert_reconciliation(
        "REC_D", "MT_DUP", "EVT_D", "2026-01-02T00:00:00Z",
        100, 1, "", 0, "WIN", db_path=db,
    )
    persistence.insert_reconciliation(
        "REC_D", "MT_DUP", "EVT_D", "2026-01-02T00:00:00Z",
        100, 1, "", 0, "WIN", db_path=db,
    )
    assert persistence.ignored_insert_count() == 1


def test_first_insert_does_not_count(db):
    _trade(db, "MT_FRESH")
    assert persistence.ignored_insert_count() == 0


def test_fingerprint_upsert_uses_begin_immediate():
    import inspect

    src = inspect.getsource(persistence.upsert_duplicate_fingerprint)
    assert "BEGIN IMMEDIATE" in src


def test_health_full_surfaces_ignored_inserts(db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    _trade(db)
    _trade(db)
    client = TestClient(srv.app, raise_server_exceptions=False)
    h = client.get("/health/full")
    assert h.status_code == 200
    assert h.json().get("db_ignored_duplicate_inserts_total", 0) >= 1
