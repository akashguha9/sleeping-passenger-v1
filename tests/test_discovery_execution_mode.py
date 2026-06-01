"""Unit tests for the three-lane discovery/execution/survival mode model.

Covers the pure functions in scripts/discovery_execution_mode.py:
price coverage, BUY_SCORE formula, why-today tiers, candidate classification
tiers, mode_state gating, leverage conflict, phantom violations, exit debt.
"""
from __future__ import annotations

import math

import pytest

from scripts.discovery_execution_config import load_discovery_execution_config
from scripts.discovery_execution_mode import (
    classify_candidate,
    clamp01,
    compute_buy_score,
    compute_mode_state,
    exit_debt,
    leverage_truth,
    phantom_open_violations,
    price_coverage,
    resolve_open_positions,
    valid_price_flag,
    why_today_tier,
)

CFG = load_discovery_execution_config()


# --------------------------------------------------------------------------- #
# BUY_SCORE formula
# --------------------------------------------------------------------------- #
def test_buy_score_weights_sum_to_one():
    weights = CFG["buy_score_weights"]
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)


def test_buy_score_formula_exact():
    components = {
        "why_today_score": 0.8,
        "price_confirmation": 0.6,
        "source_quality": 0.5,
        "cross_model_agreement": 0.4,
        "portfolio_fit": 0.2,
    }
    expected = (
        0.30 * 0.8 + 0.25 * 0.6 + 0.20 * 0.5 + 0.15 * 0.4 + 0.10 * 0.2
    )
    assert compute_buy_score(components) == pytest.approx(round(expected, 4))


def test_buy_score_clamps_components():
    # Out-of-range components are clamped to [0,1] before weighting.
    over = compute_buy_score(
        {
            "why_today_score": 5.0,
            "price_confirmation": 2.0,
            "source_quality": 1.0,
            "cross_model_agreement": 1.0,
            "portfolio_fit": 1.0,
        }
    )
    assert over == pytest.approx(1.0)
    under = compute_buy_score(
        {
            "why_today_score": -3.0,
            "price_confirmation": -1.0,
            "source_quality": 0.0,
            "cross_model_agreement": 0.0,
            "portfolio_fit": 0.0,
        }
    )
    assert under == pytest.approx(0.0)


def test_clamp01():
    assert clamp01(-1) == 0.0
    assert clamp01(2) == 1.0
    assert clamp01(0.5) == 0.5
    assert clamp01("nan-ish") == 0.0


# --------------------------------------------------------------------------- #
# WHY_TODAY tiers (boundary exactness)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "score,tier",
    [
        (0.0, "NOISE_OR_STALE"),
        (0.39, "NOISE_OR_STALE"),
        (0.40, "WEAK_DISCOVERY"),
        (0.54, "WEAK_DISCOVERY"),
        (0.55, "VALID_DISCOVERY"),
        (0.64, "VALID_DISCOVERY"),
        (0.65, "STRONG_WATCHLIST"),
        (0.72, "STRONG_WATCHLIST"),
        (0.73, "PROBE_CANDIDATE"),
        (0.79, "PROBE_CANDIDATE"),
        (0.80, "HIGH_CONVICTION"),
        (1.0, "HIGH_CONVICTION"),
    ],
)
def test_why_today_tiers(score, tier):
    assert why_today_tier(score) == tier


# --------------------------------------------------------------------------- #
# Candidate classification tiers (BUY_SCORE band + execution gate + proof)
# --------------------------------------------------------------------------- #
def _full_proof():
    return {
        "price_confirmation": 1.0,
        "volume_confirmation": 1.0,
        "source_quality": 1.0,
        "portfolio_fit": 1.0,
    }


@pytest.mark.parametrize(
    "score,exec_allowed,expected",
    [
        (0.39, False, "NOISE_OR_STALE"),
        (0.40, False, "WEAK_DISCOVERY"),
        (0.55, False, "DISCOVERED"),
        (0.65, False, "WATCHLIST"),
        (0.73, False, "CONDITIONAL_PROBE_CANDIDATE_EXECUTION_BLOCKED"),
        (0.73, True, "PROBE_BUY"),
        (0.80, False, "HIGH_CONVICTION_WATCHLIST_EXECUTION_BLOCKED"),
        (0.80, True, "BUY"),
    ],
)
def test_classify_candidate_bands(score, exec_allowed, expected):
    verdict = classify_candidate(
        score, execution_allowed=exec_allowed, proof=_full_proof()
    )
    assert verdict["classification"] == expected


