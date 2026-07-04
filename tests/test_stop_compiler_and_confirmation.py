"""Tests: stop compiler / validator / confirmation loop (Feed-the-Loop sprint).

Pins the sprint's fail-closed contract:
* missing stop            -> BLOCKED (exit 1)
* unconfirmed suggested   -> BLOCKED (a number alone is not truth)
* operator-confirmed stop -> usable; risk gate can pass
* leveraged without usable stop -> CRITICAL issue + BLOCKED
* stale holdings          -> DEGRADED (and blocked from monitoring)
* max_loss_at_stop math   -> Loss = max(0, entry - stop) x qty x leverage
* --apply-confirmed can never activate an unconfirmed or invalid stop
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.holdings_truth_gate import (
    MON_INVALID_STOP,
    MON_READY,
    MON_UNCONFIRMED_STOP,
    OP_BLOCKED,
    OP_DEGRADED,
    OP_HEALTHY,
    apply_confirmed_template,
    build_stop_loss_template,
    load_holdings_truth_gate,
    main,
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
    path.write_text(
        json.dumps({"run_date": run_date, "positions": positions}),
        encoding="utf-8",
    )
    return path


CONFIRMED = {
    "stop_loss": 90.0,
    "stop_loss_source": "operator",
    "stop_loss_confirmed": True,
    "stop_loss_confirmed_at": "2026-07-04T10:00:00Z",
    "stop_loss_updated_at": "2026-07-04T10:00:00Z",
}


def test_missing_stop_blocked_exit_1(tmp_path: Path, capsys) -> None:
    f = _write(tmp_path / "h.json", [_pos()])
    rc = main(["--validate", "--path", str(f), "--db", str(tmp_path / "no.db")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["operational_state"] == OP_BLOCKED
    assert out["missing_stop_count"] == 1


def test_unconfirmed_suggested_stop_blocks(tmp_path: Path) -> None:
    f = _write(tmp_path / "h.json", [_pos(
        stop_loss=95.0, stop_loss_source="policy_suggested",
        stop_loss_confirmed=False,
    )])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    assert gate["unconfirmed_stop_count"] == 1
    assert gate["operational_state"] == OP_BLOCKED
    blocked = gate["blocked_positions"][0]
    assert blocked["risk_monitoring"] == MON_UNCONFIRMED_STOP
    assert gate["risk_engine_ready"] is False


def test_confirmed_stop_is_usable_and_exposure_computed(tmp_path: Path) -> None:
    f = _write(tmp_path / "h.json", [_pos(**CONFIRMED)])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    assert gate["missing_stop_count"] == 0
    assert gate["unconfirmed_stop_count"] == 0
    # Loss_At_Stop = (100 - 90) * 2 * 1 = 20; equity basis = 200; frac 0.1
    assert gate["portfolio_stop_exposure"] == pytest.approx(20.0)
    assert gate["portfolio_equity_basis"] == pytest.approx(200.0)
    assert gate["portfolio_stop_exposure_fraction"] == pytest.approx(0.1)
    assert gate["operational_state"] == OP_HEALTHY
    pos = (gate["positions"] + gate["blocked_positions"])[0]
    assert pos["stop_usable"] is True
    assert pos["loss_at_stop"] == pytest.approx(20.0)


def test_leverage_multiplies_loss_at_stop(tmp_path: Path) -> None:
    f = _write(tmp_path / "h.json", [_pos(leverage=4, **CONFIRMED)])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    # (100 - 90) * 2 * 4 = 80
    assert gate["portfolio_stop_exposure"] == pytest.approx(80.0)
    assert gate["portfolio_stop_exposure_fraction"] == pytest.approx(0.4)


def test_leveraged_unconfirmed_is_critical_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "h.json", [_pos(
        leverage=4, stop_loss=95.0, stop_loss_source="policy_suggested",
        stop_loss_confirmed=False,
    )])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    assert gate["leveraged_without_stop_count"] == 1
    assert any("CRITICAL" in i for i in gate["issues"])
    assert gate["operational_state"] == OP_BLOCKED


def test_directionally_invalid_stop_blocks(tmp_path: Path) -> None:
    f = _write(tmp_path / "h.json", [_pos(
        stop_loss=110.0,  # above entry on a long: invalid
        stop_loss_source="operator", stop_loss_confirmed=True,
        stop_loss_confirmed_at="2026-07-04T10:00:00Z",
    )])
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    blocked = gate["blocked_positions"][0]
    assert blocked["risk_monitoring"] == MON_INVALID_STOP
    assert gate["operational_state"] == OP_BLOCKED


def test_stale_holdings_degraded_when_stops_fine(tmp_path: Path) -> None:
    f = _write(tmp_path / "h.json", [_pos(**CONFIRMED)], run_date="2026-05-22")
    gate = load_holdings_truth_gate(path=f, now_utc=NOW, attach_prices=False)
    assert gate["operational_state"] == OP_DEGRADED
    assert gate["positions"] == []  # stale truth never feeds monitoring


def test_template_policy_and_confirmation_flags(tmp_path: Path) -> None:
    f = _write(tmp_path / "h.json", [
        _pos(),
        _pos(ticker="NSE:HDFCBANK", normalized_ticker="HDFCBANK.NS",
             leverage=4, entry_price=768.55, quantity=5.8411),
    ])
    template = build_stop_loss_template(path=f, now_utc=NOW)
    assert len(template["entries"]) == 2
    one_x = next(e for e in template["entries"] if e["ticker"] == "NASDAQ:ANET")
    lev = next(e for e in template["entries"] if e["ticker"] == "NSE:HDFCBANK")
    assert one_x["stop_loss_candidate"] == pytest.approx(95.0)
    assert lev["stop_loss_candidate"] == pytest.approx(768.55 * 0.975, rel=1e-6)
    for e in template["entries"]:
        assert e["requires_operator_confirmation"] is True
        assert e["stop_loss_confirmed"] is False
        assert e["stop_loss_source"] == "policy_suggested"
    assert template["holdings_confirmed_current"] is False


def test_apply_confirmed_skips_unconfirmed_and_applies_confirmed(
    tmp_path: Path,
) -> None:
    holdings = _write(tmp_path / "h.json", [
        _pos(), _pos(ticker="NYSE:XOM", normalized_ticker="XOM",
                     entry_price=150.0),
    ])
    template = {
        "entries": [
            {  # NOT confirmed -> must be skipped
                "ticker": "NASDAQ:ANET", "stop_loss": 95.0,
                "stop_loss_source": "policy_suggested",
                "stop_loss_confirmed": False, "stop_loss_confirmed_at": None,
            },
            {  # confirmed -> applied with provenance upgrade
                "ticker": "NYSE:XOM", "stop_loss": 140.0,
                "stop_loss_source": "policy_suggested",
                "stop_loss_confirmed": True,
                "stop_loss_confirmed_at": "2026-07-04T11:00:00Z",
            },
        ],
    }
    tpath = tmp_path / "template.json"
    tpath.write_text(json.dumps(template), encoding="utf-8")
    result = apply_confirmed_template(
        template_path=tpath, holdings_path=holdings, now_utc=NOW, write=True,
    )
    assert result["status"] == "OK"
    assert [a["ticker"] for a in result["applied"]] == ["NYSE:XOM"]
    assert result["applied"][0]["stop_loss_source"] == "policy_confirmed"
    assert [s["ticker"] for s in result["skipped"]] == ["NASDAQ:ANET"]
    saved = json.loads(holdings.read_text(encoding="utf-8"))
    xom = next(p for p in saved["positions"] if p["ticker"] == "NYSE:XOM")
    assert xom["stop_loss"] == 140.0
    assert xom["stop_loss_confirmed"] is True
    assert xom["stop_loss_updated_at"] == "2026-07-04T11:00:00Z"
    anet = next(p for p in saved["positions"] if p["ticker"] == "NASDAQ:ANET")
    assert "stop_loss" not in anet or anet.get("stop_loss") is None
    # a backup of the pre-apply file must exist
    assert result.get("backup_path") and Path(result["backup_path"]).exists()


def test_apply_confirmed_rejects_invalid_direction(tmp_path: Path) -> None:
    holdings = _write(tmp_path / "h.json", [_pos()])
    tpath = tmp_path / "template.json"
    tpath.write_text(json.dumps({"entries": [{
        "ticker": "NASDAQ:ANET", "stop_loss": 120.0,  # above entry: invalid
        "stop_loss_confirmed": True,
        "stop_loss_confirmed_at": "2026-07-04T11:00:00Z",
    }]}), encoding="utf-8")
    result = apply_confirmed_template(
        template_path=tpath, holdings_path=holdings, now_utc=NOW, write=True,
    )
    assert result["applied"] == []
    assert "directionally valid" in result["skipped"][0]["reason"]
    saved = json.loads(holdings.read_text(encoding="utf-8"))
    assert "stop_loss" not in saved["positions"][0]


def test_apply_confirmed_refreshes_run_date_only_when_confirmed(
    tmp_path: Path,
) -> None:
    holdings = _write(tmp_path / "h.json", [_pos(**CONFIRMED)],
                      run_date="2026-05-22")
    tpath = tmp_path / "template.json"
    tpath.write_text(json.dumps({
        "entries": [],
        "holdings_confirmed_current": True,
        "holdings_confirmed_current_at": "2026-07-04T11:30:00Z",
    }), encoding="utf-8")
    result = apply_confirmed_template(
        template_path=tpath, holdings_path=holdings, now_utc=NOW, write=True,
    )
    assert result["run_date_refreshed"] is True
    saved = json.loads(holdings.read_text(encoding="utf-8"))
    assert saved["run_date"] == "2026-07-04"
    assert "operator confirmed" in saved["run_date_provenance"]
    # and WITHOUT the confirmation flag nothing changes
    holdings2 = _write(tmp_path / "h2.json", [_pos(**CONFIRMED)],
                       run_date="2026-05-22")
    tpath2 = tmp_path / "t2.json"
    tpath2.write_text(json.dumps({"entries": [],
                                  "holdings_confirmed_current": False}),
                      encoding="utf-8")
    r2 = apply_confirmed_template(
        template_path=tpath2, holdings_path=holdings2, now_utc=NOW, write=True,
    )
    assert r2["run_date_refreshed"] is False
    assert json.loads(holdings2.read_text())["run_date"] == "2026-05-22"


def test_full_confirmation_loop_unblocks_risk_gate(tmp_path: Path) -> None:
    """End-to-end: template -> operator confirms -> apply -> gate passes."""
    holdings = _write(tmp_path / "h.json", [_pos()])
    template = build_stop_loss_template(path=holdings, now_utc=NOW)
    # operator confirms the suggestion and holdings currency
    template["entries"][0]["stop_loss_confirmed"] = True
    template["entries"][0]["stop_loss_confirmed_at"] = "2026-07-04T11:00:00Z"
    template["holdings_confirmed_current"] = True
    template["holdings_confirmed_current_at"] = "2026-07-04T11:00:00Z"
    tpath = tmp_path / "template.json"
    tpath.write_text(json.dumps(template), encoding="utf-8")
    result = apply_confirmed_template(
        template_path=tpath, holdings_path=holdings, now_utc=NOW, write=True,
    )
    assert result["status"] == "OK"
    gate = load_holdings_truth_gate(path=holdings, now_utc=NOW,
                                    attach_prices=False)
    assert gate["missing_stop_count"] == 0
    assert gate["unconfirmed_stop_count"] == 0
    assert gate["operational_state"] == OP_HEALTHY
    assert gate["portfolio_stop_exposure"] is not None
