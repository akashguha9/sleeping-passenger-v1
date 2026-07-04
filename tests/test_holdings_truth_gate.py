"""Tests for the canonical holdings truth gate (Close-the-Loop sprint).

Forensic-audit requirements pinned here:
* SP-001 — risk monitoring must read canonical holdings, never phantom data;
* SP-009 — positions without stops are BLOCKED, never silently passed;
* SP-010 — stale holdings truth fails closed (HOLDINGS_TRUTH_STALE);
* SP-012 — leverage is explicit and leveraged-without-stop escalates.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.holdings_truth_gate import (
    MON_MISSING_STOP,
    MON_MISSING_STOP_LEV,
    MON_NO_PRICE,
    MON_READY,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_STALE,
    canonical_open_position_count,
    load_holdings_truth_gate,
    to_action_engine_position,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


def _write_holdings(path: Path, run_date: str, positions: list[dict]) -> Path:
    path.write_text(
        json.dumps({"run_date": run_date, "positions": positions}),
        encoding="utf-8",
    )
    return path


def _pos(**over) -> dict:
    base = {
        "ticker": "NASDAQ:ANET",
        "normalized_ticker": "ANET",
        "status": "OPEN",
        "quantity": 1.0,
        "entry_price": 100.0,
        "currency": "USD",
        "leverage": 1,
        "opened_at": "2026-07-01T00:00:00Z",
        "created_via": "manual_trade_log",
        "broker_confirmed": False,
        "human_confirmed": True,
    }
    base.update(over)
    return base


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    gate = load_holdings_truth_gate(
        path=tmp_path / "absent.json", now_utc=NOW, attach_prices=False
    )
    assert gate["status"] == STATUS_MISSING
    assert gate["positions"] == []
    assert gate["risk_engine_ready"] is False


def test_stale_run_date_fails_closed(tmp_path: Path) -> None:
    f = _write_holdings(tmp_path / "h.json", "2026-05-22", [_pos(stop_loss=90.0, stop_loss_source="operator", stop_loss_confirmed=True, stop_loss_confirmed_at="2026-07-03T10:00:00Z")])
    gate = load_holdings_truth_gate(
        path=f, now_utc=NOW, attach_prices=False
    )
    assert gate["status"] == STATUS_STALE
    # stale truth returns ZERO monitorable positions — never feeds stop math
    assert gate["positions"] == []
    assert gate["canonical_holding_count"] == 1
    assert gate["blocked_positions"][0]["ticker"] == "NASDAQ:ANET"
    assert any("STALE" in i or "stale" in i for i in gate["issues"])
    assert gate["risk_engine_ready"] is False


def test_missing_stop_blocks_position(tmp_path: Path) -> None:
    f = _write_holdings(tmp_path / "h.json", "2026-07-03", [_pos()])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    assert gate["status"] == STATUS_OK
    assert gate["missing_stop_count"] == 1
    blocked = gate["blocked_positions"][0]
    assert blocked["risk_monitoring"] == MON_MISSING_STOP
    assert gate["risk_engine_ready"] is False, "no stop -> never healthy"


def test_leveraged_without_stop_escalates(tmp_path: Path) -> None:
    f = _write_holdings(
        tmp_path / "h.json",
        "2026-07-03",
        [_pos(ticker="NSE:HDFCBANK", normalized_ticker="HDFCBANK.NS",
              leverage=4, currency="INR")],
    )
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    blocked = gate["blocked_positions"][0]
    assert blocked["risk_monitoring"] == MON_MISSING_STOP_LEV
    assert blocked["leverage"] == 4
    assert gate["leveraged_position_count"] == 1
    assert gate["leveraged_without_stop_count"] == 1
    assert any("CRITICAL" in i for i in gate["issues"])


def test_stop_present_but_no_price_still_blocked(tmp_path: Path) -> None:
    f = _write_holdings(
        tmp_path / "h.json", "2026-07-03", [_pos(stop_loss=90.0, stop_loss_source="operator", stop_loss_confirmed=True, stop_loss_confirmed_at="2026-07-03T10:00:00Z")]
    )
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=True,
                                    db_path=tmp_path / "no.db")
    blocked = gate["blocked_positions"][0]
    assert blocked["risk_monitoring"] == MON_NO_PRICE
    assert blocked["stop_loss"] == 90.0


def test_fully_specified_fresh_position_is_ready(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "mvp.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE signal_events (id INTEGER PRIMARY KEY, event_id TEXT,"
        " source_name TEXT, raw_payload TEXT, fetched_at TEXT)"
    )
    conn.execute(
        "INSERT INTO signal_events VALUES (1,'e1','market_data',?,?)",
        (json.dumps({"symbol": "ANET", "timestamp": "2026-07-03T16:00:00Z",
                     "close": 111.0}), "2026-07-03T16:00:00Z"),
    )
    conn.commit()
    conn.close()
    f = _write_holdings(tmp_path / "h.json", "2026-07-03", [_pos(stop_loss=90.0, stop_loss_source="operator", stop_loss_confirmed=True, stop_loss_confirmed_at="2026-07-03T10:00:00Z")])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, db_path=db)
    assert gate["status"] == STATUS_OK
    ready = gate["positions"][0]
    assert ready["risk_monitoring"] == MON_READY
    assert ready["current_price"] == 111.0
    assert ready["price_as_of"] == "2026-07-03T16:00:00Z"
    assert gate["risk_engine_ready"] is True

    adapted = to_action_engine_position(ready, now_utc=NOW)
    assert adapted["ticker"] == "NASDAQ:ANET"
    assert adapted["stop_loss"] == 90.0
    assert adapted["current_price"] == 111.0
    assert adapted["pnl_pct"] == pytest.approx(11.0)
    assert adapted["source"] == "verified_current_holdings"


def test_stale_price_blocks(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "mvp.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE signal_events (id INTEGER PRIMARY KEY, event_id TEXT,"
        " source_name TEXT, raw_payload TEXT, fetched_at TEXT)"
    )
    conn.execute(
        "INSERT INTO signal_events VALUES (1,'e1','market_data',?,?)",
        (json.dumps({"symbol": "ANET", "timestamp": "2026-06-01T16:00:00Z",
                     "close": 111.0}), "2026-06-01T16:00:00Z"),
    )
    conn.commit()
    conn.close()
    f = _write_holdings(tmp_path / "h.json", "2026-07-03", [_pos(stop_loss=90.0, stop_loss_source="operator", stop_loss_confirmed=True, stop_loss_confirmed_at="2026-07-03T10:00:00Z")])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, db_path=db)
    blocked = gate["blocked_positions"][0]
    assert blocked["risk_monitoring"] == "BLOCKED_STALE_PRICE"


def test_adapter_refuses_blocked_positions(tmp_path: Path) -> None:
    f = _write_holdings(tmp_path / "h.json", "2026-07-03", [_pos()])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    with pytest.raises(ValueError):
        to_action_engine_position(gate["blocked_positions"][0], now_utc=NOW)


def test_canonical_count_for_capacity_gate(tmp_path: Path) -> None:
    f = _write_holdings(
        tmp_path / "h.json", "2026-05-22",
        [_pos(ticker=f"T{i}", normalized_ticker=f"T{i}") for i in range(10)],
    )
    # count is available even when STALE — capacity must see the real book
    assert canonical_open_position_count(path=f, now_utc=NOW) == 10


def test_env_override_is_honored(tmp_path: Path, monkeypatch) -> None:
    f = _write_holdings(tmp_path / "env.json", "2026-07-03",
                        [_pos(stop_loss=90.0, stop_loss_source="operator", stop_loss_confirmed=True, stop_loss_confirmed_at="2026-07-03T10:00:00Z")])
    monkeypatch.setenv("HOLDINGS_TRUTH_PATH", str(f))
    gate = load_holdings_truth_gate(now_utc=NOW, attach_prices=False)
    assert gate["canonical_holding_count"] == 1


def test_advisory_stamps_present(tmp_path: Path) -> None:
    gate = load_holdings_truth_gate(
        path=tmp_path / "absent.json", now_utc=NOW, attach_prices=False
    )
    assert gate["advisory_status"] == "ADVISORY_ONLY"
    assert gate["execution_gate"] == "LOCKED"
