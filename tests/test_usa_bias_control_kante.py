"""Tests — USA bias control hardening (P1 of the Kanté defensive sprint).

Proves the bias math is explicit, tested, and used to DOWNGRADE false
global-discovery claims — never to fabricate non-US candidates or block a name
merely for being US. Advisory only; no execution, no broker, no network.
"""
from __future__ import annotations

import pytest

from scripts.discovery_bias_metrics import (
    B_US_CAP,
    compute_usa_bias,
    global_breadth_claim_allowed,
    render_bias_markdown,
    compute_contamination_ratios,
)


def _us(ticker):
    return {"ticker": ticker, "country": "United States", "exchange": "NASDAQ"}


def _foreign(ticker, country, exchange=""):
    return {"ticker": ticker, "country": country, "exchange": exchange}


# --- Acceptance 1: 8 US / 10 total -> B_US=0.8, violation=0.45, warning -------
def test_eight_us_of_ten_flags_bias_violation_and_warning():
    cands = [_us(f"US{i}") for i in range(8)] + [
        _foreign("RHM.DE", "Germany"),
        _foreign("RELIANCE.NS", "India"),
    ]
    bias = compute_usa_bias(cands)
    assert bias["N_total"] == 10
    assert bias["N_US"] == 8
    assert bias["B_US"] == 0.8
    assert bias["USA_bias_violation"] == round(0.8 - 0.35, 4) == 0.45
    assert "USA_BIAS_ELEVATED" in bias["status"]


# --- Acceptance 2: US-listed ADRs -> venue bias warning ----------------------
def test_us_listed_adrs_trip_venue_bias_warning():
    # Foreign-domiciled names, but all listed on US venues.
    cands = [
        _foreign("SHEL", "United Kingdom", "NYSE"),
        _foreign("BABA", "China", "NYSE"),
        _foreign("TSM", "Taiwan", "NYSE"),
        _foreign("RELIANCE.NS", "India", "NSE"),
    ]
    bias = compute_usa_bias(cands)
    assert bias["B_US_venue"] > 0.60
    assert "US_LISTING_VENUE_BIAS_ELEVATED" in bias["status"]
    # None are US by *country*, so country bias stays low — the two axes differ.
    assert bias["B_US"] == 0.0


# --- Acceptance 3: spread across 5 countries -> lower HHI, higher eff count ---
def test_five_country_spread_lowers_concentration():
    spread = [
        _foreign("RHM.DE", "Germany"),
        _foreign("SHEL", "United Kingdom"),
        _foreign("7203.T", "Japan"),
        _foreign("RELIANCE.NS", "India"),
        _us("AAPL"),
    ]
    concentrated = [_us(f"US{i}") for i in range(5)]
    spread_bias = compute_usa_bias(spread)
    conc_bias = compute_usa_bias(concentrated)
    assert spread_bias["country_concentration_hhi"] < conc_bias["country_concentration_hhi"]
    assert spread_bias["effective_country_count"] > conc_bias["effective_country_count"]
    # Even spread over 5 -> effective_country_count == 5; single country -> 1.
    assert spread_bias["effective_country_count"] == 5.0
    assert conc_bias["effective_country_count"] == 1.0
    # The concentrated set (>=5 names, eff < 2) must flag concentration.
    assert "COUNTRY_CONCENTRATION_HIGH" in conc_bias["status"]
    assert "COUNTRY_CONCENTRATION_HIGH" not in spread_bias["status"]


# --- Acceptance 4: C_global=0 + low B_US -> breadth NOT allowed --------------
def test_c_global_zero_disallows_breadth_even_with_low_us_bias():
    bias = compute_usa_bias(
        [_foreign("RHM.DE", "Germany"), _foreign("7203.T", "Japan"), _foreign("SHEL", "United Kingdom")]
    )
    assert bias["B_US"] == 0.0  # low US bias
    breadth = global_breadth_claim_allowed(bias, c_global=0.0, covered_country_count=0)
    assert breadth["global_breadth_claim_allowed"] is False
    assert breadth["claim_statement"] == "Global discovery breadth is not yet proven."
    assert any("C_global=0" in r for r in breadth["blocking_reasons"])


