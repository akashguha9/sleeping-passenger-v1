"""Behavioural tests for the manual real-money readiness gate (v2)."""
from __future__ import annotations

import pytest

from scripts import pre_real_money_preflight as prm


def _clean_preflight():
    return {"report": "pre_real_money_preflight", "ok": True, "blocking_issues": [], "warnings": []}


def _blocking_preflight():
    return {"report": "pre_real_money_preflight", "ok": False,
            "blocking_issues": ["unreconciled_backlog_block"], "warnings": []}


def _force(monkeypatch, *, cal_status="NO_DATA", real_n=0, paper_n=0,
           leverage=True, coverage=1.0, exec_surface=False, feedback=True):
    monkeypatch.setattr(prm, "_execution_surface_present", lambda: exec_surface)
    monkeypatch.setattr(prm, "_leverage_governance_active", lambda: leverage)
    monkeypatch.setattr(prm, "_securities_coverage_score", lambda db: coverage)
    monkeypatch.setattr(prm, "_feedback_loop_available", lambda: feedback)
    monkeypatch.setattr(
        prm, "_calibration_probe",
        lambda db: {"calibration_status": cal_status, "real_n": real_n, "paper_n": paper_n, "n": real_n + paper_n},
    )


def test_no_calibration_caps_at_6_5(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="NO_DATA")
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 6.5
    assert out["allowed_mode"] == prm.MODE_TINY_PROBE


def test_fixture_only_caps_at_6_5(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="FIXTURE_ONLY")
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 6.5
    assert out["calibration_status"] == "FIXTURE_ONLY"


def test_paper_calibrated_caps_at_7(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="CALIBRATED", real_n=0, paper_n=60)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 7.0
    assert out["allowed_mode"] in {prm.MODE_TINY_PROBE, prm.MODE_MANUAL_SMALL}


def test_real_calibrated_n60_can_reach_8(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="CALIBRATED", real_n=60, coverage=1.0)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] >= 7.5
    assert out["readiness_score"] <= 8.0  # never above the gate max
    assert out["allowed_mode"] in {prm.MODE_MANUAL_SMALL, prm.MODE_MANUAL_CALIBRATED}


def test_execution_surface_hard_fails(tmp_path, monkeypatch):
    _force(monkeypatch, exec_surface=True)
    out = prm.assess_real_money_readiness(tmp_path / "rm.db", preflight=_clean_preflight())
    assert out["allowed_mode"] == prm.MODE_SCALE_BLOCKED
    assert out["readiness_score"] == 0.0
    assert "execution_surface_present" in out["blockers"]


def test_leverage_missing_caps_to_5(tmp_path, monkeypatch):
    _force(monkeypatch, leverage=False, cal_status="CALIBRATED", real_n=60)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 5.0
    assert "leverage_governance_missing" in out["blockers"]


def test_weak_securities_coverage_caps_at_7(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="CALIBRATED", real_n=60, coverage=0.5)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 7.0
    assert "securities_coverage_weak" in out["warnings"]


def test_failing_tests_cap_at_6(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="CALIBRATED", real_n=60)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=False, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] <= 6.0
    assert "tests_failing" in out["blockers"]


def test_preflight_blocking_caps_at_6(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="CALIBRATED", real_n=60)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_blocking_preflight(),
    )
    assert out["readiness_score"] <= 6.0
    assert "preflight_blocking_issues" in out["blockers"]


def test_clean_calibrated_can_reach_at_least_7(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="CALIBRATED", real_n=60, coverage=1.0)
    out = prm.assess_real_money_readiness(
        tmp_path / "rm.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight=_clean_preflight(),
    )
    assert out["readiness_score"] >= 7.0


def test_output_never_uses_execution_words(tmp_path, monkeypatch):
    _force(monkeypatch, cal_status="CALIBRATED", real_n=60)
    out = prm.assess_real_money_readiness(tmp_path / "rm.db", preflight=_clean_preflight())
    blob = (out["reason"] + " " + out["allowed_mode"]).lower()
    for bad in ("buy now", "sell now", "execute order", "place order", "broker trade", "send order"):
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
        prm.MODE_SCALE_BLOCKED, prm.MODE_PAPER_ONLY, prm.MODE_TINY_PROBE,
        prm.MODE_MANUAL_SMALL, prm.MODE_MANUAL_CALIBRATED,
    }
    assert data["readiness_score"] <= 8.0
    assert data["broker_api_called"] is False
