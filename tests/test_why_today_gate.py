"""Tests for the WHY_TODAY executable gate (Phase 3)."""
from __future__ import annotations

from scripts.candidate_executable_split import classify_candidate, compute_eqs
from scripts.why_today import (
    classify_why_today,
    passes_executable_why_today,
    why_today_score,
)


def test_live_trigger_scores_full() -> None:
    assert why_today_score(freshness="FRESH_TODAY") == 1.0
    assert why_today_score("Earnings beat and gap up today") == 1.0
    assert why_today_score(has_live_event_today=True) == 1.0


def test_static_fallback_scores_quarter() -> None:
    txt = "Included in minimum viable daily market universe; live price mover confirmation unavailable."
    assert why_today_score(txt, is_static_universe_only=True) == 0.25
    assert why_today_score(txt) == 0.25


def test_stale_repeat_scores_low() -> None:
    # On yesterday's board, no fresh change, generic text.
    assert why_today_score("still like the long-term story, no change", in_yesterday=True) == 0.10


def test_missing_or_generic_scores_zero() -> None:
    assert why_today_score(None) == 0.0
    assert why_today_score("") == 0.0
    assert why_today_score("strong fundamentals, secular growth") == 0.0


def test_classify_buckets() -> None:
    assert classify_why_today(1.0) == "LIVE_TRIGGER"
    assert classify_why_today(0.25) == "STATIC_FALLBACK"
    assert classify_why_today(0.10) == "STALE_REPEAT"
    assert classify_why_today(0.0) == "MISSING_OR_GENERIC"


def test_passes_executable_threshold() -> None:
    assert passes_executable_why_today(0.70) is True
    assert passes_executable_why_today(0.69) is False
    assert passes_executable_why_today(0.25) is False


def _strong_eqs() -> dict:
    return compute_eqs({
        "data_quality": 1.0, "invalidation_defined": 1, "position_sizing_defined": 1,
        "source_health": 1.0, "portfolio_truth_clean": 1, "liquidity_quality": 1.0,
        "human_review_ready": 1,
    })


def test_weak_why_today_blocks_executable_but_keeps_candidate() -> None:
    eqs = _strong_eqs()
    verdict = classify_candidate(
        cqs=0.85, eqs=eqs["eqs"], eqs_components=eqs["components"],
        portfolio_truth="NOT_A_HOLDING", forbidden_for_execution=False,
        source_health=1.0, why_today_score=0.25,
    )
    assert verdict["executable"] is False
    assert verdict["classification"] == "BUY-CANDIDATE / NOT-EXECUTABLE"
    assert "why-today" in verdict["reason"].lower()


def test_strong_why_today_allows_executable() -> None:
    eqs = _strong_eqs()
    verdict = classify_candidate(
        cqs=0.85, eqs=eqs["eqs"], eqs_components=eqs["components"],
        portfolio_truth="NOT_A_HOLDING", forbidden_for_execution=False,
        source_health=1.0, why_today_score=1.0,
    )
    assert verdict["executable"] is True
    assert verdict["classification"] == "EXECUTABLE-PAPER-BUY"
