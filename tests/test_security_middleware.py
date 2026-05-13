"""Integration tests for the security/limits middleware in api_server.

The middleware stacks four concerns: security headers, request size guard,
rate limiting, and advisory-stamp preservation on rejection responses.
Each is verified here.

Pytest auto-disables the rate limiter (PYTEST_CURRENT_TEST is set), so the
rate-limit tests opt in via ``monkeypatch.setenv("MVP_RATE_LIMIT_ENABLED",
"1")`` and reset the limiter cache between cases.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def fresh_app(monkeypatch):
    """Reimport api_server with a clean rate-limit cache.

    Each test gets its own module-state copy so that opt-in rate-limit
    tests do not bleed into each other's bucket counters.
    """
    # Default: limiter off, headers on.  Tests override as needed.
    monkeypatch.delenv("MVP_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("MVP_SECURITY_HEADERS_DISABLED", raising=False)
    monkeypatch.delenv("MVP_MAX_REQUEST_BYTES", raising=False)

    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")

    import scripts.api_server as api_server
    importlib.reload(api_server)
    api_server._reset_rate_limiters()
    return api_server, TestClient(api_server.app)


def test_security_headers_present_on_health(fresh_app):
    _, client = fresh_app
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert "permissions-policy" in r.headers


def test_security_headers_present_on_version(fresh_app):
    _, client = fresh_app
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0
    assert "version" in body
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_security_headers_can_be_disabled(monkeypatch):
    """Operator escape hatch: MVP_SECURITY_HEADERS_DISABLED=1."""
    monkeypatch.setenv("MVP_SECURITY_HEADERS_DISABLED", "1")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as api_server
    importlib.reload(api_server)
    api_server._reset_rate_limiters()
    client = TestClient(api_server.app)
    r = client.get("/health")
    assert r.status_code == 200
    # Headers absent
    assert r.headers.get("x-content-type-options") is None


def test_oversize_post_returns_413_with_safety_stamps(monkeypatch):
    """POSTs with Content-Length over the cap return 413 and never reach a route."""
    monkeypatch.setenv("MVP_MAX_REQUEST_BYTES", "1024")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as api_server
    importlib.reload(api_server)
    api_server._reset_rate_limiters()
    client = TestClient(api_server.app)

    huge = "x" * 8192
    r = client.post(
        "/signals/EVT_TEST/reflection",
        json={"reflection_text": huge},
    )
    assert r.status_code == 413
    body = r.json()
    assert body["error"] == "request_body_too_large"
    assert body["max_request_bytes"] == 1024
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_normal_post_passes_size_guard(monkeypatch):
    """Normal-size mutating requests still reach the handler."""
    monkeypatch.setenv("MVP_MAX_REQUEST_BYTES", "1000000")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as api_server
    importlib.reload(api_server)
    api_server._reset_rate_limiters()
    client = TestClient(api_server.app)

    # The reflection endpoint will fail in a controlled way (no event)
    # but should NOT be blocked by the size guard.  We just need a
    # response that is not 413.
    r = client.post(
        "/signals/EVT_TEST/reflection",
        json={"reflection_text": "fine"},
    )
    assert r.status_code != 413


def test_rate_limiter_blocks_burst_with_safety_stamps(monkeypatch):
    """When explicitly enabled, the limiter returns 429 with advisory stamps."""
    monkeypatch.setenv("MVP_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("MVP_MUTATION_RATE_LIMIT_MAX_REQUESTS", "2")
    monkeypatch.setenv("MVP_RATE_LIMIT_WINDOW_SECONDS", "60")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as api_server
    importlib.reload(api_server)
    api_server._reset_rate_limiters()
    client = TestClient(api_server.app)

    payload = {"reflection_text": "ok"}
    r1 = client.post("/signals/EVT/reflection", json=payload)
    r2 = client.post("/signals/EVT/reflection", json=payload)
    r3 = client.post("/signals/EVT/reflection", json=payload)
    # First two may succeed-or-fail-via-route; third must be 429
    assert r3.status_code == 429
    body = r3.json()
    assert body["error"] == "rate_limited"
    assert body["scope"] == "write"
    assert body["limit"] == 2
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0
    assert r3.headers.get("retry-after") is not None
    assert r3.headers.get("x-content-type-options") == "nosniff"


def test_rate_limiter_disabled_allows_burst(monkeypatch):
    """With MVP_RATE_LIMIT_ENABLED=0 even bursts pass through the limiter."""
    monkeypatch.setenv("MVP_RATE_LIMIT_ENABLED", "0")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as api_server
    importlib.reload(api_server)
    api_server._reset_rate_limiters()
    client = TestClient(api_server.app)

    # 20 quick GETs to /health should all succeed
    for _ in range(20):
        r = client.get("/health")
        assert r.status_code == 200


def test_health_reports_security_posture(fresh_app):
    """/health should surface rate_limit_enabled and security_headers_enabled."""
    _, client = fresh_app
    r = client.get("/health")
    body = r.json()
    assert "rate_limit_enabled" in body
    assert "max_request_bytes" in body
    assert "security_headers_enabled" in body
    assert body["security_headers_enabled"] is True
    # Safety stamps preserved
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0
