"""
Tests for ``scripts.self_test_journal_quality``.

Pin
---
- A complete journal entry scores high and is learning_ready.
- Missing thesis / invalidation / outcome destroys learning_readiness
  multiplicatively (a near-complete entry without a thesis still flunks).
- Decision quality flags are emitted per-factor.
- Mistake tags + lesson improve learning readiness.
- Safety stamps locked.
- No execution permission anywhere.
- Aggregate across entries works and pins each factor's pass rate.
- Bad inputs handled safely.
"""
from __future__ import annotations

from scripts import self_test_journal_quality as jq


# ---------------------------------------------------------------------------
# Complete entry
# ---------------------------------------------------------------------------


def _complete_entry() -> dict:
    return {
        "signal_id": "EVT_LOG_QQQ",
        "thesis": "Persistence has rebuilt above breakdown level",
        "invalidation_level": 415.5,
        "expected_horizon": "2-3 weeks",
        "position_size": 0.05,
        "risk_reason": "Sized for 1% portfolio risk",
        "entry_reason": "Trigger candle closed above MA50",
        "exit_plan": "Stop below 415.5; take half off at 440",
        "confidence_before": 0.65,
        "emotional_state": "calm",
        "source_references": ["EVT_LOG_QQQ", "moltbook_entry_12"],
        "post_trade_outcome": "+2.1% over 9 days",
        "reconciliation_status": "WIN",
        "mistake_tags": ["none"],
        "lesson": "Patience around MA50 reclaim paid off",
    }


def test_complete_entry_is_learning_ready():
    result = jq.score_journal_entry(_complete_entry())
    assert result["validation_status"] == "valid"
    assert result["journal_completeness_score"] == 1.0
    assert result["learning_readiness_score"] == 1.0
    assert result["learning_ready"] is True
    assert result["missing_fields"] == []
    assert all(score == 1.0 for score in result["factor_scores"].values())


# ---------------------------------------------------------------------------
# Multiplicative destruction
# ---------------------------------------------------------------------------


def test_missing_thesis_destroys_readiness():
    entry = _complete_entry()
    del entry["thesis"]
    del entry["entry_reason"]
    result = jq.score_journal_entry(entry)
    assert result["learning_ready"] is False
    assert result["learning_readiness_score"] == 0.0
    assert "missing_thesis_or_entry_reason" in result["decision_quality_flags"]


def test_missing_outcome_destroys_readiness():
    entry = _complete_entry()
    del entry["post_trade_outcome"]
    del entry["reconciliation_status"]
    result = jq.score_journal_entry(entry)
    assert result["learning_ready"] is False
    assert "no_outcome_or_reconciliation" in result["decision_quality_flags"]


def test_missing_invalidation_destroys_readiness():
    entry = _complete_entry()
    del entry["invalidation_level"]
    del entry["exit_plan"]
    result = jq.score_journal_entry(entry)
    assert result["learning_ready"] is False
    assert "no_invalidation_or_exit_plan" in result["decision_quality_flags"]


def test_missing_reflection_destroys_readiness():
    entry = _complete_entry()
    del entry["mistake_tags"]
    del entry["lesson"]
    result = jq.score_journal_entry(entry)
    assert result["learning_ready"] is False
    assert "no_reflection_or_mistake_tags" in result["decision_quality_flags"]


# ---------------------------------------------------------------------------
# Mistake tags and lessons lift readiness
# ---------------------------------------------------------------------------


def test_mistake_tags_and_lesson_complete_the_reflection_factor():
    entry = {
        "signal_id": "X",
        "thesis": "Test",
        "invalidation_level": 1,
        "expected_horizon": "1w",
        "risk_reason": "1%",
        "post_trade_outcome": "loss",
        # No reflection yet
    }
    result_no_reflection = jq.score_journal_entry(entry)
    assert result_no_reflection["factor_scores"]["reflection"] == 0.0

    entry["mistake_tags"] = ["overtraded"]
    entry["lesson"] = "Wait for confirmation"
    result_with_reflection = jq.score_journal_entry(entry)
    assert result_with_reflection["factor_scores"]["reflection"] == 1.0
    assert (
        result_with_reflection["learning_readiness_score"]
        > result_no_reflection["learning_readiness_score"]
    )


