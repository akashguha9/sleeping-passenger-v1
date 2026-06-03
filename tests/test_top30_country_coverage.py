"""T6 — top-30 GDP country coverage in the discovery universe.

Pins single-stock (direct OR ADR) coverage for the 30 countries called out
in the audit, and the documented-gap status for the 3 untradeable ones
(Russia sanctioned, Saudi Arabia and UAE foreign-retail restricted).

The brief is explicit: "Expect ~24-25 truly tradeable; do not pad the count
with ETFs". This test enforces that contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.minimum_daily_universe import load_minimum_universe


# The 30-country target list, in the audit's order.
TOP30 = [
    "United States", "China", "Germany", "Japan", "United Kingdom", "India",
    "France", "Italy", "Russia", "Brazil", "Canada", "Australia", "Mexico",
    "Spain", "South Korea", "Turkey", "Indonesia", "Netherlands",
    "Saudi Arabia", "Switzerland", "Poland", "Taiwan", "Ireland", "Belgium",
    "Sweden", "Israel", "Argentina", "Singapore", "Austria",
    "United Arab Emirates",
]

# Countries we expect to have at LEAST one direct or ADR single-name listing.
EXPECTED_DIRECT_OR_ADR = {
    "United States", "China", "Germany", "Japan", "United Kingdom", "India",
    "France", "Italy", "Brazil", "Canada", "Australia", "Mexico", "Spain",
    "South Korea", "Turkey", "Indonesia", "Netherlands", "Switzerland",
    "Poland", "Taiwan", "Ireland", "Belgium", "Sweden", "Israel",
    "Argentina", "Singapore", "Austria",
}

# Countries documented as untradeable (single-name) and tracked in
# `documented_gaps:` -- NEVER padded with ETF entries pretending to be
# stock picks.
EXPECTED_GAPS = {"Russia", "Saudi Arabia", "United Arab Emirates"}


@pytest.fixture(scope="module")
def universe() -> dict:
    return load_minimum_universe()


@pytest.fixture(scope="module")
def yaml_raw() -> dict:
    """Read the YAML directly so we can inspect documented_gaps."""
    p = Path("config/minimum_daily_universe.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_top30_partitioned_into_direct_and_gap_with_no_overlap():
    assert EXPECTED_DIRECT_OR_ADR.isdisjoint(EXPECTED_GAPS)
    assert EXPECTED_DIRECT_OR_ADR | EXPECTED_GAPS == set(TOP30), (
        "Every top-30 country must be either covered by a direct/ADR single "
        "name or documented as a tradeability gap. No silent absences."
    )


def test_27_of_30_countries_have_at_least_one_direct_or_adr_single_stock(universe):
    countries_with_listings = {
        row.get("country") for row in universe["tickers"]
        if row.get("asset_type") == "equity"
    }
    missing = EXPECTED_DIRECT_OR_ADR - countries_with_listings
    assert not missing, (
        f"Top-30 countries missing a direct/ADR single-stock listing: {sorted(missing)}. "
        "Brief: do NOT pad the count with ETFs -- add a real single-name "
        "(local listing or ADR) or move the country to documented_gaps with "
        "an explicit reason."
    )


def test_no_etf_is_marked_as_a_top30_single_stock_pick(universe):
    """Brief: 'do not pad the count with ETFs.' Any row that is asset_type
    'equity' must NOT be a known ETF. We sweep against a small allow-list
    of known ETF tickers that COULD masquerade as a single-name pick."""
    KNOWN_ETF_TICKERS = {
        "GLD", "SLV", "USO", "UNG", "SPY", "QQQ", "IWM", "DIA",
        "EWZ", "EWY", "EWJ", "EWA", "EWS", "EWT", "EWW", "INDA", "FXI",
        "KSA", "UAE", "TUR", "EIDO",
        "XLE", "XLF", "XLK", "TLT", "IEF", "TIP", "HYG", "LQD",
    }
    bad = [
        row for row in universe["tickers"]
        if row.get("asset_type") == "equity"
        and row.get("ticker", "").upper() in KNOWN_ETF_TICKERS
    ]
    assert not bad, (
        f"Found ETF tickers tagged as 'equity' in the universe: {bad}. "
        "ETFs are not stock picks -- either tag them with a different "
        "asset_type or move them to a clearly-labeled macro bucket."
    )


def test_documented_gaps_block_lists_russia_saudi_uae(yaml_raw):
    gaps = yaml_raw.get("documented_gaps") or []
    gap_countries = {g.get("country") for g in gaps}
    assert EXPECTED_GAPS.issubset(gap_countries), (
        f"documented_gaps must explicitly include {EXPECTED_GAPS}. "
        f"Currently: {gap_countries}. Russia is sanctioned; Saudi Arabia "
        "and UAE have foreign-retail access restrictions. They must be "
        "tracked here, not silently missing."
    )
    for g in gaps:
        if g.get("country") in EXPECTED_GAPS:
            assert g.get("reason"), f"gap {g['country']} missing a reason"
            assert g.get("direct_listings") is False
            assert g.get("adr") is False


def test_russia_has_no_single_stock_entry(universe):
    """The single hard exclusion: Russia is sanctioned. Verify no Russian
    equity sneaks into the universe under any sector bucket."""
    ru = [r for r in universe["tickers"] if str(r.get("country", "")).strip() == "Russia"]
    assert not ru, (
        f"Russia is sanctioned (top-30 exclusion). Found {len(ru)} Russian "
        f"row(s): {ru}. Remove or move to documented_gaps."
    )


def test_indonesia_and_turkey_seeded_as_direct_local_listings(universe):
    """The two markets we explicitly added in T6 to round out the top-30
    coverage. They must be direct local listings (not ADRs) so the audit's
    'no ETF padding' rule is also satisfied for these two."""
    idn = [r for r in universe["tickers"] if r.get("country") == "Indonesia"]
    tur = [r for r in universe["tickers"] if r.get("country") == "Turkey"]
    assert idn, "Indonesia must have at least one single-name listing"
    assert tur, "Turkey must have at least one single-name listing"
    # Pin that these are actual local listings (yfinance .JK / .IS suffix),
    # not US-listed ADRs.
    assert any(".JK" in r.get("ticker", "") for r in idn)
    assert any(".IS" in r.get("ticker", "") for r in tur)
