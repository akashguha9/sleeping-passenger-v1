"""Tests — top-30 GDP country coverage engine."""
from __future__ import annotations

import pytest

from scripts.top30_country_coverage import (
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
