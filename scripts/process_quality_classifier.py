"""
Process-quality classifier — separate skill from luck.

Purpose
-------
A reconciled trade has both an *outcome* (WIN/LOSS/BREAKEVEN) and a
*process quality* (was the operator's decision and journal disciplined?).
The two are independent — a good process can produce a bad outcome, and
vice versa. The classifier returns the joint state so the operator can
ask "am I getting better at deciding, or just lucky?".

The classifier is **pure**: it never writes the DB, never calls broker
APIs, never grants execution permission, never normalizes input by
calling an LLM.

States
------
- ``good_process_good_outcome``   — disciplined journal + WIN
- ``good_process_bad_outcome``    — disciplined journal + LOSS
- ``bad_process_good_outcome``    — process_error OR weak journal + WIN
- ``bad_process_bad_outcome``     — process_error OR weak journal + LOSS
- ``incomplete_record``           — required journal fields are missing
- ``unknown``                     — outcome unknown / unclassifiable

Formulas
--------

    Process_Quality_Score   = (journal_completeness + (no_process_error)) / 2
    Skill_Evidence_Score    = good_process_count / total_reconciled_trades
    Luck_Risk_Score         = bad_process_good_outcome / winning_trades
    Process_Drift           = repeated_mistakes_this_window / total_this_window

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False
"""
from __future__ import annotations

from typing import Any, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

# Process-quality states.
GOOD_PROCESS_GOOD_OUTCOME = "good_process_good_outcome"
GOOD_PROCESS_BAD_OUTCOME = "good_process_bad_outcome"
BAD_PROCESS_GOOD_OUTCOME = "bad_process_good_outcome"
BAD_PROCESS_BAD_OUTCOME = "bad_process_bad_outcome"
INCOMPLETE_RECORD = "incomplete_record"
STATE_UNKNOWN = "unknown"

ALL_STATES: tuple[str, ...] = (
    GOOD_PROCESS_GOOD_OUTCOME,
    GOOD_PROCESS_BAD_OUTCOME,
    BAD_PROCESS_GOOD_OUTCOME,
    BAD_PROCESS_BAD_OUTCOME,
    INCOMPLETE_RECORD,
    STATE_UNKNOWN,
)

# Required fields for a record to be classifiable at all.  If any of these
# are missing, the record is ``incomplete_record`` regardless of outcome.
REQUIRED_JOURNAL_FIELDS: tuple[str, ...] = (
    "thesis",
    "invalidation_level",
    "exit_plan",
    "risk_reason",
)

# Journal-completeness threshold below which "good process" is impossible.
# Aligned with the journal-quality helper's 0.70 learning-ready threshold.
GOOD_PROCESS_COMPLETENESS_FLOOR = 0.70

_WIN_TOKENS = {"WIN", "WON", "PROFIT"}
_LOSS_TOKENS = {"LOSS", "LOST", "LOSE"}
_BREAKEVEN_TOKENS = {"BREAKEVEN", "BE", "FLAT"}
_UNKNOWN_TOKENS = {"UNKNOWN", "", "NA", "N/A", "PENDING"}

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "may_inform_human_review": True,
    "may_execute": False,
    "may_call_broker": False,
}


