"""Tests — theme slot accounting (Test group E, slot half)."""
from __future__ import annotations

from scripts.economic_exposure import (
    THEME_AI_SEMIS_CLOUD,
    THEME_DEFENSE,
)
from scripts.theme_slot_accounting import (
    ACTION_ADD_OK,
    ACTION_NO_NEW_HERE,
    ACTION_REPLACE_REQUIRED,
    STATUS_NEAR_CAP,
    STATUS_OVER_CAP,
    STATUS_UNDERUSED,
    compute_theme_slots,
    position_is_weakest_in_overcrowded_theme,
    position_slot_weight,
    theme_slot_summary,
)


def _pos(ticker: str, **overrides) -> dict:
    base = {"ticker": ticker, "leverage": 1.0}
    base.update(overrides)
    return base


def test_runner_slot_weight_is_ride_fraction() -> None:
    pos = _pos("NVDA", partial_tp_logged=True, booked_pct=70, ride_pct=30)
    assert position_slot_weight(pos) == 0.30


def test_full_position_slot_weight_is_one() -> None:
    assert position_slot_weight(_pos("NVDA")) == 1.0


def test_small_position_scales_by_money_allocated() -> None:
    pos = _pos("NVDA", money_allocated=25.0)
    assert position_slot_weight(pos, standard_position_size=100.0) == 0.25


def test_E9_near_cap_triggers_REPLACE_REQUIRED() -> None:
    # Fill AI_SEMIS_CLOUD to 6 holdings (warning_cap=6, hard_cap=8).
    positions = [
        _pos("NVDA"),
        _pos("AMD"),
        _pos("AVGO"),
        _pos("TSM"),
        _pos("ASML"),
        _pos("ANET"),
    ]
    rows = compute_theme_slots(positions)
    ai = next(r for r in rows if r["theme"] == THEME_AI_SEMIS_CLOUD)
    assert ai["status"] == STATUS_NEAR_CAP
    assert ai["allowed_action"] == ACTION_REPLACE_REQUIRED


def test_E10_over_cap_triggers_NO_NEW_HERE() -> None:
    # 9 AI positions → over hard_cap=8.
    positions = [
        _pos("NVDA"), _pos("AMD"), _pos("AVGO"), _pos("TSM"),
        _pos("ASML"), _pos("ANET"), _pos("MU"), _pos("INTC"),
        _pos("ORCL"),
    ]
    rows = compute_theme_slots(positions)
    ai = next(r for r in rows if r["theme"] == THEME_AI_SEMIS_CLOUD)
    assert ai["status"] == STATUS_OVER_CAP
    assert ai["allowed_action"] == ACTION_NO_NEW_HERE


def test_underused_theme_returns_ADD_OK() -> None:
    rows = compute_theme_slots([_pos("ZZZ_UNKNOWN")])
    defense = next(r for r in rows if r["theme"] == THEME_DEFENSE)
    assert defense["used_weight"] == 0.0
    assert defense["status"] == STATUS_UNDERUSED
    assert defense["allowed_action"] == ACTION_ADD_OK


def test_weakest_holding_candidates_picks_lowest_strength() -> None:
    # Two AI positions; one has explicit weaker thesis_score.
    positions = [
        _pos("NVDA", thesis_score=0.85),
        _pos("AMD", thesis_score=0.40),
    ]
    rows = compute_theme_slots(positions)
    ai = next(r for r in rows if r["theme"] == THEME_AI_SEMIS_CLOUD)
    # AMD should appear first in weakest list.
    assert ai["weakest_holding_candidates"][0] == "AMD"


def test_theme_slot_summary_top_level_aggregates() -> None:
    positions = [
        _pos("NVDA"), _pos("AMD"), _pos("AVGO"), _pos("TSM"),
        _pos("ASML"), _pos("ANET"), _pos("MU"), _pos("INTC"),
        _pos("ORCL"),  # over cap
    ]
    summary = theme_slot_summary(positions)
    assert summary["any_hard_cap_exceeded"] is True
    assert THEME_AI_SEMIS_CLOUD in summary["over_cap_themes"]
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_position_is_weakest_in_overcrowded_theme_detects_member() -> None:
    rows = [
        {
            "theme": THEME_AI_SEMIS_CLOUD,
            "status": STATUS_OVER_CAP,
            "weakest_holding_candidates": ["AMD"],
        }
    ]
    assert position_is_weakest_in_overcrowded_theme("AMD", rows) is True
    assert position_is_weakest_in_overcrowded_theme("NVDA", rows) is False


def test_position_is_weakest_normalises_listings() -> None:
    rows = [
        {
            "theme": THEME_DEFENSE,
            "status": STATUS_NEAR_CAP,
            "weakest_holding_candidates": ["EPA:AIR"],
        }
    ]
    # ETR:AIR is the same economic exposure as EPA:AIR → AIRBUS.
    assert position_is_weakest_in_overcrowded_theme("ETR:AIR", rows) is True
