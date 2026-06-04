"""Manual Decision Board — ADVISORY-ONLY human-review classifier.

Produces HUMAN-REVIEW classifications from existing evidence. It exists to help
a human decide what to look at; it CANNOT authorize action.

It emits ONLY these classifications:
    MANUAL_REVIEW_CANDIDATE, WATCH, WAIT, AVOID, RISK_BLOCK,
    EXISTING_HOLDING_REVIEW, REDUCE_REVIEW, OUTCOME_REVIEW_NEEDED

It NEVER emits: BUY, SELL, ENTER, EXECUTE, ORDER, BROKER_ROUTE.

HARD BOUNDARIES (test-enforced):
    * Imports no action_engine / broker / order / execution code.
    * Every output carries human_review_required=True and
      authorizes_action=False.
    * Doctrine stays UNRATIFIED and action authority stays REVOKED — this
      board does not and cannot change them.
    * Fails CLOSED to WAIT / RISK_BLOCK on weak or insufficient evidence.

The board can exist and run while execution authority is revoked: it is a
reading aid for a human, not a decision authority.
"""

from __future__ import annotations

from typing import Any

try:
    from scripts.action_doctrine_status import is_ratified
except ModuleNotFoundError:  # pragma: no cover - script-path fallback
    from action_doctrine_status import is_ratified

# Advisory doctrine states (NOT execution states).
ADVISORY_DECISION_BOARD_AVAILABLE = "ADVISORY_DECISION_BOARD_AVAILABLE"
OPERATOR_CONTRACT_UNRATIFIED = "OPERATOR_CONTRACT_UNRATIFIED"
OPERATOR_CONTRACT_RATIFIED = "OPERATOR_CONTRACT_RATIFIED"
EXECUTION_AUTHORITY_REVOKED = "EXECUTION_AUTHORITY_REVOKED"

CLASSIFICATIONS = (
    "MANUAL_REVIEW_CANDIDATE",
    "WATCH",
    "WAIT",
    "AVOID",
    "RISK_BLOCK",
    "EXISTING_HOLDING_REVIEW",
    "REDUCE_REVIEW",
    "OUTCOME_REVIEW_NEEDED",
)

# Note: the advisory-only invariant (this module emits no
# BUY/SELL/ENTER/EXECUTE/ORDER/BROKER_ROUTE) is enforced by
# tests/test_manual_decision_board.py, not by an in-module denylist.


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classify_candidate(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Classify one candidate for HUMAN REVIEW. Advisory-only; fail-closed.

    Recognised evidence fields (all optional; missing => conservative):
        evidence_strength [0..1], contradiction_score [0..1],
        chronology_support (bool|0..1), data_freshness ('fresh'|'stale'|...),
        survival_risk [0..1], existing_holding (bool),
        outcome_pending_review (bool), moltbook_feedback_value [-1..1].
    """
    ev = evidence if isinstance(evidence, dict) else {}

    evidence_strength = _f(ev.get("evidence_strength"))
    contradiction_score = _f(ev.get("contradiction_score"))
    survival_risk = _f(ev.get("survival_risk"))
    chronology_support_raw = ev.get("chronology_support")
    chronology_support = bool(
        chronology_support_raw if not isinstance(chronology_support_raw, (int, float))
        else chronology_support_raw >= 0.5
    )
    data_freshness = str(ev.get("data_freshness") or "unknown").lower()
    existing_holding = bool(ev.get("existing_holding"))
    outcome_pending_review = bool(ev.get("outcome_pending_review"))
    moltbook_feedback_value = _f(ev.get("moltbook_feedback_value"))

    ratified = bool(is_ratified())  # always False today; never self-ratified here
    operator_contract_state = (
        OPERATOR_CONTRACT_RATIFIED if ratified else OPERATOR_CONTRACT_UNRATIFIED
    )

    # --- classification (fail-closed precedence) ---------------------------
    classification = "WAIT"
    rationale: list[str] = []

    if outcome_pending_review:
        classification = "OUTCOME_REVIEW_NEEDED"
        rationale.append("A resolved outcome is awaiting human reconciliation.")
    elif existing_holding:
        if survival_risk >= 0.7 or contradiction_score >= 0.6:
            classification = "REDUCE_REVIEW"
            rationale.append("Existing holding shows elevated survival risk / contradiction; review for reduction.")
        else:
            classification = "EXISTING_HOLDING_REVIEW"
            rationale.append("Existing holding; routine human review.")
    elif survival_risk >= 0.8:
        classification = "RISK_BLOCK"
        rationale.append("Survival risk is high; blocked from review until risk clears.")
    elif contradiction_score >= 0.6:
        classification = "AVOID"
        rationale.append("Contradiction score is high; evidence is actively conflicted.")
    elif evidence_strength < 0.3:
        # Weak evidence while doctrine is unratified -> hard fail closed.
        classification = "RISK_BLOCK" if not ratified else "WAIT"
        rationale.append("Evidence is weak; failing closed.")
    elif evidence_strength < 0.5 or data_freshness == "stale":
        classification = "WAIT"
        rationale.append("Evidence is thin or data is stale; wait for confirmation.")
    elif evidence_strength < 0.7 or not chronology_support or contradiction_score >= 0.4:
        classification = "WATCH"
        rationale.append("Moderate evidence; keep watching.")
    else:
        classification = "MANUAL_REVIEW_CANDIDATE"
        rationale.append("Strong, chronology-supported, low-contradiction evidence; surface for HUMAN review only.")

    invalidation_required = classification in ("MANUAL_REVIEW_CANDIDATE", "EXISTING_HOLDING_REVIEW", "REDUCE_REVIEW")

    return {
        "classification": classification,
        # Hard advisory invariants — present on EVERY output.
        "human_review_required": True,
        "authorizes_action": False,
        "advisory_only": True,
        "doctrine_state": [
            ADVISORY_DECISION_BOARD_AVAILABLE,
            operator_contract_state,
            EXECUTION_AUTHORITY_REVOKED,
        ],
        "evidence": {
            "evidence_strength": round(evidence_strength, 4),
            "contradiction_score": round(contradiction_score, 4),
            "chronology_support": chronology_support,
            "data_freshness": data_freshness,
            "governance_state": EXECUTION_AUTHORITY_REVOKED,
            "operator_contract_state": operator_contract_state,
            "invalidation_required": invalidation_required,
            "moltbook_feedback_value": round(moltbook_feedback_value, 4),
            "survival_risk": round(survival_risk, 4),
        },
        "rationale": rationale,
        "note": (
            "Advisory human-review classification only. This board authorizes "
            "no action and issues no broker routing or execution instruction."
        ),
    }


def build_decision_board(candidates: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Classify a list of candidate evidence dicts into an advisory board."""
    rows = [classify_candidate(c) for c in (candidates or [])]
    by_class: dict[str, int] = {}
    for r in rows:
        by_class[r["classification"]] = by_class.get(r["classification"], 0) + 1
    return {
        "board_state": ADVISORY_DECISION_BOARD_AVAILABLE,
        "execution_authority": EXECUTION_AUTHORITY_REVOKED,
        "operator_contract": (
            OPERATOR_CONTRACT_RATIFIED if is_ratified() else OPERATOR_CONTRACT_UNRATIFIED
        ),
        "human_review_required": True,
        "authorizes_action": False,
        "rows": rows,
        "counts_by_classification": by_class,
        "note": "Advisory-only manual decision board. No execution capability.",
    }