def test_buy_and_probe_require_execution_allowed():
    # Even a max score with full proof cannot be BUY/PROBE_BUY when blocked.
    for score in (0.75, 0.95):
        v = classify_candidate(score, execution_allowed=False, proof=_full_proof())
        assert v["classification"] not in ("BUY", "PROBE_BUY")
        assert v["is_executable_classification"] is False


def test_phantom_candidate_is_quarantined():
    v = classify_candidate(0.95, execution_allowed=True, proof=_full_proof(), phantom=True)
    assert v["classification"] == "PHANTOM_QUARANTINE"


# --------------------------------------------------------------------------- #
# Price validity + coverage
# --------------------------------------------------------------------------- #
def test_valid_price_rejects_static_and_missing():
    assert valid_price_flag({"price": 10.0, "source": "LIVE_PROVIDER"}) is True
    assert valid_price_flag({"price": None, "source": "LIVE_PROVIDER"}) is False
    assert valid_price_flag({"price": 10.0, "provider": "STATIC_UNIVERSE_FALLBACK"}) is False
    assert valid_price_flag({"price": 10.0, "source": "UNVERIFIED"}) is False
    assert valid_price_flag({"price": 10.0, "source": "X", "valid_price": False}) is False


def test_valid_price_age_gate():
    assert valid_price_flag({"price": 1.0, "source": "X", "age_minutes": 30}, max_age_minutes=60) is True
    assert valid_price_flag({"price": 1.0, "source": "X", "age_minutes": 90}, max_age_minutes=60) is False


def test_price_coverage_ratio():
    rows = [
        {"ticker": "A", "price": 1.0, "source": "LIVE"},
        {"ticker": "B", "price": None, "source": "LIVE"},
        {"ticker": "C", "price": 2.0, "provider": "STATIC_FALLBACK"},
        {"ticker": "D", "price": 3.0, "source": "LIVE"},
    ]
    assert price_coverage(rows) == pytest.approx(0.5)
    assert price_coverage([]) == 0.0  # max(1, 0) guard


# --------------------------------------------------------------------------- #
# mode_state gating
# --------------------------------------------------------------------------- #
def _clean_kwargs(**over):
    base = dict(
        holdings_price_coverage=1.0,
        candidate_price_coverage=1.0,
        portfolio_truth_clean=True,
        phantom_clean=True,
        leverage_clean=True,
        exit_debt_clean=True,
        source_health_ok=True,
        advisory_safety_lock_intact=True,
    )
    base.update(over)
    return base


def test_mode_state_all_clean_allows_execution():
    m = compute_mode_state(**_clean_kwargs())
    assert m["execution_allowed"] is True
    assert m["new_risk_allowed"] is True
    assert m["discovery_allowed"] is True
    assert m["survival_attention_required"] is False
    assert m["blockers"] == []


@pytest.mark.parametrize(
    "field,blocker",
    [
        ("portfolio_truth_clean", "PORTFOLIO_TRUTH_MISMATCH"),
        ("phantom_clean", "PHANTOM_OPEN_VIOLATION"),
        ("leverage_clean", "LEVERAGE_TRUTH_CONFLICT"),
        ("exit_debt_clean", "EXIT_DEBT_UNRESOLVED"),
        ("source_health_ok", "SOURCE_HEALTH_DEGRADED"),
    ],
)
def test_mode_state_each_gate_blocks_execution_not_discovery(field, blocker):
    m = compute_mode_state(**_clean_kwargs(**{field: False}))
    assert m["execution_allowed"] is False
    assert m["new_risk_allowed"] is False
    assert m["discovery_allowed"] is True  # discovery never suppressed
    assert blocker in m["blockers"]


def test_low_price_coverage_blocks_execution_not_discovery():
    m = compute_mode_state(
        **_clean_kwargs(holdings_price_coverage=0.0, candidate_price_coverage=0.0)
    )
    assert m["execution_allowed"] is False
    assert m["discovery_allowed"] is True
    assert "H_PRICE_COVERAGE_BELOW_0_80" in m["blockers"]
    assert "C_PRICE_COVERAGE_BELOW_0_80" in m["blockers"]
    assert m["survival_attention_required"] is True


def test_broken_safety_lock_blocks_everything():
    m = compute_mode_state(**_clean_kwargs(advisory_safety_lock_intact=False))
    assert m["execution_allowed"] is False
    assert m["discovery_allowed"] is False  # safety lock is the one gate on discovery
    assert "ADVISORY_SAFETY_LOCK_BROKEN" in m["blockers"]


