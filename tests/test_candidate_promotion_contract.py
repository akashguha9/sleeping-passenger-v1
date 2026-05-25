"""Tests for the candidate promotion contract (Sprint 3 — Part 5)."""
from __future__ import annotations

import json

import pytest

from scripts import candidate_promotion_contract as cpc


def _all_green():
    return {
        "id": "ALL_GREEN",
        "CQS_final": 0.78, "EQS": 0.72, "FCS": 0.82, "ERS": 0.28,
        "WHY_TODAY": 0.78, "LPQ": 0.86,
        "model_disagreement_risk": 0.20,
        "portfolio_truth_ok": True, "stale_quarantine": False,
        "any_DIABLO": False, "live_source_block": False,
        "advisory_only": True, "human_review_required": True,
        "execution_permission": "ADVISORY_ONLY",
        "broker_api_called": False, "ai_execution_count": 0,
    }


def test_all_green_promotes_to_advisory_candidate_human_review():
    r = cpc.evaluate_candidate(_all_green())
    assert r["candidate_state"] == "ADVISORY_CANDIDATE_HUMAN_REVIEW"
    assert r["candidate_may_be_actionable_for_human_review"] is True
    assert r["downgrade_reasons"] == []


def test_weak_why_today_blocks_promotion():
    c = _all_green()
    c["WHY_TODAY"] = 0.50
    r = cpc.evaluate_candidate(c)
    assert r["candidate_state"] != "ADVISORY_CANDIDATE_HUMAN_REVIEW"
    assert "WHY_TODAY_WEAK" in r["downgrade_reasons"]


def test_stale_lpq_blocks_promotion():
    c = _all_green()
    c["LPQ"] = 0.5
    r = cpc.evaluate_candidate(c)
    assert "LPQ_BELOW_THRESHOLD" in r["downgrade_reasons"]
    assert r["candidate_may_be_actionable_for_human_review"] is False


def test_diablo_blocks_and_routes_to_diablo_review():
    c = _all_green()
    c["any_DIABLO"] = True
    r = cpc.evaluate_candidate(c)
    assert r["candidate_state"] == "DIABLO_REVIEW"
    assert "DIABLO_MODEL_VETO" in r["downgrade_reasons"]


def test_portfolio_truth_failure_blocks_promotion():
    c = _all_green()
    c["portfolio_truth_ok"] = False
    r = cpc.evaluate_candidate(c)
    assert "PORTFOLIO_TRUTH_FAIL" in r["downgrade_reasons"]
    assert r["candidate_may_be_actionable_for_human_review"] is False


def test_no_output_grants_broker_execution():
    r = cpc.evaluate_candidate(_all_green())
    # Even when promoted, every safety stamp is locked.
    assert r["broker_api_called"] is False
    assert r["ai_execution_count"] == 0
    assert r["execution_permission"] == "ADVISORY_ONLY"
    assert r["human_review_required"] is True


def test_forbidden_execution_language_absent_from_summary():
    summary = cpc.build_summary()
    body = json.dumps(summary, default=str)
    for token in cpc.FORBIDDEN_EXECUTION_LANGUAGE:
        assert token not in body, f"forbidden token '{token}' leaked"


def test_promotion_state_is_in_canonical_state_set():
    summary = cpc.build_summary()
    for c in summary["candidates"]:
        assert c["candidate_state"] in cpc.CANDIDATE_STATES


def test_downgrade_reasons_visible_for_every_blocked_candidate():
    summary = cpc.build_summary()
    for c in summary["candidates"]:
        if not c["candidate_may_be_actionable_for_human_review"]:
            assert c["downgrade_reasons"], (
                f"candidate {c['id']} blocked without an explicit reason"
            )


def test_summary_writes(tmp_path):
    target = tmp_path / "cpc.json"
    summary = cpc.write_summary(target)
    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "candidate_vs_executable_score" in on_disk
    assert on_disk["advisory_only"] is True
    assert on_disk["broker_api_called"] is False
    assert on_disk["ai_execution_count"] == 0


def test_model_disagreement_high_routes_research():
    c = _all_green()
    c["model_disagreement_risk"] = 0.70
    r = cpc.evaluate_candidate(c)
    assert r["candidate_state"] == "RESEARCH_CANDIDATE"
    assert "MODEL_DISAGREEMENT_HIGH" in r["downgrade_reasons"]


def test_moderate_disagreement_below_hard_threshold_still_allowed():
    # Per spec the composite gate uses 0.65 as the hard threshold.  A risk
    # of 0.50 does NOT block promotion on its own — moderate routing lives
    # in the disagreement-handling module, not the promotion contract.
    c = _all_green()
    c["model_disagreement_risk"] = 0.50
    r = cpc.evaluate_candidate(c)
    assert r["candidate_state"] == "ADVISORY_CANDIDATE_HUMAN_REVIEW"
    assert r["candidate_may_be_actionable_for_human_review"] is True
