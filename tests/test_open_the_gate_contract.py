"""Tests: Open-the-Gate strict confirmation contract + drawdown monitor.

Pins:
* the operator acknowledgement text is required VERBATIM — apply rejects
  anything else (fake confirmation is structurally impossible);
* leveraged positions demand an explicit leverage_risk_acknowledged;
* the confirmation-required artifacts are generated when pending, and the
  state stays BLOCKED;
* archive backup lands under data/daily_payload/archive/ before any write;
* the drawdown monitor: breach -> CRITICAL, near-stop -> WARNING, leveraged
  drawdown explicit, unmonitorable positions surfaced, never executes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.drawdown_stop_monitor import run_drawdown_monitor
from scripts.holdings_truth_gate import (
    OPERATOR_ACK_TEXT,
    apply_confirmed_template,
    load_holdings_truth_gate,
    validate_stop_template,
    write_confirmation_required_artifacts,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


def _pos(**over) -> dict:
    base = {
        "ticker": "NASDAQ:ANET", "normalized_ticker": "ANET", "status": "OPEN",
        "quantity": 2.0, "entry_price": 100.0, "currency": "USD",
        "leverage": 1, "opened_at": "2026-07-01T00:00:00Z",
        "created_via": "manual_trade_log", "broker_confirmed": False,
        "human_confirmed": True,
    }
    base.update(over)
    return base


def _write(path: Path, positions: list[dict], run_date: str = "2026-07-04") -> Path:
    path.write_text(json.dumps({"run_date": run_date, "positions": positions}),
                    encoding="utf-8")
    return path


def _entry(**over) -> dict:
    base = {
        "ticker": "NASDAQ:ANET", "stop_loss": 95.0,
        "stop_loss_source": "policy_suggested",
        "stop_loss_confirmed": True,
        "stop_loss_confirmed_at": "2026-07-04T11:00:00Z",
        "operator_confirmation_id": "op-1",
        "operator_confirmation_text": OPERATOR_ACK_TEXT,
        "risk_acknowledgement": True,
    }
    base.update(over)
    return base


def _apply(tmp_path: Path, holdings: Path, entries: list[dict]) -> dict:
    tpath = tmp_path / "t.json"
    tpath.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return apply_confirmed_template(
        template_path=tpath, holdings_path=holdings, now_utc=NOW, write=True,
    )


def test_wrong_ack_text_is_rejected(tmp_path: Path) -> None:
    holdings = _write(tmp_path / "h.json", [_pos()])
    result = _apply(tmp_path, holdings, [
        _entry(operator_confirmation_text="i confirm these stops"),
    ])
    assert result["applied"] == []
    assert "operator_confirmation_text" in result["skipped"][0]["reason"]
    saved = json.loads(holdings.read_text(encoding="utf-8"))
    assert "stop_loss" not in saved["positions"][0]


def test_missing_confirmation_id_rejected(tmp_path: Path) -> None:
    holdings = _write(tmp_path / "h.json", [_pos()])
    result = _apply(tmp_path, holdings, [
        _entry(operator_confirmation_id=None),
    ])
    assert result["applied"] == []
    assert "operator_confirmation_id" in result["skipped"][0]["reason"]


def test_missing_risk_ack_rejected(tmp_path: Path) -> None:
    holdings = _write(tmp_path / "h.json", [_pos()])
    result = _apply(tmp_path, holdings, [_entry(risk_acknowledgement=False)])
    assert result["applied"] == []
    assert "risk_acknowledgement" in result["skipped"][0]["reason"]


def test_leveraged_requires_explicit_leverage_ack(tmp_path: Path) -> None:
    holdings = _write(tmp_path / "h.json", [_pos(leverage=4)])
    rejected = _apply(tmp_path, holdings, [_entry()])
    assert rejected["applied"] == []
    assert "leverage_risk_acknowledged" in rejected["skipped"][0]["reason"]
    accepted = _apply(tmp_path, holdings, [
        _entry(leverage_risk_acknowledged=True),
    ])
    assert [a["ticker"] for a in accepted["applied"]] == ["NASDAQ:ANET"]
    saved = json.loads(holdings.read_text(encoding="utf-8"))
    assert saved["positions"][0]["leverage_risk_acknowledged"] is True
    # and the gate now treats the stop as usable
    gate = load_holdings_truth_gate(path=holdings, now_utc=NOW,
                                    attach_prices=False)
    assert gate["unconfirmed_stop_count"] == 0
    assert gate["leveraged_without_stop_count"] == 0


def test_archive_backup_created_before_write(tmp_path: Path, monkeypatch) -> None:
    import scripts.holdings_truth_gate as gate_mod

    monkeypatch.setattr(
        gate_mod, "HOLDINGS_ARCHIVE_DIR", tmp_path / "archive", raising=False
    )
    holdings = _write(tmp_path / "h.json", [_pos()])
    original = holdings.read_text(encoding="utf-8")
    result = _apply(tmp_path, holdings, [_entry()])
    assert result["status"] == "OK"
    backups = list((tmp_path / "archive").glob(
        "verified_current_holdings_*.json"
    ))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original


def test_validate_template_and_confirmation_required_artifacts(
    tmp_path: Path,
) -> None:
    holdings = _write(tmp_path / "h.json", [_pos(), _pos(
        ticker="NSE:HDFCBANK", normalized_ticker="HDFCBANK.NS", leverage=4,
        entry_price=768.55,
    )])
    tpath = tmp_path / "t.json"
    tpath.write_text(json.dumps({"entries": [
        {"ticker": "NASDAQ:ANET", "stop_loss": 95.0,
         "stop_loss_confirmed": False},
        {"ticker": "NSE:HDFCBANK", "stop_loss": 749.34,
         "stop_loss_confirmed": True,
         "stop_loss_confirmed_at": "2026-07-04T11:00:00Z",
         "operator_confirmation_id": "op-2",
         "operator_confirmation_text": OPERATOR_ACK_TEXT,
         "risk_acknowledgement": True,
         "leverage_risk_acknowledged": False},  # leveraged, not acked
    ]}), encoding="utf-8")
    validation = validate_stop_template(
        template_path=tpath, holdings_path=holdings, now_utc=NOW,
    )
    assert validation["status"] == "CONFIRMATION_REQUIRED"
    verdicts = {e["ticker"]: e["verdict"] for e in validation["entries"]}
    assert verdicts["NASDAQ:ANET"] == "UNCONFIRMED"
    assert verdicts["NSE:HDFCBANK"] == "INVALID"
    lev_reasons = next(e for e in validation["entries"]
                       if e["ticker"] == "NSE:HDFCBANK")["reasons"]
    assert any("leverage_risk_acknowledged" in r for r in lev_reasons)
    paths = write_confirmation_required_artifacts(
        validation,
        json_path=tmp_path / "req.json", md_path=tmp_path / "req.md",
    )
    md = Path(paths["md_path"]).read_text(encoding="utf-8")
    assert "BLOCKED" in md
    assert OPERATOR_ACK_TEXT in md
    assert "NASDAQ:ANET" in md and "NSE:HDFCBANK" in md
    req = json.loads(Path(paths["json_path"]).read_text(encoding="utf-8"))
    assert req["confirmed_valid"] == 0


# --------------------------------------------------------------------------
# Drawdown / stop-breach monitor
# --------------------------------------------------------------------------

def _db_with_price(tmp_path: Path, symbol: str, close: float,
                   ts: str = "2026-07-04T10:00:00Z") -> Path:
    import sqlite3

    db = tmp_path / "mvp.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS signal_events (id INTEGER PRIMARY KEY,"
        " event_id TEXT, source_name TEXT, raw_payload TEXT, fetched_at TEXT)"
    )
    conn.execute(
        "INSERT INTO signal_events (event_id, source_name, raw_payload,"
        " fetched_at) VALUES (?,?,?,?)",
        (f"e-{symbol}", "market_data",
         json.dumps({"symbol": symbol, "timestamp": ts, "close": close}), ts),
    )
    conn.commit()
    conn.close()
    return db


CONFIRMED_FULL = {
    "stop_loss": 90.0, "stop_loss_source": "operator",
    "stop_loss_confirmed": True,
    "stop_loss_confirmed_at": "2026-07-04T09:00:00Z",
}


def test_stop_breach_triggers_critical(tmp_path: Path) -> None:
    db = _db_with_price(tmp_path, "ANET", 85.0)  # below stop 90
    holdings = _write(tmp_path / "h.json", [_pos(**CONFIRMED_FULL)])
    report = run_drawdown_monitor(
        holdings_path=holdings, db_path=db, now_utc=NOW,
    )
    assert report["status"] == "BREACH"
    assert report["stop_breach_count"] == 1
    row = next(r for r in report["positions"] if r["state"] == "MONITORED")
    assert row["stop_breached"] is True
    assert row["unrealized_return"] == pytest.approx(-0.15)
    # portfolio drawdown: (85-100)*2*1 / 200 = -0.15 -> CRITICAL band
    assert report["portfolio_drawdown_fraction"] == pytest.approx(-0.15)
    assert report["alerts_generated"] >= 2  # breach + drawdown


def test_near_stop_triggers_warning(tmp_path: Path) -> None:
    db = _db_with_price(tmp_path, "ANET", 92.0)  # 2.17% above stop 90
    holdings = _write(tmp_path / "h.json", [_pos(**CONFIRMED_FULL)])
    report = run_drawdown_monitor(
        holdings_path=holdings, db_path=db, now_utc=NOW,
    )
    assert report["status"] == "NEAR_STOP"
    assert report["near_stop_count"] == 1
    assert report["stop_breach_count"] == 0


def test_leveraged_drawdown_is_explicit(tmp_path: Path) -> None:
    db = _db_with_price(tmp_path, "ANET", 95.0)
    holdings = _write(tmp_path / "h.json", [_pos(
        leverage=4, leverage_risk_acknowledged=True, **CONFIRMED_FULL,
    )])
    report = run_drawdown_monitor(
        holdings_path=holdings, db_path=db, now_utc=NOW,
    )
    row = next(r for r in report["positions"] if r["state"] == "MONITORED")
    assert row["leveraged_unrealized_return"] == pytest.approx(-0.20)
    # PnL = (95-100)*2*4 = -40; equity basis 200 -> -0.20 -> CRITICAL
    assert report["portfolio_drawdown_fraction"] == pytest.approx(-0.20)


def test_unconfirmed_positions_are_unmonitorable_not_skipped(
    tmp_path: Path,
) -> None:
    holdings = _write(tmp_path / "h.json", [_pos(
        stop_loss=90.0, stop_loss_confirmed=False,
    )])
    report = run_drawdown_monitor(
        holdings_path=holdings, db_path=tmp_path / "no.db", now_utc=NOW,
    )
    assert report["status"] == "NO_MONITORABLE_POSITIONS"
    assert report["unmonitorable_count"] == 1
    assert report["positions"][0]["state"] == "UNMONITORABLE"
    assert "Confirm stops" in report["next_operator_action"]


def test_missing_price_blocks_monitoring(tmp_path: Path) -> None:
    holdings = _write(tmp_path / "h.json", [_pos(**CONFIRMED_FULL)])
    report = run_drawdown_monitor(
        holdings_path=holdings, db_path=tmp_path / "no.db", now_utc=NOW,
    )
    assert report["monitored_count"] == 0
    assert report["positions"][0]["reason"] == "BLOCKED_NO_PRICE"


def test_monitor_has_no_execution_path() -> None:
    import inspect

    import scripts.drawdown_stop_monitor as mod

    src = inspect.getsource(mod)
    for forbidden in ("place_order", "submit_order", "execute_trade",
                      "cancel_order", "auto_buy", "auto_sell"):
        assert forbidden not in src
    assert "ADVISORY" in src.upper()
