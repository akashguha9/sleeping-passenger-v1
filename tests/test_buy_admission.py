"""Tests — buy admission classifier (Test group F)."""
from __future__ import annotations

from scripts.buy_admission import (
    ADM_ADD_SMALL_ONLY,
    ADM_ADDITIVE_OK,
    ADM_BLOCKED_BY_PORTFOLIO_REGIME,
    ADM_BLOCKED_BY_THEME_CAP,
    ADM_DIVERSIFY_OK,
    ADM_DUPLICATE_EXPOSURE,
    ADM_REPLACE_WEAKER_HOLDING,
    ADM_WATCH_ONLY,
    build_buy_admission_board,
    classify_buy_admission,
)
from scripts.economic_exposure import (
    THEME_AI_SEMIS_CLOUD,
    THEME_DEFENSE,
)
from scripts.portfolio_capacity import (
    REGIME_BUY_ALLOWED,
    REGIME_BUY_BLOCKED,
    REGIME_BUY_LIMITED,
)
from scripts.theme_slot_accounting import (
    STATUS_BALANCED,
    STATUS_NEAR_CAP,
    STATUS_OVER_CAP,
    STATUS_UNDERUSED,
)


# Theme rows are fed in directly so the tests stay deterministic and pure.

_ROOM_THEME_ROWS = [
    {
        "theme": THEME_AI_SEMIS_CLOUD,
        "used_weight": 0,
        "hard_cap": 8,
        "warning_cap": 6,
        "utilization": 0.0,
        "status": STATUS_UNDERUSED,
        "holdings": [],
        "weakest_holding_candidates": [],
        "allowed_action": "ADD_OK",
    }
]

_FULL_THEME_ROWS = [
    {
        "theme": THEME_AI_SEMIS_CLOUD,
        "used_weight": 8,
        "hard_cap": 8,
        "warning_cap": 6,
        "utilization": 1.0,
        "status": STATUS_OVER_CAP,
        "holdings": ["AMD", "NVDA"],
        "weakest_holding_candidates": ["AMD"],
        "allowed_action": "NO_NEW_HERE",
    }
]

_NEAR_CAP_THEME_ROWS = [
    {
        "theme": THEME_AI_SEMIS_CLOUD,
        "used_weight": 6.5,
        "hard_cap": 8,
        "warning_cap": 6,
        "utilization": 6.5 / 8,
        "status": STATUS_NEAR_CAP,
        "holdings": ["AMD", "NVDA"],
        "weakest_holding_candidates": ["AMD"],
        "allowed_action": "REPLACE_REQUIRED",
    }
]

_DIVERSIFY_THEME_ROWS = [
    {
        "theme": THEME_DEFENSE,
        "used_weight": 0,
        "hard_cap": 4,
        "warning_cap": 3,
        "utilization": 0.0,
        "status": STATUS_UNDERUSED,
        "holdings": [],
        "weakest_holding_candidates": [],
        "allowed_action": "ADD_OK",
    }
]

_EXIT_ROWS_AMD_WEAK = [
    {"ticker": "AMD", "thesis_score": 0.30},
    {"ticker": "NVDA", "thesis_score": 0.80},
]


def test_F1_BUY_ALLOWED_strong_candidate_classifies_ADDITIVE_OK() -> None:
    cand = {
        "ticker": "MU",
        "candidate_score": 0.90,
        "execution_readiness_score": 0.90,
        "why_today_score": 0.80,
    }
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_ROOM_THEME_ROWS,
        exit_rows=[],
        held_exposures=[],
    )
    assert row["buy_admission_class"] == ADM_ADDITIVE_OK


def test_F2_BUY_LIMITED_acceptable_candidate_classifies_ADD_SMALL_ONLY() -> None:
    cand = {
        "ticker": "MU",
        "candidate_score": 0.70,
        "execution_readiness_score": 0.70,
        "why_today_score": 0.60,
    }
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_LIMITED,
        regime_max_size_per_entry=50.0,
        theme_rows=_ROOM_THEME_ROWS,
        exit_rows=[],
        held_exposures=[],
    )
    assert row["buy_admission_class"] == ADM_ADD_SMALL_ONLY
    assert row["max_allowed_size"] <= 50.0


