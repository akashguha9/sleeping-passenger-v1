"""Behavioural tests for the central leverage governance module.

These check *behaviour*, not labels: that India venues permit up to 4.0x,
that rest-of-world venues are spot-only, that unknown jurisdiction fails
closed, and that the advisory invariants are constant.
"""
from __future__ import annotations

import pytest

from scripts import leverage_governance as lg


# --- Doctrine constants stay aligned with complex_systems_diagnostics -------

def test_doctrine_constants():
    assert lg.INDIA_LEVERAGE_CEILING == 4.0
    assert lg.ROW_LEVERAGE_CEILING == 1.0
    assert lg.DEFAULT_LEVERAGE == 1.0


def test_constants_match_complex_systems_diagnostics():
    csd = pytest.importorskip("scripts.complex_systems_diagnostics")
    assert lg.INDIA_LEVERAGE_CEILING == csd.INDIA_LEVERAGE_CEILING
    assert lg.ROW_LEVERAGE_CEILING == csd.ROW_LEVERAGE_CEILING
    assert lg.DEFAULT_LEVERAGE == csd.DEFAULT_LEVERAGE


# --- India: up to 4.0x is within policy -------------------------------------

@pytest.mark.parametrize("exchange", ["NSE", "BSE"])
def test_india_exchange_4x_passes(exchange):
    res = lg.validate_leverage_policy(ticker="RELIANCE", leverage=4.0, exchange=exchange)
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["ceiling"] == 4.0
    assert res["breach"] is False
    assert res["allowed"] is True
    assert res["severity"] == lg.SEV_NONE


def test_india_ticker_suffix_4x_passes():
    res = lg.validate_leverage_policy(ticker="RELIANCE.NS", leverage=4.0)
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["breach"] is False


def test_india_country_4x_passes():
    res = lg.validate_leverage_policy(ticker="TCS", leverage=3.0, country="IN")
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["breach"] is False


def test_nse_just_over_ceiling_flags_breach():
    res = lg.validate_leverage_policy(ticker="RELIANCE", leverage=4.01, exchange="NSE")
    assert res["jurisdiction_group"] == lg.INDIA
    assert res["breach"] is True
    assert res["allowed"] is False
    assert res["severity"] == lg.SEV_BREACH
    assert "4.0" in res["reason"] or "4x" in res["reason"]


def test_nse_well_over_ceiling_flags_breach():
    res = lg.validate_leverage_policy(ticker="RELIANCE.NS", leverage=10.0)
    assert res["breach"] is True
    assert res["severity"] == lg.SEV_BREACH


# --- Rest-of-world: spot-only -----------------------------------------------

@pytest.mark.parametrize("exchange", ["NASDAQ", "NYSE", "LSE", "ETR", "EPA", "TYO", "KRX"])
def test_row_exchange_over_1x_flags_breach(exchange):
    res = lg.validate_leverage_policy(ticker="ACME", leverage=2.0, exchange=exchange)
    assert res["jurisdiction_group"] == lg.REST_OF_WORLD
    assert res["ceiling"] == 1.0
    assert res["breach"] is True
    assert res["severity"] == lg.SEV_BREACH


@pytest.mark.parametrize("exchange", ["NASDAQ", "NYSE", "LSE", "ETR", "EPA", "TYO", "KRX"])
def test_row_exchange_1x_passes(exchange):
    res = lg.validate_leverage_policy(ticker="ACME", leverage=1.0, exchange=exchange)
    assert res["jurisdiction_group"] == lg.REST_OF_WORLD
    assert res["breach"] is False
    assert res["allowed"] is True
    assert res["severity"] == lg.SEV_NONE


def test_row_ticker_suffix_over_1x_flags_breach():
    res = lg.validate_leverage_policy(ticker="VOD.L", leverage=2.0)
    assert res["jurisdiction_group"] == lg.REST_OF_WORLD
    assert res["breach"] is True


# --- Unknown jurisdiction: fail closed --------------------------------------

def test_unknown_jurisdiction_over_1x_does_not_silently_pass():
    res = lg.validate_leverage_policy(ticker="MYSTERY", leverage=3.0)
    assert res["jurisdiction_group"] == lg.UNKNOWN
    assert res["ceiling"] == 1.0
    assert res["breach"] is True
    assert res["allowed"] is False
    assert res["severity"] == lg.SEV_BREACH


def test_unknown_jurisdiction_1x_warns_but_allowed():
    res = lg.validate_leverage_policy(ticker="MYSTERY", leverage=1.0)
    assert res["jurisdiction_group"] == lg.UNKNOWN
    assert res["breach"] is False
    assert res["allowed"] is True
    assert res["severity"] == lg.SEV_WARNING


# --- Defaults / coercion ----------------------------------------------------

def test_missing_leverage_defaults_to_1():
    res = lg.validate_leverage_policy(ticker="AAPL", leverage=None, exchange="NASDAQ")
    assert res["actual_leverage"] == 1.0
    assert res["breach"] is False


def test_sub_unit_leverage_floored_to_1():
    res = lg.validate_leverage_policy(ticker="AAPL", leverage=0.5, exchange="NASDAQ")
    assert res["actual_leverage"] == 1.0


def test_garbage_leverage_defaults_to_1():
    res = lg.validate_leverage_policy(ticker="AAPL", leverage="not-a-number", exchange="NYSE")
    assert res["actual_leverage"] == 1.0
    assert res["breach"] is False


# --- Advisory invariants are constant ---------------------------------------

@pytest.mark.parametrize("lev,exch", [(4.0, "NSE"), (25.0, "NSE"), (1.0, "NYSE"), (5.0, "MYSTERY")])
def test_advisory_invariants_constant(lev, exch):
    res = lg.validate_leverage_policy(ticker="X", leverage=lev, exchange=exch)
    assert res["advisory_only"] is True
    assert res["human_execution_required"] is True
    assert res["broker_api_called"] is False
