"""Secret custody proofs (Pass 3, Phase 4) — synthetic providers only."""
from __future__ import annotations

import pytest

from scripts import manage_secrets as ms
from scripts import secret_provider as sp


@pytest.fixture
def clean_env(monkeypatch):
    for name in sp.known_secret_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SECRET_PROVIDER", raising=False)
    return monkeypatch


def test_known_names_come_from_config_contract(clean_env):
    names = sp.known_secret_names()
    assert "EDINET_API_KEY" in names
    assert "XAI_API_KEY" in names
    # The owner token has its own lifecycle and is excluded from custody.
    assert not any(n.startswith("MVP_API_TOKEN") for n in names)


def test_env_provider_roundtrip_and_missing_secret(clean_env):
    provider = sp.EnvProvider()
    assert provider.get("EDINET_API_KEY") is None  # missing fails safely
    provider.set("EDINET_API_KEY", "synthetic-test-value")
    assert provider.get("EDINET_API_KEY") == "synthetic-test-value"
    assert "EDINET_API_KEY" in provider.list_set_names()
    provider.delete("EDINET_API_KEY")
    assert provider.get("EDINET_API_KEY") is None


def test_default_mode_is_env_and_invalid_modes_fall_back(clean_env):
    assert sp.configured_mode() == sp.MODE_ENV
    clean_env.setenv("SECRET_PROVIDER", "definitely-not-a-mode")
    assert sp.configured_mode() == sp.MODE_ENV
    assert isinstance(sp.get_provider(), sp.EnvProvider)


def test_wcm_provider_unavailable_off_windows(clean_env):
    import sys

    if sys.platform == "win32":
        pytest.skip("Windows host: WCM is actually available")
    with pytest.raises(sp.SecretProviderError):
        sp.get_provider(sp.MODE_WCM)


def test_resolve_secret_falls_back_to_env(clean_env):
    clean_env.setenv("SECRET_PROVIDER", sp.MODE_WCM)  # unavailable here
    clean_env.setenv("OPENDART_API_KEY", "env-fallback-value")
    assert sp.resolve_secret("OPENDART_API_KEY") == "env-fallback-value"
    assert sp.resolve_secret("EDINET_API_KEY") is None


def test_hydrate_is_noop_in_env_mode_and_when_wcm_unavailable(clean_env):
    assert sp.hydrate_environment() == 0
    clean_env.setenv("SECRET_PROVIDER", sp.MODE_WCM)
    assert sp.hydrate_environment() == 0  # unavailable off-Windows: no-op, no raise


# ---------------------------------------------------------------------------
# CLI: redaction, raw reveal flag, stdin set, audit
# ---------------------------------------------------------------------------


def test_cli_get_is_redacted_by_default(clean_env, capsys):
    provider = sp.InMemoryProvider()
    provider.set("EDINET_API_KEY", "raw-secret-abc")
    assert ms.cmd_get(provider, "EDINET_API_KEY", show_secret=None) == 0
    out = capsys.readouterr().out
    assert ms.REDACTED in out
    assert "raw-secret-abc" not in out


def test_cli_raw_reveal_requires_exact_acknowledgement(clean_env, capsys):
    provider = sp.InMemoryProvider()
    provider.set("EDINET_API_KEY", "raw-secret-abc")
    assert ms.cmd_get(provider, "EDINET_API_KEY", show_secret="I_UNDERSTAND") == 0
    assert "raw-secret-abc" in capsys.readouterr().out
    # Wrong acknowledgement string at the CLI layer → refused, value unseen.
    monkey_provider = sp.InMemoryProvider()
    monkey_provider.set("EDINET_API_KEY", "raw-secret-abc")
    rc = ms.main(["get", "--name", "EDINET_API_KEY", "--show-secret", "yes"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "raw-secret-abc" not in captured.out + captured.err


def test_cli_get_missing_secret_fails_safely(clean_env, capsys):
    assert ms.cmd_get(sp.InMemoryProvider(), "EDINET_API_KEY", None) == 1
    assert ms.NOT_SET in capsys.readouterr().out


def test_cli_set_reads_value_from_stdin_not_argv(clean_env, capsys):
    import io

    provider = sp.InMemoryProvider()
    assert ms.cmd_set(provider, "EDINET_API_KEY", stdin=io.StringIO("stdin-value\n")) == 0
    assert provider.get("EDINET_API_KEY") == "stdin-value"
    # Empty input stores nothing.
    assert ms.cmd_set(provider, "XAI_API_KEY", stdin=io.StringIO("\n")) == 2
    assert provider.get("XAI_API_KEY") is None


def test_cli_unknown_name_refused(clean_env):
    with pytest.raises(SystemExit):
        ms.cmd_get(sp.InMemoryProvider(), "TOTALLY_UNKNOWN_KEY", None)


def test_cli_list_names_marks_set_state(clean_env, capsys):
    provider = sp.InMemoryProvider()
    provider.set("EDINET_API_KEY", "zq9-distinctive-secret")
    ms.cmd_list_names(provider)
    out = capsys.readouterr().out
    assert "EDINET_API_KEY: SET" in out
    assert "OPENDART_API_KEY: not set" in out
    assert "zq9-distinctive-secret" not in out  # value never printed


def test_cli_audit_passes_on_clean_repo(clean_env, capsys):
    assert ms.cmd_audit() == 0
    assert "PASS" in capsys.readouterr().out
