"""Sprint 5 proofs — D1, S9, I1."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
# S9 — server-stamped logged_by
# ---------------------------------------------------------------------------


def test_s9_logged_by_is_server_stamped(monkeypatch, _safe_env):
    srv = _safe_env
    captured = {}

    def _fake_log(**kwargs):
        captured.update(kwargs)
        return {
            "trade_id": "MT_1",
            "status": "logged",
            "advisory_status": "ADVISORY_ONLY",
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": 0,
            "logged_by": kwargs.get("logged_by"),
        }

    monkeypatch.setattr(srv, "log_manual_trade", _fake_log)
    client = TestClient(srv.app)

    # Client tries to claim to be someone else
    r = client.post(
        "/manual-trades",
        headers={"Authorization": "Bearer tok"},
        json={
            "event_id": "E1",
            "ticker": "AAPL",
            "side": "LONG",
            "quantity": "1",
            "price": "1",
            "thesis": "t",
            "logged_by": "ceo@megacorp",  # ATTEMPT: client-forged identity
        },
    )
    assert r.status_code == 200, r.text
    # Server-stamped identity wins
    assert captured["logged_by"] == "operator@token-auth"
    assert captured["logged_by"] != "ceo@megacorp"


def test_s9_loopback_identity_when_no_token(monkeypatch):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    importlib.reload(rc)
    import scripts.api_server as srv

    importlib.reload(srv)

    captured = {}

    def _fake_log(**kwargs):
        captured.update(kwargs)
        return {"trade_id": "MT_1", "status": "logged",
                "advisory_status": "ADVISORY_ONLY", "execution_gate": "LOCKED",
                "broker_api_called": False, "ai_execution_count": 0}

    monkeypatch.setattr(srv, "log_manual_trade", _fake_log)
    client = TestClient(srv.app)
    r = client.post(
        "/manual-trades",
        json={
            "event_id": "E1",
            "ticker": "AAPL",
            "side": "LONG",
            "quantity": "1",
            "price": "1",
            "thesis": "t",
            "logged_by": "totally-trustworthy",
        },
    )
    assert r.status_code == 200, r.text
    assert captured["logged_by"] == "operator@loopback"


# ---------------------------------------------------------------------------
# D1 — reflection delete endpoint
# ---------------------------------------------------------------------------


def test_d1_delete_reflection_route_exists(_safe_env):
    srv = _safe_env
    paths = [r.path for r in srv.app.routes]
    assert "/reflections/{reflection_id}" in paths


def test_d1_delete_reflection_requires_token(_safe_env):
    srv = _safe_env
    client = TestClient(srv.app)
    r = client.delete("/reflections/REF_1")
    assert r.status_code == 401


def test_d1_soft_delete_persistence(tmp_path):
    """Pure persistence-layer test of the new helper."""
    from scripts.persistence import insert_reflection, soft_delete_reflection

    db = tmp_path / "d1.db"
    # Force schema creation
    insert_reflection(
        reflection_id="REF_TEST_1",
        event_id="E1",
        author="human",
        conviction_level="MODERATE",
        reflection_text="my deeply personal trade thesis",
        reflected_at="2024-01-01T00:00:00Z",
        db_path=db,
    )
    # Confirm row exists
    import sqlite3

    con = sqlite3.connect(db)
    assert con.execute(
        "SELECT 1 FROM user_reflections WHERE reflection_id=?",
        ("REF_TEST_1",),
    ).fetchone() == (1,)
    con.close()

    out = soft_delete_reflection("REF_TEST_1", db_path=db)
    assert out["deleted"] is True

    con = sqlite3.connect(db)
    assert (
        con.execute(
            "SELECT 1 FROM user_reflections WHERE reflection_id=?",
            ("REF_TEST_1",),
        ).fetchone()
        is None
    )
    con.close()


def test_d1_delete_missing_returns_404(tmp_path):
    from scripts.persistence import soft_delete_reflection

    db = tmp_path / "d1miss.db"
    # Create empty schema via a no-op insert and delete
    out = soft_delete_reflection("REF_NOPE", db_path=db)
    assert out["deleted"] is False
    assert out["reason"] == "not_found"


# ---------------------------------------------------------------------------
# I1 — forged-learning vector is closed by S1+S5+S9 stack
# ---------------------------------------------------------------------------


def test_i1_forged_learning_data_blocked(monkeypatch, _safe_env):
    """Composite: unauthenticated POST is refused; token-auth POST is
    stamped with server-side identity; replay protected by L3."""
    srv = _safe_env
    client = TestClient(srv.app)

    # 1. Without token: 401
    r = client.post(
        "/manual-trades",
        json={
            "event_id": "E1",
            "ticker": "AAPL",
            "side": "LONG",
            "quantity": "1",
            "price": "1",
            "thesis": "t",
        },
    )
    assert r.status_code == 401

    # 2. With token but forged logged_by: server stamps over it
    captured = {}

    def _fake_log(**kwargs):
        captured.update(kwargs)
        return {
            "trade_id": "MT_X",
            "status": "logged",
            "advisory_status": "ADVISORY_ONLY",
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": 0,
        }

    monkeypatch.setattr(srv, "log_manual_trade", _fake_log)
    r2 = client.post(
        "/manual-trades",
        headers={"Authorization": "Bearer tok"},
        json={
            "event_id": "E1", "ticker": "AAPL", "side": "LONG",
            "quantity": "1", "price": "1", "thesis": "t",
            "logged_by": "Someone Else Entirely",
        },
    )
    assert r2.status_code == 200
    assert captured["logged_by"].startswith("operator@")
    assert "Someone Else Entirely" not in captured["logged_by"]