# --- Acceptance 5: C_global>0 but high B_US -> breadth degraded/disallowed ----
def test_high_us_concentration_disallows_breadth_even_with_coverage():
    bias = compute_usa_bias([_us(f"US{i}") for i in range(9)] + [_foreign("RHM.DE", "Germany")])
    assert bias["B_US"] > B_US_CAP
    breadth = global_breadth_claim_allowed(bias, c_global=1 / 30, covered_country_count=1)
    assert breadth["global_breadth_claim_allowed"] is False
    assert any("B_US" in r for r in breadth["blocking_reasons"])


# --- Acceptance 6: one non-US covered, balanced -> at-least-one-country claim -
def test_one_non_us_country_covered_allows_modest_claim():
    bias = compute_usa_bias(
        [_foreign("RHM.DE", "Germany"), _foreign("7203.T", "Japan"), _us("AAPL")]
    )
    assert bias["B_US"] <= B_US_CAP
    assert bias["effective_country_count"] >= 2
    breadth = global_breadth_claim_allowed(bias, c_global=1 / 30, covered_country_count=1)
    assert breadth["global_breadth_claim_allowed"] is True
    # The claim is modest — at least one country, NOT "full global discovery".
    assert "at least one" in breadth["claim_statement"].lower() or "proven" in breadth["claim_statement"].lower()
    assert "full global" not in breadth["claim_statement"].lower()


# --- Acceptance 7: static US fallback cannot masquerade as global discovery ---
def test_static_us_fallback_cannot_masquerade_as_global():
    cands = [
        {"ticker": t, "country": "United States", "exchange": "NASDAQ", "source_class": "STATIC_FALLBACK"}
        for t in ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL")
    ]
    bias = compute_usa_bias(cands)
    contamination = compute_contamination_ratios(cands)
    # 100% US static -> bias + concentration flagged, breadth disallowed.
    assert bias["B_US"] == 1.0
    assert "USA_BIAS_ELEVATED" in bias["status"]
    assert "COUNTRY_CONCENTRATION_HIGH" in bias["status"]
    assert contamination["R_live"] == 0.0
    breadth = global_breadth_claim_allowed(bias, c_global=0.0, covered_country_count=0)
    assert breadth["global_breadth_claim_allowed"] is False


# --- Acceptance 8: metrics appear in the rendered bias block -----------------
def test_render_surfaces_all_bias_metrics_and_breadth():
    bias = compute_usa_bias([_us("AAPL"), _us("MSFT"), _foreign("RHM.DE", "Germany")])
    contamination = compute_contamination_ratios(
        [{"ticker": "AAPL", "source_class": "STATIC_FALLBACK"}]
    )
    breadth = global_breadth_claim_allowed(bias, c_global=0.0, covered_country_count=0)
    md = render_bias_markdown(bias, contamination, breadth)
    for token in (
        "B_US=",
        "B_US_venue=",
        "USA_bias_violation",  # appears via 'violation=' label
        "HHI=",
        "effective_country_count=",
        "global_breadth_claim_allowed:",
    ):
        # 'USA_bias_violation' is rendered as 'violation=' — accept either.
        assert token in md or token.replace("USA_bias_violation", "violation=") in md
    assert "Global discovery breadth is not yet proven." in md


# --- Truthfulness guard: bias measurement never fabricates / never blocks US -
def test_us_name_is_never_blocked_merely_for_being_us():
    # compute_usa_bias is pure measurement: it returns ratios/flags, no candidate
    # is removed or marked non-executable here.
    cands = [_us("AAPL")]
    bias = compute_usa_bias(cands)
    assert bias["N_total"] == 1  # the US name is still present/counted
    assert "blocked" not in bias  # no blocking key — measurement only


def test_empty_output_is_safe_and_makes_no_breadth_claim():
    bias = compute_usa_bias([])
    assert bias["B_US"] == 0.0
    assert bias["effective_country_count"] == 0.0
    breadth = global_breadth_claim_allowed(bias, c_global=0.0, covered_country_count=0)
    assert breadth["global_breadth_claim_allowed"] is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
