"""Tests — UK RNS + Companies House filing adapters (P2).

Deterministic, no network, no API key. Proves: injected RNS rows become fresh
mapped SignalEvent-like rows; unconfigured/empty providers never claim live;
private/unlisted Companies House rows are retained but not tradable; and a
fresh UK filing lifts C_filings for the United Kingdom.
"""
from __future__ import annotations

import pytest

from scripts.global_filings_loader import (
    PRIVATE_UNLISTED_REASON,
    STATUS_LIVE_VERIFIED,
    STATUS_OK_EMPTY,
    STATUS_PROVIDER_NOT_CONFIGURED,
    build_uk_filing_events,
    load_companies_house_filings,
    load_uk_rns_filings,
    normalize_companies_house_row,
    normalize_uk_rns_row,
)
from scripts.top30_country_coverage import build_country_coverage_from_payload

_FRESH = "2026-05-29T08:00:00+00:00"


def _rns_row():
    return {
        "entity_name": "Shell",
        "ticker": "SHEL.L",
        "headline": "Shell plc half-year results",
        "event_type": "regulatory",
        "published_at_utc": _FRESH,
        "freshness_score": 1.0,
    }


# 1: RNS fixture row -> fresh SignalEvent-like row -----------------------------

def test_uk_rns_row_becomes_fresh_signal_event():
    ev = normalize_uk_rns_row(_rns_row())
    assert ev["source_name"] == "UK_RNS"
    assert ev["country"] == "United Kingdom"
    assert ev["jurisdiction"] == "UK"
    assert ev["ticker"] == "SHEL.L"
    assert ev["is_live"] is True
    assert ev["freshness_score"] > 0
    assert ev["executable_allowed"] is False
    assert ev["safety"]["execution_gate"] == "LOCKED"


# 2: Companies House row parsed honestly --------------------------------------

def test_companies_house_listed_row_maps():
    ev = normalize_companies_house_row(
        {"entity_name": "Shell", "ticker": "SHEL.L",
         "company_number": "04366849", "headline": "RNS via CH",
         "published_at_utc": _FRESH, "freshness_score": 1.0}
    )
    assert ev["source_name"] == "UK_COMPANIES_HOUSE"
    assert ev["ticker"] == "SHEL.L"
    assert ev["tradable_candidate"] is True


# 3: provider not configured does not claim live ------------------------------

def test_provider_not_configured_not_live(monkeypatch):
    monkeypatch.delenv("LSE_RNS_API_KEY", raising=False)
    events, meta = load_uk_rns_filings()  # no injection, no key
    assert events == []
    assert meta["status"] == STATUS_PROVIDER_NOT_CONFIGURED
    assert meta["is_live"] is False


# 4: empty provider response is OK_EMPTY, not fake live ------------------------

def test_empty_response_is_ok_empty_not_live():
    events, meta = load_uk_rns_filings([])  # attempted, zero rows
    assert events == []
    assert meta["status"] == STATUS_OK_EMPTY
    assert meta["is_live"] is False


def test_stale_row_is_not_live():
    ev = normalize_uk_rns_row(
        {"entity_name": "Shell", "ticker": "SHEL.L",
         "published_at_utc": "2020-01-01T00:00:00+00:00"}
    )
    assert ev["is_live"] is False
    assert ev["freshness_score"] == 0.0


# 5: fresh UK RNS row improves C_filings for the UK ---------------------------

def test_fresh_uk_filing_lifts_c_filings():
    events, _ = build_uk_filing_events(rns_rows=[_rns_row()])
    payload = {
        "price_movers": {"movers": []},
        "news_events": {"events": []},
        "filings_events": {"events": events},
    }
    mapping_rows = [
        {"mapping_confidence": e["mapping_confidence"], "country": e["country"],
         "ticker": e["ticker"]}
        for e in events if e.get("ticker")
    ]
    cov = build_country_coverage_from_payload(
        payload, mapping_rows=mapping_rows, universe_records=[]
    )
    assert cov["ratios"]["C_filings"] > 0.0
    uk = next(r for r in cov["countries"] if r["country"] == "United Kingdom")
    assert uk["filings_support"] == 1


# 6: live verified status when fresh rows present -----------------------------

def test_live_verified_when_fresh_rows_present():
    _, meta = build_uk_filing_events(rns_rows=[_rns_row()])
    assert meta["is_live"] is True
    rns_meta = next(p for p in meta["providers"] if p["provider"] == "lse_rns")
    assert rns_meta["status"] == STATUS_LIVE_VERIFIED


# 7: private / unlisted Companies House row retained but not tradable ----------

def test_private_unlisted_company_retained_not_tradable():
    events, meta = load_companies_house_filings(
        [{"entity_name": "Acme Private Holdings Ltd", "company_number": "12345678",
          "headline": "Annual accounts filed", "published_at_utc": _FRESH,
          "freshness_score": 1.0}]
    )
    assert len(events) == 1  # retained, never dropped
    row = events[0]
    assert row["ticker"] is None
    assert row["tradable_candidate"] is False
    assert row["mapping_failure_reason"] == PRIVATE_UNLISTED_REASON


# 8: every row carries advisory safety stamps ---------------------------------

def test_all_rows_carry_advisory_stamps():
    events, _ = build_uk_filing_events(
        rns_rows=[_rns_row()],
        companies_house_rows=[{"entity_name": "Acme Private Ltd",
                               "company_number": "999", "published_at_utc": _FRESH,
                               "freshness_score": 1.0}],
    )
    for e in events:
        assert e["executable_allowed"] is False
        assert e["advisory_only"] is True
        s = e["safety"]
        assert s["execution_gate"] == "LOCKED"
        assert s["broker_api_called"] is False
        assert s["ai_execution_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
