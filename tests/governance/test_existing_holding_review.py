"""Section 9 — Existing holding review."""
from __future__ import annotations


def _reviews(gov_result):
    return {r.ticker: r for r in gov_result.existing_holding_review_board}


def test_all_H_reviewed(gov_result):
    reviews = _reviews(gov_result)
    H = {"ANET", "ASML", "CVX", "HDFCBANK.NS", "LMT", "MSFT", "RELIANCE.NS", "RTX", "TSM", "XOM"}
    assert set(reviews) == H


def test_4x_india_urgent_reduce_exit(gov_result):
    reviews = _reviews(gov_result)
    for t in ("HDFCBANK.NS", "RELIANCE.NS"):
        r = reviews[t]
        assert r.classification == "REDUCE_EXIT_REVIEW"
        assert r.severity == "URGENT"
        assert r.reason == "4x leverage + missing current price"
        assert r.leverage_risk == 0.75


def test_cvx_thesis_conflict(gov_result):
    r = _reviews(gov_result)["CVX"]
    assert r.classification in ("REDUCE_EXIT_REVIEW", "THESIS_CONFLICT_REVIEW")
    assert "thesis conflict" in r.reason
    assert "missing current price" in r.reason
    assert r.severity in ("HIGH", "MEDIUM-HIGH")


def test_other_holdings_price_missing(gov_result):
    reviews = _reviews(gov_result)
    for t in ("ANET", "ASML", "LMT", "MSFT", "RTX", "TSM", "XOM"):
        r = reviews[t]
        assert r.classification == "EXISTING_HOLDING_REVIEW"
        assert "current price missing" in r.reason


def test_reduce_exit_board_contents(gov_result):
    tickers = {r.ticker for r in gov_result.reduce_exit_review_board}
    assert {"HDFCBANK.NS", "RELIANCE.NS", "CVX"} <= tickers


def test_reviews_authorize_no_action(gov_result):
    for r in gov_result.existing_holding_review_board:
        assert r.human_review_required is True
        assert r.authorizes_action is False
