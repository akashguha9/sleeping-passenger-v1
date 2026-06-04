"""Section 1 — Portfolio Truth Gate: H = V \\ (C ∪ S ∪ D)."""
from __future__ import annotations

from scripts.governance.daily_gate import compute_portfolio_truth, i_current

V = ["ANET", "ASML", "CVX", "HDFCBANK.NS", "LMT", "MSFT", "RELIANCE.NS", "RTX", "TSM", "XOM"]


def _truth():
    return compute_portfolio_truth(
        verified_current_holdings=[{"ticker": t, "status": "OPEN"} for t in V],
        closed_positions=["GLD"],
        sold_positions=["GLD"],
        not_owned_do_not_manage=["UNG", "TIP", "TLT", "FCG", "GLD"],
    )


def test_H_equals_full_verified_set():
    truth, H, D = _truth()
    assert sorted(H) == sorted(V)
    assert truth.current_holdings_H == sorted(V)


def test_indicator_form():
    truth, H, D = _truth()
    for t in V:
        assert i_current(t, H) == 1
        assert truth.indicator[t] == 1
    for t in ["UNG", "TIP", "TLT", "FCG", "GLD"]:
        assert i_current(t, H) == 0


def test_bad_sets_quarantined():
    truth, H, D = _truth()
    for t in ["UNG", "TIP", "TLT", "FCG", "GLD"]:
        assert t in truth.quarantined
        assert t not in H


def test_zim_not_in_H():
    truth, H, D = _truth()
    assert i_current("ZIM", H) == 0


def test_closed_status_holding_excluded_from_V():
    truth, H, D = compute_portfolio_truth(
        verified_current_holdings=[
            {"ticker": "AAA", "status": "OPEN"},
            {"ticker": "BBB", "status": "CLOSED"},
        ],
        closed_positions=[],
        sold_positions=[],
        not_owned_do_not_manage=[],
    )
    assert "AAA" in H
    assert "BBB" not in H
