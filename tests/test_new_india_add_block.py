"""Tests — hard India new-add block (P2 of the Kanté defensive hardening sprint).

Proves that ``new_india_add_allowed`` is a HARD binary gate over NEW India
candidates only, and that it never claims power over existing-position review.
Advisory only; no execution, no broker.
"""
from __future__ import annotations

import pytest

from scripts.capital_rotation_guard import NEW_INDIA_ADD_BLOCKED, new_india_add_allowed
from scripts.leverage_policy import INDIA_MAX_LEVERAGE


def test_clean_india_add_is_allowed():
    verdict = new_india_add_allowed(
        ticker="RELIANCE.NS",
        country="India",
        existing_india_risk_unresolved=False,
        existing_india_leverage=1.0,
        live_price_visibility_ok=True,
        live_risk_visibility_ok=True,
    )
    assert verdict["is_india_instrument"] is True
    assert verdict["new_india_add_allowed"] is True
    assert verdict["blocking_reasons"] == []


def test_unresolved_india_risk_hard_blocks_new_add():
    verdict = new_india_add_allowed(
        ticker="RELIANCE.NS",
        country="India",
        existing_india_risk_unresolved=True,
    )
    assert verdict["new_india_add_allowed"] is False
    assert verdict["advisory_class"] == NEW_INDIA_ADD_BLOCKED
    assert verdict["blocking_reasons"]


def test_4x_exposure_with_degraded_visibility_hard_blocks_new_add():
    verdict = new_india_add_allowed(
        ticker="NSE:RELIANCE",
        country="India",
        existing_india_leverage=INDIA_MAX_LEVERAGE,  # 4x ceiling
        existing_india_position_count=4,
        live_price_visibility_ok=False,
        live_risk_visibility_ok=True,
    )
    assert verdict["new_india_add_allowed"] is False
    assert any("ceiling" in r for r in verdict["blocking_reasons"])


def test_4x_exposure_with_full_visibility_is_not_blocked_by_this_rule():
    # 4x exposure alone (visibility intact, risk resolved) is not a hard block here.
    verdict = new_india_add_allowed(
        ticker="RELIANCE.NS",
        country="India",
        existing_india_leverage=INDIA_MAX_LEVERAGE,
        live_price_visibility_ok=True,
        live_risk_visibility_ok=True,
    )
    assert verdict["new_india_add_allowed"] is True


def test_non_india_instrument_is_out_of_scope_and_allowed():
    # The gate must NEVER block a non-India name, even with unresolved-risk flags set.
    verdict = new_india_add_allowed(
        ticker="AAPL",
        country="United States",
        existing_india_risk_unresolved=True,
        existing_india_leverage=INDIA_MAX_LEVERAGE,
        live_price_visibility_ok=False,
    )
    assert verdict["is_india_instrument"] is False
    assert verdict["new_india_add_allowed"] is True


def test_gate_scope_and_safety_invariants():
    verdict = new_india_add_allowed(ticker="RELIANCE.NS", existing_india_risk_unresolved=True)
    # Scope contract: NEW adds only; existing review is explicitly unaffected.
    assert verdict["applies_to"] == "NEW_INDIA_CANDIDATE_ONLY"
    assert verdict["existing_position_review_unaffected"] is True
    # Advisory-only invariants present whether allowed or blocked.
    assert verdict["execution_gate"] == "LOCKED"
    assert verdict["broker_api_called"] is False
    assert verdict["ai_execution_count"] == 0
    assert verdict["executes_trade"] is False
    assert verdict["human_execution_required"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
