"""Tests for the Backend/API quality readiness surface (Sprint 3 — Part 1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import backend_api_quality as baq


def test_envelope_contract_for_missing_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(baq, "RELEASE_DIR", tmp_path)
    env = baq.read_artifact_envelope("daily_signal")
    assert env["ok"] is False
    assert env["error"] == "missing_artifact"
    assert env["advisory_only"] is True
    assert env["human_review_required"] is True
    assert env["execution_permission"] == "ADVISORY_ONLY"
    assert env["data"] is None
    assert "missing" in " ".join(env["warnings"]).lower() or "not present" in (
        " ".join(env["warnings"]).lower()
    )


def test_envelope_contract_for_malformed_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(baq, "RELEASE_DIR", tmp_path)
    (tmp_path / "daily_signal_readiness_summary.json").write_text(
        "not json", encoding="utf-8"
    )
    env = baq.read_artifact_envelope("daily_signal")
    assert env["ok"] is False
    assert env["error"] == "malformed_artifact"
    assert env["blocking_reasons"], "must surface parse error"


def test_envelope_returns_payload_for_present_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(baq, "RELEASE_DIR", tmp_path)
    payload = {"ok": True, "overall_daily_signal_readiness": 9.42}
    (tmp_path / "daily_signal_readiness_summary.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    env = baq.read_artifact_envelope("daily_signal")
    assert env["ok"] is True
    assert env["data"]["overall_daily_signal_readiness"] == 9.42
    assert env["source"].endswith("daily_signal_readiness_summary.json")


def test_live_refresh_endpoint_fails_closed_without_env():
    env = baq.live_refresh_run_locked_response(
        mvp_live_refresh_ok=False,
        advisory_only=True,
        human_execution_required=True,
        execution_gate="LOCKED",
    )
    assert env["ok"] is False
    assert env["error"] == "live_refresh_locked"
    assert any("MVP_LIVE_REFRESH_OK" in r for r in env["blocking_reasons"])
    assert env["execution_permission"] == "ADVISORY_ONLY"


def test_live_refresh_endpoint_fails_closed_without_safety_floor():
    env = baq.live_refresh_run_locked_response(
        mvp_live_refresh_ok=True,
        advisory_only=False,
        human_execution_required=True,
        execution_gate="LOCKED",
    )
    assert env["ok"] is False
    assert any("ADVISORY_ONLY" in r for r in env["blocking_reasons"])


def test_live_refresh_endpoint_does_not_call_broker():
    # Even when permitted, the endpoint does not actually contact networks.
    env = baq.live_refresh_run_locked_response(
        mvp_live_refresh_ok=True,
        advisory_only=True,
        human_execution_required=True,
        execution_gate="LOCKED",
    )
    assert env["ok"] is True
    assert env["data"]["instruction"].startswith(
        "run scripts/operator_live_provider_refresh.py"
    )
    assert env["broker_api_called"] is False
    assert env["ai_execution_count"] == 0


def test_envelope_never_exposes_secrets(monkeypatch):
    monkeypatch.setenv("MVP_API_TOKEN", "super-secret-token-do-not-leak")
    monkeypatch.setenv("SEC_USER_AGENT", "operator email@example.com")
    env = baq.live_refresh_run_locked_response(
        mvp_live_refresh_ok=False,
        advisory_only=True,
        human_execution_required=True,
        execution_gate="LOCKED",
    )
    body = json.dumps(env, default=str)
    assert "super-secret-token-do-not-leak" not in body
    assert "email@example.com" not in body


def test_backend_api_quality_summary_writes(tmp_path):
    target = tmp_path / "backend_api_quality_summary.json"
    summary = baq.write_summary(target)
    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "backend_api_quality_score" in on_disk
    assert on_disk["advisory_only"] is True
    assert on_disk["broker_api_called"] is False
    assert on_disk["ai_execution_count"] == 0


def test_backend_api_quality_score_high_when_all_present():
    score = baq.backend_api_quality_score(
        readiness_endpoints_exist=True,
        responses_typed_and_structured=True,
        error_handling_structured=True,
        operator_live_refresh_locked=True,
        no_secret_exposure=True,
        api_tests_pass=True,
    )
    assert score == 10.0


def test_backend_api_quality_score_falls_with_missing_endpoint():
    score = baq.backend_api_quality_score(
        readiness_endpoints_exist=False,
        responses_typed_and_structured=True,
        error_handling_structured=True,
        operator_live_refresh_locked=True,
        no_secret_exposure=True,
        api_tests_pass=True,
    )
    assert score < 10.0


def test_endpoint_handlers_registered_on_api_server():
    # The api_server module must have every readiness handler the summary
    # asserts.  This is the hard wiring test.
    from scripts import api_server
    expected_handlers = (
        "get_release_gate_readiness",
        "get_daily_signal_readiness",
        "get_source_health_api",
        "get_live_refresh_summary",
        "get_portfolio_truth_api",
        "get_fresh_discovery_api",
        "get_why_today_summary",
        "get_model_disagreement_summary",
        "get_signal_input_quality_summary",
        "get_compliance_readiness",
        "get_business_value_summary",
        "post_live_refresh_run",
    )
    for name in expected_handlers:
        assert hasattr(api_server, name), f"missing handler {name}"
