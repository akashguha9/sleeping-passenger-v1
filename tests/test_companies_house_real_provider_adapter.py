"""Tests — Companies House real provider adapter (mission P2).

Deterministic, offline (injected transport / fixtures), no API key, no network.
Proves configured-vs-not honesty, row normalization, listed-vs-private listing
status, private/unlisted retained but non-tradable, and that the API key value
is never logged.
"""
from __future__ import annotations

import json

import pytest

from scripts.global_filings_loader import (
    LISTED_MAPPED,
    PRIVATE_COMPANY_OR_UNLISTED,
    PRIVATE_UNLISTED_REASON,
    STATUS_LIVE_VERIFIED,
    STATUS_NETWORK_DISABLED,
    STATUS_OK_EMPTY,
    STATUS_PROVIDER_NOT_CONFIGURED,
    companies_house_config_state,
    fetch_companies_house_filings,
    normalize_companies_house_row,
)

_FRESH = "2026-05-29T08:00:00+00:00"


def _listed_raw():
    return {
        "entity_name": "Shell", "ticker": "SHEL.L", "company_number": "04366849",
        "headline": "RNS via CH", "filing_type": "annual-return",
        "published_at_utc": _FRESH, "freshness_score": 1.0,
    }


def _private_raw():
    return {
        "entity_name": "Acme Private Holdings Ltd", "company_number": "12345678",
        "headline": "Annual accounts filed", "filing_type": "accounts",
        "published_at_utc": _FRESH, "freshness_score": 1.0,
    }


# --- config ------------------------------------------------------------------

def test_configured_vs_not():
    on = companies_house_config_state({"COMPANIES_HOUSE_API_KEY": "ch-secret"})
    assert on["configured"] is True and on["api_key_present"] is True
    off = companies_house_config_state({})
    assert off["configured"] is False
    assert "ch-secret" not in json.dumps(on)


# --- normalization: listed vs private ----------------------------------------

def test_listed_row_maps_and_is_tradable():
    ev = normalize_companies_house_row(_listed_raw())
    assert ev["source_name"] == "UK_COMPANIES_HOUSE"
    assert ev["source_type"] == "registry_filing"
    assert ev["country"] == "United Kingdom"
    assert ev["jurisdiction"] == "UK"
    assert ev["company_number"] == "04366849"
    assert ev["filing_type"] == "annual-return"
    assert ev["ticker"] == "SHEL.L"
    assert ev["listed_status"] == LISTED_MAPPED
    assert ev["tradable_candidate"] is True
    assert ev["mapping_confidence"] >= 0.70
    assert ev["fetched_at_utc"]
    assert ev["executable_allowed"] is False


def test_private_unlisted_retained_not_tradable():
    ev = normalize_companies_house_row(_private_raw())
    assert ev["company_number"] == "12345678"  # retained as evidence
    assert ev["ticker"] is None
    assert ev["listed_status"] == PRIVATE_COMPANY_OR_UNLISTED
    assert ev["tradable_candidate"] is False
    assert ev["mapping_failure_reason"] == PRIVATE_UNLISTED_REASON


def test_stale_listed_row_not_live():
    ev = normalize_companies_house_row(
        {"entity_name": "Shell", "ticker": "SHEL.L", "company_number": "1",
         "published_at_utc": "2019-01-01T00:00:00+00:00"}
    )
    assert ev["is_live"] is False


# --- fetch honesty -----------------------------------------------------------

def test_network_disabled():
    events, meta = fetch_companies_house_filings(allow_network=False, env={})
    assert events == []
    assert meta["status"] == STATUS_NETWORK_DISABLED
    assert meta["is_live"] is False


def test_not_configured_with_network():
    events, meta = fetch_companies_house_filings(allow_network=True, env={})
    assert events == []
    assert meta["status"] == STATUS_PROVIDER_NOT_CONFIGURED


def test_empty_injected_is_ok_empty():
    events, meta = fetch_companies_house_filings(transport=lambda: [])
    assert events == []
    assert meta["status"] == STATUS_OK_EMPTY
    assert meta["is_live"] is False


def test_injected_private_row_retained_not_tradable():
    events, meta = fetch_companies_house_filings(transport=lambda: [_private_raw()])
    assert len(events) == 1
    assert events[0]["tradable_candidate"] is False
    assert meta["status"] == STATUS_LIVE_VERIFIED  # fresh, but never tradable
    assert meta["is_live"] is True


def test_meta_never_logs_secret():
    env = {"COMPANIES_HOUSE_API_KEY": "ch-top-secret-key"}
    _, meta = fetch_companies_house_filings(transport=lambda: [_listed_raw()], env=env)
    assert "ch-top-secret-key" not in json.dumps(meta, default=str)


def test_all_rows_carry_locked_stamps():
    events, _ = fetch_companies_house_filings(
        transport=lambda: [_listed_raw(), _private_raw()]
    )
    for e in events:
        assert e["executable_allowed"] is False
        assert e["safety"]["execution_gate"] == "LOCKED"
        assert e["safety"]["broker_api_called"] is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
