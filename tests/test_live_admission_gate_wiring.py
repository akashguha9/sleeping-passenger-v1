"""Phase 2 — admission gates are enforced inside the live promotion flow.

Proves ``candidate_promotion_contract.evaluate_candidate`` (the live promotion
brain) now calls the central ``evaluate_admission_gates`` contract and attaches
a ``gate_result`` block, so a DIABLO / stale / leverage-invalid / capacity /
moltbook-blocked candidate is forced to its BLOCKED_BY_* class — with no
execution wording anywhere.
"""
from __future__ import annotations

import json

from scripts.admission_gates import (
    ADVISORY_CANDIDATE,
    BLOCKED_BY_DIABLO,
    BLOCKED_BY_FRESHNESS,
    BLOCKED_BY_LEVERAGE_POLICY,
    BLOCKED_BY_MOLTBOOK_HISTORY,
    BLOCKED_BY_PORTFOLIO_CAPACITY,
    FORBIDDEN_ADVISORY_WORDING,
)
from scripts.candidate_promotion_contract import evaluate_candidate
from scripts.live_decision_path import run_live_decision_path


def _full_pass_candidate(**overrides):
    """A candidate that clears every promotion + admission gate."""
    base = dict(
        id="C1",
        CQS_final=0.9,
        EQS=0.8,
        FCS=0.8,
        ERS=0.1,
        WHY_TODAY=0.8,
        LPQ=0.95,
        portfolio_truth_ok=True,
        stale_quarantine=False,
        any_DIABLO=False,
        model_disagreement_risk=0.1,
        live_source_block=False,
        advisory_only=True,
        human_review_required=True,
        execution_permission="ADVISORY_ONLY",
        broker_api_called=False,
        ai_execution_count=0,
        # admission-gate-specific inputs
        state="HURACAN",
        chaos_risk=0.1,
        data_freshness=0.9,
        leverage_valid=True,
        portfolio_capacity_ok=True,
        moltbook_block=False,
    )
    base.update(overrides)
    return base


def test_all_gates_pass_allows_advisory_candidate_for_human_review():
    res = evaluate_candidate(_full_pass_candidate())
    assert res["gate_result"]["gate_passed"] is True
    assert res["gate_result"]["final_advisory_class"] == ADVISORY_CANDIDATE


def test_diablo_candidate_is_blocked_in_live_decision_path():
    res = evaluate_candidate(_full_pass_candidate(any_DIABLO=True))
    assert res["gate_result"]["gate_passed"] is False
    assert res["gate_result"]["final_advisory_class"] == BLOCKED_BY_DIABLO


def test_stale_or_zero_fresh_rows_blocks_candidate():
    res = evaluate_candidate(_full_pass_candidate(stale_quarantine=True))
    assert res["gate_result"]["gate_passed"] is False
    assert res["gate_result"]["final_advisory_class"] == BLOCKED_BY_FRESHNESS


def test_leverage_policy_violation_blocks_candidate():
    res = evaluate_candidate(_full_pass_candidate(leverage_valid=False))
    assert res["gate_result"]["gate_passed"] is False
    assert res["gate_result"]["final_advisory_class"] == BLOCKED_BY_LEVERAGE_POLICY


def test_moltbook_block_blocks_candidate():
    res = evaluate_candidate(_full_pass_candidate(moltbook_block=True))
    assert res["gate_result"]["gate_passed"] is False
    assert res["gate_result"]["final_advisory_class"] == BLOCKED_BY_MOLTBOOK_HISTORY


def test_capacity_block_blocks_candidate():
    res = evaluate_candidate(_full_pass_candidate(portfolio_capacity_ok=False))
    assert res["gate_result"]["gate_passed"] is False
    assert res["gate_result"]["final_advisory_class"] == BLOCKED_BY_PORTFOLIO_CAPACITY


def test_blocked_candidate_still_has_advisory_only_stamps():
    res = evaluate_candidate(_full_pass_candidate(any_DIABLO=True))
    stamps = res["gate_result"]["safety_stamps"]
    assert stamps["advisory_only"] is True
    assert stamps["execution_gate"] == "LOCKED"
    assert stamps["broker_api_called"] is False
    assert stamps["ai_execution_count"] == 0
    # The top-level promotion contract invariants are also untouched.
    assert res["execution_permission"] == "ADVISORY_ONLY"
    assert res["broker_api_called"] is False


def test_forbidden_execution_language_absent_from_live_advisory_output():
    # promotion contract output
    res = evaluate_candidate(_full_pass_candidate())
    blob = json.dumps(res).upper()
    for word in FORBIDDEN_ADVISORY_WORDING:
        assert word not in blob
    # orchestrator output
    out = run_live_decision_path(
        signal_id="S", axes={"EMS": 0.6, "EQS": 0.6, "DS": 0.6, "LS": 0.6,
                             "EFS": 0.6, "APS": 0.6},
        ticker="X", country="India", rows_added=3, canonical_age_hours=1.0,
        capital=1_000_000.0, cash_available=500_000.0,
        entry_price=100.0, hard_stop_price=95.0, db_path=None,
    )
    blob2 = json.dumps(out).upper()
    for word in FORBIDDEN_ADVISORY_WORDING:
        assert word not in blob2


def test_existing_promotion_keys_preserved():
    """Wiring is additive — the original contract keys must still exist."""
    res = evaluate_candidate(_full_pass_candidate())
    for key in (
        "id", "candidate_state", "candidate_may_be_actionable_for_human_review",
        "gates", "downgrade_reasons", "formula_components",
        "advisory_only", "human_review_required", "execution_permission",
        "broker_api_called", "ai_execution_count",
    ):
        assert key in res
