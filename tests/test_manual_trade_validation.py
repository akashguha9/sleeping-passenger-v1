"""Tests for manual-trade validation hardening (Phase 12 items 14-17).

Ticker canonicalization (no silent cross-exchange collision), currency mapping,
malformed-input rejection, and the duplicate natural key. All deterministic.
"""
from __future__ import annotations

import importlib

mtv = importlib.import_module("scripts.manual_trade_validation")


# --- ticker canonicalization (15) ------------------------------------------
def test_explicit_exchange_symbol_resolves():
    r = mtv.canonical_ticker("NSE:BHARTIARTL")
    assert r.ok and r.canonical == "NSE:BHARTIARTL"
    assert r.exchange == "NSE" and r.currency == "INR"


def test_suffix_form_maps_to_canonical():
    r = mtv.canonical_ticker("8306.T")
    assert r.ok and r.canonical == "TYO:8306" and r.currency == "JPY"
    r2 = mtv.canonical_ticker("RELIANCE.NS")
    assert r2.ok and r2.canonical == "NSE:RELIANCE" and r2.currency == "INR"


def test_same_symbol_different_exchange_does_not_collide():
    air_epa = mtv.canonical_ticker("EPA:AIR")
    air_etr = mtv.canonical_ticker("ETR:AIR")
    assert air_epa.ok and air_etr.ok
    assert air_epa.canonical != air_etr.canonical
    # natural keys differ too
    k1 = mtv.manual_trade_natural_key({"ticker": "EPA:AIR", "entry_price": 100,
                                       "direction": "LONG", "provenance_type": "LIVE_MANUAL"})
    k2 = mtv.manual_trade_natural_key({"ticker": "ETR:AIR", "entry_price": 100,
                                       "direction": "LONG", "provenance_type": "LIVE_MANUAL"})
    assert k1 != k2


def test_bare_symbol_is_rejected():
    for bare in ("RELIANCE", "SAP", "TSM", "MSFT"):
        r = mtv.canonical_ticker(bare)
        assert not r.ok
        assert r.reason == "bare_symbol_no_exchange"


def test_unsupported_exchange_rejected():
    r = mtv.canonical_ticker("ZZZ:FOO")
    assert not r.ok and r.reason.startswith("unsupported_exchange")
    r2 = mtv.canonical_ticker("FOO", exchange="ZZZ")
    assert not r2.ok and r2.reason.startswith("unsupported_exchange")


def test_bare_symbol_with_explicit_exchange_resolves():
    r = mtv.canonical_ticker("RELIANCE", exchange="NSE")
    assert r.ok and r.canonical == "NSE:RELIANCE"


def test_canonical_collapses_equivalent_forms():
    # RELIANCE.NS and NSE:RELIANCE are the same economic instrument.
    a = mtv.canonical_ticker("RELIANCE.NS").canonical
    b = mtv.canonical_ticker("NSE:RELIANCE").canonical
    assert a == b == "NSE:RELIANCE"


# --- currency mapping (16) -------------------------------------------------
def test_currency_for_exchange_explicit_map():
    expected = {"NSE": "INR", "NASDAQ": "USD", "NYSE": "USD", "NYSEARCA": "USD",
                "LSE": "GBP", "ETR": "EUR", "EPA": "EUR", "TYO": "JPY", "KRX": "KRW"}
    for ex, cur in expected.items():
        assert mtv.currency_for_exchange(ex) == cur


def test_unknown_exchange_currency_is_none():
    assert mtv.currency_for_exchange("ZZZ") is None


# --- whole-record validation (14) ------------------------------------------
def _base():
    return {"ticker": "NSE:RELIANCE", "exchange": "NSE", "entry_price": 100.0,
            "quantity": 10, "currency": "INR", "direction": "LONG",
            "entry_date": "2026-01-10", "provenance_type": "LIVE_MANUAL"}


def test_clean_record_passes():
    assert mtv.validate_manual_trade(_base()) == []
    assert mtv.is_valid_manual_trade(_base())


def test_rejects_each_malformed_field():
    cases = {
        "non_positive_entry_price": {**_base(), "entry_price": 0},
        "non_positive_quantity": {**_base(), "quantity": -5},
        "invalid_entry_date": {**_base(), "entry_date": "not-a-date"},
        "exit_before_entry": {**_base(), "exit_date": "2026-01-05"},
        "bare_symbol_no_exchange": {**_base(), "ticker": "RELIANCE", "exchange": ""},
        "missing_provenance_type": {k: v for k, v in _base().items() if k != "provenance_type"},
        "unknown_mode": {**_base(), "provenance_type": "WHATEVER"},
    }
    for expected_code, rec in cases.items():
        violations = mtv.validate_manual_trade(rec)
        assert expected_code in violations, f"{expected_code} not flagged: {violations}"


def test_currency_exchange_mismatch_flagged():
    rec = {**_base(), "currency": "USD"}  # NSE should be INR
    assert "currency_exchange_mismatch" in mtv.validate_manual_trade(rec)


def test_notional_accepted_in_place_of_quantity():
    rec = {**_base(), "quantity": 0, "notional": 5000}
    assert "non_positive_quantity" not in mtv.validate_manual_trade(rec)


# --- duplicate natural key (17) --------------------------------------------
def test_identical_trades_share_natural_key():
    a = mtv.manual_trade_natural_key(_base())
    b = mtv.manual_trade_natural_key(dict(_base()))
    assert a == b


def test_equivalent_ticker_forms_share_natural_key():
    a = mtv.manual_trade_natural_key({**_base(), "ticker": "RELIANCE.NS", "exchange": ""})
    b = mtv.manual_trade_natural_key({**_base(), "ticker": "NSE:RELIANCE"})
    assert a == b


def test_different_provenance_changes_key():
    a = mtv.manual_trade_natural_key({**_base(), "provenance_type": "LIVE_MANUAL"})
    b = mtv.manual_trade_natural_key({**_base(), "provenance_type": "PAPER"})
    assert a != b