def _norm(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _is_filled_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _truthy_process_error(value: Any) -> bool:
    """``process_error`` is meaningful when set to anything other than empty
    or a "none-like" sentinel ("none"/"no"/"clean"). Case-insensitive.
    """
    if not _is_filled_text(value):
        return False
    norm = str(value).strip().lower()
    return norm not in {"none", "no", "clean", "n/a", "na", "-"}


def _classify_outcome(outcome_status: Any) -> str:
    """Map varied outcome labels to {WIN, LOSS, BREAKEVEN, UNKNOWN}."""
    token = _norm(outcome_status)
    if token in _WIN_TOKENS:
        return "WIN"
    if token in _LOSS_TOKENS:
        return "LOSS"
    if token in _BREAKEVEN_TOKENS:
        return "BREAKEVEN"
    return "UNKNOWN"


def _required_field_missing(record: dict[str, Any]) -> list[str]:
    return [
        f for f in REQUIRED_JOURNAL_FIELDS if not _is_filled_text(record.get(f))
    ]


def classify_trade(record: Any) -> dict[str, Any]:
    """Classify a single reconciled-trade record.

    Parameters
    ----------
    record : dict
        Expected fields (all optional, missing treated as empty):
        - ``outcome_status``: WIN | LOSS | BREAKEVEN | UNKNOWN
        - ``journal_completeness_score`` in [0,1]
        - ``learning_ready``: bool (optional; falls back to threshold check)
        - ``process_error``: string (truthy means a process error was logged)
        - ``process_error_notes``: free text
        - ``mistake_tags``: comma string or list
        - ``thesis``, ``invalidation_level``, ``exit_plan``, ``risk_reason``

    Returns
    -------
    dict
        ``process_quality_state`` (one of ALL_STATES),
        ``process_quality_score`` in [0,1],
        ``skill_evidence_score`` mirror (per-record proxy: 1 if good process,
        0 otherwise),
        ``luck_risk_score`` per-record proxy (1 if WIN with bad/incomplete
        process, 0 otherwise),
        ``classification_reasons`` (list[str]),
        ``operator_action`` (str),
        plus the canonical safety stamps.
    """
    if not isinstance(record, dict):
        out = {
            "diagnostic": "process_quality_classifier",
            "process_quality_state": STATE_UNKNOWN,
            "process_quality_score": 0.0,
            "skill_evidence_score": 0.0,
            "luck_risk_score": 0.0,
            "classification_reasons": ["record_not_a_dict"],
            "operator_action": (
                "Pass a dict with outcome_status and journal fields."
            ),
        }
        out.update(_SAFETY_STAMPS)
        return out

    reasons: list[str] = []
    outcome = _classify_outcome(record.get("outcome_status"))

    missing = _required_field_missing(record)
    if missing:
        reasons.append(f"missing_required_fields:{','.join(missing)}")
        out = {
            "diagnostic": "process_quality_classifier",
            "process_quality_state": INCOMPLETE_RECORD,
            "process_quality_score": 0.0,
            "skill_evidence_score": 0.0,
            "luck_risk_score": 0.0,
            "classification_reasons": reasons,
            "outcome_status": outcome,
            "operator_action": (
                "Fill in the missing journal fields ("
                + ", ".join(missing)
                + ") before classifying this trade. An unclassifiable trade "
                "produces no learning."
            ),
        }
        out.update(_SAFETY_STAMPS)
        return out

    if outcome == "UNKNOWN":
        reasons.append("outcome_unknown_or_pending")
        out = {
            "diagnostic": "process_quality_classifier",
            "process_quality_state": STATE_UNKNOWN,
            "process_quality_score": 0.0,
            "skill_evidence_score": 0.0,
            "luck_risk_score": 0.0,
            "classification_reasons": reasons,
            "outcome_status": outcome,
            "operator_action": (
                "Record an outcome_status (WIN/LOSS/BREAKEVEN) before "
                "classifying. Until then, the trade is not learnable."
            ),
        }
        out.update(_SAFETY_STAMPS)
        return out

    has_process_error = _truthy_process_error(record.get("process_error"))
    completeness = float(record.get("journal_completeness_score") or 0.0)
    learning_ready_val = record.get("learning_ready")
    if isinstance(learning_ready_val, bool):
        learning_ready = learning_ready_val
    else:
        learning_ready = completeness >= GOOD_PROCESS_COMPLETENESS_FLOOR

    good_process = (not has_process_error) and learning_ready
    process_quality_score = (
        (1.0 if not has_process_error else 0.0) + min(max(completeness, 0.0), 1.0)
    ) / 2.0

    if good_process:
        reasons.append("journal_strong")
        reasons.append("no_process_error_logged")
    else:
        if has_process_error:
            reasons.append("process_error_logged")
        if not learning_ready:
            reasons.append("journal_below_learning_ready_threshold")

    if outcome == "BREAKEVEN":
        # Breakeven outcomes are still classifiable but treated as "bad_outcome"
        # for the state matrix only when we need a 2x2 view; for reporting we
        # surface the breakeven state distinctly to avoid lying about win-rate.
        state = (
            GOOD_PROCESS_BAD_OUTCOME if good_process else BAD_PROCESS_BAD_OUTCOME
        )
        reasons.append("breakeven_counted_as_non_win")
    elif outcome == "WIN":
        state = (
            GOOD_PROCESS_GOOD_OUTCOME if good_process else BAD_PROCESS_GOOD_OUTCOME
        )
    else:  # LOSS
        state = (
            GOOD_PROCESS_BAD_OUTCOME if good_process else BAD_PROCESS_BAD_OUTCOME
        )

    luck_risk = 1.0 if (state == BAD_PROCESS_GOOD_OUTCOME) else 0.0
    skill_evidence = 1.0 if good_process else 0.0

    operator_action = _build_operator_action(state, has_process_error, learning_ready)

    out = {
        "diagnostic": "process_quality_classifier",
        "process_quality_state": state,
        "process_quality_score": round(process_quality_score, 6),
        "skill_evidence_score": skill_evidence,
        "luck_risk_score": luck_risk,
        "classification_reasons": reasons,
        "outcome_status": outcome,
        "operator_action": operator_action,
    }
    out.update(_SAFETY_STAMPS)
    return out


def _build_operator_action(state: str, had_error: bool, learning_ready: bool) -> str:
    if state == GOOD_PROCESS_GOOD_OUTCOME:
        return (
            "Repeat what worked. Keep the journal pattern intact. "
            "Outcome alone is not proof — track repetition."
        )
    if state == GOOD_PROCESS_BAD_OUTCOME:
        return (
            "Process was disciplined; outcome was negative. Do NOT change "
            "the playbook based on one bad outcome. Tag the random factor."
        )
    if state == BAD_PROCESS_GOOD_OUTCOME:
        return (
            "Lucky win. Do NOT reinforce the bad process. Re-do the journal "
            "fields and write the lesson now while the trade is fresh."
        )
    if state == BAD_PROCESS_BAD_OUTCOME:
        return (
            "Repeat-mistake risk. Capture the missing journal fields, name "
            "the process error explicitly, and add a rule update to the "
            "Moltbook before the next trade."
        )
    if state == INCOMPLETE_RECORD:
        return "Fill journal fields before classifying."
    return "Reconcile outcome_status before classifying."


def aggregate(records: Any) -> dict[str, Any]:
    """Roll up a list of classified records into operator-facing scores.

    Returns
    -------
    dict
        ``trade_count``, ``classified_count`` (excludes incomplete/unknown),
        ``state_distribution``, ``skill_evidence_score`` overall,
        ``luck_risk_score`` overall, ``incomplete_record_count``,
        ``unknown_count``, plus safety stamps.
    """
    if (not isinstance(records, Iterable) or
            isinstance(records, (str, bytes, dict))):
        out = {
            "diagnostic": "process_quality_classifier_aggregate",
            "trade_count": 0,
            "classified_count": 0,
            "state_distribution": {s: 0 for s in ALL_STATES},
            "skill_evidence_score": 0.0,
            "luck_risk_score": 0.0,
            "incomplete_record_count": 0,
            "unknown_count": 0,
            "validation_status": "invalid",
        }
        out.update(_SAFETY_STAMPS)
        return out

    dist: dict[str, int] = {s: 0 for s in ALL_STATES}
    total = 0
    classified = 0
    incomplete = 0
    unknown = 0
    good_process = 0
    win_count = 0
    bad_proc_good_outcome = 0

    for rec in records:
        total += 1
        result = classify_trade(rec)
        state = result["process_quality_state"]
        dist[state] = dist.get(state, 0) + 1
        if state == INCOMPLETE_RECORD:
            incomplete += 1
            continue
        if state == STATE_UNKNOWN:
            unknown += 1
            continue
        classified += 1
        if state in (GOOD_PROCESS_GOOD_OUTCOME, GOOD_PROCESS_BAD_OUTCOME):
            good_process += 1
        if result.get("outcome_status") == "WIN":
            win_count += 1
        if state == BAD_PROCESS_GOOD_OUTCOME:
            bad_proc_good_outcome += 1

    skill_evidence = (good_process / classified) if classified else 0.0
    luck_risk = (bad_proc_good_outcome / win_count) if win_count else 0.0

    out = {
        "diagnostic": "process_quality_classifier_aggregate",
        "trade_count": total,
        "classified_count": classified,
        "state_distribution": dist,
        "skill_evidence_score": round(skill_evidence, 6),
        "luck_risk_score": round(luck_risk, 6),
        "incomplete_record_count": incomplete,
        "unknown_count": unknown,
        "validation_status": "valid" if total else "not_applicable",
    }
    out.update(_SAFETY_STAMPS)
    return out


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "GOOD_PROCESS_GOOD_OUTCOME",
    "GOOD_PROCESS_BAD_OUTCOME",
    "BAD_PROCESS_GOOD_OUTCOME",
    "BAD_PROCESS_BAD_OUTCOME",
    "INCOMPLETE_RECORD",
    "STATE_UNKNOWN",
    "ALL_STATES",
    "REQUIRED_JOURNAL_FIELDS",
    "GOOD_PROCESS_COMPLETENESS_FLOOR",
    "classify_trade",
    "aggregate",
]
