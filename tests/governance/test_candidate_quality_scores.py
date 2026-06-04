"""Sections 5/6/7 — FCS, ERS, MRS and candidate classification."""
from __future__ import annotations

from scripts.governance.daily_gate import (
    execution_readiness_score,
    fresh_candidate_score,
    manual_review_score,
)


def _board(gov_result):
    return {a.ticker: a for a in gov_result.candidate_quality_board}


def test_fcs_clamped_and_capped_when_source_failed():
    cand = {"evidence_strength": 1, "model_agreement": 1, "catalyst_freshness": 1,
            "theme_strength": 1, "risk_reward_clarity": 1, "data_freshness": 1}
    # high raw FCS, but source failed => capped at 0.69
    assert fresh_candidate_score(cand, why_today=0.9, source_status="FAILED") == 0.69
    # why_today < 0.70 => capped at 0.69 even when source healthy
    assert fresh_candidate_score(cand, why_today=0.5, source_status="HIGH") == 0.69


def test_ers_hard_caps():
    cand = {"data_freshness": 1, "invalidation_clarity": 1, "liquidity_confidence": 1,
            "risk_reward_clarity": 1, "reconciliation_cleanliness": 1}
    assert execution_readiness_score(cand, source_health=0.1, why_today=0.9, current_price_missing=False) <= 0.40
    assert execution_readiness_score(cand, source_health=0.9, why_today=0.9, current_price_missing=True) <= 0.50
    assert execution_readiness_score(cand, source_health=0.9, why_today=0.5, current_price_missing=False) <= 0.60


def test_mrs_normalized_range():
    raw, norm = manual_review_score({"evidence_strength": 1, "model_agreement": 1,
                                     "catalyst_freshness": 1, "theme_strength": 1,
                                     "risk_reward_clarity": 1})
    assert raw == 100.0
    assert norm == 100.0
    raw0, norm0 = manual_review_score({})
    assert 0.0 <= norm0 <= 100.0


def test_fixture_classifications(gov_result):
    board = _board(gov_result)
    assert board["RHM.DE"].classification == "WATCH"
    assert board["AIR.PA"].classification == "WATCH"
    assert board["SAP.DE"].classification == "WATCH"
    assert board["NVDA"].classification == "WAIT"
    assert board["NOC"].classification == "WAIT"
    assert board["TSLA"].classification in ("AVOID TODAY", "RISK BLOCK")
    assert board["CSCO"].classification == "AVOID TODAY"


def test_fixture_fcs_rough_ordering(gov_result):
    board = _board(gov_result)
    assert board["RHM.DE"].fcs >= board["AIR.PA"].fcs >= board["SAP.DE"].fcs
    assert board["SAP.DE"].fcs >= 0.55  # WATCH floor
    assert board["NVDA"].fcs < 0.55     # below WATCH
    # no candidate may be executable on an advisory-only board
    assert all(not a.executable for a in gov_result.candidate_quality_board)


def test_no_manual_add_when_source_failed(gov_result):
    assert gov_result.top_manual_add_consideration == []
    assert all(not a.manual_add_consideration for a in gov_result.candidate_quality_board)
