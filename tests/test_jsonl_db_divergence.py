"""F10 regression: JSONL/DB journal divergence is detected and surfaced.

Audit finding F10: the JSONL append and the SQLite insert are two
unrelated writes; process death (or the pre-F1 silent failure) between
them produced a permanent split-brain the operator could never see.

Chosen remediation (minimum viable per the sprint spec): /health/full
compares the JSONL manual-trade line count against the DB row count for
the same provenance and reports the delta + a boolean flag.  The full
JSONL-as-WAL redesign is out of scope for this sprint; the comparison
makes the failure mode visible, which is the operational requirement.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import persistence


def _rebind_defaults(fn, new_db: Path):
    if fn.__defaults__:
        fn.__defaults__ = tuple(
            new_db if isinstance(d, Path) else d for d in fn.__defaults__
        )
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    import scripts.signal_inbox_api as api

    db = tmp_path / "div.db"
    persistence.init_schema(db)
    originals: dict = {}
    for name in ("init_schema", "_get_conn", "insert_manual_trade",
                 "get_manual_trade", "get_event_id_for_trade",
                 "count_manual_trades_by_provenance"):
        fn = getattr(persistence, name)
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    try:
        yield api, db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


def test_no_divergence_when_both_writes_land(isolated):
    api, db = isolated
    api.log_manual_trade(
        event_id="EVT_OK", ticker="BTC", side="BUY",
        quantity=1, price=100, thesis="ok",
    )
    d = api.journal_divergence()
    assert d["manual_trades_jsonl_lines"] == 1
    assert d["manual_trades_db_rows"] == 1
    assert d["journal_divergence_detected"] is False


def test_divergence_detected_when_db_write_lost(isolated, monkeypatch):
    import sqlite3 as _sq

    api, db = isolated

    def boom(*a, **k):
        raise _sq.OperationalError("locked")

    monkeypatch.setattr(persistence, "insert_manual_trade", boom)
    res = api.log_manual_trade(
        event_id="EVT_LOST", ticker="BTC", side="BUY",
        quantity=1, price=100, thesis="lost",
    )
    assert res["status"] == "error"  # F1: fail loud
    # JSONL row exists (written before the DB attempt) but the DB row
    # doesn't — divergence must be visible.
    d = api.journal_divergence()
    assert d["manual_trades_jsonl_lines"] == 1
    assert d["manual_trades_db_rows"] == 0
    assert d["journal_divergence_detected"] is True


def test_health_full_carries_divergence_fields(isolated):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    api, db = isolated
    client = TestClient(srv.app, raise_server_exceptions=False)
    h = client.get("/health/full").json()
    assert "journal_divergence_detected" in h
    assert "manual_trades_jsonl_lines" in h
    assert "manual_trades_db_rows" in h