def test_F3_BUY_BLOCKED_returns_BLOCKED_BY_PORTFOLIO_REGIME() -> None:
    cand = {
        "ticker": "MU",
        "candidate_score": 0.95,
        "execution_readiness_score": 0.95,
        "why_today_score": 0.95,
    }
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_BLOCKED,
        regime_max_size_per_entry=0.0,
        theme_rows=_ROOM_THEME_ROWS,
        exit_rows=[],
        held_exposures=[],
    )
    assert row["buy_admission_class"] == ADM_BLOCKED_BY_PORTFOLIO_REGIME
    assert row["max_allowed_size"] == 0.0


def test_F4_duplicate_exposure_classifies_DUPLICATE_EXPOSURE() -> None:
    cand = {
        "ticker": "GOOG",
        "candidate_score": 0.85,
        "execution_readiness_score": 0.85,
        "why_today_score": 0.85,
    }
    # ALPHABET already held via NASDAQ:GOOGL.
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_ROOM_THEME_ROWS,
        exit_rows=[],
        held_exposures=["ALPHABET"],
    )
    assert row["buy_admission_class"] == ADM_DUPLICATE_EXPOSURE


def test_F5_better_candidate_in_full_theme_classifies_REPLACE_WEAKER_HOLDING() -> None:
    cand = {
        "ticker": "MU",
        "candidate_score": 0.85,
        "execution_readiness_score": 0.85,
        "why_today_score": 0.85,
    }
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_FULL_THEME_ROWS,
        exit_rows=_EXIT_ROWS_AMD_WEAK,
        held_exposures=["AMD", "NVIDIA"],
    )
    assert row["buy_admission_class"] == ADM_REPLACE_WEAKER_HOLDING
    assert row["replace_target_ticker"] == "AMD"
    assert row["add_or_replace_recommendation"] == "REPLACE"


def test_F6_underused_theme_classifies_DIVERSIFY_OK() -> None:
    cand = {
        "ticker": "GD",
        "candidate_score": 0.70,
        "execution_readiness_score": 0.70,
        "why_today_score": 0.50,
    }
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_DIVERSIFY_THEME_ROWS,
        exit_rows=[],
        held_exposures=[],
    )
    assert row["buy_admission_class"] == ADM_DIVERSIFY_OK


def test_F7_weak_candidate_classifies_WATCH_ONLY() -> None:
    cand = {
        "ticker": "MU",
        "candidate_score": 0.30,
        "execution_readiness_score": 0.30,
        "why_today_score": 0.30,
    }
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_ROOM_THEME_ROWS,
        exit_rows=[],
        held_exposures=[],
    )
    assert row["buy_admission_class"] == ADM_WATCH_ONLY
    assert row["max_allowed_size"] == 0.0


def test_full_theme_with_weak_candidate_BLOCKED_BY_THEME_CAP() -> None:
    cand = {
        "ticker": "MU",
        "candidate_score": 0.30,
        "execution_readiness_score": 0.30,
        "why_today_score": 0.30,
    }
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_FULL_THEME_ROWS,
        exit_rows=_EXIT_ROWS_AMD_WEAK,
        held_exposures=[],
    )
    assert row["buy_admission_class"] == ADM_BLOCKED_BY_THEME_CAP


def test_admission_outputs_carry_safety_stamps() -> None:
    cand = {"ticker": "MU", "candidate_score": 0.5}
    row = classify_buy_admission(
        cand,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_ROOM_THEME_ROWS,
        exit_rows=[],
        held_exposures=[],
    )
    assert row["advisory_only"] is True
    assert row["broker_api_called"] is False
    assert row["ai_execution_count"] == 0
    assert row["execution_permission"] == "LOCKED"


def test_build_board_aggregates_counts() -> None:
    cands = [
        {"ticker": "MU", "candidate_score": 0.90, "execution_readiness_score": 0.9, "why_today_score": 0.8},
        {"ticker": "ZZZ_UNKNOWN", "candidate_score": 0.1},
    ]
    board = build_buy_admission_board(
        cands,
        portfolio_regime=REGIME_BUY_ALLOWED,
        regime_max_size_per_entry=200.0,
        theme_rows=_ROOM_THEME_ROWS,
        exit_rows=[],
        held_exposures=[],
    )
    assert board["candidate_count"] == 2
    assert board["counts"][ADM_ADDITIVE_OK] >= 1
    assert board["advisory_only"] is True
