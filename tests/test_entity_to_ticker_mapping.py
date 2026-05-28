"""Tests — entity-to-ticker mapping (global, confidence-scored, never drops)."""
from __future__ import annotations

import pytest

from scripts import persistence
from scripts.entity_ticker_mapper import (
    DEFAULT_THETA_MAP,
    map_event_to_tickers,
    valid_mapped_event,
)


def test_exact_name_match_high_confidence():
    # "SAP SE" is an exact name in the committed global securities master (DE).
    rows = map_event_to_tickers({"entity_name": "SAP SE", "country": "DE"})
    assert rows[0]["mapping_status"] == "MAPPED"
    assert rows[0]["ticker"] == "SAP.DE"
    assert rows[0]["country"] == "Germany"
    assert rows[0]["mapping_confidence"] >= DEFAULT_THETA_MAP


def test_non_us_alias_maps_to_local_ticker_via_db(tmp_path):
    db = tmp_path / "t.db"
    persistence.upsert_security_alias("RHEINMETALL", "RHM.DE", confidence=1.0, db_path=db)
    rows = map_event_to_tickers(
        {"entity_name": "RHEINMETALL", "country": "DE"}, db_path=db
    )
    assert rows[0]["ticker"] == "RHM.DE"
    assert rows[0]["country"] == "Germany"
    assert rows[0]["is_local_listing"] is True
    assert rows[0]["mapping_confidence"] >= DEFAULT_THETA_MAP


def test_passthrough_ticker_local_listing_flag():
    rows = map_event_to_tickers({"ticker": "RELIANCE.NS", "country": "IN"})
    assert rows[0]["ticker"] == "RELIANCE.NS"
    assert rows[0]["is_local_listing"] is True
    assert rows[0]["mapping_confidence"] >= 0.70


def test_adr_etf_on_us_exchange_flagged_is_adr():
    # An MSCI country ETF in the master is foreign-country but US-listed (NYSE).
    rows = map_event_to_tickers({"entity_name": "iShares MSCI Japan ETF"})
    assert rows[0]["ticker"] == "EWJ"
    assert rows[0]["country"] == "Japan"
    assert rows[0]["is_adr"] is True
    assert rows[0]["is_local_listing"] is False


def test_ambiguous_entity_is_not_silently_mapped():
    # "iShares" matches many ETFs -> ambiguous, retained as UNMAPPED.
    rows = map_event_to_tickers({"entity_name": "iShares"})
    assert rows[0]["mapping_status"] == "UNMAPPED"
    assert rows[0]["mapping_failure_reason"] == "MULTIPLE_LOW_CONFIDENCE_MATCHES"


def test_unmapped_event_is_retained_with_reason():
    rows = map_event_to_tickers({"entity_name": "Totally Unknown Private GmbH", "country": "DE"})
    assert len(rows) == 1
    assert rows[0]["mapping_status"] == "UNMAPPED"
    assert rows[0]["ticker"] is None
    assert rows[0]["mapping_failure_reason"]


def test_no_entity_no_ticker_reason():
    rows = map_event_to_tickers({"headline": "markets moved"})
    assert rows[0]["mapping_failure_reason"] == "NO_ENTITY"


def test_valid_mapped_event_gate():
    mapped = map_event_to_tickers({"ticker": "RHM.DE", "country": "DE"})[0]
    assert valid_mapped_event(mapped, top30_set={"Germany"}) is True
    # A phantom ticker is never valid.
    mapped_phantom = map_event_to_tickers(
        {"ticker": "GLD", "country": "US"}, phantom_set={"GLD"}
    )[0]
    assert valid_mapped_event(mapped_phantom) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
