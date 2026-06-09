"""F5 regression: advisory stamps on EVERY error path, including 422/404/405.

Audit finding F5: the custom exception handler was registered for
``fastapi.HTTPException`` only.  FastAPI's default ``RequestValidationError``
handler (422) and Starlette's router-raised ``HTTPException`` (404 unknown
route, 405 method-not-allowed) bypassed it, returning bare
``{"detail": ...}`` bodies with no ``execution_gate`` / ``broker_api_called``
stamps — violating the hard invariant "every response and every error path".

Contract: every status code the API can produce carries the stamp block:
200, 400, 404, 405, 413, 422, 429, 500.
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.signal_inbox_api as sia
    import scripts.api_server as srv

    monkeypatch.setattr(sia, "MANUAL_TRADE_LOG", tmp_path / "mt.jsonl")
    monkeypatch.setattr(sia, "RECONCILIATIONS_LOG", tmp_path / "rec.jsonl")
    return TestClient(srv.app, raise_server_exceptions=False)


def _assert_stamped(body: dict, where: str) -> None:
    assert body.get("execution_gate") == "LOCKED", f"{where}: gate missing"
    assert body.get("broker_api_called") is False, f"{where}: broker flag missing"
    assert body.get("ai_execution_count") == 0, f"{where}: count missing"
    assert body.get("advisory_status") == "ADVISORY_ONLY", f"{where}: status missing"


def test_200_is_stamped(client):
    r = client.get("/health")
    assert r.status_code == 200
    _assert_stamped(r.json(), "200 /health")


def test_400_is_stamped(client, monkeypatch):
    # Validation refusal inside the service layer → HTTP 400.
    r = client.post(
        "/manual-trades",
        json={
            "event_id": "EVT_400",
            "ticker": "X",
            "side": "HOLD",  # invalid side → service-level refusal
            "quantity": "1",
            "price": "1",
            "thesis": "t",
        },
    )
    assert r.status_code == 400
    _assert_stamped(r.json(), "400 bad side")


def test_404_unknown_route_is_stamped(client):
    r = client.get("/definitely-not-a-route")
    assert r.status_code == 404
    _assert_stamped(r.json(), "404 unknown route")


def test_405_method_not_allowed_is_stamped(client):
    r = client.delete("/manual-trades")
    assert r.status_code == 405
    _assert_stamped(r.json(), "405 method not allowed")


def test_422_validation_error_is_stamped(client):
    r = client.post(
        "/manual-trades",
        json={
            "event_id": "EVT_422",
            "ticker": "X",
            "side": "BUY",
            "quantity": "not-a-number",
            "price": "abc",
            "thesis": "t",
        },
    )
    assert r.status_code == 422
    body = r.json()
    _assert_stamped(body, "422 validation error")
    # FastAPI's structured validation detail must survive for the frontend.
    assert "detail" in body


def test_413_payload_too_large_is_stamped(client):
    big = "x" * (2 * 1024 * 1024)  # 2MB > 1MB default cap
    r = client.post(
        "/manual-trades",
        content=big,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(big)),
        },
    )
    assert r.status_code == 413
    _assert_stamped(r.json(), "413 payload too large")


def test_500_unhandled_is_stamped(client, monkeypatch):
    import scripts.signal_inbox_api as sia

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sia._persistence, "insert_manual_trade", boom)
    r = client.post(
        "/manual-trades",
        json={
            "event_id": "EVT_500",
            "ticker": "BTC",
            "side": "BUY",
            "quantity": "1",
            "price": "1",
            "thesis": "t",
        },
    )
    assert r.status_code == 500
    _assert_stamped(r.json(), "500 db write failure")
