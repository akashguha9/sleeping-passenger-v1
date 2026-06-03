"""Sprint 6 proofs — A1/A2/A3 (architecture), A4, R1, R2, R3."""
from __future__ import annotations

import importlib
from pathlib import Path

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
# A4 — single worker pinned
# ---------------------------------------------------------------------------


def test_a4_uvicorn_pinned_to_one_worker():
    src = Path("scripts/api_server.py").read_text()
    assert "workers=1" in src, "A4 regression: workers=1 pin removed"


# ---------------------------------------------------------------------------
# R1 — backup sidecar configured
# ---------------------------------------------------------------------------


def test_r1_backup_loop_exists_and_executable():
    p = Path("scripts/backup_loop.sh")
    assert p.exists(), "R1 regression: backup_loop.sh missing"
    assert p.read_text().count("backup_local_state.py") >= 1


def test_r1_compose_has_backup_service():
    yml = Path("docker-compose.yml").read_text()
    assert "backup:" in yml
    assert "backup_loop.sh" in yml
    assert "BACKUP_RETENTION_DAYS" in yml


# ---------------------------------------------------------------------------
# R2 — write-failure counter on /health/full
# ---------------------------------------------------------------------------


def test_r2_health_full_exposes_write_failure_counter(_safe_env):
    from fastapi.testclient import TestClient

    srv = _safe_env
    srv._reset_health_counters()
    client = TestClient(srv.app)
    r = client.get("/health/full", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("db_write_failures_total") == 0
    assert body.get("degraded") is False


def test_r2_failed_write_bumps_counter(_safe_env, monkeypatch):
    from fastapi.testclient import TestClient

    srv = _safe_env
    srv._reset_health_counters()

    # Force a write failure
    def _boom(**kwargs):
        raise RuntimeError("disk full simulation")

    monkeypatch.setattr(
        "scripts.persistence.insert_source_health", _boom, raising=False
    )
    srv._log_source_health({"total_snapshot_rows": 0}, "OFF")
    assert srv._WRITE_FAILURE_COUNT >= 1

    client = TestClient(srv.app)
    r = client.get("/health/full", headers={"Authorization": "Bearer tok"})
    body = r.json()
    assert body["db_write_failures_total"] >= 1
    assert body["degraded"] is True


# ---------------------------------------------------------------------------
# R3 — shared timeout/retry helper
# ---------------------------------------------------------------------------


def test_r3_request_helper_retries_then_succeeds(monkeypatch):
    """The helper must retry on RequestException and return when the
    next attempt succeeds."""
    from scripts import external_data_common as ed

    calls = {"n": 0}

    import requests

    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

    def _fake_request(method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.ConnectionError("transient")
        return _Resp()

    monkeypatch.setattr(requests, "request", _fake_request)
    out = ed.request_with_retry(
        "http://example.com",
        retries=2,
        backoff_seconds=0.01,
    )
    assert out.status_code == 200
    assert calls["n"] == 2  # one failure, one success


def test_r3_request_helper_gives_up_after_retries(monkeypatch):
    from scripts import external_data_common as ed
    import requests

    def _always_fail(method, url, **kwargs):
        raise requests.ConnectionError("never works")

    monkeypatch.setattr(requests, "request", _always_fail)
    with pytest.raises(requests.RequestException):
        ed.request_with_retry(
            "http://example.com",
            retries=2,
            backoff_seconds=0.001,
        )
