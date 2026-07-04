"""Phase 2 — deterministic ticker resolution tests (advisory-only)."""
from __future__ import annotations

from scripts.ticker_resolution import (
    ACCEPT_CONFIDENCE,
    REASON_AMBIGUOUS,
    REASON_NO_IDENTIFIER,
    RESOLVER_VERSION,
    company_name_to_ticker,
    resolve_ticker,
    sec_cik_to_ticker,
    ticker_valid,
)


def test_resolves_ticker_from_direct_field():
    res = resolve_ticker(event_row={"ticker": "spy"})
    assert res["ticker"] == "SPY"
    assert res["method"] == "direct_symbol_field"
    assert res["confidence"] >= ACCEPT_CONFIDENCE


def test_resolves_ticker_from_payload_symbol():
    res = resolve_ticker(payload={"symbol": "TLT"})
    assert res["ticker"] == "TLT"
    assert res["source_field"] == "payload.symbol"


def test_resolves_sec_cik_to_aapl():
    res = resolve_ticker(payload={"cik": "0000320193", "entity_name": None})
    assert res["ticker"] == "AAPL"
    assert res["method"] == "sec_cik_map"
    assert res["confidence"] >= ACCEPT_CONFIDENCE
    # Integer form resolves too.
    assert sec_cik_to_ticker(320193) == "AAPL"


def test_resolves_sec_company_name_to_msft():
    res = resolve_ticker(payload={"entity_name": "MICROSOFT CORP"})
    assert res["ticker"] == "MSFT"
    assert res["method"] == "company_name_map"


def test_rejects_unknown_ticker():
    assert not ticker_valid("UNKNOWN")
    assert not ticker_valid("")
    assert not ticker_valid(None)
    assert not ticker_valid("N/A")


def test_rejects_ambiguous_company_name():
    res = resolve_ticker(payload={"entity_name": "Alphabet Inc."})
    assert res["ticker"] is None
    assert res["reason"] == REASON_AMBIGUOUS
    t, reason = company_name_to_ticker("Alphabet Inc.")
    assert t is None and reason == REASON_AMBIGUOUS


def test_does_not_fuzzy_guess_low_confidence():
    # An unknown small-cap company name is never guessed.
    res = resolve_ticker(payload={"entity_name": "Acme Widgets Holdings LLC"})
    assert res["ticker"] is None
    assert res["reason"] == REASON_NO_IDENTIFIER
    assert res["confidence"] == 0.0


def test_preserves_exchange_prefixes():
    # Dotted/suffixed and prefixed symbols are accepted verbatim.
    assert resolve_ticker(payload={"symbol": "RHM.DE"})["ticker"] == "RHM.DE"
    assert resolve_ticker(payload={"symbol": "BTC-USD"})["ticker"] == "BTC-USD"
    assert resolve_ticker(event_row={"ticker": "NSE:SBIN"})["ticker"] == "NSE:SBIN"


def test_ticker_resolution_returns_method_and_confidence():
    res = resolve_ticker(score_vector={"ticker": "Tesla, Inc."})
    assert res["ticker"] == "TSLA"
    assert res["method"] == "score_vector_company_name"
    assert res["resolver_version"] == RESOLVER_VERSION
    assert 0.0 < res["confidence"] <= 1.0


def test_no_fake_ticker_for_unmapped_company():
    # No identifier of any kind -> None, never invented.
    res = resolve_ticker(payload={"title": "Some macro news with no issuer"})
    assert res["ticker"] is None
    assert res["reason"] == REASON_NO_IDENTIFIER


def test_title_company_name_resolution():
    res = resolve_ticker(payload={"title": "NVIDIA Corporation reports Q3 filing"})
    assert res["ticker"] == "NVDA"
    assert res["method"] == "title_company_name"


def test_direct_field_beats_cik_priority():
    # An explicit clean symbol wins over a CIK that maps elsewhere.
    res = resolve_ticker(payload={"symbol": "MSFT", "cik": "0000320193"})
    assert res["ticker"] == "MSFT"
    assert res["method"] == "direct_symbol_field"
