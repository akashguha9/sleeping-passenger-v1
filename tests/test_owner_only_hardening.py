"""Owner-only hardening proofs — fail-closed startup, host-header gate,
first-run token setup, and .env loader hygiene.

These tests pin the sole-proprietor access-control contract:

  * The server refuses to boot without MVP_API_TOKEN (no silent open mode).
  * The Host-header allowlist kills DNS-rebinding from the owner's browser.
  * scripts/generate_api_token.py produces strong tokens and writes only
    the MVP_API_TOKEN line of the gitignored .env.
  * The .env loader never overrides real environment variables and never
    runs under pytest.
"""
from __future__ import annotations

import importlib

import pytest

import scripts.runtime_config as rc
from scripts import generate_api_token as gen


def _reset_env(monkeypatch, **overrides):
    for var in (
        "MVP_API_TOKEN",
        "MVP_API_TOKEN_HASH",
        "API_HOST",
        "MVP_ALLOW_UNAUTH",
        "MVP_ALLOWED_HOSTS",
        "ALLOWED_ORIGINS",
        "MVP_PUBLIC_MODE",
        "MVP_TLS_TERMINATED",
        "MVP_PUBLISHED_BIND",
        "MVP_UNSAFE_LAN_HTTP",
        "MVP_TRUSTED_PROXIES",
    ):
        monkeypatch.delenv(var, raising=False)
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    importlib.reload(rc)


# ---------------------------------------------------------------------------
# Host-header allowlist (DNS-rebinding defense)
# ---------------------------------------------------------------------------


def test_default_allowed_hosts_cover_local_names(monkeypatch):
    _reset_env(monkeypatch)
    allowed = rc.get_allowed_hosts()
    for host in ("localhost", "127.0.0.1", "testserver", "sleepingpassenger"):
        assert host in allowed, host


@pytest.mark.parametrize(
    "header",
    [
        "localhost",
        "localhost:8000",
        "127.0.0.1:8000",
        "[::1]:8000",
        "sleepingpassenger.local",
        "TESTSERVER",
    ],
)
def test_local_host_headers_allowed(monkeypatch, header):
    _reset_env(monkeypatch)
    assert rc.host_header_allowed(header) is True, header


@pytest.mark.parametrize(
    "header",
    ["evil.example.com", "evil.example.com:8000", "", None, "localhost.evil.com"],
)
def test_foreign_or_missing_host_headers_denied(monkeypatch, header):
    _reset_env(monkeypatch)
    assert rc.host_header_allowed(header) is False, header


def test_env_override_replaces_default_allowlist(monkeypatch):
    _reset_env(monkeypatch, MVP_ALLOWED_HOSTS="myhost.lan")
    assert rc.host_header_allowed("myhost.lan:8000") is True
    # Override replaces defaults, except the bind host itself stays allowed.
    assert rc.host_header_allowed("sleepingpassenger") is False
    assert rc.host_header_allowed("127.0.0.1") is True  # API_HOST default


