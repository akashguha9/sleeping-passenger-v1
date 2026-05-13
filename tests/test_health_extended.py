"""
Tests for the expanded /health endpoint added in the Kanté repair sprint.

These complement the existing test_api_server.py /health tests, which only
assert the legacy minimum fields.  Here we pin the new operational fields:
  * environment tag
  * db_available flag
  * db_path string (never an absolute filesystem path)
  * api_token_required flag (reflects MVP_API_TOKEN presence)
  * allowed_origins_count
  * execution_gate=LOCKED
  * broker_api_called=false
  * broker_order_id=NONE
  * generated_at timestamp string

The safety stamps must remain locked in every environment.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def client_default(monkeypatch):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    monkeypatch.delenv("MVP_ENVIRONMENT", raising=False)
    import scripts.api_server as srv
    return TestClient(srv.app)


@pytest.fixture
def client_with_env(monkeypatch):
    monkeypatch.setenv("MVP_API_TOKEN", "tkn")
    monkeypatch.setenv("MVP_ENVIRONMENT", "ci-test")
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "http://a.example,http://b.example,http://c.example",
    )
    import scripts.api_server as srv
    return TestClient(srv.app)


def test_health_status_ok(client_default):
    r = client_default.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_safety_stamps_locked(client_default):
    data = client_default.get("/health").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"
    assert data["execution_mode"] == "HUMAN_ONLY"
    assert data["execution_gate"] == "LOCKED"
    assert data["ai_execution_count"] == 0
    assert data["broker_api_called"] is False
    assert data["broker_order_id"] == "NONE"
    assert data["human_review_required"] is True


def test_health_default_environment(client_default):
    data = client_default.get("/health").json()
    assert data["environment"] == "local"


def test_health_reports_token_not_required_by_default(client_default):
    data = client_default.get("/health").json()
    assert data["api_token_required"] is False


def test_health_db_fields_present(client_default):
    data = client_default.get("/health").json()
    assert "db_available" in data
    assert "db_path" in data
    # db_path must be a string and must not be empty
    assert isinstance(data["db_path"], str)
    assert data["db_path"].strip()
    # db_path must NEVER leak the user's home directory or absolute path
    assert "C:\\Users" not in data["db_path"]
    assert "/Users/" not in data["db_path"]


def test_health_allowed_origins_count_is_int(client_default):
    data = client_default.get("/health").json()
    assert isinstance(data["allowed_origins_count"], int)
    assert data["allowed_origins_count"] >= 1


def test_health_generated_at_present(client_default):
    data = client_default.get("/health").json()
    assert "generated_at" in data
    assert data["generated_at"].endswith("+00:00") or data["generated_at"].endswith("Z")


def test_health_reports_token_required_when_set(client_with_env):
    data = client_with_env.get("/health").json()
    assert data["api_token_required"] is True


def test_health_reports_custom_environment(client_with_env):
    data = client_with_env.get("/health").json()
    assert data["environment"] == "ci-test"


def test_health_reports_custom_allowed_origins_count(client_with_env):
    data = client_with_env.get("/health").json()
    assert data["allowed_origins_count"] == 3


def test_health_safety_stamps_locked_even_with_env_changes(client_with_env):
    # The safety contract is locked regardless of environment configuration.
    data = client_with_env.get("/health").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"
    assert data["execution_gate"] == "LOCKED"
    assert data["ai_execution_count"] == 0
    assert data["broker_api_called"] is False
