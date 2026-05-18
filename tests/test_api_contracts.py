"""Sprint 9B — API contract tests.

Lock the response *shapes* of the most important endpoints so future
refactors cannot accidentally break the frontend or weaken the safety
invariants.  These tests intentionally do NOT pin every field value —
just the keys the frontend depends on plus the advisory-only safety
stamps.

Read-only endpoints assert:
  * 200 OK (or documented empty-safe status)
  * required keys present
  * advisory_status / execution_gate / broker_api_called / etc. correct
  * missing data degrades to safe empty shape (no crash)

Mutating endpoints assert:
  * unauth (no token, token required) -> 401/403 with safety stamps
  * authorised happy path returns expected shape
  * bad payload fails safely
  * no execution-permission language anywhere
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
    db = tmp_path / "contracts.db"
    persistence.init_schema(db)
    for name in [
        "init_schema", "_get_conn", "insert_manual_trade",
        "get_trades_for_event", "get_event_id_for_trade",
        "get_all_manual_trades", "insert_reconciliation",
        "get_reconciliations_for_trade", "get_all_reconciliations",
    ]:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(signal_inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(signal_inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(signal_inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    yield db


@pytest.fixture()
def client(monkeypatch, tmp_db):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    import scripts.api_server as srv
    importlib.reload(srv)
    return TestClient(srv.app)


@pytest.fixture()
def client_with_token(monkeypatch, tmp_db):
    monkeypatch.setenv("MVP_API_TOKEN", "contract-test-token")
    import scripts.api_server as srv
    importlib.reload(srv)
    return TestClient(srv.app)


_FORBIDDEN_PHRASES = (
    "place order",
    "submit order",
    "execute trade",
    "trade now",
    "broker api call",
    "broker api connected",
    "ai-approved",
    "auto-trade",
    "permission granted",
)


def _assert_safe_response_text(body_text: str) -> None:
    blob = body_text.lower()
    for bad in _FORBIDDEN_PHRASES:
        assert bad not in blob, f"forbidden phrase {bad!r} found in response"


def _assert_advisory_stamps(body: dict, *, require_human_review: bool = True) -> None:
    assert body.get("advisory_status") == "ADVISORY_ONLY"
    # execution_gate may be absent on certain micro-endpoints; assert
    # when present.
    if "execution_gate" in body:
        assert body["execution_gate"] == "LOCKED"
    if "broker_api_called" in body:
        assert body["broker_api_called"] is False
    if "ai_execution_count" in body:
        assert body["ai_execution_count"] == 0
    if "execution_permission" in body:
        assert body["execution_permission"] is False
    if "can_execute" in body:
        assert body["can_execute"] is False
    if require_human_review and "human_review_required" in body:
        assert body["human_review_required"] is True


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_contract_health(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for k in (
        "status", "advisory_status", "execution_mode", "execution_gate",
        "ai_execution_count", "broker_api_called", "broker_order_id",
        "human_review_required", "version", "db_available",
        "api_token_required",
    ):
        assert k in body, f"/health missing key {k}"
    _assert_advisory_stamps(body)
    _assert_safe_response_text(r.text)


# ---------------------------------------------------------------------------
# GET /api/version
# ---------------------------------------------------------------------------


def test_contract_api_version(client) -> None:
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    for k in ("app_name", "version", "advisory_status", "execution_gate",
              "broker_api_called", "ai_execution_count"):
        assert k in body
    _assert_advisory_stamps(body, require_human_review=False)


# ---------------------------------------------------------------------------
# GET /live-sources/status
# ---------------------------------------------------------------------------


def test_contract_live_sources_status(client) -> None:
    r = client.get("/live-sources/status")
    assert r.status_code == 200
    body = r.json()
    for k in (
        "operation", "sources", "source_count", "freshness_distribution",
        "advisory_status", "execution_gate", "broker_api_called",
        "ai_execution_count", "execution_permission", "can_execute",
        "human_review_required",
    ):
        assert k in body, f"/live-sources/status missing key {k}"
    # Sprint 7D.1 — health_summary should be present (degraded shape OK).
    assert "health_summary" in body
    _assert_advisory_stamps(body)
    _assert_safe_response_text(r.text)


# ---------------------------------------------------------------------------
# GET /live-signals
# ---------------------------------------------------------------------------


def test_contract_live_signals(client) -> None:
    r = client.get("/live-signals")
    assert r.status_code == 200
    body = r.json()
    for k in ("advisory_status", "ai_execution_count", "human_review_required"):
        assert k in body
    _assert_advisory_stamps(body)
    _assert_safe_response_text(r.text)


# ---------------------------------------------------------------------------
# GET /learning-completeness (Sprint 7C.1)
# ---------------------------------------------------------------------------


def test_contract_learning_completeness_empty(client) -> None:
    r = client.get("/learning-completeness")
    assert r.status_code == 200
    body = r.json()
    for k in (
        "report", "db_available", "reconciled_count",
        "learning_complete_count", "learning_incomplete_count",
        "missing_field_distribution", "items", "warnings",
        "advisory_status", "execution_gate", "broker_api_called",
        "ai_execution_count", "execution_permission", "can_execute",
        "human_review_required", "trade_mode_distribution",
    ):
        assert k in body, f"/learning-completeness missing key {k}"
    _assert_advisory_stamps(body)
    _assert_safe_response_text(r.text)


# ---------------------------------------------------------------------------
# GET /manual-trades
# ---------------------------------------------------------------------------


def test_contract_manual_trades_list_empty(client) -> None:
    r = client.get("/manual-trades")
    assert r.status_code == 200
    body = r.json()
    for k in (
        "operation", "trade_count", "trades", "advisory_status",
        "execution_mode", "ai_execution_count", "human_review_required",
        "broker_api_called",
    ):
        assert k in body
    _assert_advisory_stamps(body)
    _assert_safe_response_text(r.text)


# ---------------------------------------------------------------------------
# POST /manual-trades — happy path + token gate
# ---------------------------------------------------------------------------


def test_contract_post_manual_trade_happy_path(client) -> None:
    payload = {
        "event_id": "EV_CONTRACT_1",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1.0,
        "price": 100.0,
        "thesis": "contract happy path coverage",
        "reactor_state_at_decision": "WARM_WATCH",
        "decision_grade_energy_at_decision": 0.5,
    }
    r = client.post("/manual-trades", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in (
        "status", "trade_id", "advisory_status", "execution_gate",
        "broker_api_called", "execution_permission", "can_execute",
        "trade_mode", "paper_trade_only", "real_capital_at_risk",
        "reactor_state_at_decision", "decision_grade_energy_at_decision",
    ):
        assert k in body, f"POST /manual-trades missing key {k}"
    _assert_advisory_stamps(body)
    _assert_safe_response_text(r.text)


def test_contract_post_manual_trade_paper_mode(client) -> None:
    payload = {
        "event_id": "EV_CONTRACT_PAPER",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1.0,
        "price": 100.0,
        "thesis": "contract paper",
        "trade_mode": "PAPER",
    }
    r = client.post("/manual-trades", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["trade_mode"] == "PAPER"
    assert body["paper_trade_only"] is True
    assert body["real_capital_at_risk"] is False
    _assert_advisory_stamps(body)


def test_contract_post_manual_trade_no_token_required_unset(client) -> None:
    payload = {
        "event_id": "EV_CONTRACT_NO_TOKEN",
        "ticker": "AAPL", "side": "BUY", "quantity": 1.0, "price": 1.0,
        "thesis": "ok",
    }
    r = client.post("/manual-trades", json=payload)
    assert r.status_code == 200


def test_contract_post_manual_trade_rejected_without_token_when_required(
    client_with_token,
) -> None:
    payload = {
        "event_id": "EV_NEEDS_AUTH",
        "ticker": "X", "side": "BUY", "quantity": 1.0, "price": 1.0,
        "thesis": "ok",
    }
    r = client_with_token.post("/manual-trades", json=payload)
    assert r.status_code in (401, 403)
    _assert_safe_response_text(r.text)


def test_contract_post_manual_trade_accepted_with_correct_token(
    client_with_token,
) -> None:
    payload = {
        "event_id": "EV_HAS_AUTH",
        "ticker": "X", "side": "BUY", "quantity": 1.0, "price": 1.0,
        "thesis": "ok",
    }
    r = client_with_token.post(
        "/manual-trades",
        json=payload,
        headers={"Authorization": "Bearer contract-test-token"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_advisory_stamps(body)


def test_contract_post_manual_trade_rejects_invalid_payload(client) -> None:
    """Bad payload returns a safe non-200; never crashes."""
    payload = {"thesis": "missing required fields"}
    r = client.post("/manual-trades", json=payload)
    assert r.status_code in (400, 422)
    _assert_safe_response_text(r.text)


# ---------------------------------------------------------------------------
# POST /manual-trades/{id}/reconcile
# ---------------------------------------------------------------------------


def test_contract_reconcile_trade_happy_path(client) -> None:
    log = client.post("/manual-trades", json={
        "event_id": "EV_REC",
        "ticker": "X", "side": "BUY", "quantity": 1.0, "price": 1.0,
        "thesis": "ok",
    }).json()
    trade_id = log["trade_id"]
    r = client.post(
        f"/manual-trades/{trade_id}/reconcile",
        json={
            "actual_fill_price": 1.0,
            "actual_quantity": 1.0,
            "outcome_status": "WIN",
            "outcome_quality": "skill",
            "lesson": "captured",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("operation", "reconciliation_id", "advisory_status"):
        assert k in body
    _assert_advisory_stamps(body)
    _assert_safe_response_text(r.text)


# ---------------------------------------------------------------------------
# POST /moltbook
# ---------------------------------------------------------------------------


def test_contract_moltbook_token_gated(client_with_token) -> None:
    r = client_with_token.post(
        "/moltbook",
        json={
            "event_id": "EV", "ticker": "X",
            "original_signal_thesis": "t",
            "ai_interpretation": "i",
            "user_reflection": "r",
            "final_human_decision": "d",
            "mistake_type": "good_signal_good_execution",
            "lesson_learned": "L",
        },
    )
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Mutating signal endpoints token-gate sanity
# ---------------------------------------------------------------------------


def test_contract_mutating_signal_endpoints_require_token(client_with_token) -> None:
    for path, body in (
        ("/signals/EV/validate", {}),
        ("/signals/EV/reflection", {"reflection_text": "x", "conviction_level": "MODERATE"}),
        ("/signals/EV/ai-summary", {"summary_text": "x"}),
        ("/signals/EV/decision", {"status": "watchlist"}),
    ):
        r = client_with_token.post(path, json=body)
        assert r.status_code in (401, 403), f"{path} should require token, got {r.status_code}"


# ---------------------------------------------------------------------------
# /db/status — empty DB does not crash
# ---------------------------------------------------------------------------


def test_contract_db_status(client) -> None:
    r = client.get("/db/status")
    assert r.status_code == 200
    body = r.json()
    for k in ("db_path", "db_exists", "table_row_counts", "advisory_status"):
        assert k in body
    _assert_advisory_stamps(body, require_human_review=False)
