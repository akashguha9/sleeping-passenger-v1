"""Tests for FP/FN accounting."""
from __future__ import annotations

from scripts.outcome_accounting import (
    INSUFFICIENT_SAMPLE_THRESHOLD,
    OutcomeAccountingResult,
    compute_outcome_accounting,
)


def test_perfect_predictions_yield_precision_and_recall_one():
    pairs = [
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "up_5pct_in_24h"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "up_2pct_in_24h"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "up_2pct_in_24h"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "up_5pct_in_24h"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "up_2pct_in_24h"},
        {"predicted_action": "MONITOR", "outcome_label": "flat"},
        {"predicted_action": "BLOCK_ENTRY", "outcome_label": "flat"},
    ]
    result = compute_outcome_accounting(pairs)
    assert isinstance(result, OutcomeAccountingResult)
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.false_positive == 0
    assert result.false_negative == 0
    assert result.true_positive == 5
    assert result.true_negative == 2
    assert result.insufficient_sample is False


def test_all_wrong_predictions_yield_precision_zero():
    pairs = [
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "flat"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "flat"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "flat"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "flat"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "flat"},
        {"predicted_action": "BLOCK_ENTRY", "outcome_label": "up_5pct_in_24h"},
    ]
    result = compute_outcome_accounting(pairs)
    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.false_positive == 5
    assert result.false_negative == 1


def test_no_labels_yields_none_metrics():
    pairs = [
        {"predicted_action": "MONITOR", "outcome_label": None},
        {"predicted_action": "BLOCK_ENTRY", "outcome_label": ""},
    ]
    result = compute_outcome_accounting(pairs)
    assert result.labeled_count == 0
    assert result.precision is None
    assert result.recall is None
    assert result.false_positive_rate is None
    assert result.false_negative_rate is None
    assert result.insufficient_sample is True


def test_zero_denominator_safety():
    pairs = [
        {"predicted_action": "MONITOR", "outcome_label": "flat"},
        {"predicted_action": "MONITOR", "outcome_label": "flat"},
        {"predicted_action": "MONITOR", "outcome_label": "flat"},
        {"predicted_action": "MONITOR", "outcome_label": "flat"},
        {"predicted_action": "MONITOR", "outcome_label": "flat"},
    ]
    result = compute_outcome_accounting(pairs)
    # No positive predictions and no positive outcomes -> precision/recall undefined
    assert result.precision is None
    assert result.recall is None
    assert result.false_positive_rate == 0.0
    assert result.true_negative == 5


def test_insufficient_sample_marked_below_threshold():
    pairs = [
        {"predicted_action": "MONITOR", "outcome_label": "flat"},
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "up_2pct_in_24h"},
    ]
    result = compute_outcome_accounting(pairs)
    assert result.labeled_count < INSUFFICIENT_SAMPLE_THRESHOLD
    assert result.insufficient_sample is True
    assert "insufficient_sample" in result.note


def test_mixed_case_classification():
    pairs = [
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "up_2pct_in_24h"},  # TP
        {"predicted_action": "REVIEW_FOR_ENTRY", "outcome_label": "flat"},            # FP
        {"predicted_action": "MONITOR", "outcome_label": "up_5pct_in_24h"},           # FN
        {"predicted_action": "MONITOR", "outcome_label": "flat"},                     # TN
        {"predicted_action": "BLOCK_ENTRY", "outcome_label": "down_2pct_in_24h"},     # FN
        {"predicted_action": "EXIT_NOW", "outcome_label": "down_5pct_in_24h"},        # TP
    ]
    result = compute_outcome_accounting(pairs)
    assert result.true_positive == 2
    assert result.false_positive == 1
    assert result.true_negative == 1
    assert result.false_negative == 2
    assert result.precision == round(2 / 3, 6)
    assert result.recall == round(2 / 4, 6)


def test_tuple_input_supported():
    pairs = [
        ("REVIEW_FOR_ENTRY", "up_2pct_in_24h"),
        ("MONITOR", "flat"),
    ]
    result = compute_outcome_accounting(pairs)
    assert result.sample_count == 2
    assert result.labeled_count == 2
