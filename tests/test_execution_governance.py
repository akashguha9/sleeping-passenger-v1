from scripts.execution_governance import (
    classify_override,
    evaluate_automation_readiness,
    evaluate_competence_validation,
    evaluate_first_principles_gate,
    evaluate_structured_learning_gate,
)


def test_fpeg_passes_with_explicit_first_principles_reasoning() -> None:
    result = evaluate_first_principles_gate(
        action_row={
            "ticker": "RTX",
            "action": "REVIEW_FOR_ENTRY",
            "policy_state": "REVIEW_READY",
            "active_blockers": [],
            "why_this_move": "validation improved and asymmetry remains open",
            "trigger": "clean candidate is fully gate-cleared",
            "invalidation": "entry thesis fails if validation degrades",
            "regime": "review_ready",
            "why_now": "blockers cleared this run",
        }
    )

    assert result["fpeg_state"] == "pass"
    assert result["fpeg_score"] == 1.0
    assert result["human_execution_required"] is True
    assert result["suggestion_only"] is True


def test_fpeg_blocks_when_reasoning_is_sparse() -> None:
    result = evaluate_first_principles_gate(
        action_row={
            "ticker": "RTX",
            "action": "REVIEW_FOR_ENTRY",
            "reasons": ["looks good"],
        }
    )

    assert result["fpeg_state"] == "insufficient_reasoning"
    assert "invalidation" in result["missing_requirements"]


def test_cvg_and_slg_are_conservative_without_profile() -> None:
    cvg = evaluate_competence_validation(None)
    slg = evaluate_structured_learning_gate(None)

    assert cvg["configured"] is False
    assert cvg["cvg_state"] == "insufficient_profile"
    assert slg["configured"] is False
    assert slg["slg_state"] == "insufficient_profile"


def test_classify_override_taxonomy_is_explicit() -> None:
    assert classify_override("REVIEW_FOR_ENTRY", "MONITOR")["override_classification"] == "defer_execution"
    assert classify_override("MONITOR", "EXIT_NOW")["override_classification"] == "tighten_risk"
    assert classify_override("MONITOR", "REVIEW_FOR_ENTRY")["override_classification"] == "escalate_risk"


def test_automation_readiness_stays_suggestion_only() -> None:
    result = evaluate_automation_readiness(
        gate_summary={"fpeg_pass_rate": 1.0},
        override_summary={"total_override_count": 50, "average_interaction_quality": 0.95},
        reconciliation_summary={"total_closed_paper_trades": 100},
    )

    assert result["current_stage"] == "suggestion_only"
    assert result["eligible_for_limited_delegation"] is False
    assert "manual_approval_required_by_design" in result["blocking_reasons"]
