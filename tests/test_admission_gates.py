"""Objective 7 — hard state veto contract tests."""
from __future__ import annotations

from scripts.admission_gates import (
    ADVISORY_CANDIDATE,
    ALLOWED_ADVISORY_CLASSES,
    BLOCKED_BY_DIABLO,
    BLOCKED_BY_FRESHNESS,
    BLOCKED_BY_LEVERAGE_POLICY,
    BLOCKED_BY_MOLTBOOK_HISTORY,
    FORBIDDEN_ADVISORY_WORDING,
    evaluate_admission_gates,
)


def _clean_candidate(**overrides):
    base = dict(
        base_candidate=True,
        state="HURACAN",
        shock_override="NONE",
        chaos_risk=0.1,
        data_freshness=0.9,
        leverage_valid=True,
        portfolio_capacity_ok=True,
        moltbook_block=False,
        advisory_only=True,
        human_execution_required=True,
    )
    base.update(overrides)
    return base


def test_clean_candidate_is_admitted():
    res = evaluate_admission_gates(_clean_candidate())
    assert res.admitted is True
    assert res.advisory_class == ADVISORY_CANDIDATE


def test_diablo_state_blocks_advisory_candidate():
    res = evaluate_admission_gates(_clean_candidate(state="DIABLO"))
    assert res.admitted is False
    assert res.advisory_class == BLOCKED_BY_DIABLO


def test_freshness_block_prevents_candidate():
    res = evaluate_admission_gates(_clean_candidate(data_freshness=0.05))
    assert res.admitted is False
    assert res.advisory_class == BLOCKED_BY_FRESHNESS


def test_leverage_policy_block_prevents_candidate():
    res = evaluate_admission_gates(_clean_candidate(leverage_valid=False))
    assert res.admitted is False
    assert res.advisory_class == BLOCKED_BY_LEVERAGE_POLICY


def test_moltbook_block_prevents_candidate():
    res = evaluate_admission_gates(_clean_candidate(moltbook_block=True))
    assert res.admitted is False
    assert res.advisory_class == BLOCKED_BY_MOLTBOOK_HISTORY


def test_safety_gate_always_required():
    # Force a broken safety posture via candidate flags.
    res = evaluate_admission_gates(_clean_candidate(advisory_only=False))
    assert res.admitted is False
    assert res.gates["G_safety"] is False
    d = res.to_dict()
    assert d["execution_permission"] == "ADVISORY_ONLY"
    assert d["execution_gate"] == "LOCKED"
    assert d["broker_api_called"] is False
    assert d["ai_execution_count"] == 0


def test_forbidden_executable_language_absent():
    # Across every gate path, the advisory_class must be an allowed,
    # non-execution label.
    candidates = [
        _clean_candidate(),
        _clean_candidate(state="DIABLO"),
        _clean_candidate(data_freshness=0.0),
        _clean_candidate(leverage_valid=False),
        _clean_candidate(portfolio_capacity_ok=False),
        _clean_candidate(moltbook_block=True),
        _clean_candidate(shock_override="ACTIVE_BLOCK"),
        _clean_candidate(chaos_risk=0.99),
        _clean_candidate(base_candidate=False),
    ]
    for c in candidates:
        res = evaluate_admission_gates(c)
        assert res.advisory_class in ALLOWED_ADVISORY_CLASSES
        assert res.advisory_class.upper() not in FORBIDDEN_ADVISORY_WORDING
