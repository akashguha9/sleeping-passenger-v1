"""Objective 2 — leverage-policy ceiling enforcement (advisory-only risk control).

Policy (Year-1 operating philosophy):
    L_max(ticker, country) = 4  for Indian equity
                           = 1  for rest-of-world (spot-only)

These tests prove the policy is enforced *in code* (not just documented) at
two levels:

  * the pure :mod:`scripts.leverage_policy` validator, and
  * the ``log_manual_trade`` API boundary — an out-of-policy leverage is
    rejected BEFORE persistence, with the advisory-only safety stamps intact.

Rejecting bad leverage is risk control, not execution: no broker field is
unlocked, ``execution_gate`` stays LOCKED, ``broker_api_called`` stays False,
``ai_execution_count`` stays 0.
"""
from __future__ import annotations

import pytest

from scripts.leverage_policy import (
    INDIA_MAX_LEVERAGE,
    ROW_MAX_LEVERAGE,
    LEVERAGE_POLICY_VIOLATION,
    get_max_allowed_leverage,
    is_india_instrument,
    validate_leverage_policy,
)


def _api():
    import scripts.signal_inbox_api as api
    return api


# ---------------------------------------------------------------------------
# Pure validator — India detection + ceilings
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ticker,country",
    [
        ("NSE:RELIANCE", "India"),
        ("BSE:TCS", "India"),
        ("RELIANCE.NS", None),
        ("TCS.BO", None),
        ("INFY.NS", "in"),
    ],
)
def test_india_instruments_detected(ticker, country):
    assert is_india_instrument(ticker, country) is True
    assert get_max_allowed_leverage(ticker, country) == INDIA_MAX_LEVERAGE


@pytest.mark.parametrize(
    "ticker,country",
    [
        ("NASDAQ:MSFT", "USA"),
        ("NYSE:XOM", "USA"),
        ("TSM", "Taiwan"),
        ("ASML", "Netherlands"),
        ("GLD", "USA"),
        ("SPY", None),
    ],
)
def test_rest_of_world_instruments_spot_only(ticker, country):
    assert is_india_instrument(ticker, country) is False
    assert get_max_allowed_leverage(ticker, country) == ROW_MAX_LEVERAGE


# India accept/reject matrix (from the spec) -------------------------------

@pytest.mark.parametrize(
    "ticker,country,lev,ok",
    [
        ("NSE:RELIANCE", "India", 1.0, True),
        ("NSE:RELIANCE", "India", 4.0, True),
        ("NSE:RELIANCE", "India", 4.01, False),
        ("NSE:RELIANCE", "India", 25.0, False),
        ("RELIANCE.NS", None, 4.0, True),
        ("RELIANCE.NS", None, 4.01, False),
        ("BSE:TCS", "India", 4.0, True),
        ("TCS.BO", None, 4.01, False),
    ],
)
def test_india_leverage_matrix(ticker, country, lev, ok):
    res = validate_leverage_policy(ticker, country, lev)
    assert res.valid is ok
    if not ok:
        assert res.reason == LEVERAGE_POLICY_VIOLATION
        assert res.allowed_max_leverage == INDIA_MAX_LEVERAGE


# Rest-of-world accept/reject matrix (from the spec) -----------------------

@pytest.mark.parametrize(
    "ticker,country,lev,ok",
    [
        ("NASDAQ:MSFT", "USA", 1.0, True),
        ("NASDAQ:MSFT", "USA", 1.01, False),
        ("NYSE:XOM", "USA", 4.0, False),
        ("TSM", "Taiwan", 4.0, False),
        ("ASML", "Netherlands", 2.0, False),
        ("GLD", "USA", 4.0, False),
    ],
)
def test_rest_of_world_leverage_matrix(ticker, country, lev, ok):
    res = validate_leverage_policy(ticker, country, lev)
    assert res.valid is ok
    if not ok:
        assert res.reason == LEVERAGE_POLICY_VIOLATION
        assert res.allowed_max_leverage == ROW_MAX_LEVERAGE


def test_no_ticker_allows_25x_anywhere():
    """Defensive: 25x must be rejected for every jurisdiction."""
    for ticker, country in [("RELIANCE.NS", "India"), ("MSFT", "USA"), ("ASML", None)]:
        assert validate_leverage_policy(ticker, country, 25.0).valid is False


# ---------------------------------------------------------------------------
# API boundary — rejection happens before persistence, stamps preserved
# ---------------------------------------------------------------------------

def test_api_rejects_row_above_1x_before_persistence(tmp_path, monkeypatch):
    api = _api()
    log_path = tmp_path / "trades.jsonl"
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", log_path)
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.log_manual_trade(
        event_id="EVT_MSFT", ticker="MSFT", side="BUY",
        quantity=1, price=100, thesis="x", leverage=2.0,
    )
    assert "error" in result
    assert result["reason"] == LEVERAGE_POLICY_VIOLATION
    # Nothing was written — rejection is before persistence.
    assert not log_path.exists() or log_path.read_text().strip() == ""


def test_api_accepts_india_up_to_4x(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.log_manual_trade(
        event_id="EVT_RELIANCE", ticker="RELIANCE.NS", side="BUY",
        quantity=1, price=100, thesis="x", leverage=4.0,
    )
    assert result.get("status") == "logged"
    assert result["leverage"] == 4.0


def test_api_rejects_india_above_4x(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.log_manual_trade(
        event_id="EVT_RELIANCE", ticker="RELIANCE.NS", side="BUY",
        quantity=1, price=100, thesis="x", leverage=4.01,
    )
    assert "error" in result
    assert result["reason"] == LEVERAGE_POLICY_VIOLATION


def test_api_accepts_row_spot_1x(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.log_manual_trade(
        event_id="EVT_SPY", ticker="SPY", side="BUY",
        quantity=1, price=100, thesis="x", leverage=1.0,
    )
    assert result.get("status") == "logged"
    assert result["leverage"] == 1.0


# ---------------------------------------------------------------------------
# Safety regression — rejection NEVER unlocks execution
# ---------------------------------------------------------------------------

def test_leverage_rejection_preserves_advisory_stamps(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.log_manual_trade(
        event_id="EVT_XOM", ticker="NYSE:XOM", side="BUY",
        quantity=1, price=100, thesis="x", leverage=4.0,
    )
    assert "error" in result
    # Advisory-only invariants on the rejection path.
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == "NONE"
    assert result["ai_execution_count"] == 0
    assert result["human_review_required"] is True
    assert result["execution_permission"] == "ADVISORY_ONLY"


def test_validator_result_carries_locked_stamps_on_reject():
    res = validate_leverage_policy("MSFT", "USA", 5.0)
    d = res.to_dict()
    assert d["leverage_policy_valid"] is False
    assert d["execution_gate"] == "LOCKED"
    assert d["broker_api_called"] is False
    assert d["ai_execution_count"] == 0
    assert d["execution_permission"] == "ADVISORY_ONLY"
    assert d["human_execution_required"] is True
