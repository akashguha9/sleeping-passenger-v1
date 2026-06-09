"""F1/F2 regression: journal DB write failures must FAIL LOUD, never silent.

Audit findings F1/F2: ``log_manual_trade``, ``reconcile_trade`` and
``cancel_manual_trade_log`` wrapped their SQLite writes in
``except Exception: pass`` and returned success-shaped responses.  A locked
or read-only database meant the operator saw "logged" while the canonical
store never received the row — silently corrupting the calibration dataset.

Contract under test:
* a raising DB write returns ``status="error"`` / ``reason="db_write_failed"``
  from the service function (never ``status="logged"``);
* the API layer surfaces it as HTTP 500 with the full advisory stamp block
  (``execution_gate=LOCKED``, ``broker_api_called=False``);
* the failure increments the journal write-failure counter so
  ``/health/full`` reports ``degraded=True``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import persistence
from scripts import signal_inbox_api as api


def _boom(*_args, **_kwargs):
    raise sqlite3.OperationalError("database is locked")


def _rebind_defaults(fn, new_db: Path):
    """Swap the def-time-bound ``db_path=DB_PATH`` default for ``new_db``."""
    if fn.__defaults__:
        fn.__defaults__ = tuple(
            new_db if isinstance(d, Path) else d for d in fn.__defaults__
        )
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


_HELPERS = [
    "init_schema",
    "_get_conn",
    "insert_manual_trade",
    "get_manual_trade",
    "get_manual_trade_raw_broker_flag",
    "cancel_manual_trade",
    "get_trades_for_event",
    "get_event_id_for_trade",
    "get_all_manual_trades",
    "insert_reconciliation",
    "get_reconciliations_for_trade",
    "get_all_reconciliations",
]


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "fail_loud.db"
    persistence.init_schema(db)
    originals: dict = {}
    for name in _HELPERS:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(
        api, "MANUAL_TRADE_CANCELLATIONS_LOG", log_dir / "cancels.jsonl"
    )
    api._reset_db_write_failures()
    try:
        yield db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None
        api._reset_db_write_failures()


def _log_kwargs(**over):
    base = dict(
        event_id="EVT_f1",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=42000.0,
        thesis="fail-loud regression",
    )
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Service-level: each write path returns a structured error, never success
# ---------------------------------------------------------------------------


def test_log_manual_trade_db_failure_returns_error(tmp_db, monkeypatch):
    monkeypatch.setattr(persistence, "insert_manual_trade", _boom)
    result = api.log_manual_trade(**_log_kwargs())
    assert result["status"] == "error"
    assert result["reason"] == "db_write_failed"
    assert result["db_persisted"] is False
    assert "error" in result
    # advisory stamps survive the error path
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    assert api.db_write_failure_count() == 1


def test_reconcile_trade_db_failure_returns_error(tmp_db, monkeypatch):
    ok = api.log_manual_trade(**_log_kwargs(event_id="EVT_f2"))
    assert ok["status"] == "logged"
    trade_id = ok["trade_id"]

    monkeypatch.setattr(persistence, "insert_reconciliation", _boom)
    rec = api.reconcile_trade(
        trade_id,
        actual_fill_price=43000.0,
        actual_quantity=1.0,
        pnl_estimate=1000.0,
    )
    assert rec["status"] == "error"
    assert rec["reason"] == "db_write_failed"
    assert rec["execution_gate"] == "LOCKED"
    assert rec["broker_api_called"] is False
    assert api.db_write_failure_count() == 1


def test_cancel_manual_trade_db_failure_returns_error(tmp_db, monkeypatch):
    ok = api.log_manual_trade(**_log_kwargs(event_id="EVT_f2c"))
    assert ok["status"] == "logged"
    trade_id = ok["trade_id"]

    monkeypatch.setattr(persistence, "cancel_manual_trade", _boom)
    res = api.cancel_manual_trade_log(trade_id, reason="dup")
    assert res["status"] == "error"
    assert res["reason"] == "db_write_failed"
    assert res["execution_gate"] == "LOCKED"
    assert res["broker_api_called"] is False
    assert api.db_write_failure_count() == 1
    # The cancellation must NOT have been audit-logged as if it happened.
    assert not api.MANUAL_TRADE_CANCELLATIONS_LOG.exists()


def test_db_success_path_still_logs(tmp_db):
    """Guard: the fix must not break the healthy write path."""
    result = api.log_manual_trade(**_log_kwargs(event_id="EVT_ok"))
    assert result["status"] == "logged"
    assert api.db_write_failure_count() == 0
    row = persistence.get_manual_trade(result["trade_id"])
    assert row is not None


# ---------------------------------------------------------------------------
# HTTP-level: the API converts the error dict into a stamped 500
# ---------------------------------------------------------------------------


@pytest.fixture()
def http_client(tmp_db):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    return TestClient(srv.app, raise_server_exceptions=False)


def _assert_stamped_500(resp):
    assert resp.status_code == 500
    body = resp.json()
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    detail = body.get("detail") or {}
    assert detail.get("reason") == "db_write_failed"
    assert detail.get("db_persisted") is False
    assert detail.get("execution_gate") == "LOCKED"


def test_post_manual_trade_db_failure_is_stamped_500(http_client, monkeypatch):
    monkeypatch.setattr(persistence, "insert_manual_trade", _boom)
    r = http_client.post(
        "/manual-trades",
        json={
            "event_id": "EVT_http_f1",
            "ticker": "BTC",
            "side": "BUY",
            "quantity": "1",
            "price": "42000",
            "thesis": "fail-loud http",
        },
    )
    _assert_stamped_500(r)


def test_post_reconcile_db_failure_is_stamped_500(http_client, monkeypatch):
    ok = api.log_manual_trade(**_log_kwargs(event_id="EVT_http_f2"))
    trade_id = ok["trade_id"]
    monkeypatch.setattr(persistence, "insert_reconciliation", _boom)
    r = http_client.post(
        f"/manual-trades/{trade_id}/reconcile",
        json={
            "actual_fill_price": "43000",
            "actual_quantity": "1",
            "pnl_estimate": "1000",
        },
    )
    _assert_stamped_500(r)


def test_post_cancel_db_failure_is_stamped_500(http_client, monkeypatch):
    ok = api.log_manual_trade(**_log_kwargs(event_id="EVT_http_f2c"))
    trade_id = ok["trade_id"]
    monkeypatch.setattr(persistence, "cancel_manual_trade", _boom)
    r = http_client.post(f"/manual-trades/{trade_id}/cancel", json={})
    assert r.status_code == 500
    body = r.json()
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert (body.get("detail") or {}).get("reason") == "db_write_failed"


def test_health_full_degrades_after_journal_write_failure(http_client, monkeypatch):
    monkeypatch.setattr(persistence, "insert_manual_trade", _boom)
    http_client.post(
        "/manual-trades",
        json={
            "event_id": "EVT_health",
            "ticker": "BTC",
            "side": "BUY",
            "quantity": "1",
            "price": "1",
            "thesis": "degrade health",
        },
    )
    h = http_client.get("/health/full")
    assert h.status_code == 200
    body = h.json()
    assert body["db_write_failures_total"] >= 1
    assert body["degraded"] is True
