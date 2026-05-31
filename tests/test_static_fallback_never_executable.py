"""Tests — static/fallback names can never become executable buys."""
from __future__ import annotations

import pytest

from scripts.daily_synthesis_pipeline import run_daily_synthesis
from scripts.why_today import (
    STATIC_FALLBACK_SCORE,
    classify_non_live,
    executable_candidate,
    extended_why_today_score,
    why_today_score,
)


def test_static_universe_why_today_below_executable_floor():
    score = why_today_score(
        "Included in minimum viable daily market universe; live price mover confirmation unavailable.",
        is_static_universe_only=True,
    )
    assert score == STATIC_FALLBACK_SCORE
    assert score < 0.70


def test_executable_candidate_blocks_static_even_with_other_signals():
    # Every other condition passes, but is_static_universe_only must veto.
    assert (
        executable_candidate(
            why_today_score_value=1.0,
            source_health_score=1.0,
            valid_price=True,
            mapping_confidence=1.0,
            country_coverage_confidence=1.0,
            in_phantom_closed_sold=False,
            is_static_universe_only=True,
        )
        is False
    )


def test_executable_candidate_allows_clean_live_name():
    assert (
        executable_candidate(
            why_today_score_value=0.8,
            source_health_score=0.8,
            valid_price=True,
            mapping_confidence=0.8,
            country_coverage_confidence=0.5,
            in_phantom_closed_sold=False,
            is_static_universe_only=False,
        )
        is True
    )


def test_extended_score_penalizes_static_and_phantom():
    live = extended_why_today_score(
        fresh_news_score=1.0, price_mover_score=1.0, ticker_mapping_confidence=1.0,
        country_coverage_confidence=1.0,
    )
    static = extended_why_today_score(
        fresh_news_score=1.0, price_mover_score=1.0, ticker_mapping_confidence=1.0,
        country_coverage_confidence=1.0, is_static_universe_only=True,
    )
    phantom = extended_why_today_score(
        fresh_news_score=1.0, price_mover_score=1.0, ticker_mapping_confidence=1.0,
        country_coverage_confidence=1.0, phantom=True,
    )
    assert live > static
    assert phantom == 0.0


def _clean_executable_kwargs():
    return dict(
        why_today_score_value=1.0,
        source_health_score=1.0,
        valid_price=True,
        mapping_confidence=1.0,
        country_coverage_confidence=1.0,
        in_phantom_closed_sold=False,
        is_static_universe_only=False,
    )


def test_executable_candidate_directly_requires_news_and_mapping_support():
    base = _clean_executable_kwargs()
    assert executable_candidate(**base) is True
    assert executable_candidate(**base, news_support=False) is False
    assert executable_candidate(**base, mapping_support=False) is False


def test_executable_candidate_requires_membership_in_l_today():
    base = _clean_executable_kwargs()
    # A prior-only candidate (absent from L_today) can never be executable.
    assert executable_candidate(**base, in_l_today=False) is False


def test_executable_candidate_requires_valid_price():
    base = _clean_executable_kwargs()
    base["valid_price"] = False
    assert executable_candidate(**base) is False


def test_executable_candidate_requires_locked_advisory_contract():
    base = _clean_executable_kwargs()
    # Any broken safety invariant makes the candidate non-executable by definition.
    assert executable_candidate(**base, execution_gate="UNLOCKED") is False
    assert executable_candidate(**base, broker_api_called=True) is False
    assert executable_candidate(**base, ai_execution_count=1) is False
    assert executable_candidate(**base, advisory_only=False) is False
    assert executable_candidate(**base, human_review_required=False) is False


def test_classify_non_live_buckets():
    assert classify_non_live(
        in_holdings=False, in_static_universe=True, in_phantom_closed_sold=False, in_yesterday=False
    ) == "RESEARCH_ONLY_STATIC"
    assert classify_non_live(
        in_holdings=True, in_static_universe=True, in_phantom_closed_sold=False, in_yesterday=False
    ) == "EXISTING_POSITION_REVIEW"
    assert classify_non_live(
        in_holdings=False, in_static_universe=False, in_phantom_closed_sold=True, in_yesterday=False
    ) == "PHANTOM_QUARANTINE"
    assert classify_non_live(
        in_holdings=False, in_static_universe=False, in_phantom_closed_sold=False, in_yesterday=False
    ) == "MODEL_PRIOR_ONLY"


def test_pipeline_on_static_payload_yields_zero_executables():
    # The committed payload is the static fallback; nothing may be executable.
    result = run_daily_synthesis()
    executables = result["candidate_executable_split"]["executable_paper_buys"]
    assert executables == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
