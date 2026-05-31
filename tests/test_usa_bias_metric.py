"""Tests — USA bias + fallback contamination metrics."""
from __future__ import annotations

import pytest

from scripts.discovery_bias_metrics import (
    B_US_CAP,
    compute_contamination_ratios,
    compute_usa_bias,
    render_bias_markdown,
)


def _us(ticker):
    return {"ticker": ticker, "country": "United States", "exchange": "NASDAQ"}


def _foreign(ticker, country):
    return {"ticker": ticker, "country": country, "exchange": ""}


def test_b_us_ratio():
    cands = [_us("AAPL"), _us("MSFT"), _foreign("RHM.DE", "Germany"), _foreign("RELIANCE.NS", "India")]
    bias = compute_usa_bias(cands)
    assert bias["N_US"] == 2
    assert bias["N_total"] == 4
    assert bias["B_US"] == 0.5


def test_usa_bias_violation_and_warning():
    cands = [_us("AAPL"), _us("MSFT"), _us("NVDA"), _foreign("RHM.DE", "Germany")]
    bias = compute_usa_bias(cands)
    assert bias["B_US"] == 0.75
    assert bias["USA_bias_violation"] == round(0.75 - B_US_CAP, 4)
    assert "USA_BIAS_ELEVATED" in bias["status"]
    assert "US_LISTING_VENUE_BIAS_ELEVATED" in bias["status"]


def test_venue_bias_counts_adrs_and_etfs_on_us_exchanges():
    cands = [
        {"ticker": "SHEL", "country": "United Kingdom", "exchange": "NYSE"},
        {"ticker": "RELIANCE.NS", "country": "India", "exchange": ""},
    ]
    bias = compute_usa_bias(cands)
    # SHEL is UK by country but US-listed by venue.
    assert bias["B_US"] == 0.0
    assert bias["B_US_venue"] == 0.5


def test_no_candidates_is_safe():
    bias = compute_usa_bias([])
    assert bias["B_US"] == 0.0
    assert bias["USA_bias_violation"] == 0.0


def test_contamination_ratios():
    cands = [
        {"ticker": "RHM.DE", "source_class": "LIVE", "in_l_today": True},
        {"ticker": "AAPL", "source_class": "STATIC_FALLBACK"},
        {"ticker": "MSFT", "source_class": "STATIC_FALLBACK"},
        {"ticker": "GLD", "source_class": "PHANTOM", "phantom": True},
        {"ticker": "TSLA", "source_class": "MEMORY_OR_STALE"},
    ]
    c = compute_contamination_ratios(cands)
    assert c["R_static"] == 0.4
    assert c["R_memory"] == 0.2
    assert c["R_phantom"] == 0.2
    assert c["R_live"] == 0.2
    assert "PHANTOM_CONTAMINATION_PRESENT" in c["warnings"]


def test_no_live_candidates_warning():
    cands = [{"ticker": "AAPL", "source_class": "STATIC_FALLBACK"}] * 3
    c = compute_contamination_ratios(cands)
    assert c["R_live"] == 0.0
    assert "NO_LIVE_DISCOVERED_CANDIDATES" in c["warnings"]
    assert "STATIC_CONTAMINATION_HIGH" in c["warnings"]


def test_b_us_formula_matches_spec():
    # B_US = N_US / max(1, N_total); USA_bias_violation = max(0, B_US - 0.35).
    cands = [_us("AAPL"), _us("MSFT"), _us("NVDA"), _foreign("RHM.DE", "Germany"), _foreign("7203.T", "Japan")]
    bias = compute_usa_bias(cands)
    assert bias["N_US"] == 3
    assert bias["N_total"] == 5
    assert bias["B_US"] == round(3 / max(1, 5), 4)
    assert bias["USA_bias_violation"] == round(max(0.0, bias["B_US"] - B_US_CAP), 4)


def test_b_us_uses_max_1_denominator_when_empty():
    bias = compute_usa_bias([])
    assert bias["N_total"] == 0
    # Denominator is max(1, N_total) -> never a ZeroDivisionError; B_US == 0.
    assert bias["B_US"] == 0.0
    assert bias["USA_bias_violation"] == 0.0


def test_us_heavy_static_fallback_cannot_masquerade_as_global_discovery():
    cands = [
        {"ticker": t, "country": "United States", "exchange": "NASDAQ",
         "source_class": "STATIC_FALLBACK"}
        for t in ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL")
    ]
    bias = compute_usa_bias(cands)
    contamination = compute_contamination_ratios(cands)
    # 100% US -> bias violation is flagged, not silently treated as global.
    assert bias["B_US"] == 1.0
    assert bias["USA_bias_violation"] == round(1.0 - B_US_CAP, 4)
    assert "USA_BIAS_ELEVATED" in bias["status"]
    # 100% static + 0% live-discovered -> cannot be claimed as global discovery.
    assert contamination["R_static"] == 1.0
    assert contamination["R_live"] == 0.0
    assert "STATIC_CONTAMINATION_HIGH" in contamination["warnings"]
    assert "NO_LIVE_DISCOVERED_CANDIDATES" in contamination["warnings"]


def test_render_markdown_contains_metrics():
    bias = compute_usa_bias([_us("AAPL")])
    c = compute_contamination_ratios([{"ticker": "AAPL", "source_class": "STATIC_FALLBACK"}])
    md = render_bias_markdown(bias, c)
    assert "B_US=" in md
    assert "R_static=" in md


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
