"""Behavioural tests for securities-master-backed jurisdiction resolution.

Precedence: EXPLICIT > SECURITIES_MASTER > TICKER_HEURISTIC > UNKNOWN_FAIL_CLOSED.
The securities lookup is injected as a callable so the core module stays pure.
"""
from __future__ import annotations

import pytest

from scripts import leverage_governance as lg


def _master(rows: dict[str, dict]):
    """Return a securities_lookup callable backed by an in-memory dict."""
    def _lookup(sym: str):
        return rows.get(sym.upper())
    return _lookup


# --- SECURITIES_MASTER resolution -------------------------------------------

def test_bare_us_ticker_resolves_row_from_master():
    lookup = _master({"AAPL": {"exchange_code": "NASDAQ", "country": "US"}})
    res = lg.validate_leverage_policy(ticker="AAPL", leverage=1.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.REST_OF_WORLD
    assert res["jurisdiction_resolution_source"] == lg.SRC_SECURITIES_MASTER
    assert res["breach"] is False


def test_bare_us_ticker_over_spot_breaches_via_master():
    lookup = _master({"AAPL": {"exchange_code": "NASDAQ", "country": "US"}})
    res = lg.validate_leverage_policy(ticker="AAPL", leverage=2.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.REST_OF_WORLD
    assert res["jurisdiction_resolution_source"] == lg.SRC_SECURITIES_MASTER
    assert res["breach"] is True and res["severity"] == lg.SEV_BREACH


def test_bare_india_ticker_resolves_india_from_master():
    lookup = _master({"RELIANCE": {"exchange_code": "NSE", "country": "IN"}})
    res = lg.validate_leverage_policy(ticker="RELIANCE", leverage=4.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["jurisdiction_resolution_source"] == lg.SRC_SECURITIES_MASTER
    assert res["ceiling"] == 4.0 and res["breach"] is False


def test_master_india_over_4x_breaches():
    lookup = _master({"RELIANCE": {"exchange_code": "NSE", "country": "IN"}})
    res = lg.validate_leverage_policy(ticker="RELIANCE", leverage=5.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["breach"] is True


# --- Precedence: EXPLICIT wins over master ----------------------------------

def test_explicit_overrides_master():
    # Master says US/NASDAQ, but operator explicitly tags India.
    lookup = _master({"AAPL": {"exchange_code": "NASDAQ", "country": "US"}})
    res = lg.validate_leverage_policy(
        ticker="AAPL", leverage=3.0, jurisdiction="IN", securities_lookup=lookup
    )
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["jurisdiction_resolution_source"] == lg.SRC_EXPLICIT
    assert res["breach"] is False  # 3x <= 4x India ceiling


# --- Precedence: TICKER_HEURISTIC when master misses ------------------------

def test_ticker_heuristic_when_master_has_no_row():
    lookup = _master({})  # empty master
    res = lg.validate_leverage_policy(ticker="RELIANCE.NS", leverage=4.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["jurisdiction_resolution_source"] == lg.SRC_TICKER_HEURISTIC


def test_nse_prefix_resolves_india_via_heuristic():
    res = lg.validate_leverage_policy(ticker="NSE:RELIANCE", leverage=4.0)
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["jurisdiction_resolution_source"] == lg.SRC_TICKER_HEURISTIC


@pytest.mark.parametrize("exch", ["TYO", "KRX", "ETR", "LSE", "NYSE", "NASDAQ"])
def test_row_exchanges_resolve_explicit(exch):
    res = lg.validate_leverage_policy(ticker="X", leverage=1.0, exchange=exch)
    assert res["jurisdiction_group"] == lg.REST_OF_WORLD
    assert res["jurisdiction_resolution_source"] == lg.SRC_EXPLICIT


# --- UNKNOWN fail-closed -----------------------------------------------------

def test_unknown_when_master_misses_and_no_suffix():
    lookup = _master({})
    res = lg.validate_leverage_policy(ticker="MYSTERYCO", leverage=3.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.UNKNOWN
    assert res["jurisdiction_resolution_source"] == lg.SRC_UNKNOWN_FAIL_CLOSED
    assert res["breach"] is True  # >1x on unknown fails closed


def test_master_row_without_jurisdiction_falls_through_to_unknown():
    # Master row exists but has no exchange/country -> cannot classify -> UNKNOWN.
    lookup = _master({"WEIRD": {"exchange_code": "", "country": ""}})
    res = lg.validate_leverage_policy(ticker="WEIRD", leverage=2.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.UNKNOWN
    assert res["jurisdiction_resolution_source"] == lg.SRC_UNKNOWN_FAIL_CLOSED


def test_lookup_exception_does_not_break_policy():
    def _boom(sym: str):
        raise RuntimeError("db down")
    res = lg.validate_leverage_policy(ticker="RELIANCE.NS", leverage=4.0, securities_lookup=_boom)
    # Falls back to ticker heuristic; never raises.
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["jurisdiction_resolution_source"] == lg.SRC_TICKER_HEURISTIC


# --- No execution surface introduced ----------------------------------------

def test_resolution_never_grants_execution():
    lookup = _master({"AAPL": {"exchange_code": "NASDAQ", "country": "US"}})
    res = lg.validate_leverage_policy(ticker="AAPL", leverage=9.0, securities_lookup=lookup)
    assert res["broker_api_called"] is False
    assert res["advisory_only"] is True
    assert res["human_execution_required"] is True
