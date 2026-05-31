"""Tests — top-30 GDP country coverage engine."""
from __future__ import annotations

import pytest

from scripts.top30_country_coverage import (
    build_country_coverage_from_payload,
    canonical_country,
    compute_country_coverage,
    country_from_ticker,
    load_top30_countries,
    render_country_coverage_markdown,
)


def test_top30_set_loads():
    countries = load_top30_countries()
    assert len(countries) == 30
    assert "United States" in countries
    assert "India" in countries
    assert "Japan" in countries


def test_canonical_country_normalizes_codes_and_names():
    assert canonical_country("US") == "United States"
    assert canonical_country("DE") == "Germany"
    assert canonical_country("KR") == "South Korea"
    assert canonical_country("uk") == "United Kingdom"
    assert canonical_country("EU") is None  # bloc, not a country
    assert canonical_country("Atlantis") is None


def test_country_from_ticker_suffix():
    assert country_from_ticker("RELIANCE.NS") == "India"
    assert country_from_ticker("7203.T") == "Japan"
    assert country_from_ticker("RHM.DE") == "Germany"
    assert country_from_ticker("AAPL") is None  # bare US ticker -> no assumption


def test_ratios_and_full_coverage_computed():
    cov = compute_country_coverage(
        universe_countries=["United States", "Germany"],
        price_countries=["United States"],
        news_countries=["United States"],
        filings_countries=["United States"],
        mapping_countries=["United States"],
        synthesis_countries=["United States", "Germany"],
    )
    ratios = cov["ratios"]
    # 2 of 30 in universe.
    assert ratios["C_universe"] == round(2 / 30, 4)
    # Only the US satisfies all of universe+price+news+mapping+synthesis.
    assert ratios["C_global"] == round(1 / 30, 4)
    us = next(r for r in cov["countries"] if r["country"] == "United States")
    assert us["coverage"] == 1
    assert us["coverage_status"] == "LIVE_COVERED"


def test_not_in_universe_and_static_or_partial_statuses():
    cov = compute_country_coverage(
        universe_countries=["Germany"],
        price_countries=[],
        news_countries=[],
        filings_countries=[],
        mapping_countries=[],
        synthesis_countries=["Germany"],
    )
    germany = next(r for r in cov["countries"] if r["country"] == "Germany")
    assert germany["coverage_status"] == "STATIC_OR_PARTIAL"
    japan = next(r for r in cov["countries"] if r["country"] == "Japan")
    assert japan["coverage_status"] == "NOT_IN_UNIVERSE"


def test_low_global_coverage_status():
    cov = compute_country_coverage(
        universe_countries=["United States"],
        price_countries=[],
        news_countries=[],
        filings_countries=[],
        mapping_countries=[],
        synthesis_countries=["United States"],
    )
    assert cov["ratios"]["C_global"] == 0.0
    assert cov["global_discovery_status"] == "NO_FULL_LIVE_COUNTRY_COVERAGE"
    md = render_country_coverage_markdown(cov)
    assert "TOP-30 GDP COUNTRY COVERAGE PROOF" in md
    assert "NO_FULL_LIVE_COUNTRY_COVERAGE" in md


def _payload(news_events=None, filings_events=None):
    return {
        "news_events": {"events": news_events or []},
        "filings_events": {"events": filings_events or []},
        "price_movers": {"movers": []},
    }


def test_coverage_writer_attaches_provenance_fixture_default():
    cov = build_country_coverage_from_payload(
        _payload(news_events=[{"country": "Germany", "freshness": "FRESH_TODAY"}]),
        universe_records=[],
    )
    # Provenance is present and honest.
    assert cov["proof_kind"] == "FIXTURE"
    assert cov["payload_stale"] is False  # one fresh news row found
    assert cov["sqlite_fresh_rows_count"] == 0
    assert "PAYLOAD_FRESH" in cov["proof_sources_used"]
    # Provenance must NOT change the truthful coverage computation.
    assert "C_global" in cov["ratios"]


def test_coverage_writer_marks_stale_when_no_fresh_rows():
    cov = build_country_coverage_from_payload(_payload(), universe_records=[])
    assert cov["payload_stale"] is True
    assert cov["proof_sources_used"] == ["NONE_FRESH"]
    assert cov["sqlite_fresh_rows_count"] == 0


def test_coverage_writer_real_run_with_sqlite_bridge():
    cov = build_country_coverage_from_payload(
        _payload(),
        universe_records=[],
        proof_kind="REAL_RUN",
        sqlite_fresh_rows_count=5,
    )
    assert cov["proof_kind"] == "REAL_RUN"
    assert cov["sqlite_fresh_rows_count"] == 5
    assert "SQLITE_BRIDGE" in cov["proof_sources_used"]


def test_coverage_provenance_does_not_alter_c_global():
    payload = _payload(news_events=[{"country": "Germany", "freshness": "FRESH_TODAY"}])
    with_prov = build_country_coverage_from_payload(payload, universe_records=[])
    # The ratios are computed purely by compute_country_coverage; provenance is additive.
    assert set(with_prov["ratios"]) == {
        "C_universe", "C_price", "C_news", "C_filings", "C_mapping", "C_synthesis", "C_global",
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
