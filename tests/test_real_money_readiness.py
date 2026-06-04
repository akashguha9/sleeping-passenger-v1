"""Behavioural tests for the manual real-money readiness gate."""
from __future__ import annotations

import pytest

from scripts import pre_real_money_preflight as prm


def _clean_preflight():
    return {"report": "pre_real_money_preflight", "ok": True, "blocking_issues": [], "warnings": []}


def _blocking_preflight():
    return {"report": "pre_real_money_preflight", "ok": False,
            "blocking_issues": ["unreconciled_backlog_block"], "warnings": []}


def test_clean_advisory_state_can_reach_seven(tmp_path):
    # Force a CALIBRATED-style state by monkeypatching the calibration probe
    # via a seeded DB is heavy; instead drive through the public function with
    # a clean preflight and rely on the real (uncalibrated) calibration: that
    # caps at 6.5 / TINY_PROBE. To reach 7 we simulate calibrated below.
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db",
        backend_tests_passing=True,
        frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    # Empty DB -> uncalibrated -> capped at 6.5, tiny-probe.
    assert out["allowed_mode"] == prm.MODE_TINY_PROBE
    assert out["readiness_score"] <= 6.5
    assert out["readiness_score"] <= prm.READINESS_MAX
    # never scaling-ready
    assert out["readiness_score"] <= 7.0


def test_uncalibrated_caps_score(tmp_path):
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db",
        backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["checks"]["calibration_status"] == "UNCALIBRATED"
    assert out["readiness_score"] <= 6.5
    assert "scores_uncalibrated" in out["warnings"]


def test_failing_tests_cap_score(tmp_path):
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db",
        backend_tests_passing=False, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 6.0
    assert "tests_failing" in out["blockers"]
    assert out["allowed_mode"] == prm.MODE_PAPER_ONLY


def test_preflight_blocking_forces_paper_only(tmp_path):
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db",
        backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_blocking_preflight(),
    )
    assert out["allowed_mode"] == prm.MODE_PAPER_ONLY
    assert "preflight_blocking_issues" in out["blockers"]
    assert out["readiness_score"] <= 6.0


def test_execution_surface_hard_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(prm, "_execution_surface_present", lambda: True)
    out = prm.assess_real_money_readiness(tmp_path / "rm.db", preflight=_clean_preflight())
    assert out["allowed_mode"] == prm.MODE_SCALE_BLOCKED
    assert out["readiness_score"] == 0.0
    assert "execution_surface_present" in out["blockers"]


def test_leverage_missing_caps_to_five(tmp_path, monkeypatch):
    monkeypatch.setattr(prm, "_leverage_governance_active", lambda: False)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 5.0
    assert "leverage_governance_missing" in out["blockers"]
    assert out["allowed_mode"] == prm.MODE_PAPER_ONLY


def test_calibrated_state_reaches_seven_manual_ready(tmp_path, monkeypatch):
    # Simulate a CALIBRATED calibration probe.
    monkeypatch.setattr(prm, "_calibration_status", lambda db: ("CALIBRATED", False, 60))
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] == 7.0
    assert out["allowed_mode"] == prm.MODE_MANUAL_READY
    # Hard cap: never scaling-ready.
    assert out["readiness_score"] <= prm.READINESS_MAX


def test_output_never_uses_execution_words(tmp_path):
    out = prm.assess_real_money_readiness(tmp_path / "rm.db", preflight=_clean_preflight())
    blob = (out["reason"] + " " + out["allowed_mode"]).lower()
    for bad in ("buy", "sell", "execute order", "place order", "broker trade"):
        assert bad not in blob
    assert out["broker_api_called"] is False
    assert out["can_execute"] is False


def test_api_endpoint(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from scripts import api_server
    import scripts.persistence as persistence
    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "rm_api.db", raising=False)
    client = TestClient(api_server.app)
    r = client.get("/api/readiness/real-money")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["allowed_mode"] in {
        prm.MODE_SCALE_BLOCKED, prm.MODE_PAPER_ONLY, prm.MODE_TINY_PROBE, prm.MODE_MANUAL_READY
    }
    assert data["readiness_score"] <= 7.0
    assert data["broker_api_called"] is False
