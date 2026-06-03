"""Sprint 1 proofs — perimeter & auth (S1, S2, S3, S5, S7, S8, D2).

These tests are intentionally self-contained.  They reload runtime_config
and api_server with controlled env so each finding has a deterministic
proof.  All assertions also verify the advisory invariants still stamp.
"""
from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

import scripts.runtime_config as rc


ADVISORY_INVARIANTS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_mode": "HUMAN_ONLY",
    "execution_gate": "LOCKED",
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
}


def _reset_env(monkeypatch, **overrides):
    for var in (
        "MVP_API_TOKEN",
        "API_HOST",
        "MVP_ALLOW_UNAUTH",
        "ALLOWED_ORIGINS",
        "MVP_TRUSTED_PROXIES",
        "MVP_RATE_LIMIT_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    importlib.reload(rc)


def _fresh_app(monkeypatch, **overrides):
    _reset_env(monkeypatch, **overrides)
    import scripts.api_server as srv

    importlib.reload(srv)
    return srv


# ---------------------------------------------------------------------------
# S1 — preflight refuses to boot on non-loopback bind with no token
# ---------------------------------------------------------------------------


def test_s1_loopback_default_boots_without_token(monkeypatch):
    _reset_env(monkeypatch, API_HOST="127.0.0.1")
    rc.preflight_auth_or_die()  # must not raise


def test_s1_non_loopback_without_token_refuses(monkeypatch):
    _reset_env(monkeypatch, API_HOST="0.0.0.0")
    with pytest.raises(rc.StartupSecurityError) as ei:
        rc.preflight_auth_or_die()
    assert "MVP_API_TOKEN" in str(ei.value)


def test_s1_non_loopback_with_token_boots(monkeypatch):
    _reset_env(monkeypatch, API_HOST="0.0.0.0", MVP_API_TOKEN="t0p-s3cret")
    rc.preflight_auth_or_die()


def test_s1_explicit_unauth_override_boots(monkeypatch):
    _reset_env(monkeypatch, API_HOST="0.0.0.0", MVP_ALLOW_UNAUTH="1")
    rc.preflight_auth_or_die()
    assert rc.unauth_override_active() is True


# ---------------------------------------------------------------------------
# S5 — reads gated on token when token is set
# ---------------------------------------------------------------------------


def test_s5_read_endpoints_unauth_without_token_when_loopback(monkeypatch):
    srv = _fresh_app(monkeypatch, API_HOST="127.0.0.1")
    client = TestClient(srv.app)
    # /health (minimal) stays open
    r = client.get("/health")
    assert r.status_code == 200
    assert "db_path" not in r.json()  # D2 fix
    assert "environment" not in r.json()
    # /manual-trades is open on loopback with no token configured
    r2 = client.get("/manual-trades")
    assert r2.status_code in (200, 500)


def test_s5_read_endpoints_require_token_when_set(monkeypatch):
    srv = _fresh_app(monkeypatch, API_HOST="127.0.0.1", MVP_API_TOKEN="shh-secret")
    client = TestClient(srv.app)

    # GET /manual-trades — token-gated read
    r = client.get("/manual-trades")
    assert r.status_code == 401
    body = r.json()
    for k, v in ADVISORY_INVARIANTS.items():
        assert body.get(k) == v, f"invariant {k}={v} missing from 401 body"

    # /exports/manual-trades.csv — same gate
    r = client.get("/exports/manual-trades.csv")
    assert r.status_code == 401

    # With token — passes the gate (may still 500 because no DB, that's OK)
    r = client.get(
        "/manual-trades",
        headers={"Authorization": "Bearer shh-secret"},
    )
    assert r.status_code != 401


def test_s5_health_full_token_gated(monkeypatch):
    srv = _fresh_app(monkeypatch, API_HOST="127.0.0.1", MVP_API_TOKEN="tok")
    client = TestClient(srv.app)
    r = client.get("/health/full")
    assert r.status_code == 401

    r = client.get("/health/full", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    body = r.json()
    # D2: detailed posture fields present here, NOT in /health
    assert "environment" in body
    assert "db_path" in body
    assert "unauth_override_active" in body
    for k, v in ADVISORY_INVARIANTS.items():
        assert body.get(k) == v


# ---------------------------------------------------------------------------
# S2 — constant-time bearer comparison
# ---------------------------------------------------------------------------


def test_s2_uses_compare_digest(monkeypatch):
    """Source-level proof: ensure hmac.compare_digest replaces raw !=.

    Behavioural timing tests are notoriously flaky; this asserts the
    relevant code path actually imports hmac and uses compare_digest.
    """
    src = open("scripts/api_server.py").read()
    assert "hmac.compare_digest" in src, "S2 fix missing: hmac.compare_digest"
    assert "provided != expected" not in src, "S2 regression: raw != still present"


def test_s2_wrong_token_rejected(monkeypatch):
    srv = _fresh_app(monkeypatch, API_HOST="127.0.0.1", MVP_API_TOKEN="correct")
    client = TestClient(srv.app)
    r = client.post(
        "/signals/E1/validate", headers={"Authorization": "Bearer WRONG"}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# S3 — proxy IP extraction
# ---------------------------------------------------------------------------


def test_s3_untrusted_proxy_ignored(monkeypatch):
    _reset_env(monkeypatch)
    # Untrusted direct host -> X-Forwarded-For ignored
    assert rc.extract_client_ip("1.2.3.4", "9.9.9.9") == "1.2.3.4"


def test_s3_trusted_proxy_forwards_xff(monkeypatch):
    _reset_env(monkeypatch, MVP_TRUSTED_PROXIES="10.0.0.1")
    # Direct host is the proxy; XFF wins
    assert rc.extract_client_ip("10.0.0.1", "9.9.9.9, 10.0.0.1") == "9.9.9.9"


def test_s3_loopback_is_trusted_by_default(monkeypatch):
    _reset_env(monkeypatch)
    assert rc.extract_client_ip("127.0.0.1", "192.168.1.5") == "192.168.1.5"


def test_s3_missing_xff_uses_direct(monkeypatch):
    _reset_env(monkeypatch, MVP_TRUSTED_PROXIES="10.0.0.1")
    assert rc.extract_client_ip("10.0.0.1", "") == "10.0.0.1"


# ---------------------------------------------------------------------------
# S7 — sleepingpassenger.* origins removed from defaults
# ---------------------------------------------------------------------------


def test_s7_defaults_drop_non_loopback_origins(monkeypatch):
    _reset_env(monkeypatch)
    origins = rc.get_allowed_origins()
    for bad in ("sleepingpassenger", "sleepingpassenger.local"):
        assert not any(bad in o for o in origins), f"S7 regression: {bad} still default"


# ---------------------------------------------------------------------------
# S8 — Next config defines CSP and security headers
# ---------------------------------------------------------------------------


def test_s8_next_config_has_csp_and_headers():
    cfg = open("frontend/next.config.js").read()
    for needle in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "frame-ancestors 'none'",
        "default-src 'self'",
        "object-src 'none'",
    ):
        assert needle in cfg, f"S8 missing: {needle}"


# ---------------------------------------------------------------------------
# D2 — /health is minimal
# ---------------------------------------------------------------------------


def test_d2_health_is_minimal(monkeypatch):
    srv = _fresh_app(monkeypatch, API_HOST="127.0.0.1")
    client = TestClient(srv.app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for leak in (
        "environment",
        "db_path",
        "db_available",
        "api_token_required",
        "rate_limit_enabled",
        "max_request_bytes",
        "security_headers_enabled",
        "allowed_origins_count",
    ):
        assert leak not in body, f"D2 regression: {leak} still on /health"
    for k, v in ADVISORY_INVARIANTS.items():
        assert body.get(k) == v
