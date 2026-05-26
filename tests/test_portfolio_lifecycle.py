"""Tests — exit lifecycle + thesis lifecycle (Test groups A + B)."""
from __future__ import annotations

import math

from scripts.portfolio_lifecycle import (
    EXIT_DATA_BLOCKED,
    EXIT_HOLD_OK,
    EXIT_NOW,
    EXIT_PARTIAL_TP_NOW,
    EXIT_RUNNER_EXIT_REVIEW,
    EXIT_RUNNER_HOLD,
    EXIT_STALE_REVIEW,
    EXIT_TRIM_REVIEW,
    THESIS_BROKEN,
    THESIS_CONFIRMED,
    THESIS_DECAYING,
    THESIS_REPLACED,
    THESIS_UNCHANGED,
    classify_exit_status,
    classify_position,
    classify_thesis_status,
    compute_position_metrics,
    compute_thesis_score,
)


# Test fixtures: a fully-specified clean position the operator can mutate.
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
        "partial_tp_logged": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Group A — exit lifecycle
# ---------------------------------------------------------------------------


def test_A1_stop_breach_triggers_EXIT_NOW() -> None:
    pos = _clean_pos(live_price=90.0)  # below stop_loss=95
    result = classify_exit_status(pos)
    assert result["exit_status"] == EXIT_NOW
    assert "stop_breach" in result["reason_codes"]


def test_A2_at_tp_and_no_partial_triggers_PARTIAL_TP_NOW() -> None:
    pos = _clean_pos(live_price=135.0, partial_tp_logged=False)
    result = classify_exit_status(pos)
    assert result["exit_status"] == EXIT_PARTIAL_TP_NOW


def test_A3_runner_hold_with_clean_price_and_confirmed_thesis() -> None:
    pos = _clean_pos(
        partial_tp_logged=True,
        booked_pct=70,
        ride_pct=30,
        live_price=125.0,
        trailing_stop=110.0,
    )
    result = classify_exit_status(
        pos, {"thesis_status": THESIS_CONFIRMED}
    )
    assert result["exit_status"] == EXIT_RUNNER_HOLD


def test_A4_runner_below_trailing_stop_triggers_RUNNER_EXIT_REVIEW() -> None:
    pos = _clean_pos(
        partial_tp_logged=True,
        booked_pct=70,
        ride_pct=30,
        live_price=108.0,
        trailing_stop=109.0,  # live <= trailing
    )
    result = classify_exit_status(
        pos, {"thesis_status": THESIS_UNCHANGED}
    )
    assert result["exit_status"] == EXIT_RUNNER_EXIT_REVIEW
    assert "trailing_stop_breach" in result["reason_codes"]


def test_A5_missing_live_price_triggers_DATA_BLOCKED() -> None:
    pos = _clean_pos(live_price=None)
    result = classify_exit_status(pos)
    assert result["exit_status"] == EXIT_DATA_BLOCKED
    assert any("live_price" in r for r in result["reason_codes"])


def test_A6_stale_unproductive_triggers_STALE_REVIEW() -> None:
    pos = _clean_pos(
        age_days=40,            # past horizon=20
        expected_horizon_days=20,
        live_price=99.0,         # pnl_pct < 0
    )
    result = classify_exit_status(pos)
    assert result["exit_status"] == EXIT_STALE_REVIEW


def test_A7_duplicate_economic_exposure_triggers_TRIM_REVIEW() -> None:
    pos = _clean_pos()
    result = classify_exit_status(
        pos, {"duplicate_economic_exposure": True}
    )
    assert result["exit_status"] == EXIT_TRIM_REVIEW
    assert "duplicate_economic_exposure" in result["reason_codes"]


def test_A8_clean_position_returns_HOLD_OK() -> None:
    pos = _clean_pos()
    result = classify_exit_status(pos)
    assert result["exit_status"] == EXIT_HOLD_OK


def test_phantom_or_do_not_manage_row_triggers_EXIT_NOW() -> None:
    pos = _clean_pos(trade_state="CLOSED")
    result = classify_exit_status(pos)
    assert result["exit_status"] == EXIT_NOW
    assert "phantom_or_do_not_manage_row" in result["reason_codes"]


