"""Tests for the lightweight /api/version endpoint.

/api/version is the contract surface a future uptime check / status badge
should hit, and it must:
  * never touch the DB
  * always return advisory safety stamps
  * never leak secrets or paths
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as api_server
    importlib.reload(api_server)
    api_server._reset_rate_limiters()
    return TestClient(api_server.app)


def test_api_version_returns_expected_fields(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["app_name"] == "Signal Advisory API"
    assert isinstance(body["version"], str) and body["version"]
    assert "environment" in body
    assert "generated_at" in body


def test_api_version_carries_safety_stamps(client):
    r = client.get("/api/version")
    body = r.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_mode"] == "HUMAN_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["broker_order_id"] == "NONE"
    assert body["ai_execution_count"] == 0
    assert body["human_review_required"] is True


def test_api_version_does_not_leak_secrets(client, monkeypatch):
    """No env-secret-shaped values should appear in the response."""
    monkeypatch.setenv("MVP_API_TOKEN", "supersecret-token-do-not-leak")
    r = client.get("/api/version")
    body_text = r.text
    assert "supersecret-token-do-not-leak" not in body_text


def test_api_version_does_not_call_persistence(client):
    """The endpoint must not depend on the DB existing."""
    # No mocking needed: if /api/version touched persistence on a missing
    # DB it would either 500 or expose a path.  We assert 200 + no error.
    r = client.get("/api/version")
    assert r.status_code == 200
    assert "error" not in r.json()
