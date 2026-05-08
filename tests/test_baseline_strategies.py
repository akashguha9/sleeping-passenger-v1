"""Tests for the deterministic baseline strategies."""
from __future__ import annotations

import pytest

from scripts.baseline_strategies import (
    AlwaysHoldBaseline,
    NaiveMomentumBaseline,
    RandomChoiceBaseline,
    summarise_baseline_decisions,
)


def _records():
    return [
        {"record_id": "r1", "instrument": "RTX", "feature_value": 0.7},
        {"record_id": "r2", "instrument": "ZIM", "feature_value": 0.45},
        {"record_id": "r3", "instrument": "GLD", "feature_value": 0.1},
        {"record_id": "r4", "instrument": "TLT", "feature_value": 0.6},
        {"record_id": "r5", "instrument": "TIP", "feature_value": 0.25},
    ]


def test_always_hold_baseline_emits_hold_for_every_record():
    decisions = AlwaysHoldBaseline().decide(_records())
    assert all(decision.predicted_action == "HOLD" for decision in decisions)
    assert {decision.record_id for decision in decisions} == {"r1", "r2", "r3", "r4", "r5"}


def test_random_choice_baseline_is_deterministic_for_a_seed():
    a = [decision.predicted_action for decision in RandomChoiceBaseline(seed=42).decide(_records())]
    b = [decision.predicted_action for decision in RandomChoiceBaseline(seed=42).decide(_records())]
    assert a == b
    c = [decision.predicted_action for decision in RandomChoiceBaseline(seed=7).decide(_records())]
    assert c != a or len(set(a)) == 1  # different seed should change output (unless trivially uniform)


def test_random_choice_baseline_resets_between_calls():
    baseline = RandomChoiceBaseline(seed=1)
    first = [d.predicted_action for d in baseline.decide(_records())]
    second = [d.predicted_action for d in baseline.decide(_records())]
    assert first == second


def test_naive_momentum_baseline_threshold_logic():
    decisions = {
        decision.record_id: decision.predicted_action
        for decision in NaiveMomentumBaseline(upper=0.6, lower=0.3).decide(_records())
    }
    assert decisions["r1"] == "REVIEW_FOR_ENTRY"
    assert decisions["r2"] == "MONITOR"
    assert decisions["r3"] == "BLOCK_ENTRY"
    assert decisions["r4"] == "REVIEW_FOR_ENTRY"
    assert decisions["r5"] == "BLOCK_ENTRY"


def test_naive_momentum_baseline_rejects_invalid_thresholds():
    with pytest.raises(ValueError):
        NaiveMomentumBaseline(upper=0.3, lower=0.6)


def test_summarise_baseline_decisions_action_counts():
    decisions = AlwaysHoldBaseline().decide(_records())
    summary = summarise_baseline_decisions("always_hold", decisions)
    assert summary["baseline_name"] == "always_hold"
    assert summary["decision_count"] == 5
    assert summary["action_counts"] == {"HOLD": 5}
    assert "investment advice" in summary["note"]
