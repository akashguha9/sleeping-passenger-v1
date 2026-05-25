"""Tests for candidate memory decay (Phase 4)."""
from __future__ import annotations

import math

from scripts.candidate_memory_decay import (
    DEFAULT_LAMBDA,
    adjusted_cqs,
    compute_memory_decay,
    decay_factor,
    decayed_score,
    infer_days_without_fresh_signal,
)


def test_decay_factor_table() -> None:
    assert decay_factor(0) == 1.0
    assert math.isclose(decay_factor(1), 0.7788, abs_tol=0.001)
    assert math.isclose(decay_factor(2), 0.6065, abs_tol=0.001)
    assert math.isclose(decay_factor(3), 0.4724, abs_tol=0.001)
    assert math.isclose(decay_factor(5), 0.2865, abs_tol=0.001)
    assert math.isclose(decay_factor(7), 0.1738, abs_tol=0.001)


def test_d3_factor_is_about_0_472() -> None:
    assert abs(decay_factor(3) - 0.472) < 0.01


def test_decayed_score_uses_lambda() -> None:
    assert decayed_score(0.80, 0) == 0.80
    assert math.isclose(decayed_score(0.80, 3), 0.80 * 0.4724, abs_tol=0.001)


def test_stale_high_score_decays_below_threshold() -> None:
    # A 0.72 candidate that has gone 5 days without fresh signal falls below the
    # 0.60 ACQS floor.
    acqs = adjusted_cqs(0.72, 5)
    assert acqs < 0.60


def test_fresh_signal_resets_decay() -> None:
    # Even with 5 stale days on record, a fresh signal today resets d -> 0.
    fresh = adjusted_cqs(0.72, 5, fresh_signal_present=True)
    assert fresh == 0.72
    rec = compute_memory_decay("RTX", 0.72, days_without_fresh_signal=5, fresh_signal_present=True)
    assert rec["days_without_fresh_signal"] == 0
    assert rec["decay_factor"] == 1.0
    assert rec["decayed_candidate_score"] == 0.72


def test_compute_record_shape() -> None:
    rec = compute_memory_decay("RTX", 0.72, days_without_fresh_signal=2)
    assert rec["ticker"] == "RTX"
    assert rec["decay_lambda"] == DEFAULT_LAMBDA
    assert math.isclose(rec["decay_factor"], 0.6065, abs_tol=0.001)
    assert math.isclose(rec["decayed_candidate_score"], 0.4367, abs_tol=0.001)
    assert rec["fresh_signal_present"] is False


def test_infer_days() -> None:
    assert infer_days_without_fresh_signal(fresh_signal_present=True, in_yesterday=True) == 0
    assert infer_days_without_fresh_signal(fresh_signal_present=False, in_yesterday=True) == 1
    assert infer_days_without_fresh_signal(fresh_signal_present=False, in_yesterday=False) == 0
    assert infer_days_without_fresh_signal(fresh_signal_present=False, in_yesterday=True, prior_days=2) == 3
