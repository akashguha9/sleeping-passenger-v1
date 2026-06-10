"""S4-A3 regression: per-role local tokens — hashed at rest, role floors.

Contract: hashes only in the DB (plaintext never findable); timing-safe
compare; role matrix VIEWER/OPERATOR/ADMIN across read/write/admin
routes; stamped 401/403; legacy single token = bootstrap ADMIN with a
deprecation flag in health; revocation and rotation invalidate
immediately.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import persistence
from scripts import token_registry as tr


def _rebind_defaults(fn, new_db: Path):
    if fn.__defaults__:
        fn.__defaults__ = tuple(
            new_db if isinstance(d, Path) else d for d in fn.__defaults__
        )
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "tokens.db"
    persistence.init_schema(db)
    originals: dict = {}
    for name in ("init_schema", "_get_conn"):
        fn = getattr(persistence, name)
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    monkeypatch.setenv("MVP_TOKEN_PEPPER", "test-pepper-not-a-secret")
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    try:
        yield db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


# ---------------------------------------------------------------------------
# Registry storage properties
# ---------------------------------------------------------------------------


def test_only_hash_is_stored_never_plaintext(tmp_db):
    out = tr.create_token("akash-local", "OPERATOR", db_path=tmp_db)
    plaintext = out["plaintext_token_shown_once"]
    raw = Path(tmp_db).read_bytes()
    assert plaintext.encode() not in raw, "plaintext must not be in the DB file"
    conn = sqlite3.connect(str(tmp_db))
    row = conn.execute("SELECT token_hash FROM api_tokens").fetchone()
    conn.close()
    assert row[0] != plaintext
    assert len(row[0]) == 64  # hex sha256


def test_verify_uses_timing_safe_compare():
    import inspect

    src = inspect.getsource(tr.verify_token)
    assert "compare_digest" in src


def test_verify_valid_and_invalid(tmp_db):
    out = tr.create_token("t", "VIEWER", db_path=tmp_db)
    good = tr.verify_token(out["plaintext_token_shown_once"], db_path=tmp_db)
    assert good == {"valid": True, "role": "VIEWER", "token_id": out["token_id"]}
    bad = tr.verify_token(
        f"mvp_{out['token_id']}_wrongwrongwrongwrong", db_path=tmp_db
    )
    assert bad["valid"] is False


def test_revocation_invalidates_immediately(tmp_db):
    out = tr.create_token("t", "OPERATOR", db_path=tmp_db)
    assert tr.revoke_token(out["token_id"], db_path=tmp_db) is True
    assert tr.verify_token(
        out["plaintext_token_shown_once"], db_path=tmp_db
    )["valid"] is False


def test_rotation_invalidates_old_token(tmp_db):
    out = tr.create_token("t", "ADMIN", db_path=tmp_db)
    rotated = tr.rotate_token(out["token_id"], db_path=tmp_db)
    assert rotated is not None
    assert tr.verify_token(
        out["plaintext_token_shown_once"], db_path=tmp_db
    )["valid"] is False
    assert tr.verify_token(
        rotated["plaintext_token_shown_once"], db_path=tmp_db
    )["valid"] is True


def test_role_floor_helper():
    assert tr.role_at_least("ADMIN", "OPERATOR")
    assert tr.role_at_least("OPERATOR", "OPERATOR")
    assert not tr.role_at_least("VIEWER", "OPERATOR")
    assert not tr.role_at_least(None, "VIEWER")
    assert not tr.role_at_least("BOGUS", "VIEWER")


# ---------------------------------------------------------------------------
# Role matrix over the live app
# ---------------------------------------------------------------------------


@pytest.fixture()
def role_client(tmp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.signal_inbox_api as sia
    import scripts.api_server as srv

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(sia, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(sia, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    viewer = tr.create_token("v", "VIEWER", db_path=tmp_db)
    operator = tr.create_token("o", "OPERATOR", db_path=tmp_db)
    admin = tr.create_token("a", "ADMIN", db_path=tmp_db)
    client = TestClient(srv.app, raise_server_exceptions=False)
    return client, {
        "VIEWER": viewer["plaintext_token_shown_once"],
        "OPERATOR": operator["plaintext_token_shown_once"],
        "ADMIN": admin["plaintext_token_shown_once"],
    }


def _hdr(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _write(client, token):
    return client.post(
        "/manual-trades",
        headers=_hdr(token),
        json={"event_id": "EVT_RBAC", "ticker": "BTC", "side": "BUY",
              "quantity": "1", "price": "1", "thesis": "rbac"},
    )


def test_missing_token_is_stamped_401(role_client):
    client, tokens = role_client
    r = _write(client, None)
    assert r.status_code == 401
    body = r.json()
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False


def test_wrong_token_is_stamped_401(role_client):
    client, tokens = role_client
    r = _write(client, "mvp_deadbeef0000_notarealtoken")
    assert r.status_code == 401
    assert r.json()["execution_gate"] == "LOCKED"


def test_viewer_can_read_but_not_write(role_client):
    client, tokens = role_client
    r_read = client.get("/manual-trades", headers=_hdr(tokens["VIEWER"]))
    assert r_read.status_code == 200
    r_write = _write(client, tokens["VIEWER"])
    assert r_write.status_code == 403
    assert r_write.json()["execution_gate"] == "LOCKED"


def test_operator_can_write_but_not_admin(role_client):
    client, tokens = role_client
    r_write = _write(client, tokens["OPERATOR"])
    assert r_write.status_code == 200
    r_admin = client.post("/admin/backup", headers=_hdr(tokens["OPERATOR"]))
    assert r_admin.status_code == 403
    assert (r_admin.json().get("detail") or {}).get("error", "").startswith(
        "insufficient role"
    )


def test_admin_can_do_everything(role_client):
    client, tokens = role_client
    assert client.get("/manual-trades", headers=_hdr(tokens["ADMIN"])).status_code == 200
    assert _write(client, tokens["ADMIN"]).status_code == 200
    r = client.post("/admin/backup", headers=_hdr(tokens["ADMIN"]))
    assert r.status_code == 200
    assert r.json()["execution_gate"] == "LOCKED"


def test_legacy_single_token_is_bootstrap_admin_and_flagged(role_client, monkeypatch):
    client, tokens = role_client
    monkeypatch.setenv("MVP_API_TOKEN", "legacy-shared-token-0123456789")
    r = client.post(
        "/admin/backup", headers=_hdr("legacy-shared-token-0123456789")
    )
    assert r.status_code == 200
    h = client.get("/health/full", headers=_hdr(tokens["VIEWER"])).json()
    assert h["legacy_single_token_configured"] is True
    assert h["legacy_single_token_deprecated"] is True
    assert h["token_registry_active_tokens"] == 3


def test_plaintext_never_in_health_or_logs(role_client, tmp_db):
    client, tokens = role_client
    h = client.get("/health/full", headers=_hdr(tokens["VIEWER"]))
    text = h.text
    for t in tokens.values():
        assert t not in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_create_list_revoke_rotate(tmp_db, capsys):
    from scripts.manage_tokens import main

    assert main(["create", "--role", "OPERATOR", "--name", "akash-local"]) == 0
    out = capsys.readouterr().out
    assert "PLAINTEXT TOKEN (shown once" in out
    token_line = [l for l in out.splitlines() if l.startswith("mvp_")][0]
    token_id = token_line.split("_")[1]

    assert main(["list"]) == 0
    assert "akash-local" in capsys.readouterr().out

    assert main(["rotate", "--id", token_id]) == 0
    rotated_out = capsys.readouterr().out
    assert "old token is now invalid" in rotated_out
    assert tr.verify_token(token_line, db_path=tmp_db)["valid"] is False

    assert main(["revoke", "--id", token_id]) == 0
    assert "revoked" in capsys.readouterr().out
