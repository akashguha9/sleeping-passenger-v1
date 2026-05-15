"""Sprint 7C.1 — GET /learning-completeness API contract tests.

The endpoint must:
  * be read-only (GET, no token required when MVP_API_TOKEN is unset)
  * degrade safely with an empty/no-DB state (no crash)
  * surface incomplete trades when the DB has reconciled rows
  * expose paper/manual distinction via trade_mode_distribution
  * carry every advisory-only safety stamp
  * never imply broker execution or trade authorisation
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from scripts import persistence
from scripts import signal_inbox_api


def _rebind_defaults(fn, new_db: Path) -> None:
    if fn.__defaults__:
        new_defs = tuple(new_db if isinstance(d, Path) else d for d in fn.__defaults__)
        fn.__defaults__ = new_defs
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "lc_api.db"
    persistence.init_schema(db)
    helper_names = [
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_trades_for_event",
        "get_event_id_for_trade",
        "get_all_manual_trades",
        "insert_reconciliation",
        "get_reconciliations_for_trade",
        "get_all_reconciliations",
    ]
    originals: dict = {}
    for name in helper_names:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(signal_inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(signal_inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(signal_inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    try:
        yield db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


@pytest.fixture()
def client(monkeypatch, tmp_db):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    import scripts.api_server as srv
    importlib.reload(srv)
    return TestClient(srv.app)


def _safety_stamps_ok(body: dict) -> None:
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0
    assert body["execution_permission"] is False
    assert body["can_execute"] is False
    assert body["human_review_required"] is True


def test_learning_completeness_empty_db(client) -> None:
    r = client.get("/learning-completeness")
    assert r.status_code == 200, r.text
    body = r.json()
    _safety_stamps_ok(body)
    assert body["learning_complete_count"] == 0
    assert body["learning_incomplete_count"] == 0
    assert body["incomplete_count"] == 0
    assert body["complete_count"] == 0
    assert body.get("items") == []


def test_learning_completeness_no_token_required(client) -> None:
    """Read-only endpoint stays accessible regardless of MVP_API_TOKEN policy."""
    r = client.get("/learning-completeness")
    assert r.status_code == 200
    # No Authorization header was sent and the request succeeded.


def test_learning_completeness_paper_manual_distinction(client, tmp_db: Path) -> None:
    """trade_mode_distribution distinguishes paper from real_manual."""
    signal_inbox_api.log_manual_trade(
        event_id="EV_PAPER",
        ticker="PAP",
        side="BUY",
        quantity=1.0,
        price=1.0,
        thesis="paper rehearsal",
        trade_mode="PAPER",
    )
    signal_inbox_api.log_manual_trade(
        event_id="EV_REAL",
        ticker="REAL",
        side="BUY",
        quantity=1.0,
        price=1.0,
        thesis="real manual",
        trade_mode="REAL_MANUAL",
    )
    r = client.get("/learning-completeness")
    assert r.status_code == 200, r.text
    body = r.json()
    _safety_stamps_ok(body)
    dist = body.get("trade_mode_distribution") or {}
    assert dist.get("PAPER", 0) == 1
    assert dist.get("REAL_MANUAL", 0) == 1
    assert body.get("paper_trade_count") == 1
    assert body.get("real_manual_trade_count") == 1


def test_learning_completeness_surfaces_incomplete_rows(client, tmp_db: Path) -> None:
    """Reconciled rows missing outcome_quality / lesson are reported."""
    # Log a trade and reconcile it WITHOUT the learning fields.
    log = signal_inbox_api.log_manual_trade(
        event_id="EV_INC",
        ticker="ZZZ",
        side="BUY",
        quantity=1.0,
        price=1.0,
        thesis="incomplete journal",
    )
    trade_id = log["trade_id"]
    signal_inbox_api.reconcile_trade(
        trade_id,
        actual_fill_price=1.0,
        actual_quantity=1.0,
        outcome_notes="",
        pnl_estimate=0.0,
        outcome_status="WIN",
        # outcome_quality / lesson intentionally empty
    )
    r = client.get("/learning-completeness")
    assert r.status_code == 200, r.text
    body = r.json()
    _safety_stamps_ok(body)
    assert body["learning_incomplete_count"] >= 1
    # missing fields should be itemised so the UI can render guidance.
    dist = body.get("missing_field_distribution") or {}
    assert sum(dist.values()) >= 1


def test_learning_completeness_no_execution_language(client) -> None:
    """No part of the response should imply broker execution permission."""
    r = client.get("/learning-completeness")
    assert r.status_code == 200
    blob = r.text.lower()
    forbidden = (
        "place order",
        "submit order",
        "execute trade",
        "broker api",
        "ai-approved",
        "permission granted",
        "trade now",
        "auto-trade",
        "auto trade",
    )
    for bad in forbidden:
        assert bad not in blob, f"forbidden phrase {bad!r} found in response"
