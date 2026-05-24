"""Tests for model disagreement value (Phase 5)."""
from __future__ import annotations

import math

from scripts.model_disagreement import (
    compute_model_disagreement,
    cross_model_agreement,
)


def test_identical_scores_zero_disagreement() -> None:
    rec = compute_model_disagreement("RTX", {"gpt": 0.7, "claude": 0.7, "gemini": 0.7})
    assert rec["disagreement_variance"] == 0.0
    assert rec["disagreement_std"] == 0.0
    assert rec["normalized_disagreement"] == 0.0


def test_outlier_increases_disagreement() -> None:
    base = compute_model_disagreement("RTX", {"gpt": 0.70, "claude": 0.72, "gemini": 0.71})
    outlier = compute_model_disagreement("RTX", {"gpt": 0.70, "claude": 0.72, "gemini": 0.10})
    assert outlier["disagreement_variance"] > base["disagreement_variance"]
    assert outlier["normalized_disagreement"] > base["normalized_disagreement"]


def test_high_score_low_disagreement_is_clean_consensus() -> None:
    rec = compute_model_disagreement(
        "RTX", {"gpt": 0.78, "claude": 0.80, "gemini": 0.79, "grok": 0.81, "mistral": 0.80}
    )
    assert rec["mean_model_score"] >= 0.70
    assert rec["normalized_disagreement"] < 0.15
    assert rec["model_consensus_quality"] == "CLEAN_CONSENSUS"


def test_high_score_high_disagreement_is_research_candidate() -> None:
    rec = compute_model_disagreement(
        "RTX", {"gpt": 0.95, "claude": 0.90, "gemini": 0.30, "grok": 0.95, "mistral": 0.55}
    )
    assert rec["mean_model_score"] >= 0.70
    assert rec["normalized_disagreement"] >= 0.35
    assert rec["model_consensus_quality"] == "HIGH_CONVICTION_DISAGREEMENT"


def test_low_score_high_disagreement_is_uncertain() -> None:
    rec = compute_model_disagreement(
        "RTX", {"gpt": 0.10, "claude": 0.20, "gemini": 0.95, "grok": 0.15, "mistral": 0.30}
    )
    assert rec["mean_model_score"] < 0.55
    assert rec["normalized_disagreement"] >= 0.35
    assert rec["model_consensus_quality"] == "UNCERTAIN_OR_CONFLICTED"


def test_insufficient_coverage() -> None:
    rec = compute_model_disagreement("RTX", {"gpt": 0.8})
    assert rec["n_models"] == 1
    assert rec["model_consensus_quality"] == "INSUFFICIENT_CROSS_MODEL_COVERAGE"
    none_rec = compute_model_disagreement("RTX", {})
    assert none_rec["model_consensus_quality"] == "INSUFFICIENT_CROSS_MODEL_COVERAGE"


def test_variance_matches_population_formula() -> None:
    scores = {"gpt": 0.75, "claude": 0.78, "gemini": 0.85, "grok": 0.60, "mistral": 0.72}
    rec = compute_model_disagreement("RTX", scores)
    values = list(scores.values())
    mean = sum(values) / len(values)
    expected_var = sum((v - mean) ** 2 for v in values) / len(values)
    assert math.isclose(rec["disagreement_variance"], round(expected_var, 6), abs_tol=1e-6)


def test_cross_model_agreement() -> None:
    assert cross_model_agreement({"gpt": 0.7, "claude": 0.7}) == 0.4
    assert cross_model_agreement({"gpt": 0.7, "claude": 0.7, "gemini": 0.7, "grok": 0.7, "mistral": 0.7}) == 1.0
