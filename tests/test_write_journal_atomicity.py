"""S4-A1 regression: journal writes are atomic-or-recoverable via event WAL.

Five required scenarios:
1. crash after JSONL append, before DB commit → not success, health shows
   recoverable, guarded replay applies exactly once;
2. crash after DB commit, before APPLIED marker → startup reconciliation
   detects the domain row and marks APPLIED without duplicate insert;
3. duplicate idempotency key → prior applied receipt, no duplicate row,
   apply not re-run;
4. DB write failure via the API → stamped failure, gate LOCKED, event
   RECOVERABLE with the JSONL intent present;
5. F10 divergence detection still passes (run alongside this file).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import persistence
from scripts import write_journal as wj
from scripts.write_journal_registry import appliers, exists_checks


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


_HELPERS = [
    "init_schema", "_get_conn", "insert_manual_trade", "get_manual_trade",
    "get_event_id_for_trade", "insert_reconciliation",
    "get_reconciliations_for_trade", "cancel_manual_trade",
    "get_manual_trade_raw_broker_flag", "count_manual_trades_by_provenance",
]


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    import scripts.signal_inbox_api as api

    db = tmp_path / "wal.db"
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


def _wal_rows(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM write_journal ORDER BY event_id")]
    finally:
        conn.close()


def _payload(trade_id: str) -> dict:
    return {
        "trade_id": trade_id, "event_id": f"EVT_{trade_id}", "ticker": "BTC",
        "side": "BUY", "quantity": "0.1", "price": "42000.5",
        "executed_at": "2026-06-10T00:00:00Z", "thesis": "wal", "notes": "",
        "logged_by": "human", "leverage": "1", "trade_mode": "REAL_MANUAL",
        "created_via": "manual_trade_log", "currency": "USD",
        "ai_model_used": "",
    }


# ---------------------------------------------------------------------------
# Happy path: success only from APPLIED
# ---------------------------------------------------------------------------


def test_applied_lifecycle_and_success_receipt(tmp_db):
    import scripts.signal_inbox_api as api

    result = api.log_manual_trade(
        event_id="EVT_WAL_OK", ticker="BTC", side="BUY",
        quantity="0.1", price="42000.5", thesis="wal happy",
    )
    assert result["status"] == "logged"
    rows = _wal_rows(tmp_db)
    assert len(rows) == 1
    assert rows[0]["state"] == wj.STATE_APPLIED
    assert rows[0]["event_type"] == "manual_trade"
    # domain row exists exactly once
    assert persistence.get_manual_trade(result["trade_id"]) is not None


# ---------------------------------------------------------------------------
# Scenario 1: crash after JSONL, before DB commit
# ---------------------------------------------------------------------------


def test_crash_between_jsonl_and_db_is_recoverable_and_replays_once(tmp_db, tmp_path):
    payload = _payload("MT_CRASH1")
    jsonl = tmp_path / "logs" / "mt.jsonl"

    class _Crash(RuntimeError):
        pass

    def crashing_apply():
        raise _Crash("simulated process death before DB commit")

    with pytest.raises(wj.WriteJournalError):
        wj.append_then_apply_event(
            event_type="manual_trade",
            idempotency_key="MT_CRASH1",
            payload=payload,
            jsonl_append=lambda: jsonl.parent.mkdir(exist_ok=True) or jsonl.write_text(
                json.dumps(payload) + "\n"
            ),
            apply=crashing_apply,
            db_path=tmp_db,
        )
    rows = _wal_rows(tmp_db)
    assert rows[0]["state"] == wj.STATE_RECOVERABLE
    assert jsonl.exists()  # the intent survived

    # health counters show it
    counters = wj.journal_counters(tmp_db)
    assert counters["write_journal_recoverable_total"] == 1
    assert counters["write_journal_degraded"] is True

    # guarded replay applies EXACTLY once through the canonical applier
    out = wj.replay_recoverable(appliers(tmp_db), exists_checks(tmp_db), tmp_db)
    assert out["replayed"] == [rows[0]["event_id"]]
    assert persistence.get_manual_trade("MT_CRASH1", db_path=tmp_db) is not None
    # second replay: nothing recoverable left
    out2 = wj.replay_recoverable(appliers(tmp_db), exists_checks(tmp_db), tmp_db)
    assert out2["replayed"] == [] and out2["still_failed"] == []
    conn = sqlite3.connect(str(tmp_db))
    n = conn.execute(
        "SELECT COUNT(*) FROM manual_trades WHERE trade_id='MT_CRASH1'"
    ).fetchone()[0]
    conn.close()
    assert n == 1


# ---------------------------------------------------------------------------
# Scenario 2: crash after DB commit, before APPLIED marker
# ---------------------------------------------------------------------------


def test_crash_between_commit_and_marker_marks_applied_without_duplicate(tmp_db):
    payload = _payload("MT_CRASH2")
    # Simulate: domain row committed, journal stuck at DB_COMMITTED.
    appliers(tmp_db)["manual_trade"](payload)
    conn = wj._conn(tmp_db)
    now = "2026-06-10T00:00:00+00:00"
    conn.execute(
        "INSERT INTO write_journal (event_type, idempotency_key, payload_json,"
        " payload_hash, state, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("manual_trade", "MT_CRASH2", json.dumps(payload), "h",
         wj.STATE_DB_COMMITTED, now, now),
    )
    conn.commit()
    conn.close()

    out = wj.startup_reconcile(exists_checks(tmp_db), tmp_db)
    assert len(out["marked_applied"]) == 1
    assert out["flagged_recoverable"] == []
    rows = _wal_rows(tmp_db)
    assert rows[0]["state"] == wj.STATE_APPLIED
    conn = sqlite3.connect(str(tmp_db))
    n = conn.execute(
        "SELECT COUNT(*) FROM manual_trades WHERE trade_id='MT_CRASH2'"
    ).fetchone()[0]
    conn.close()
    assert n == 1  # no duplicate insert


def test_startup_flags_interrupted_intents_without_auto_replay(tmp_db):
    conn = wj._conn(tmp_db)
    now = "2026-06-10T00:00:00+00:00"
    conn.execute(
        "INSERT INTO write_journal (event_type, idempotency_key, payload_json,"
        " payload_hash, state, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("manual_trade", "MT_STUCK", json.dumps(_payload("MT_STUCK")), "h",
         wj.STATE_JSONL_APPENDED, now, now),
    )
    conn.commit()
    conn.close()
    out = wj.startup_reconcile(exists_checks(tmp_db), tmp_db)
    assert len(out["flagged_recoverable"]) == 1
    # NOT auto-replayed: domain row must not exist yet.
    assert persistence.get_manual_trade("MT_STUCK", db_path=tmp_db) is None


# ---------------------------------------------------------------------------
# Scenario 3: duplicate idempotency key
# ---------------------------------------------------------------------------


def test_duplicate_idempotency_key_returns_prior_receipt(tmp_db):
    payload = _payload("MT_DUPKEY")
    calls = {"apply": 0, "jsonl": 0}

    def apply():
        calls["apply"] += 1
        appliers(tmp_db)["manual_trade"](payload)

    def jsonl():
        calls["jsonl"] += 1

    r1 = wj.append_then_apply_event(
        event_type="manual_trade", idempotency_key="MT_DUPKEY",
        payload=payload, jsonl_append=jsonl, apply=apply, db_path=tmp_db,
    )
    r2 = wj.append_then_apply_event(
        event_type="manual_trade", idempotency_key="MT_DUPKEY",
        payload=payload, jsonl_append=jsonl, apply=apply, db_path=tmp_db,
    )
    assert r1["replayed_receipt"] is False
    assert r2["replayed_receipt"] is True
    assert r2["state"] == wj.STATE_APPLIED
    assert calls["apply"] == 1 and calls["jsonl"] == 1
    assert len(_wal_rows(tmp_db)) == 1
    conn = sqlite3.connect(str(tmp_db))
    n = conn.execute(
        "SELECT COUNT(*) FROM manual_trades WHERE trade_id='MT_DUPKEY'"
    ).fetchone()[0]
    conn.close()
    assert n == 1


# ---------------------------------------------------------------------------
# Scenario 4: DB write failure via the API — stamped + recoverable
# ---------------------------------------------------------------------------


def test_api_db_failure_is_stamped_and_recoverable(tmp_db, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(persistence, "insert_manual_trade", boom)
    client = TestClient(srv.app, raise_server_exceptions=False)
    r = client.post(
        "/manual-trades",
        json={"event_id": "EVT_WALFAIL", "ticker": "BTC", "side": "BUY",
              "quantity": "1", "price": "1", "thesis": "t"},
    )
    assert r.status_code == 500
    body = r.json()
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert (body.get("detail") or {}).get("reason") == "db_write_failed"
    rows = _wal_rows(tmp_db)
    assert len(rows) == 1
    assert rows[0]["state"] == wj.STATE_RECOVERABLE
    # JSONL intent exists → recoverable, not lost
    assert (tmp_db.parent / "logs" / "mt.jsonl").exists()


def test_health_full_carries_wal_counters(tmp_db):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    h = client.get("/health/full").json()
    assert h["journal_atomicity_mode"] == "event_wal"
    assert "write_journal_pending_total" in h
    assert "write_journal_recoverable_total" in h
    assert "write_journal_failed_total" in h


def test_recoverable_event_degrades_health(tmp_db, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    def boom(*a, **k):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(persistence, "insert_manual_trade", boom)
    client = TestClient(srv.app, raise_server_exceptions=False)
    client.post(
        "/manual-trades",
        json={"event_id": "EVT_DEG", "ticker": "BTC", "side": "BUY",
              "quantity": "1", "price": "1", "thesis": "t"},
    )
    h = client.get("/health/full").json()
    assert h["write_journal_recoverable_total"] >= 1
    assert h["degraded"] is True