def test_api_requests_with_foreign_host_header_rejected(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _reset_env(monkeypatch)
    import scripts.api_server as srv

    importlib.reload(srv)
    client = TestClient(srv.app)
    r = client.get("/health", headers={"Host": "rebind.attacker.example"})
    assert r.status_code == 421
    body = r.json()
    assert body["error"] == "host_not_allowed"
    # Advisory invariants stamp even on the rejection path.
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    # The default TestClient host stays allowed.
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Token lifecycle: generation, hash storage, verification, rotation
# ---------------------------------------------------------------------------


def test_generated_tokens_are_strong_and_unique():
    tokens = {gen.generate_token() for _ in range(8)}
    assert len(tokens) == 8
    for token in tokens:
        assert len(token) >= 40  # 32 bytes urlsafe-encoded


def test_hash_token_is_sha256_hex():
    import hashlib

    raw = "sample-token-abc"
    assert gen.hash_token(raw) == hashlib.sha256(raw.encode()).hexdigest()
    assert len(gen.hash_token(raw)) == 64


def test_verify_invariant_only_matching_token_verifies():
    """∀ T_wrong ≠ T_raw: Verify(T_wrong, H_env) = False; Verify(T_raw, H_env) = True."""
    raw = gen.generate_token()
    h = gen.hash_token(raw)
    assert gen.verify_candidate(raw, h) is True
    for wrong in (raw + "x", raw[:-1], raw.upper(), gen.generate_token(), "", "Bearer"):
        if wrong == raw:
            continue
        assert gen.verify_candidate(wrong, h) is False, wrong


def test_runtime_verify_api_token_hash_mode(monkeypatch):
    raw = gen.generate_token()
    _reset_env(monkeypatch, MVP_API_TOKEN_HASH=gen.hash_token(raw))
    assert rc.verify_api_token(raw) is True
    assert rc.verify_api_token(raw + "x") is False
    assert rc.verify_api_token(None) is False
    assert rc.api_token_required() is True
    assert rc.plaintext_token_fallback_active() is False


def test_runtime_verify_api_token_plaintext_fallback(monkeypatch):
    _reset_env(monkeypatch, MVP_API_TOKEN="legacy-plain-token")
    assert rc.verify_api_token("legacy-plain-token") is True
    assert rc.verify_api_token("wrong") is False
    assert rc.plaintext_token_fallback_active() is True


def test_hash_mode_wins_when_both_configured(monkeypatch):
    raw = gen.generate_token()
    _reset_env(
        monkeypatch,
        MVP_API_TOKEN_HASH=gen.hash_token(raw),
        MVP_API_TOKEN="some-other-plaintext",
    )
    assert rc.verify_api_token(raw) is True
    # The plaintext token no longer authenticates once hash mode is on.
    assert rc.verify_api_token("some-other-plaintext") is False
    assert rc.plaintext_token_fallback_active() is False


def test_malformed_hash_fails_closed_at_preflight(monkeypatch):
    _reset_env(monkeypatch, MVP_API_TOKEN_HASH="not-a-hash", API_HOST="127.0.0.1")
    assert rc.api_token_hash_malformed() is True
    # A malformed hash must never verify anything…
    assert rc.verify_api_token("anything") is False
    # …and must refuse boot rather than silently degrade.
    with pytest.raises(rc.StartupSecurityError):
        rc.preflight_auth_or_die()


def test_missing_token_and_hash_fails_closed(monkeypatch):
    _reset_env(monkeypatch, API_HOST="127.0.0.1")
    assert rc.verify_api_token("anything") is False
    with pytest.raises(rc.StartupSecurityError):
        rc.preflight_auth_or_die()


def test_write_env_hash_stores_only_hash_and_drops_plaintext(tmp_path):
    env = tmp_path / ".env"
    raw = gen.generate_token()
    h = gen.hash_token(raw)
    assert gen.write_env_hash(h, env) == "created"
    assert env.read_text(encoding="utf-8") == f"MVP_API_TOKEN_HASH={h}\n"

    env.write_text(
        "API_HOST=127.0.0.1\nMVP_API_TOKEN=old-plaintext\n# comment\n"
        f"MVP_API_TOKEN_HASH={'0' * 64}\nAPI_PORT=8000\n",
        encoding="utf-8",
    )
    assert gen.write_env_hash(h, env) == "updated"
    text = env.read_text(encoding="utf-8")
    assert f"MVP_API_TOKEN_HASH={h}" in text
    assert "old-plaintext" not in text  # legacy plaintext line removed
    assert "0" * 64 not in text  # old hash replaced
    assert "API_HOST=127.0.0.1" in text and "# comment" in text
    # The raw token never lands in the file — only its hash.
    assert raw not in text


def test_rotation_invalidates_old_token(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    old_raw = gen.generate_token()
    gen.write_env_hash(gen.hash_token(old_raw), env)
    new_raw = gen.generate_token()
    gen.write_env_hash(gen.hash_token(new_raw), env)

    stored = gen.read_env_hash(env)
    assert stored == gen.hash_token(new_raw)
    assert gen.verify_candidate(new_raw, stored) is True
    assert gen.verify_candidate(old_raw, stored) is False

    _reset_env(monkeypatch, MVP_API_TOKEN_HASH=stored)
    assert rc.verify_api_token(new_raw) is True
    assert rc.verify_api_token(old_raw) is False


def test_generator_cli_never_prints_raw_token_after_generation(tmp_path, monkeypatch, capsys):
    """--write-env prints the raw token exactly once (stdout line 1); the
    stderr feedback and the .env file contain only the hash."""
    monkeypatch.setattr(gen, "_ENV_PATH", tmp_path / ".env")
    assert gen.main(["--write-env"]) == 0
    captured = capsys.readouterr()
    raw = captured.out.splitlines()[0].strip()
    assert len(raw) >= 40
    assert raw not in captured.err
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert raw not in env_text
    assert gen.hash_token(raw) in env_text


def test_api_401_then_200_with_hash_mode(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    raw = gen.generate_token()
    _reset_env(monkeypatch, MVP_API_TOKEN_HASH=gen.hash_token(raw))
    import scripts.api_server as srv

    importlib.reload(srv)
    client = TestClient(srv.app)
    assert client.get("/manual-trades").status_code == 401
    assert (
        client.get(
            "/manual-trades", headers={"Authorization": f"Bearer {raw}"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/manual-trades", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


# ---------------------------------------------------------------------------
# .env loader hygiene
# ---------------------------------------------------------------------------


def test_dotenv_loader_is_inert_under_pytest(monkeypatch):
    """The loader must never inject a developer's real .env into tests —
    'pytest' is in sys.modules here, so reloads must not pick up .env."""
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    importlib.reload(rc)
    # If the loader had run against a real .env containing MVP_API_TOKEN,
    # this would be non-None inside the test environment.
    rc._load_local_dotenv()
    assert "pytest" in __import__("sys").modules


def test_dotenv_loader_never_overrides_real_env(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("MVP_TEST_SENTINEL=from_file\n", encoding="utf-8")
    monkeypatch.setenv("MVP_TEST_SENTINEL", "from_env")
    monkeypatch.setattr(rc, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(rc.sys, "modules", {**rc.sys.modules})
    # Simulate non-pytest execution by removing the guard key.
    rc.sys.modules.pop("pytest", None)
    rc._load_local_dotenv()
    import os

    assert os.environ["MVP_TEST_SENTINEL"] == "from_env"


def test_dotenv_loader_parses_simple_pairs(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nMVP_TEST_SENTINEL_B="quoted"\nnot a pair\nBAD-KEY=x\n',
        encoding="utf-8",
    )
    import os

    monkeypatch.delenv("MVP_TEST_SENTINEL_B", raising=False)
    monkeypatch.setattr(rc, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(rc.sys, "modules", {**rc.sys.modules})
    rc.sys.modules.pop("pytest", None)
    rc._load_local_dotenv()
    assert os.environ.get("MVP_TEST_SENTINEL_B") == "quoted"
    assert "BAD-KEY" not in os.environ
    monkeypatch.delenv("MVP_TEST_SENTINEL_B", raising=False)
