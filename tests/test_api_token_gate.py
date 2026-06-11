"""
Tests for the MVP_API_TOKEN gate on the Signal Advisory API.

Behaviour contract:
  * GET routes are always open (read-only advisory data).
  * Mutating POST routes require ``Authorization: Bearer <token>`` ONLY if
    ``MVP_API_TOKEN`` is set in the environment.
  * If ``MVP_API_TOKEN`` is unset/empty, mutating POSTs are permitted —
    appropriate for the local-only single-user MVP, with a startup warning.
  * Advisory safety stamps are preserved on every response, including 401s.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

# Skip the whole module if FastAPI is unavailable so the rest of the suite
# is unaffected.
fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


_ADVISORY = {
    "advisory_status": "ADVISORY_ONLY",
    "human_review_required": True,
    "execution_mode": "HUMAN_ONLY",
    "ai_execution_count": 0,
}

_TRADE_PAYLOAD = {
    "event_id": "TOKEN_TEST_001",
    "ticker": "AAPL",
    "side": "BUY",
    "quantity": 1.0,
    "price": 100.0,
    "thesis": "token-gate test",
    "notes": "",
    "logged_by": "human",
}


@pytest.fixture
def client_no_token(monkeypatch):
    """MVP_API_TOKEN explicitly unset → request-level open mode.

    Only reachable in a real server via the explicit loopback-only
    MVP_ALLOW_UNAUTH=1 override — startup otherwise fails closed
    (see tests/test_hackathon_sprint1.py)."""
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    import scripts.api_server as srv

    _trade_resp = {
        **_ADVISORY,
        "operation": "log_manual_trade",
        "trade_id": "TRADE_token_test",
        "event_id": "TOKEN_TEST_001",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1.0,
        "price": 100.0,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "generated_at": "2026-01-01T00:00:00Z",
    }
    with patch.object(srv, "log_manual_trade", return_value=_trade_resp):
        yield TestClient(srv.app)


@pytest.fixture
def client_with_token(monkeypatch):
    """MVP_API_TOKEN set → mutating POSTs require Bearer auth."""
    monkeypatch.setenv("MVP_API_TOKEN", "test-secret-token")
    import scripts.api_server as srv

    _trade_resp = {
        **_ADVISORY,
        "operation": "log_manual_trade",
        "trade_id": "TRADE_token_test",
        "event_id": "TOKEN_TEST_001",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1.0,
        "price": 100.0,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "generated_at": "2026-01-01T00:00:00Z",
    }
    with patch.object(srv, "log_manual_trade", return_value=_trade_resp):
        yield TestClient(srv.app)


# ---------------------------------------------------------------------------
# Token UNSET → mutating routes are open (local-dev default).
# ---------------------------------------------------------------------------


def test_no_token_get_health_open(client_no_token):
    r = client_no_token.get("/health")
    assert r.status_code == 200
    # D2: api_token_required is SENSITIVE posture — now on /health/full,
    # not the unauth probe.  No token + loopback => /health/full is open.
    assert "api_token_required" not in r.json()
    full = client_no_token.get("/health/full")
    assert full.status_code == 200
    assert full.json()["api_token_required"] is False


def test_no_token_post_manual_trade_allowed(client_no_token):
    r = client_no_token.post("/manual-trades", json=_TRADE_PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Token SET → GETs still open, POSTs require correct Bearer.
# ---------------------------------------------------------------------------


def test_with_token_get_health_still_open(client_with_token):
    # Minimal /health stays open even when a token is configured.
    r = client_with_token.get("/health")
    assert r.status_code == 200
    assert "api_token_required" not in r.json()
    # D2: posture reported on /health/full, which now requires the token.
    full = client_with_token.get(
        "/health/full", headers={"Authorization": "Bearer test-secret-token"}
    )
    assert full.status_code == 200
    assert full.json()["api_token_required"] is True


def test_with_token_post_without_header_rejected(client_with_token):
    r = client_with_token.post("/manual-trades", json=_TRADE_PAYLOAD)
    assert r.status_code == 401
    body = r.json()
    # Even on 401 we never weaken the safety contract.
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["ai_execution_count"] == 0
    assert body["broker_api_called"] is False
    assert body["execution_gate"] == "LOCKED"


def test_with_token_post_with_wrong_token_rejected(client_with_token):
    r = client_with_token.post(
        "/manual-trades",
        json=_TRADE_PAYLOAD,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["ai_execution_count"] == 0


def test_with_token_post_with_correct_token_allowed(client_with_token):
    r = client_with_token.post(
        "/manual-trades",
        json=_TRADE_PAYLOAD,
        headers={"Authorization": "Bearer test-secret-token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["broker_api_called"] is False


def test_with_token_post_malformed_authorization_header_rejected(client_with_token):
    # Missing "Bearer " prefix
    r = client_with_token.post(
        "/manual-trades",
        json=_TRADE_PAYLOAD,
        headers={"Authorization": "test-secret-token"},
    )
    assert r.status_code == 401
