"""Tests — the synthesis prompt context carries the L_today invariant + proofs."""
from __future__ import annotations

import pytest

from scripts.daily_synthesis_pipeline import (
    render_portfolio_truth_context,
    run_daily_synthesis,
)


@pytest.fixture(scope="module")
def context_and_result():
    result = run_daily_synthesis()
    ctx = render_portfolio_truth_context(result)
    return ctx, result


def test_prompt_includes_l_today_table(context_and_result):
    ctx, _ = context_and_result
    assert "L_TODAY INVARIANT" in ctx
    assert "L_today (live-discovered today):" in ctx
    assert "static_universe (RESEARCH_ONLY_STATIC):" in ctx
    assert "verified holdings H (EXISTING_POSITION_REVIEW):" in ctx


def test_prompt_forbids_static_or_invented_as_live(context_and_result):
    ctx, _ = context_and_result
    assert "Do NOT treat any candidate as live-discovered unless it appears in L_today" in ctx
    assert "MODEL_PRIOR_ONLY" in ctx
    assert "PHANTOM_QUARANTINE" in ctx


def test_prompt_requires_country_coverage_proof(context_and_result):
    ctx, result = context_and_result
    assert "TOP-30 GDP COUNTRY COVERAGE PROOF" in ctx
    assert "C_global=" in ctx
    assert "country_coverage" in result
    assert "global_discovery_status" in result["country_coverage"]


def test_prompt_includes_usa_bias_and_contamination(context_and_result):
    ctx, result = context_and_result
    assert "USA BIAS + FALLBACK CONTAMINATION METRICS" in ctx
    assert "B_US=" in ctx
    assert "R_static=" in ctx
    assert "usa_bias" in result and "contamination" in result


def test_prompt_includes_unmapped_and_price_validity(context_and_result):
    ctx, _ = context_and_result
    assert "PRICE VALIDITY + UNMAPPED EVENTS:" in ctx
    assert "unmapped_event_count:" in ctx


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