# --------------------------------------------------------------------------- #
# Leverage truth conflict
# --------------------------------------------------------------------------- #
def test_leverage_clean_when_within_policy_no_divergence():
    holdings = [
        {"ticker": "NASDAQ:MSFT", "country": "United States", "leverage": 1},
        {"ticker": "NSE:HDFCBANK", "country": "India", "leverage": 4},
    ]
    res = leverage_truth(holdings)
    assert res["leverage_clean"] is True
    assert res["conflicts"] == []


def test_leverage_truth_conflict_surfaced_not_resolved():
    holdings = [
        {"ticker": "NSE:HDFCBANK", "country": "India", "leverage": 1, "leverage_policy": 4},
    ]
    res = leverage_truth(holdings)
    assert res["leverage_clean"] is False
    assert res["has_leverage_truth_conflict"] is True
    conflict = res["conflicts"][0]
    assert conflict["status"] == "LEVERAGE_TRUTH_CONFLICT"
    # Never silently picks a side — both values are preserved.
    assert conflict["leverage_sheet"] == 1
    assert conflict["leverage_policy"] == 4
    assert conflict["resolution"] == "UNRESOLVED_HUMAN_REVIEW_REQUIRED"


def test_leverage_over_max_blocks_clean():
    holdings = [{"ticker": "NYSE:XOM", "country": "United States", "leverage": 4}]
    res = leverage_truth(holdings)
    assert res["leverage_clean"] is False
    assert res["over_max"][0]["status"] == "LEVERAGE_POLICY_VIOLATION"


# --------------------------------------------------------------------------- #
# Phantom violations
# --------------------------------------------------------------------------- #
def test_phantom_open_violations_detected():
    rows = [
        {"ticker": "UNG", "state": "OPEN"},
        {"ticker": "GLD", "state": "OPEN"},
        {"ticker": "MSFT", "state": "OPEN"},  # not phantom
    ]
    res = phantom_open_violations(rows)
    assert res["phantom_clean"] is False
    assert set(res["phantom_open_violations"]) == {"UNG", "GLD"}
    assert "MSFT" not in res["phantom_open_violations"]


def test_phantom_closed_state_not_a_violation():
    rows = [{"ticker": "GLD", "state": "CLOSED"}]
    res = phantom_open_violations(rows)
    assert res["phantom_clean"] is True


# --------------------------------------------------------------------------- #
# Open-position reconciliation
# --------------------------------------------------------------------------- #
def test_resolve_open_positions_clean_match():
    sheet = [{"ticker": "MSFT", "state": "OPEN"}, {"ticker": "RTX", "state": "OPEN"}]
    res = resolve_open_positions(sheet, ["MSFT", "RTX"])
    assert res["reconciliation_clean"] is True
    assert res["symmetric_difference"] == []


def test_resolve_open_positions_symmetric_difference():
    sheet = [{"ticker": "MSFT", "state": "OPEN"}, {"ticker": "AAPL", "state": "OPEN"}]
    res = resolve_open_positions(sheet, ["MSFT", "RTX"])
    assert res["reconciliation_clean"] is False
    assert set(res["symmetric_difference"]) == {"AAPL", "RTX"}


def test_resolve_open_positions_excludes_closed_rows():
    sheet = [{"ticker": "MSFT", "state": "OPEN"}, {"ticker": "ZIM", "state": "STOP_CLOSED"}]
    res = resolve_open_positions(sheet, ["MSFT"])
    assert "ZIM" in res["closed_rows_excluded"]
    assert res["reconciliation_clean"] is True


# --------------------------------------------------------------------------- #
# Exit debt
# --------------------------------------------------------------------------- #
def test_exit_debt_closed_stop_not_counted():
    rows = [
        {"ticker": "CVX", "trade_state": "STOP_HIT", "mvp_recon_status": "STOP_CLOSED"},
        {"ticker": "XOM", "trade_state": "STOP_HIT", "mvp_recon_status": "CLOSED_RECONCILED"},
    ]
    res = exit_debt(rows)
    assert res["exit_debt_count"] == 0
    assert res["exit_debt_clean"] is True


def test_exit_debt_unresolved_open_stop_counted():
    rows = [{"ticker": "ZIM", "trade_state": "STOP_HIT", "mvp_recon_status": "OPEN_RECONCILED"}]
    res = exit_debt(rows)
    assert res["exit_debt_count"] == 1
    assert res["exit_debt_clean"] is False


def test_exit_debt_score_normalized():
    rows = [
        {"ticker": f"T{i}", "trade_state": "STOP_HIT", "mvp_recon_status": "OPEN"}
        for i in range(10)
    ]
    res = exit_debt(rows)
    assert res["exit_debt_score"] == 1.0  # min(1, 10/5)
