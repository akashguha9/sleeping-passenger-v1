"""Tests — Real Evidence Sprint Phase 5: portfolio correlation guard.

Proves a candidate can be blocked by correlation / variance / exposure caps,
that missing covariance is conservative (UNKNOWN + blocked), that the guard
integrates with the live decision path, and that it NEVER unlocks execution.
"""
from __future__ import annotations

import pytest

from scripts import portfolio_correlation_guard as g
from scripts.live_decision_path import run_live_decision_path


# Two strongly co-moving return series (corr ~ +1).
_R_HIGH = [0.01, -0.02, 0.03, -0.01, 0.02, -0.015]
_R_HIGH_2 = [0.011, -0.019, 0.031, -0.009, 0.021, -0.014]
# An anti-/weakly-correlated series.
_R_LOW = [-0.01, 0.02, -0.03, 0.01, -0.02, 0.015]


# --- 1. high pairwise correlation blocks candidate ------------------------
def test_high_pairwise_correlation_blocks_candidate():
    res = g.evaluate_correlation_guard(
        candidate={"ticker": "AAA", "weight": 0.05, "sector": "Tech", "country": "US"},
        existing_positions=[{"ticker": "BBB", "weight": 0.05, "sector": "Energy", "country": "US"}],
        returns_by_ticker={"AAA": _R_HIGH, "BBB": _R_HIGH_2},
        rho_max=0.80,
    )
    assert res["max_pairwise_correlation"] > 0.80
    assert res["correlation_guard_ok"] is False
    assert res["correlation_status"] == g.STATUS_BLOCKED


# --- 2. missing covariance -> UNKNOWN and blocks/downgrades ---------------
def test_missing_covariance_returns_unknown_and_blocks_or_downgrades():
    res = g.evaluate_correlation_guard(
        candidate={"ticker": "AAA", "weight": 0.05, "sector": "Tech", "country": "US"},
        existing_positions=[{"ticker": "BBB", "weight": 0.05, "sector": "Tech", "country": "US"}],
        returns_by_ticker=None,  # no data
    )
    assert res["correlation_status"] == g.STATUS_UNKNOWN
    assert res["correlation_guard_ok"] is False
    assert res["advisory_class"] == g.WATCHLIST_CORRELATION_UNKNOWN
    assert "missing" in res["correlation_block_reason"].lower()


# --- 3. portfolio variance cap blocks candidate ---------------------------
def test_portfolio_variance_cap_blocks_candidate():
    cov = {
        ("AAA", "AAA"): 0.04, ("BBB", "BBB"): 0.04,
        ("AAA", "BBB"): 0.039, ("BBB", "AAA"): 0.039,
    }
    res = g.evaluate_correlation_guard(
        candidate={"ticker": "AAA", "weight": 0.5, "sector": "Tech", "country": "US"},
        existing_positions=[{"ticker": "BBB", "weight": 0.5, "sector": "Energy", "country": "DE"}],
        covariance_matrix=cov,
        rho_max=0.999,            # don't let correlation be the blocker
        sigma2_max=0.001,         # tiny variance cap -> must block
    )
    assert res["portfolio_variance_after"] is not None
    assert res["portfolio_variance_after"] > 0.001
    assert res["correlation_guard_ok"] is False


# --- 4. sector cap blocks candidate ---------------------------------------
def test_sector_cap_blocks_candidate():
    res = g.evaluate_correlation_guard(
        candidate={"ticker": "AAA", "weight": 0.20, "sector": "Tech", "country": "US"},
        existing_positions=[
            {"ticker": "BBB", "weight": 0.20, "sector": "Tech", "country": "US"},
            {"ticker": "CCC", "weight": 0.10, "sector": "Tech", "country": "US"},
        ],
        returns_by_ticker={"AAA": _R_LOW, "BBB": _R_HIGH, "CCC": _R_HIGH_2},
        sector_cap=0.30,
    )
    assert res["sector_exposure_after"] > 0.30
    assert res["correlation_guard_ok"] is False
    assert "sector" in res["correlation_block_reason"].lower()


