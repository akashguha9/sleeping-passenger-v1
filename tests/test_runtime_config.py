"""
Tests for scripts.runtime_config — the env-driven central config helper.

Validates:
  * env-driven overrides of API_HOST / API_PORT / ALLOWED_ORIGINS
  * default fallbacks when env vars are unset
  * MVP_API_TOKEN presence flag
  * MVP_DB_PATH override + safe display string
  * advisory safety constants are stable
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.runtime_config as rc


def test_advisory_constants_locked():
    assert rc.ADVISORY_STATUS == "ADVISORY_ONLY"
    assert rc.EXECUTION_MODE == "HUMAN_ONLY"
    assert rc.EXECUTION_GATE == "LOCKED"
    assert rc.AI_EXECUTION_COUNT == 0
    assert rc.BROKER_API_CALLED is False
    assert rc.BROKER_ORDER_ID == "NONE"


def test_runtime_safety_stamps_block_locked():
    stamps = rc.runtime_safety_stamps()
    assert stamps["advisory_status"] == "ADVISORY_ONLY"
    assert stamps["execution_mode"] == "HUMAN_ONLY"
    assert stamps["execution_gate"] == "LOCKED"
    assert stamps["ai_execution_count"] == 0
    assert stamps["broker_api_called"] is False
    assert stamps["broker_order_id"] == "NONE"
    assert stamps["human_review_required"] is True


def test_default_api_host(monkeypatch):
    monkeypatch.delenv("API_HOST", raising=False)
    assert rc.get_api_host() == "127.0.0.1"


def test_override_api_host(monkeypatch):
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    assert rc.get_api_host() == "0.0.0.0"


def test_default_api_port(monkeypatch):
    monkeypatch.delenv("API_PORT", raising=False)
    assert rc.get_api_port() == 8000


def test_override_api_port(monkeypatch):
    monkeypatch.setenv("API_PORT", "9090")
    assert rc.get_api_port() == 9090


def test_invalid_api_port_falls_back(monkeypatch):
    monkeypatch.setenv("API_PORT", "not-a-number")
    assert rc.get_api_port() == 8000


def test_out_of_range_api_port_falls_back(monkeypatch):
    monkeypatch.setenv("API_PORT", "999999")
    assert rc.get_api_port() == 8000


def test_default_allowed_origins(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    origins = rc.get_allowed_origins()
    assert "http://localhost:3000" in origins
    assert "http://127.0.0.1:3000" in origins


def test_override_allowed_origins(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.example, http://b.example ,")
    origins = rc.get_allowed_origins()
    assert origins == ["http://a.example", "http://b.example"]


def test_token_unset(monkeypatch):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    assert rc.get_api_token() is None
    assert rc.api_token_required() is False


def test_token_empty_string_treated_as_unset(monkeypatch):
    monkeypatch.setenv("MVP_API_TOKEN", "   ")
    assert rc.get_api_token() is None
    assert rc.api_token_required() is False


def test_token_set(monkeypatch):
    monkeypatch.setenv("MVP_API_TOKEN", "secret")
    assert rc.get_api_token() == "secret"
    assert rc.api_token_required() is True


def test_environment_tag_default(monkeypatch):
    monkeypatch.delenv("MVP_ENVIRONMENT", raising=False)
    assert rc.get_environment_tag() == "local"


def test_environment_tag_override(monkeypatch):
    monkeypatch.setenv("MVP_ENVIRONMENT", "staging")
    assert rc.get_environment_tag() == "staging"


def test_default_db_path(monkeypatch):
    monkeypatch.delenv("MVP_DB_PATH", raising=False)
    p = rc.get_db_path()
    assert isinstance(p, Path)
    assert p.name == "mvp_local.db"
    assert p.parent.name == "runtime"


def test_db_path_override(monkeypatch, tmp_path):
    target = tmp_path / "custom.db"
    monkeypatch.setenv("MVP_DB_PATH", str(target))
    assert rc.get_db_path() == target


def test_safe_db_display_path_default(monkeypatch):
    monkeypatch.delenv("MVP_DB_PATH", raising=False)
    display = rc.safe_db_display_path()
    # Default repo-relative POSIX form
    assert display == "runtime/mvp_local.db"


def test_safe_db_display_path_outside_repo(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere" / "user.db"
    monkeypatch.setenv("MVP_DB_PATH", str(target))
    display = rc.safe_db_display_path()
    # Must NOT leak the full absolute path — just the filename.
    assert display == "user.db"
    assert str(tmp_path) not in display


def test_db_available_false_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("MVP_DB_PATH", str(tmp_path / "does_not_exist.db"))
    assert rc.db_available() is False


def test_db_available_true_when_present(monkeypatch, tmp_path):
    p = tmp_path / "present.db"
    p.write_bytes(b"")
    monkeypatch.setenv("MVP_DB_PATH", str(p))
    assert rc.db_available() is True
