"""Emergency lockdown mode proofs (Pass 3, Phase 7)."""
from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import scripts.api_server as srv  # noqa: E402
import scripts.runtime_config as rc  # noqa: E402

TOKEN = "lockdown-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def lockdown_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MVP_API_TOKEN", TOKEN)
    monkeypatch.delenv("MVP_API_TOKEN_HASH", raising=False)
    monkeypatch.setenv("MVP_LOCKDOWN_MODE", "1")
    monkeypatch.setenv("MVP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    return TestClient(srv.app), tmp_path / "audit.jsonl"


def test_lockdown_flag_helper(monkeypatch):
    monkeypatch.delenv("MVP_LOCKDOWN_MODE", raising=False)
    assert rc.lockdown_mode_active() is False
    monkeypatch.setenv("MVP_LOCKDOWN_MODE", "1")
    assert rc.lockdown_mode_active() is True


def test_all_mutating_routes_blocked_with_423(lockdown_client):
    client, _ = lockdown_client
    mutating = [
        ("POST", "/manual-trades"),
        ("POST", "/moltbook"),
        ("POST", "/signals/EV1/validate"),
        ("POST", "/signals/EV1/reflection"),
        ("POST", "/manual-trades/T1/reconcile"),
        ("POST", "/reconciliation/auto-update"),
        ("DELETE", "/reflections/R1"),
        ("POST", "/chart-structure/bootstrap-symbol"),
    ]
    for method, path in mutating:
        r = client.request(method, path, headers=AUTH, json={})
        assert r.status_code == 423, f"{method} {path} → {r.status_code}"
        body = r.json()
        assert body["error"] == "lockdown_mode_active"
        # Advisory invariants stamp even on the lockdown path.
        assert body["execution_gate"] == "LOCKED"
        assert body["broker_api_called"] is False


def test_reads_still_work_with_token_during_lockdown(lockdown_client):
    client, _ = lockdown_client
    assert client.get("/manual-trades", headers=AUTH).status_code == 200
    assert client.get("/health").status_code == 200


def test_unauth_reads_still_blocked_during_lockdown(lockdown_client):
    client, _ = lockdown_client
    assert client.get("/manual-trades").status_code == 401


def test_lockdown_visible_on_health(lockdown_client, monkeypatch):
    client, _ = lockdown_client
    assert client.get("/health").json()["lockdown_mode"] is True
    monkeypatch.setenv("MVP_LOCKDOWN_MODE", "0")
    assert client.get("/health").json()["lockdown_mode"] is False


def test_lockdown_block_emits_chained_audit_event(lockdown_client):
    from scripts import verify_audit_log as val

    client, audit_path = lockdown_client
    client.post("/manual-trades", headers=AUTH, json={})
    events = [
        json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(e["event_type"] == "lockdown_block" for e in events)
    assert val.verify_chain(audit_path)["valid"] is True


def test_restore_script_refuses_under_lockdown(monkeypatch, tmp_path):
    from scripts import restore_private_data as rpd

    monkeypatch.setenv("MVP_LOCKDOWN_MODE", "1")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"archive": "x.tar.gz", "archive_sha256": "0" * 64,
                    "encrypted": False}),
        encoding="utf-8",
    )
    with pytest.raises(rpd.RestoreRefused) as ei:
        rpd.restore(manifest)
    assert "LOCKDOWN" in str(ei.value).upper()


def test_streamlit_warns_on_lockdown():
    import pathlib

    text = pathlib.Path("src/dashboard/streamlit_app.py").read_text(encoding="utf-8")
    assert "MVP_LOCKDOWN_MODE" in text
    assert "LOCKDOWN" in text.upper()


def test_frontend_banner_component_exists():
    import pathlib

    banner = pathlib.Path("frontend/src/components/LockdownBanner.tsx")
    layout = pathlib.Path("frontend/src/app/layout.tsx")
    assert banner.exists()
    assert "lockdown_mode" in banner.read_text(encoding="utf-8")
    assert "LockdownBanner" in layout.read_text(encoding="utf-8")
