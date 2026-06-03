"""Sprint 7 proofs — I2 (bootstrap-symbol abuse) and I3 (expensive scope)."""
from __future__ import annotations

import importlib

import pytest

import scripts.runtime_config as rc


@pytest.fixture
def _safe_env(monkeypatch):
    for v in ("MVP_API_TOKEN", "API_HOST", "MVP_ALLOW_UNAUTH"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("MVP_API_TOKEN", "tok")
    importlib.reload(rc)
    import scripts.api_server as srv

    importlib.reload(srv)
    return srv


# ---------------------------------------------------------------------------
# I2 — bootstrap-symbol quota + denylist
# ---------------------------------------------------------------------------


def test_i2_quota_blocks_after_exhaustion(monkeypatch, _safe_env):
    from fastapi.testclient import TestClient

    srv = _safe_env
    srv._reset_bootstrap_quota()
    monkeypatch.setenv("MVP_BOOTSTRAP_SYMBOL_QUOTA", "2")

    # Stub the real bootstrap so we don't hit yfinance
    def _fake(symbol, period, interval):
        return {
            "ok": True,
            "symbol": symbol,
            "advisory_status": "ADVISORY_ONLY",
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": 0,
        }

    monkeypatch.setattr(srv, "_bootstrap_symbol", _fake)
    client = TestClient(srv.app)
    headers = {"Authorization": "Bearer tok"}
    body = {"symbol": "AAPL", "period": "max", "interval": "1d"}

    r1 = client.post("/chart-structure/bootstrap-symbol", headers=headers, json=body)
    r2 = client.post("/chart-structure/bootstrap-symbol", headers=headers, json=body)
    r3 = client.post("/chart-structure/bootstrap-symbol", headers=headers, json=body)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 429
    body3 = r3.json()
    assert body3["detail"]["reason"] == "bootstrap_quota"
    # Advisory invariants stamped on the refusal
    assert body3["execution_gate"] == "LOCKED"
    assert body3["broker_api_called"] is False
    assert body3["ai_execution_count"] == 0


def test_i2_denylist_blocks_symbol(monkeypatch, _safe_env):
    from fastapi.testclient import TestClient

    srv = _safe_env
    srv._reset_bootstrap_quota()
    monkeypatch.setenv("MVP_BOOTSTRAP_SYMBOL_DENYLIST", "EVIL,ALSOBAD")
    monkeypatch.setenv("MVP_BOOTSTRAP_SYMBOL_QUOTA", "50")

    def _fake(symbol, period, interval):  # pragma: no cover — should not be called
        raise AssertionError("denylisted symbol reached bootstrap function")

    monkeypatch.setattr(srv, "_bootstrap_symbol", _fake)
    client = TestClient(srv.app)
    r = client.post(
        "/chart-structure/bootstrap-symbol",
        headers={"Authorization": "Bearer tok"},
        json={"symbol": "evil", "period": "max", "interval": "1d"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["detail"]["reason"] == "bootstrap_denylist"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False


def test_i2_quota_zero_disables_route(monkeypatch, _safe_env):
    from fastapi.testclient import TestClient

    srv = _safe_env
    srv._reset_bootstrap_quota()
    monkeypatch.setenv("MVP_BOOTSTRAP_SYMBOL_QUOTA", "0")

    client = TestClient(srv.app)
    r = client.post(
        "/chart-structure/bootstrap-symbol",
        headers={"Authorization": "Bearer tok"},
        json={"symbol": "AAPL", "period": "max", "interval": "1d"},
    )
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# I3 — expensive scope cap
# ---------------------------------------------------------------------------


def test_i3_default_expensive_is_smaller_than_read(monkeypatch):
    monkeypatch.delenv("MVP_RATE_LIMIT_EXPENSIVE_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("MVP_RATE_LIMIT_MAX_REQUESTS", raising=False)
    importlib.reload(rc)
    standard = rc.rate_limit_max_requests()
    expensive = rc.rate_limit_expensive_max_requests()
    assert expensive <= standard
    assert expensive >= 1


def test_i3_explicit_override_respected(monkeypatch):
    monkeypatch.setenv("MVP_RATE_LIMIT_EXPENSIVE_MAX_REQUESTS", "7")
    importlib.reload(rc)
    assert rc.rate_limit_expensive_max_requests() == 7


def test_i3_expensive_prefixes_resolved(_safe_env):
    """The middleware should classify these as 'expensive'."""
    srv = _safe_env
    for p in ("/exports/foo.csv", "/diagnostics/cockpit",
              "/learning-completeness", "/self-test/summary"):
        assert srv._scope_for(p, is_mutating=False) == "expensive", p

    # Normal reads stay 'read'
    assert srv._scope_for("/signals", is_mutating=False) == "read"
    # Mutating routes win
    assert srv._scope_for("/exports/foo.csv", is_mutating=True) == "write"


def test_i3_middleware_uses_expensive_bucket_when_enabled(monkeypatch, _safe_env):
    """Hard-throttle the expensive bucket to 1/min and confirm a second
    GET to an /exports/* path is refused with 429."""
    from fastapi.testclient import TestClient

    srv = _safe_env
    srv._reset_rate_limiters()

    monkeypatch.setenv("MVP_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("MVP_RATE_LIMIT_EXPENSIVE_MAX_REQUESTS", "1")
    monkeypatch.setenv("MVP_RATE_LIMIT_WINDOW_SECONDS", "60")
    importlib.reload(rc)
    importlib.reload(srv)
    srv._reset_rate_limiters()

    client = TestClient(srv.app)
    headers = {"Authorization": "Bearer tok"}

    # First expensive request: allowed (may 500 because no DB — that's
    # OK; what matters is it's NOT 429).
    r1 = client.get("/exports/manual-trades.csv", headers=headers)
    assert r1.status_code != 429
    # Second one within the window: blocked
    r2 = client.get("/exports/manual-trades.csv", headers=headers)
    assert r2.status_code == 429
    body = r2.json()
    assert body["scope"] == "expensive"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
