"""Objective 8 — capital-rotation / capacity guard tests."""
from __future__ import annotations

from scripts.capital_rotation_guard import (
    BLOCKED_BY_PORTFOLIO_CAPACITY,
    MAX_POSITION_PCT,
    WAIT,
    compute_downside_risk_pct,
    evaluate_capacity,
)


def _args(**overrides):
    base = dict(
        ticker="MSFT",
        country="USA",
        capital=100_000.0,
        cash_available=100_000.0,
        entry_price=100.0,
        hard_stop_price=95.0,   # 5% downside
        leverage=1.0,
        leverage_valid=True,
        side="BUY",
        p_adj=0.75,
        freshness_score=1.0,
        moltbook_penalty=0.0,
        regime_ok=True,
        existing_country_exposure=0.0,
    )
    base.update(overrides)
    return base


def test_missing_stop_blocks_position_size():
    res = evaluate_capacity(**_args(hard_stop_price=None))
    assert res["position_size_allowed"] is False
    assert res["portfolio_capacity_ok"] is False
    assert res["downside_risk_pct"] is None
    assert res["advisory_class"] == WAIT


def test_position_size_uses_downside_risk():
    # Wider stop -> larger downside -> smaller notional for the same budget.
    tight = evaluate_capacity(**_args(hard_stop_price=99.0))   # 1% downside
    wide = evaluate_capacity(**_args(hard_stop_price=90.0))    # 10% downside
    assert tight["downside_risk_pct"] == compute_downside_risk_pct(100.0, 99.0)
    # Both may be capped by max-position, so compare the *raw* relationship via
    # risk_budget/downside; tight downside gives a larger raw notional.
    assert tight["risk_budget"] == wide["risk_budget"]
    raw_tight = tight["risk_budget"] / tight["downside_risk_pct"]
    raw_wide = wide["risk_budget"] / wide["downside_risk_pct"]
    assert raw_tight > raw_wide


def test_leverage_policy_required_for_capacity():
    res = evaluate_capacity(**_args(leverage_valid=False))
    assert res["portfolio_capacity_ok"] is False
    assert res["advisory_class"] == BLOCKED_BY_PORTFOLIO_CAPACITY


def test_cash_required_calculated_from_notional_and_leverage():
    no_lev = evaluate_capacity(**_args(leverage=1.0))
    lev2 = evaluate_capacity(**_args(leverage=2.0))
    # Same notional, double leverage -> half the cash required.
    assert lev2["position_notional"] == no_lev["position_notional"]
    assert lev2["cash_required"] == no_lev["cash_required"] / 2.0


def test_country_cap_blocks_excess_exposure():
    # Already near the 25% rest-of-world cap; a new position breaches it.
    res = evaluate_capacity(
        **_args(existing_country_exposure=24_500.0, capital=100_000.0)
    )
    assert res["country_cap_ok"] is False
    assert res["portfolio_capacity_ok"] is False
    assert res["advisory_class"] == BLOCKED_BY_PORTFOLIO_CAPACITY


def test_capacity_block_downgrades_to_wait():
    # Missing stop -> WAIT (cannot size at all).
    res = evaluate_capacity(**_args(hard_stop_price=None))
    assert res["advisory_class"] == WAIT


def test_capacity_guard_does_not_execute_trade():
    res = evaluate_capacity(**_args())
    assert res["executes_trade"] is False
    assert res["execution_gate"] == "LOCKED"
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0
    # Max single position respected.
    assert res["position_notional"] <= res["max_position_notional"] + 1e-6


def test_notional_capped_at_max_position_pct():
    # Tiny downside would imply a huge notional; it must be capped at 10%.
    res = evaluate_capacity(**_args(hard_stop_price=99.99, p_adj=1.0))
    assert res["position_notional"] <= 100_000.0 * MAX_POSITION_PCT + 1e-6
