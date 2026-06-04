"""Manual Decision Board — advisory-only classifier (Phase 2).

Proves the board fails closed, never authorizes action, never emits execution
language, keeps action authority revoked, and consumes chronology support.
"""

import ast
import json
from pathlib import Path

from scripts import manual_decision_board as mdb
from scripts.action_doctrine_status import is_ratified
from scripts.narrative_operator_wisdom_filter import (
    evaluate_narrative_operator_wisdom_filter,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_weak_evidence_unratified_is_risk_block() -> None:
    assert is_ratified() is False
    out = mdb.classify_candidate({"evidence_strength": 0.1})
    assert out["classification"] == "RISK_BLOCK"
    assert out["human_review_required"] is True
    assert out["authorizes_action"] is False


def test_strong_evidence_is_manual_review_candidate_but_human_required() -> None:
    out = mdb.classify_candidate({
        "evidence_strength": 0.9,
        "contradiction_score": 0.1,
        "chronology_support": True,
        "data_freshness": "fresh",
        "survival_risk": 0.1,
    })
    assert out["classification"] == "MANUAL_REVIEW_CANDIDATE"
    assert out["human_review_required"] is True
    assert out["authorizes_action"] is False
    assert out["evidence"]["invalidation_required"] is True


def test_output_never_contains_forbidden_terms() -> None:
    samples = [
        {"evidence_strength": 0.9, "chronology_support": True, "data_freshness": "fresh"},
        {"evidence_strength": 0.05},
        {"existing_holding": True, "survival_risk": 0.9},
        {"outcome_pending_review": True},
        {"contradiction_score": 0.8, "evidence_strength": 0.8},
    ]
    blob = json.dumps(mdb.build_decision_board(samples)).upper()
    for term in ("BUY", "SELL", "ENTER", "EXECUTE", "ORDER", "BROKER_ROUTE"):
        assert term not in blob


def test_classifications_are_within_allowed_set() -> None:
    samples = [
        {"evidence_strength": 0.9, "chronology_support": True, "data_freshness": "fresh"},
        {"evidence_strength": 0.6, "chronology_support": True},
        {"evidence_strength": 0.4},
        {"evidence_strength": 0.05},
        {"contradiction_score": 0.8, "evidence_strength": 0.8},
        {"survival_risk": 0.9},
        {"existing_holding": True},
        {"existing_holding": True, "survival_risk": 0.9},
        {"outcome_pending_review": True},
    ]
    for s in samples:
        assert mdb.classify_candidate(s)["classification"] in mdb.CLASSIFICATIONS


def test_action_authority_remains_revoked_after_board() -> None:
    mdb.build_decision_board([{"evidence_strength": 0.95, "chronology_support": True,
                               "data_freshness": "fresh"}])
    result = evaluate_narrative_operator_wisdom_filter(None)
    assert result["action_authority"] == "REVOKED"
    assert result["allowed_to_execute"] is False


def test_board_consumes_chronology_support() -> None:
    # Strong evidence WITHOUT chronology support downgrades to WATCH (not review).
    no_support = mdb.classify_candidate({
        "evidence_strength": 0.9, "contradiction_score": 0.1,
        "data_freshness": "fresh", "chronology_support": False,
    })
    assert no_support["classification"] == "WATCH"
    with_support = mdb.classify_candidate({
        "evidence_strength": 0.9, "contradiction_score": 0.1,
        "data_freshness": "fresh", "chronology_support": True,
    })
    assert with_support["classification"] == "MANUAL_REVIEW_CANDIDATE"


def test_board_degrades_gracefully_without_chronology() -> None:
    # No chronology fields at all -> still produces a valid advisory row.
    out = mdb.classify_candidate({"evidence_strength": 0.55})
    assert out["classification"] in mdb.CLASSIFICATIONS
    assert out["evidence"]["chronology_support"] is False


def test_empty_input_fails_closed_to_wait() -> None:
    out = mdb.classify_candidate(None)
    assert out["classification"] in ("WAIT", "RISK_BLOCK")
    assert out["authorizes_action"] is False


def test_no_execution_or_broker_imports() -> None:
    tree = ast.parse((SCRIPTS / "manual_decision_board.py").read_text(encoding="utf-8-sig"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    joined = " ".join(imported).lower()
    for bad in ("action_engine", "broker", "execution_governance", "paper_execution", "order"):
        assert bad not in joined
