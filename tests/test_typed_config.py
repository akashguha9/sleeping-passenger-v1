"""Tests for the integrated-sprint typed config schema."""
from __future__ import annotations

import os

import pytest

from scripts import typed_config


def _clear_env(monkeypatch, *names):
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_defaults_load_safely(monkeypatch):
    _clear_env(
        monkeypatch,
        "ADVISORY_ONLY", "HUMAN_EXECUTION_REQUIRED", "EXECUTION_GATE",
        "DIAGNOSTICS_SNAPSHOT_TTL_SECONDS",
    )
    cfg = typed_config.load_typed_config()
    assert cfg.advisory_only is True
    assert cfg.human_execution_required is True
    assert cfg.execution_gate.upper() == "LOCKED"
    assert cfg.diagnostics_snapshot_ttl_seconds == 300
    assert cfg.diagnostics_cold_recompute_budget_ms == 8000


def test_invalid_numeric_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_SNAPSHOT_TTL_SECONDS", "not-a-number")
    cfg = typed_config.load_typed_config()
    assert cfg.diagnostics_snapshot_ttl_seconds == 300


def test_out_of_range_int_falls_back(monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_HOT_CACHE_BUDGET_MS", "999999999")
    cfg = typed_config.load_typed_config()
    assert cfg.diagnostics_hot_cache_budget_ms == 750


def test_safety_breaking_advisory_off_fails(monkeypatch):
    monkeypatch.setenv("ADVISORY_ONLY", "false")
    with pytest.raises(typed_config.ConfigSafetyError):
        typed_config.load_typed_config()


def test_safety_breaking_human_execution_off_fails(monkeypatch):
    monkeypatch.setenv("HUMAN_EXECUTION_REQUIRED", "0")
    with pytest.raises(typed_config.ConfigSafetyError):
        typed_config.load_typed_config()


def test_safety_breaking_execution_gate_unlocked_fails(monkeypatch):
    monkeypatch.setenv("EXECUTION_GATE", "UNLOCKED")
    with pytest.raises(typed_config.ConfigSafetyError):
        typed_config.load_typed_config()


def test_validate_typed_config_reports_ok_by_default(monkeypatch):
    _clear_env(
        monkeypatch,
        "ADVISORY_ONLY", "HUMAN_EXECUTION_REQUIRED", "EXECUTION_GATE",
    )
    result = typed_config.validate_typed_config()
    assert result["typed_config_ok"] is True
    assert result["advisory_only"] is True


def test_validate_typed_config_surfaces_safety_failure(monkeypatch):
    monkeypatch.setenv("ADVISORY_ONLY", "false")
    result = typed_config.validate_typed_config()
    assert result["typed_config_ok"] is False
    assert "ADVISORY_ONLY" in result["reason"]


def test_to_dict_includes_advisory_stamps(monkeypatch):
    _clear_env(monkeypatch, "ADVISORY_ONLY")
    cfg = typed_config.load_typed_config()
    blob = cfg.to_dict()
    assert blob["advisory_status"] == "ADVISORY_ONLY"
    assert blob["execution_gate"] == "LOCKED"
    assert blob["broker_api_called"] is False
    assert blob["ai_execution_count"] == 0


def test_env_example_has_no_real_secrets():
    import re
    from pathlib import Path
    text = Path(__file__).resolve().parents[1].joinpath(".env.example").read_text(
        encoding="utf-8")
    # Sanity: no inline xai-/sk- token sequences in the placeholder file.
    assert not re.search(r"xai-[A-Za-z0-9]{16,}", text)
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", text)
    # Sanity: ADVISORY_ONLY defaults are present.
    assert "ADVISORY_ONLY=true" in text
    assert "HUMAN_EXECUTION_REQUIRED=true" in text
    assert "EXECUTION_GATE=LOCKED" in text
