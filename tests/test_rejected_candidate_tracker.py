"""Tests for scripts/rejected_candidate_tracker.py — learning from rejections."""
from __future__ import annotations

from datetime import date

from scripts.rejected_candidate_tracker import (
    CORRECT_REJECTION,
    FALSE_NEGATIVE_REVIEW,
    INCONCLUSIVE_REVIEW,
    NEUTRAL_REJECTION,
    PENDING_HORIZON,
    RejectedCandidate,
    classify_rejection_quality,
    summarize_rejections,
    to_moltbook_entry,
)


def _rc(**kw):
    base = dict(date_rejected=date(2026, 5, 28), ticker="X", country="US",
               rejection_reason="low_liquidity")
    base.update(kw)
    return RejectedCandidate(**base)


def test_false_negative_from_return_or_mfe():
    assert classify_rejection_quality(_rc(later_5d_return=0.06)) == FALSE_NEGATIVE_REVIEW
    assert classify_rejection_quality(
        _rc(later_5d_return=0.01, max_favorable_after_rejection=0.09)
    ) == FALSE_NEGATIVE_REVIEW


def test_correct_rejection():
    assert classify_rejection_quality(
        _rc(later_5d_return=-0.05, max_adverse_after_rejection=-0.07)
    ) == CORRECT_REJECTION


def test_neutral_rejection():
    assert classify_rejection_quality(_rc(later_5d_return=0.01)) == NEUTRAL_REJECTION


def test_pending_when_horizon_missing():
    assert classify_rejection_quality(_rc()) == PENDING_HORIZON


def test_inconclusive_in_the_gap():
    # +0.03 is above the neutral band but below the false-negative trigger.
    assert classify_rejection_quality(_rc(later_5d_return=0.03)) == INCONCLUSIVE_REVIEW


def test_moltbook_entry_is_advisory():
    entry = to_moltbook_entry(_rc(later_5d_return=0.06))
    assert entry["event_type"] == "rejected_candidate_review"
    assert entry["classification"] == FALSE_NEGATIVE_REVIEW
    assert entry["advisory_only"] is True
    assert entry["execution_gate"] == "LOCKED"
    assert entry["broker_api_called"] is False
    assert entry["lesson"]


def test_summarize_counts_and_false_negative_rate():
    rejections = [
        _rc(later_5d_return=0.06),  # false negative
        _rc(later_5d_return=-0.05, max_adverse_after_rejection=-0.07),  # correct
        _rc(later_5d_return=0.0),  # neutral
        _rc(),  # pending (excluded from rate)
    ]
    summary = summarize_rejections(rejections)
    assert summary["total"] == 4
    assert summary["counts"][FALSE_NEGATIVE_REVIEW] == 1
    assert summary["counts"][PENDING_HORIZON] == 1
    # 1 false negative out of 3 scored.
    assert summary["false_negative_rate"] == round(1 / 3, 4)
