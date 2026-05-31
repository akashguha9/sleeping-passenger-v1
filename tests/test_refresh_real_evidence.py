"""Tests — one-command real-evidence refresh (Phase 6).

Deterministic, offline.  Proves the refresh runs every step in order, writes
the bundle + calibration JSON when asked, keeps the predictive claim locked
below the gate, never requires the network by default, gates the real canary
behind an explicit flag + env opt-in, preserves advisory safety, and never
executes a trade.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.refresh_real_evidence import STEPS, refresh_real_evidence


_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.45, "LS": 0.5, "EFS": 0.5, "APS": 0.5}


def _fixtures():
    # Deterministic fixture rows so the canary persists canonical (non-mock) rows
    # offline.  Each record carries the six advisory axes so the daily decision
    # batch can produce a real model_probability.
    def recs(prefix):
        return {"records": [
            {"event_id": f"{prefix}_{i}", "axes": dict(_AXES), "headline": f"{prefix} {i}"}
            for i in range(3)
        ], "canary_real": False, "api_health_status": "OK"}
    return {"yfinance": recs("yf"), "polymarket": recs("pm"), "sec_edgar": recs("sec")}


def _assert_locked(summary: dict) -> None:
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["predictive_claim_allowed"] is False
    assert summary["real_money_ready"] is False


# --- 1. runs steps in order ----------------------------------------------- #

def test_refresh_runs_steps_in_order_with_fixtures(tmp_path):
    db = tmp_path / "mvp.db"
    summary = refresh_real_evidence(
        db_path=db,
        fixtures=_fixtures(),
        sources=["yfinance", "polymarket", "sec_edgar"],
        write=False,
    )
    assert summary["steps_run"] == list(STEPS)
    _assert_locked(summary)


# --- 2. writes bundle + calibration json ---------------------------------- #

def test_refresh_writes_bundle_and_calibration_json(tmp_path):
    db = tmp_path / "mvp.db"
    cal_json = tmp_path / "cal.json"
    bundle_json = tmp_path / "bundle.json"
    bundle_md = tmp_path / "bundle.md"
    canary_json = tmp_path / "canary.json"
    summary = refresh_real_evidence(
        db_path=db,
        fixtures=_fixtures(),
        sources=["yfinance", "polymarket", "sec_edgar"],
        write=True,
        canary_json_path=canary_json,
        calibration_json_path=cal_json,
        bundle_json_path=bundle_json,
        bundle_md_path=bundle_md,
    )
    assert cal_json.exists()
    assert bundle_json.exists()
    assert bundle_md.exists()
    assert summary["bundle_json_path"] == str(bundle_json)
    assert summary["wrote_artifacts"] is True


# --- 3. predictive claim locked below the gate ---------------------------- #

def test_refresh_reports_predictive_claim_locked_below_gate(tmp_path):
    db = tmp_path / "mvp.db"
    summary = refresh_real_evidence(
        db_path=db,
        fixtures=_fixtures(),
        sources=["yfinance", "polymarket", "sec_edgar"],
        write=False,
    )
    assert summary["predictive_claim_allowed"] is False
    assert summary["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert summary["n_real_forward"] < 200


# --- 4. no network by default --------------------------------------------- #

def test_refresh_does_not_require_network_by_default(tmp_path, monkeypatch):
    # Even with the env flag set, default real_canary=False stays offline.
    monkeypatch.setenv("REAL_EVIDENCE_CANARY", "1")
    db = tmp_path / "mvp.db"
    summary = refresh_real_evidence(db_path=db, fixtures=_fixtures(), write=False)
    assert summary["allow_network"] is False
    assert summary["real_canary"] is False


# --- 5. real canary requires explicit flag + env -------------------------- #

def test_refresh_real_canary_requires_explicit_flag(tmp_path, monkeypatch):
    db = tmp_path / "mvp.db"
    # Flag requested but env NOT set -> blocked, stays offline.
    monkeypatch.delenv("REAL_EVIDENCE_CANARY", raising=False)
    summary = refresh_real_evidence(
        db_path=db, fixtures=_fixtures(), real_canary=True, write=False
    )
    assert summary["allow_network"] is False
    assert summary["real_canary_blocked"] is True


# --- 6. preserves advisory safety ----------------------------------------- #

def test_refresh_preserves_advisory_safety_stamps(tmp_path):
    db = tmp_path / "mvp.db"
    summary = refresh_real_evidence(db_path=db, fixtures=_fixtures(), write=False)
    _assert_locked(summary)


# --- 7. does not execute trades ------------------------------------------- #

def test_refresh_does_not_execute_trades(tmp_path):
    import json

    db = tmp_path / "mvp.db"
    summary = refresh_real_evidence(db_path=db, fixtures=_fixtures(), write=False)
    blob = json.dumps(summary).lower()
    for word in ("place order", "broker_execute", "buy now", "sell now", "execute trade"):
        assert word not in blob


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
