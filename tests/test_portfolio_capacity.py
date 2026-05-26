"""Tests — portfolio capacity + regime (Test groups C + D)."""
from __future__ import annotations

from scripts.exit_review_board import build_exit_review_board
from scripts.portfolio_capacity import (
    REGIME_BUY_ALLOWED,
    REGIME_BUY_BLOCKED,
    REGIME_BUY_LIMITED,
    classify_portfolio_regime,
    compute_portfolio_capacity,
    compute_risk_budget,
)


def _clean_pos(**overrides) -> dict:
    base = {
        "ticker": "NVDA",
        "buy_price": 100.0,
        "live_price": 110.0,
        "stop_loss": 95.0,
        "tp_price": 130.0,
        "leverage": 1.0,
        "age_days": 5,
        "expected_horizon_days": 20,
        "source_health": "LIVE_VERIFIED",
    }
    base.update(overrides)
    return base


def _build_capacity(
    positions: list[dict],
    *,
    source_health: str = "LIVE_VERIFIED",
    cash_available: float | None = 1000.0,
    target_cash_buffer: float | None = 1000.0,
    live_prices: dict[str, float] | None = None,
    india_4x_unreviewed: int = 0,
) -> tuple[dict, dict]:
    board = build_exit_review_board(positions, live_price_lookup=live_prices)
    capacity = compute_portfolio_capacity(
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health=source_health,
        cash_available=cash_available,
        target_cash_buffer=target_cash_buffer,
        india_4x_unreviewed_count=india_4x_unreviewed,
    )
    return board, capacity


# ---------------------------------------------------------------------------
# Group C — capacity score
# ---------------------------------------------------------------------------


def test_C1_clean_portfolio_with_live_sources_scores_high() -> None:
    positions = [_clean_pos(ticker="NVDA"), _clean_pos(ticker="MSFT")]
    _, capacity = _build_capacity(positions)
    assert capacity["portfolio_capacity_score"] >= 8.0


def test_C3_stop_breach_drops_score_below_5_or_blocks() -> None:
    positions = [_clean_pos(live_price=80.0)]  # stop=95, breached
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    assert (
        capacity["portfolio_capacity_score"] < 5.0
        or regime["portfolio_regime"] == REGIME_BUY_BLOCKED
    )
    assert regime["portfolio_regime"] == REGIME_BUY_BLOCKED


def test_C4_phantom_open_row_drives_BUY_BLOCKED() -> None:
    positions = [_clean_pos(trade_state="CLOSED")]
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    assert regime["portfolio_regime"] == REGIME_BUY_BLOCKED


def test_C5_dirty_data_reduces_score() -> None:
    # No live price → DATA_BLOCKED → critical-missing penalty.
    positions = [_clean_pos(live_price=None)]
    _, capacity = _build_capacity(positions)
    assert capacity["raw_components"]["P_dirty"] >= 1.0
    assert capacity["portfolio_capacity_score"] < 6.0


def test_C6_duplicate_exposure_penalty_reduces_score() -> None:
    positions = [
        _clean_pos(ticker="EPA:AIR"),
        _clean_pos(ticker="ETR:AIR"),
        _clean_pos(ticker="NVDA"),
    ]
    _, capacity = _build_capacity(positions)
    assert capacity["raw_components"]["P_dup"] > 0


def test_C7_india_4x_unreviewed_drives_BUY_BLOCKED() -> None:
    positions = [
        _clean_pos(
            ticker="NSE:HDFCBANK",
            leverage=4,
            country="India",
        )
    ]
    board, capacity = _build_capacity(
        positions, india_4x_unreviewed=1
    )
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
        india_4x_unreviewed_count=1,
    )
    assert regime["portfolio_regime"] == REGIME_BUY_BLOCKED


# ---------------------------------------------------------------------------
# Group D — regime classifier
# ---------------------------------------------------------------------------


def test_D1_clean_portfolio_is_BUY_ALLOWED() -> None:
    positions = [_clean_pos(ticker="NVDA"), _clean_pos(ticker="MSFT")]
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    assert regime["portfolio_regime"] == REGIME_BUY_ALLOWED
    assert regime["max_size_per_entry"] > 0


def test_D2_partial_TP_due_drives_BUY_LIMITED() -> None:
    # At TP, partial not logged → PARTIAL_TP_NOW.
    positions = [_clean_pos(live_price=135.0)]
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    assert regime["portfolio_regime"] == REGIME_BUY_LIMITED
    assert regime["allowed_new_entries"] == 3
    assert regime["max_size_per_entry"] <= 50.0


def test_D5_critical_live_price_missing_drives_BUY_BLOCKED() -> None:
    positions = [_clean_pos(live_price=None)]
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    assert regime["portfolio_regime"] == REGIME_BUY_BLOCKED


def test_D6_BUY_LIMITED_caps_match_spec() -> None:
    # Force LIMITED by creating a partial-TP-due row (one of the spec triggers).
    positions = [_clean_pos(live_price=135.0)]
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    assert regime["portfolio_regime"] == REGIME_BUY_LIMITED
    assert regime["allowed_new_entries"] == 3
    assert regime["max_size_per_entry"] == 50.0


def test_BUY_ALLOWED_outputs_carry_safety_stamps() -> None:
    positions = [_clean_pos()]
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    assert regime["advisory_only"] is True
    assert regime["broker_api_called"] is False
    assert regime["ai_execution_count"] == 0
    assert regime["execution_permission"] == "LOCKED"


# ---------------------------------------------------------------------------
# Risk budget dashboard
# ---------------------------------------------------------------------------


def test_risk_budget_with_known_cash_subtracts_buffers() -> None:
    positions = [_clean_pos()]
    board, capacity = _build_capacity(positions)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    budget = compute_risk_budget(
        exit_board=board,
        regime=regime,
        cash_available=2000.0,
    )
    assert budget["available_new_risk_budget"] >= 0
    assert budget["cash_budget_unknown"] is False
    assert budget["max_size_per_entry"] == regime["max_size_per_entry"]


def test_risk_budget_unknown_cash_returns_regime_cap_only() -> None:
    positions = [_clean_pos()]
    board, capacity = _build_capacity(positions, cash_available=None, target_cash_buffer=None)
    regime = classify_portfolio_regime(
        capacity,
        exit_board=board,
        theme_summary=board["theme_slot_summary"],
        source_health="LIVE_VERIFIED",
    )
    budget = compute_risk_budget(
        exit_board=board, regime=regime, cash_available=None
    )
    assert budget["cash_budget_unknown"] is True
    assert budget["available_new_risk_budget"] == regime["max_total_new_capital"]