# ---------------------------------------------------------------------------
# Bonus flags
# ---------------------------------------------------------------------------


def test_bonus_flags_emitted_for_emotional_state_and_confidence():
    entry = _complete_entry()
    del entry["emotional_state"]
    del entry["confidence_before"]
    result = jq.score_journal_entry(entry)
    assert "emotional_state_not_recorded" in result["decision_quality_flags"]
    assert "pre_trade_confidence_not_recorded" in result["decision_quality_flags"]


# ---------------------------------------------------------------------------
# Empty values count as missing
# ---------------------------------------------------------------------------


def test_empty_string_treated_as_missing():
    entry = _complete_entry()
    entry["thesis"] = "   "
    result = jq.score_journal_entry(entry)
    assert result["factor_scores"]["thesis"] in (0.0, 1.0)
    # entry_reason is still present, so the factor remains 1.0
    assert result["factor_scores"]["thesis"] == 1.0


def test_zero_position_size_is_treated_as_missing():
    entry = _complete_entry()
    entry["position_size"] = 0
    result = jq.score_journal_entry(entry)
    # risk_reason is still present, so the factor stays 1.0
    assert result["factor_scores"]["risk_rationale"] == 1.0


# ---------------------------------------------------------------------------
# Safety stamps
# ---------------------------------------------------------------------------


def test_safety_stamps_locked():
    for entry in (_complete_entry(), {}, {"thesis": "x"}):
        result = jq.score_journal_entry(entry)
        assert result["advisory_status"] == "ADVISORY_ONLY"
        assert result["execution_gate"] == "LOCKED"
        assert result["broker_api_called"] is False
        assert result["ai_execution_count"] == 0
        assert result["execution_permission"] is False
        assert result["can_execute"] is False


def test_invalid_entry_handled_safely():
    result = jq.score_journal_entry("not a dict")  # type: ignore[arg-type]
    assert result["validation_status"] == "invalid"
    assert result["learning_ready"] is False
    assert result["execution_permission"] is False


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def test_aggregate_over_entries():
    entries = [
        _complete_entry(),
        {**_complete_entry(), "thesis": ""},  # missing thesis-factor
        {},  # empty
    ]
    # Make second entry truly missing the thesis factor by also clearing entry_reason
    entries[1]["entry_reason"] = ""

    agg = jq.score_journal_entries(entries)
    assert agg["entry_count"] == 3
    assert agg["learning_ready_count"] == 1
    assert 0.0 <= agg["average_completeness"] <= 1.0
    assert 0.0 <= agg["average_learning_readiness"] <= 1.0
    assert agg["factor_pass_rates"]["thesis"] < 1.0
    assert agg["factor_pass_rates"]["outcome_log"] < 1.0
    assert agg["advisory_status"] == "ADVISORY_ONLY"
    assert agg["execution_permission"] is False


def test_aggregate_empty_list_is_not_applicable():
    agg = jq.score_journal_entries([])
    assert agg["entry_count"] == 0
    assert agg["validation_status"] == "not_applicable"
    assert agg["execution_permission"] is False


def test_aggregate_non_iterable_is_invalid():
    agg = jq.score_journal_entries(42)  # type: ignore[arg-type]
    assert agg["validation_status"] == "invalid"
    assert agg["execution_permission"] is False


# ---------------------------------------------------------------------------
# Side-effect freedom
# ---------------------------------------------------------------------------


def test_entry_not_mutated():
    entry = _complete_entry()
    snapshot = dict(entry)
    jq.score_journal_entry(entry)
    assert entry == snapshot