def test_theme_hard_cap_exceeded_triggers_TRIM_REVIEW() -> None:
    pos = _clean_pos()
    result = classify_exit_status(
        pos, {"theme_hard_cap_exceeded": True}
    )
    assert result["exit_status"] == EXIT_TRIM_REVIEW


# ---------------------------------------------------------------------------
# Group B — thesis lifecycle
# ---------------------------------------------------------------------------


def test_B1_high_score_classifies_CONFIRMED() -> None:
    assert classify_thesis_status(0.85) == THESIS_CONFIRMED


def test_B2_medium_score_classifies_UNCHANGED() -> None:
    assert classify_thesis_status(0.60) == THESIS_UNCHANGED


def test_B3_weak_score_classifies_DECAYING() -> None:
    assert classify_thesis_status(0.40) == THESIS_DECAYING


def test_B4_hard_invalidation_classifies_BROKEN() -> None:
    assert classify_thesis_status(0.80, hard_invalidation=True) == THESIS_BROKEN
    assert classify_thesis_status(0.20) == THESIS_BROKEN


def test_B5_replaced_by_stronger_candidate_classifies_REPLACED() -> None:
    assert (
        classify_thesis_status(0.80, replaced_by_stronger_candidate=True)
        == THESIS_REPLACED
    )


def test_thesis_score_drops_on_stop_breach() -> None:
    pos = _clean_pos(live_price=80.0)  # below stop
    score = compute_thesis_score(pos)
    # Price-structure component is 0, so total score is bounded.
    assert score < 0.55


def test_thesis_score_clamped_to_unit_interval() -> None:
    pos = _clean_pos()
    score = compute_thesis_score(
        pos,
        {
            "relative_strength_score": 5,    # out of bounds
            "catalyst_validity_score": -1,   # out of bounds
            "theme_quality_score": 0.9,
        },
    )
    assert 0.0 <= score <= 1.0


def test_hard_invalidation_overrides_score_in_compute() -> None:
    pos = _clean_pos()
    score = compute_thesis_score(pos, {"hard_invalidation": True})
    assert score == 0.0


# ---------------------------------------------------------------------------
# Numeric derivations sanity
# ---------------------------------------------------------------------------


def test_compute_position_metrics_basic_math() -> None:
    pos = _clean_pos()
    m = compute_position_metrics(pos)
    assert m["pnl_pct"] is not None
    assert math.isclose(m["pnl_pct"], 0.10, rel_tol=1e-6)
    assert math.isclose(m["distance_to_stop_pct"], (110 - 95) / 110, rel_tol=1e-6)
    assert math.isclose(m["distance_to_tp_pct"], (130 - 110) / 110, rel_tol=1e-6)
    assert m["data_ok"] is True


def test_compute_position_metrics_handles_missing_fields() -> None:
    m = compute_position_metrics({"ticker": "X"})
    assert m["live_price"] is None
    assert m["pnl_pct"] is None
    assert m["data_ok"] is False


# ---------------------------------------------------------------------------
# classify_position end-to-end
# ---------------------------------------------------------------------------


def test_classify_position_returns_full_schema() -> None:
    pos = _clean_pos()
    row = classify_position(pos)
    expected_keys = {
        "ticker", "economic_exposure_key", "theme_buckets", "trade_state",
        "buy_price", "live_price", "stop_loss", "tp_price",
        "partial_tp_logged", "booked_pct", "ride_pct",
        "age_days", "expected_horizon_days", "leverage",
        "pnl_pct", "leveraged_pnl_pct",
        "distance_to_stop_pct", "distance_to_tp_pct",
        "freshness_score", "thesis_score", "thesis_status",
        "exit_status", "reason_codes", "human_action_required",
        "advisory_only", "broker_api_called", "ai_execution_count",
    }
    assert expected_keys.issubset(set(row.keys()))
    assert row["advisory_only"] is True
    assert row["broker_api_called"] is False
    assert row["ai_execution_count"] == 0