# --- 5. single-name cap blocks candidate ----------------------------------
def test_single_name_cap_blocks_candidate():
    res = g.evaluate_correlation_guard(
        candidate={"ticker": "AAA", "weight": 0.50, "sector": "Tech", "country": "US"},
        existing_positions=[{"ticker": "BBB", "weight": 0.10, "sector": "Energy", "country": "US"}],
        returns_by_ticker={"AAA": _R_LOW, "BBB": _R_HIGH},
        single_name_cap=0.10,
    )
    assert res["single_name_exposure_after"] > 0.10
    assert res["correlation_guard_ok"] is False
    assert "single-name" in res["correlation_block_reason"].lower()


# --- 6. country cap still enforced ----------------------------------------
def test_country_cap_still_enforced():
    # Non-India country cap is 0.25.  Candidate + existing US > 0.25.
    res = g.evaluate_correlation_guard(
        candidate={"ticker": "AAA", "weight": 0.05, "sector": "Tech", "country": "US"},
        existing_positions=[{"ticker": "BBB", "weight": 0.30, "sector": "Energy", "country": "US"}],
        returns_by_ticker={"AAA": _R_LOW, "BBB": _R_HIGH},
        single_name_cap=0.99, sector_cap=0.99, rho_max=0.999,
    )
    assert res["country_exposure_after"] > res["country_cap"]
    assert res["correlation_guard_ok"] is False
    assert "country" in res["correlation_block_reason"].lower()


# --- 7. integrates with live decision path --------------------------------
def test_correlation_guard_integrates_with_live_decision_path():
    out = run_live_decision_path(
        signal_id="sig-corr",
        axes={"EMS": 0.7, "EQS": 0.6, "DS": 0.6, "LS": 0.6, "EFS": 0.6, "APS": 0.6},
        ticker="AAA", country="US", sector="Tech",
        api_health_status="OK", rows_added=5, canonical_age_hours=1.0,
        capital=100_000.0, cash_available=100_000.0,
        entry_price=100.0, hard_stop_price=95.0,
        candidate_weight=0.05,
        portfolio_positions=[{"ticker": "BBB", "weight": 0.05, "sector": "Tech", "country": "US"}],
        returns_by_ticker={"AAA": _R_HIGH, "BBB": _R_HIGH_2},  # highly correlated
        db_path=None,
    )
    cg = out["capacity_result"]["correlation_guard"]
    assert cg["correlation_status"] == g.STATUS_BLOCKED
    assert out["capacity_ok"] is False
    # Highly-correlated add must not be promoted to an actionable candidate.
    assert out["candidate_may_be_actionable_for_human_review"] is False


def test_live_path_without_portfolio_context_is_inert():
    out = run_live_decision_path(
        signal_id="sig-noctx",
        axes={"EMS": 0.7, "EQS": 0.6, "DS": 0.6, "LS": 0.6, "EFS": 0.6, "APS": 0.6},
        ticker="AAA", country="US", sector="Tech",
        api_health_status="OK", rows_added=5, canonical_age_hours=1.0,
        capital=100_000.0, cash_available=100_000.0,
        entry_price=100.0, hard_stop_price=95.0,
        db_path=None,
    )
    cg = out["capacity_result"]["correlation_guard"]
    assert cg["correlation_status"] == g.STATUS_NOT_EVALUATED
    assert cg["correlation_guard_ok"] is True


# --- 8. guard does not unlock execution -----------------------------------
def test_correlation_guard_does_not_unlock_execution():
    res = g.evaluate_correlation_guard(
        candidate={"ticker": "AAA", "weight": 0.02, "sector": "Tech", "country": "US"},
        existing_positions=[],
    )
    assert res["execution_gate"] == "LOCKED"
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0
    assert res["executes_trade"] is False
    assert res["human_execution_required"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
