"""Regression tests: the action engine must not watch a phantom ledger.

Forensic audit SP-001 (Critical): the only stop/TP monitoring in the system
read moltbook/open_positions.json — a file the project itself demoted as
stale/phantom — while the canonical holdings truth was consumed by nothing.
These tests pin the fix: with no explicit path, build_action_report sources
positions from scripts/holdings_truth_gate (fail-closed), stamps the source,
and surfaces blocked positions as operator-visible risk alerts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.action_engine import build_action_report


def _minimal_state() -> dict:
    return {
        "per_signal_attribution": [],
        "execution_policy": {
            "policy_state": "BLOCKED",
            "allow_new_risk": False,
        },
        "active_blockers": ["GSCE_BLOCKED"],
        "signal_refinery": None,
        "simulation_context": {},
    }


def _write_holdings(path: Path, run_date: str, positions: list[dict]) -> Path:
    path.write_text(
        json.dumps({"run_date": run_date, "positions": positions}),
        encoding="utf-8",
    )
    return path


def test_default_source_is_canonical_not_moltbook(monkeypatch, tmp_path: Path) -> None:
    """With no explicit path, the moltbook ledger must NOT be read."""
    holdings = _write_holdings(
        tmp_path / "h.json",
        "2026-07-04",
        [{
            "ticker": "NSE:HDFCBANK", "normalized_ticker": "HDFCBANK.NS",
            "status": "OPEN", "quantity": 5.8, "entry_price": 768.55,
            "currency": "INR", "leverage": 4,
            "opened_at": "2026-05-18T00:00:00Z",
            "created_via": "manual_trade_log",
            "broker_confirmed": False, "human_confirmed": True,
        }],
    )
    monkeypatch.setenv("HOLDINGS_TRUTH_PATH", str(holdings))
    report = build_action_report(runtime_state=_minimal_state())
    assert report["position_source"]["source"] == "verified_current_holdings"
    # The phantom moltbook tickers must not appear anywhere in the actions.
    tickers = {a["ticker"] for a in report["actions"]}
    assert not ({"UNG", "FCG", "TIP"} & tickers), (
        "phantom moltbook positions leaked into the action report"
    )
    # The leveraged, stop-less real position surfaces as a CRITICAL alert.
    alerts = report["position_risk_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["ticker"] == "NSE:HDFCBANK"
    assert alerts[0]["severity"] == "CRITICAL"
    assert alerts[0]["risk_monitoring"] == "BLOCKED_MISSING_STOP_LEVERAGED"
    assert report["position_source"]["risk_engine_ready"] is False


def test_stale_holdings_truth_yields_zero_monitored_positions(
    monkeypatch, tmp_path: Path
) -> None:
    holdings = _write_holdings(
        tmp_path / "h.json",
        "2026-05-22",  # weeks stale
        [{
            "ticker": "NASDAQ:ANET", "normalized_ticker": "ANET",
            "status": "OPEN", "quantity": 1.0, "entry_price": 141.97,
            "currency": "USD", "leverage": 1, "stop_loss": 120.0,
            "opened_at": "2026-05-18T00:00:00Z",
            "created_via": "manual_trade_log",
            "broker_confirmed": False, "human_confirmed": True,
        }],
    )
    monkeypatch.setenv("HOLDINGS_TRUTH_PATH", str(holdings))
    report = build_action_report(runtime_state=_minimal_state())
    assert report["position_source"]["status"] == "HOLDINGS_TRUTH_STALE"
    assert report["position_source"]["monitorable_position_count"] == 0
    assert not any(a["has_open_position"] for a in report["actions"])
    errors = report["open_positions_validation"]["errors"]
    assert any("stale" in e.lower() for e in errors), (
        "staleness must be operator-visible in validation errors"
    )


def test_missing_holdings_truth_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOLDINGS_TRUTH_PATH", str(tmp_path / "absent.json"))
    report = build_action_report(runtime_state=_minimal_state())
    assert report["position_source"]["status"] == "HOLDINGS_TRUTH_MISSING"
    assert report["position_source"]["canonical_holding_count"] == 0
    assert report["actions"] == [] or not any(
        a["has_open_position"] for a in report["actions"]
    )


def test_explicit_path_is_stamped_not_hidden(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture_positions.json"
    fixture.write_text(json.dumps([]), encoding="utf-8")
    report = build_action_report(
        runtime_state=_minimal_state(), open_positions_path=fixture
    )
    assert report["position_source"]["source"] == "EXPLICIT_PATH"
    assert str(fixture) in report["position_source"]["path"]


def test_ready_position_flows_into_stop_monitoring(
    monkeypatch, tmp_path: Path
) -> None:
    """A fresh, stop-carrying, priced position gets real action treatment."""
    import sqlite3

    db = tmp_path / "mvp.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE signal_events (id INTEGER PRIMARY KEY, event_id TEXT,"
        " source_name TEXT, raw_payload TEXT, fetched_at TEXT)"
    )
    conn.execute(
        "INSERT INTO signal_events VALUES (1,'e1','market_data',?,?)",
        (json.dumps({"symbol": "ANET",
                     "timestamp": "2026-07-04T16:00:00Z", "close": 100.0}),
         "2026-07-04T16:00:00Z"),
    )
    conn.commit()
    conn.close()
    holdings = _write_holdings(
        tmp_path / "h.json",
        "2026-07-04",
        [{
            "ticker": "NASDAQ:ANET", "normalized_ticker": "ANET",
            "status": "OPEN", "quantity": 1.0, "entry_price": 141.97,
            "currency": "USD", "leverage": 1,
            "stop_loss": 120.0,  # current 100 < stop 120: breached
            "stop_loss_source": "operator", "stop_loss_confirmed": True,
            "stop_loss_confirmed_at": "2026-07-04T09:00:00Z",
            "opened_at": "2026-05-18T00:00:00Z",
            "created_via": "manual_trade_log",
            "broker_confirmed": False, "human_confirmed": True,
        }],
    )
    monkeypatch.setenv("HOLDINGS_TRUTH_PATH", str(holdings))
    from scripts import persistence

    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    report = build_action_report(runtime_state=_minimal_state())
    assert report["position_source"]["monitorable_position_count"] == 1
    row = next(a for a in report["actions"] if a["ticker"] == "NASDAQ:ANET")
    assert row["has_open_position"] is True
    # Stop breach on a REAL canonical position must surface an exit-family
    # action (never silence).
    assert row["action"] in {"EXIT_NOW", "REDUCE_NOW", "TIGHTEN_STOP"} or any(
        "stop" in r.lower() for r in row["reasons"]
    )
