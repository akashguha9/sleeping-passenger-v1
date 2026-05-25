"""Tests for the integrated ACQS/FCS/ERS scoring + final classification (Phase 6)."""
from __future__ import annotations

import math

from scripts.daily_scoring import (
    classify_final,
    compute_acqs,
    compute_ers,
    compute_fcs,
    cross_model_agreement,
    freshness_score_from_label,
)


def test_acqs_applies_memory_decay() -> None:
    assert compute_acqs(0.80, 0) == 0.80
    assert math.isclose(compute_acqs(0.80, 3), 0.80 * 0.4724, abs_tol=0.001)
    assert compute_acqs(0.80, 5, fresh_signal_present=True) == 0.80


def test_fcs_is_bounded_and_weighted() -> None:
    out = compute_fcs({
        "acqs": 0.8, "mean_model_score": 0.8, "cross_model_agreement": 1.0,
        "why_today_score": 1.0, "data_quality": 0.8, "freshness_score": 1.0,
        "liquidity_quality": 0.8,
    })
    assert 0.0 <= out["fcs"] <= 1.0
    assert out["fcs"] >= 0.70


def test_fcs_penalised_by_disagreement_and_contamination() -> None:
    clean = compute_fcs({"acqs": 0.8, "mean_model_score": 0.8, "cross_model_agreement": 1.0,
                         "why_today_score": 1.0, "data_quality": 0.8, "freshness_score": 1.0,
                         "liquidity_quality": 0.8})
    noisy = compute_fcs({"acqs": 0.8, "mean_model_score": 0.8, "cross_model_agreement": 1.0,
                         "why_today_score": 1.0, "data_quality": 0.8, "freshness_score": 1.0,
                         "liquidity_quality": 0.8, "normalized_disagreement": 0.9,
                         "portfolio_contamination_penalty": 1.0})
    assert noisy["fcs"] < clean["fcs"]


def test_executable_requires_all_gates() -> None:
    strong = dict(
        fcs=0.80, ers=0.80, why_today_score=1.0, source_health=0.9,
        invalidation_defined=1, position_sizing_defined=1,
        normalized_disagreement=0.10, forbidden_for_execution=False,
    )
    assert classify_final(**strong)["classification"] == "EXECUTABLE-PAPER-BUY"
    assert classify_final(**strong)["executable"] is True

    # Weak why-today blocks executable.
    blocked = dict(strong, why_today_score=0.25)
    v = classify_final(**blocked)
    assert v["executable"] is False
    assert v["classification"] == "BUY-CANDIDATE / NOT-EXECUTABLE"
    assert "why-today" in v["reason"].lower()

    # High disagreement => research candidate, never executable.
    research = dict(strong, normalized_disagreement=0.40)
    v2 = classify_final(**research)
    assert v2["executable"] is False
    assert v2["classification"] == "RESEARCH_CANDIDATE"


def test_portfolio_truth_exclusion() -> None:
    # Forbidden (closed/sold/do-not-treat) can never be executable.
    v = classify_final(
        fcs=0.90, ers=0.90, why_today_score=1.0, source_health=1.0,
        invalidation_defined=1, position_sizing_defined=1,
        normalized_disagreement=0.0, forbidden_for_execution=True,
    )
    assert v["executable"] is False
    assert v["classification"] in {"WATCHLIST", "AVOID"}

    # Verified holding => exit review only.
    held = classify_final(
        fcs=0.90, ers=0.90, why_today_score=1.0, source_health=1.0,
        invalidation_defined=1, position_sizing_defined=1,
        normalized_disagreement=0.0, forbidden_for_execution=False,
        portfolio_truth="VERIFIED_OPEN_HOLDING",
    )
    assert held["classification"] == "SELL / EXIT REVIEW"
    assert held["executable"] is False


def test_ers_components() -> None:
    out = compute_ers({
        "data_quality": 1.0, "source_health": 1.0, "invalidation_defined": 1,
        "position_sizing_defined": 1, "portfolio_truth_clean": 1,
        "why_today_score": 1.0, "human_review_ready": 1,
    })
    assert math.isclose(out["ers"], 1.0, abs_tol=1e-6)


def test_helpers() -> None:
    assert cross_model_agreement(3) == 0.6
    assert freshness_score_from_label("FRESH_TODAY") == 1.0
    assert freshness_score_from_label("UNVERIFIED") == 0.0
