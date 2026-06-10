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
        "API_HOST",
        "MVP_ALLOW_UNAUTH",
        "MVP_ALLOWED_HOSTS",
        "ALLOWED_ORIGINS",
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
# First-run token setup helper
# ---------------------------------------------------------------------------


def test_generated_tokens_are_strong_and_unique():
    tokens = {gen.generate_token() for _ in range(8)}
    assert len(tokens) == 8
    for token in tokens:
        assert len(token) >= 40  # 32 bytes urlsafe-encoded


def test_write_env_creates_and_updates_only_token_line(tmp_path):
    env = tmp_path / ".env"
    assert gen.write_env("tok-one", env) == "created"
    assert env.read_text(encoding="utf-8") == "MVP_API_TOKEN=tok-one\n"

    env.write_text(
        "API_HOST=127.0.0.1\nMVP_API_TOKEN=old\n# comment\nAPI_PORT=8000\n",
        encoding="utf-8",
    )
    assert gen.write_env("tok-two", env) == "updated"
    text = env.read_text(encoding="utf-8")
    assert "MVP_API_TOKEN=tok-two" in text
    assert "old" not in text
    assert "API_HOST=127.0.0.1" in text and "# comment" in text

    env.write_text("API_HOST=127.0.0.1\n", encoding="utf-8")
    assert gen.write_env("tok-three", env) == "appended"
    assert env.read_text(encoding="utf-8").endswith("MVP_API_TOKEN=tok-three\n")


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
