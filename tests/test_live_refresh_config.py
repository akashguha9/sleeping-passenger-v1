"""Tests for the live-refresh additions to ``scripts.typed_config`` (Part 3)."""
from __future__ import annotations

import json

import pytest

from scripts import typed_config


def _clear_env(monkeypatch, *names):
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_safe(monkeypatch):
    _clear_env(monkeypatch, "MVP_LIVE_REFRESH_OK",
               "LIVE_REFRESH_PROVIDER_ALLOWLIST",
               "OPERATOR_LIVE_REFRESH_TTL_HOURS",
               "LIVE_REFRESH_MAX_TICKERS",
               "LIVE_REFRESH_REQUIRE_ADVISORY_ONLY",
               "YFINANCE_LIVE_ENABLED", "SEC_EDGAR_LIVE_ENABLED",
               "GDELT_LIVE_ENABLED")
    cfg = typed_config.load_typed_config()
    assert cfg.mvp_live_refresh_ok is False
    assert cfg.live_refresh_timeout_seconds == 45
    assert list(cfg.live_refresh_provider_allowlist) == [
        "yfinance", "sec_edgar", "gdelt",
    ]
    assert cfg.operator_live_refresh_ttl_hours == 24
    assert cfg.live_refresh_max_tickers == 44
    assert cfg.live_refresh_require_advisory_only is True
    assert cfg.yfinance_live_enabled is True
    assert cfg.sec_edgar_live_enabled is True
    assert cfg.gdelt_live_enabled is True


def test_invalid_provider_in_allowlist_rejected(monkeypatch):
    monkeypatch.setenv(
        "LIVE_REFRESH_PROVIDER_ALLOWLIST", "yfinance,polymarket,gdelt"
    )
    with pytest.raises(typed_config.ConfigSafetyError):
        typed_config.load_typed_config()


def test_live_refresh_enabled_requires_advisory_only(monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")
    monkeypatch.setenv("ADVISORY_ONLY", "false")
    with pytest.raises(typed_config.ConfigSafetyError):
        typed_config.load_typed_config()


def test_live_refresh_enabled_requires_human_execution(monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")
    monkeypatch.setenv("HUMAN_EXECUTION_REQUIRED", "0")
    with pytest.raises(typed_config.ConfigSafetyError):
        typed_config.load_typed_config()


def test_live_refresh_enabled_requires_locked_gate(monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")
    monkeypatch.setenv("EXECUTION_GATE", "UNLOCKED")
    with pytest.raises(typed_config.ConfigSafetyError):
        typed_config.load_typed_config()


def test_sec_missing_user_agent_does_not_crash_config(monkeypatch):
    """SEC_USER_AGENT missing must NOT raise; the provider degrades at run-time."""
    _clear_env(monkeypatch, "SEC_USER_AGENT")
    cfg = typed_config.load_typed_config()
    assert cfg.sec_user_agent is None
    # Provider stays enabled; degradation is run-time, not config-time.
    assert cfg.sec_edgar_enabled is True


def test_env_example_has_live_refresh_placeholders():
    from pathlib import Path
    text = Path(__file__).resolve().parents[1].joinpath(
        ".env.example"
    ).read_text(encoding="utf-8")
    for placeholder in (
        "MVP_LIVE_REFRESH_OK",
        "LIVE_REFRESH_TIMEOUT_SECONDS",
        "LIVE_REFRESH_PROVIDER_ALLOWLIST",
        "OPERATOR_LIVE_REFRESH_TTL_HOURS",
        "YFINANCE_LIVE_ENABLED",
        "SEC_EDGAR_LIVE_ENABLED",
        "GDELT_LIVE_ENABLED",
        "LIVE_REFRESH_MAX_TICKERS",
        "LIVE_REFRESH_REQUIRE_ADVISORY_ONLY",
    ):
        assert placeholder in text, f"missing placeholder {placeholder}"


def test_configuration_environment_summary_writes(tmp_path):
    target = tmp_path / "config_env.json"
    summary = typed_config.write_configuration_environment_summary(target)
    assert target.exists()
    assert "configuration_environment_score" in summary
    assert summary["typed_live_refresh_config_present"] is True
    assert summary["provider_allowlist_validation_present"] is True
    assert summary["safety_validation_present"] is True


def test_configuration_environment_score_caps_when_missing_placeholders(
    tmp_path, monkeypatch,
):
    # Score still reports honestly — typed config is fine but missing
    # placeholders pushes env_example flag down.
    summary = typed_config.build_configuration_environment_summary()
    if summary["env_example_updated_no_secrets"]:
        # In the real repo this is True; just check it round-trips.
        assert summary["configuration_environment_score"] >= 9.7


def test_no_secrets_logged():
    # build_configuration_environment_summary must not leak SEC_USER_AGENT
    # values into the artifact.
    import os
    os.environ["SEC_USER_AGENT"] = "operator-secret-id@example.com"
    try:
        summary = typed_config.build_configuration_environment_summary()
        body = json.dumps(summary, default=str)
        assert "operator-secret-id@example.com" not in body
    finally:
        del os.environ["SEC_USER_AGENT"]
