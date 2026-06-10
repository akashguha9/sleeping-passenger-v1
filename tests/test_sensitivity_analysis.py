"""Sensitivity analysis proofs (Pass 4, Phase 9) — known linear answers."""
from __future__ import annotations

import math

import pytest

from scripts import sensitivity_analysis as sa

W = {"a": 0.6, "b": 0.3, "c": 0.1}
X = {"a": 0.9, "b": 0.5, "c": 0.2}


def test_base_score_linear():
    assert sa.base_score(W, X) == pytest.approx(0.6 * 0.9 + 0.3 * 0.5 + 0.1 * 0.2)


def test_feature_perturbation_is_exactly_w_eps():
    d = sa.feature_perturbations(W, X, epsilon=0.1)
    assert d["a"] == pytest.approx(0.06)
    assert d["b"] == pytest.approx(0.03)
    assert d["c"] == pytest.approx(0.01)


def test_weight_perturbation_is_exactly_x_eps():
    d = sa.weight_perturbations(W, X, epsilon=0.1)
    assert d["a"] == pytest.approx(0.09)
    assert d["c"] == pytest.approx(0.02)


def test_dominant_feature_detected():
    report = sa.analyze(W, X, decision_threshold=0.5)
    assert report["dominant_feature"] == "a"
    assert report["dominance"]["a"] > 0.6


def test_missing_critical_feature_flips_decision():
    # S = 0.69; without 'a' → 0.17 (< 0.5): 'a' is decision-critical.
    flips = sa.missing_feature_flips(W, X, decision_threshold=0.5)
    assert "a" in flips and "c" not in flips


def test_unstable_model_triggers_abstain():
    # Score sits exactly on the threshold → noise flips it constantly.
    weights = {"a": 0.5, "b": 0.5}
    features = {"a": 0.5, "b": 0.5}
    report = sa.analyze(weights, features, decision_threshold=0.5, sigma=0.2)
    assert report["recommendation"] == sa.ABSTAIN
    assert report["recommendation_reasons"]


def test_stable_model_proceeds_with_human_review():
    weights = {"a": 0.4, "b": 0.3, "c": 0.3}
    features = {"a": 0.95, "b": 0.95, "c": 0.9}
    report = sa.analyze(weights, features, decision_threshold=0.3, sigma=0.02)
    assert report["recommendation"] == sa.PROCEED
    assert report["advisory_only"] is True and report["human_required"] is True


def test_weights_must_sum_to_one_when_required():
    with pytest.raises(sa.SensitivityError):
        sa.analyze({"a": 0.5, "b": 0.2}, {"a": 1.0, "b": 1.0})
    # Explicitly opting out is allowed (e.g. penalty terms).
    report = sa.analyze({"a": 0.5, "b": 0.2}, {"a": 1.0, "b": 1.0},
                        require_weight_sum_1=False)
    assert report["base_score"] == pytest.approx(0.7)


@pytest.mark.parametrize("bad", [float("nan"), None])
def test_nan_or_missing_features_are_explicit_errors(bad):
    with pytest.raises(sa.SensitivityError):
        sa.analyze(W, {**X, "a": bad})


def test_negative_feature_values_handled():
    features = {**X, "c": -0.4}
    report = sa.analyze(W, features, decision_threshold=0.5)
    assert math.isfinite(report["base_score"])
    assert report["dominance"]["c"] > 0  # |w·x| dominance handles negatives


def test_monte_carlo_deterministic_with_seed():
    a = sa.monte_carlo_stability(W, X, decision_threshold=0.5, seed=7)
    b = sa.monte_carlo_stability(W, X, decision_threshold=0.5, seed=7)
    assert a == b


def test_key_mismatch_refused():
    with pytest.raises(sa.SensitivityError):
        sa.analyze(W, {"a": 0.1, "b": 0.2, "z": 0.3})
