"""Candidate proof: news/filing without price/volume is WATCHLIST, never BUY.

A candidate may enter discovery on a fresh news/filing alone, but PROBE_BUY/BUY
require price + volume + source proof. This protects against promoting an
unconfirmed name to an advisory buy.
"""
from __future__ import annotations

import pytest

from scripts.discovery_execution_mode import (
    classify_candidate,
    compute_buy_score,
    why_today_tier,
)

_NON_BUY = {
    "NOISE_OR_STALE",
    "WEAK_DISCOVERY",
    "DISCOVERED",
    "WATCHLIST",
    "STRONG_WATCHLIST",
    "CONDITIONAL_PROBE_CANDIDATE_EXECUTION_BLOCKED",
    "HIGH_CONVICTION_WATCHLIST_EXECUTION_BLOCKED",
}


@pytest.mark.parametrize(
    "ticker,why_today",
    [
        ("HSBA.L", 0.72),
        ("8306.T", 0.65),
        ("291A.T", 0.62),
    ],
)
def test_news_filing_without_price_is_not_buy(ticker, why_today):
    # Fresh news/filing + good source, but NO price/volume confirmation.
    components = {
        "why_today_score": why_today,
        "price_confirmation": 0.0,
        "source_quality": 0.8,
        "cross_model_agreement": 0.6,
        "portfolio_fit": 0.5,
    }
    buy_score = compute_buy_score(components)
    # Even with execution permitted, missing price/volume proof forbids a buy.
    verdict = classify_candidate(
        buy_score,
        execution_allowed=True,
        proof={
            "price_confirmation": 0.0,
            "volume_confirmation": 0.0,
            "source_quality": 0.8,
            "portfolio_fit": 0.5,
        },
    )
    assert verdict["classification"] in _NON_BUY
    assert verdict["classification"] not in ("BUY", "PROBE_BUY")


def test_high_score_but_missing_proof_downgrades_to_watchlist():
    # Score reaches the PROBE band purely from non-price components, but the
    # proof floor (price_confirmation >= 0.60) is not met -> not a buy.
    components = {
        "why_today_score": 1.0,
        "price_confirmation": 0.0,
        "source_quality": 1.0,
        "cross_model_agreement": 1.0,
        "portfolio_fit": 1.0,
    }
    buy_score = compute_buy_score(components)
    assert buy_score >= 0.73  # would be PROBE band on score alone
    verdict = classify_candidate(
        buy_score,
        execution_allowed=True,
        proof={
            "price_confirmation": 0.0,
            "volume_confirmation": 0.0,
            "source_quality": 1.0,
            "portfolio_fit": 1.0,
        },
    )
    assert verdict["classification"] == "WATCHLIST"
    assert verdict["execution_blocked_reason"] == "PRICE_VOLUME_CONFIRMATION_MISSING"


def test_full_proof_and_execution_allowed_can_be_buy():
    components = {
        "why_today_score": 0.9,
        "price_confirmation": 0.9,
        "source_quality": 0.9,
        "cross_model_agreement": 0.8,
        "portfolio_fit": 0.8,
    }
    buy_score = compute_buy_score(components)
    assert buy_score >= 0.80
    verdict = classify_candidate(
        buy_score,
        execution_allowed=True,
        proof={
            "price_confirmation": 0.9,
            "volume_confirmation": 0.9,
            "source_quality": 0.9,
            "portfolio_fit": 0.8,
        },
    )
    assert verdict["classification"] == "BUY"


def test_why_today_tier_axis_independent_of_buy_score():
    # The HSBA.L-style name is STRONG_WATCHLIST on the why-today axis even though
    # its BUY_SCORE classification stays sub-buy (missing price proof).
    assert why_today_tier(0.72) == "STRONG_WATCHLIST"
