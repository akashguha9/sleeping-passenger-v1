"""
Self-test journal quality diagnostic.

Purpose
-------
Score whether a manual decision / trade log entry is *learnable* — i.e.
whether the operator captured enough structural detail at decision time
and at reconciliation time to be able to attribute the outcome to skill,
luck, or process error months later.

The diagnostic is **deterministic**, performs **no DB writes**, makes
**no broker calls**, and never grants any form of execution permission.

It answers one question:

    "If I look at this trade in six months, can I tell whether my
     process worked or I got lucky?"

Formula
-------

    Learning_Readiness =
          Thesis
        × Invalidation
        × Horizon
        × Risk_Rationale
        × Outcome_Log
        × Reflection

Each factor is in [0, 1]. The score is multiplicative on purpose — a
missing thesis or a missing invalidation level *destroys* learnability
even if every other field is rich. Average it and you mask the gap.

Buckets:

    Learning_Readiness >= 0.70  -> learning_ready=True
    Learning_Readiness <  0.70  -> learning_ready=False

The completeness score is a separate, additive view (sum of present
fields ÷ total fields) so the operator can see "how many slots did I
fill" alongside "is this learnable".

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Public API
----------
- ``score_journal_entry(entry)`` -> dict
- ``score_journal_entries(entries)`` -> dict   (aggregate over a list)
- ``REQUIRED_FIELDS`` / ``LEARNING_FACTORS`` -> tuple
"""
from __future__ import annotations

from typing import Any, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"


# Fields that signal "the operator captured the decision context".
REQUIRED_FIELDS: tuple[str, ...] = (
    "signal_id",
    "thesis",
    "invalidation_level",
    "expected_horizon",
    "position_size",
    "risk_reason",
    "entry_reason",
    "exit_plan",
    "confidence_before",
    "emotional_state",
    "source_references",
    "post_trade_outcome",
    "reconciliation_status",
    "mistake_tags",
    "lesson",
)


# The six factors that multiply into Learning_Readiness. Each maps to one
# or more entry fields; presence of any of them lights up the factor.
LEARNING_FACTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("thesis", ("thesis", "entry_reason")),
    ("invalidation", ("invalidation_level", "exit_plan")),
    ("horizon", ("expected_horizon",)),
    ("risk_rationale", ("risk_reason", "position_size")),
    ("outcome_log", ("post_trade_outcome", "reconciliation_status")),
    ("reflection", ("mistake_tags", "lesson")),
)


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


def _is_filled(value: Any) -> bool:
    """A field is "filled" if it carries any non-empty, non-default content."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # Zero position size / zero confidence isn't a captured decision.
        return value != 0
    return True


def score_journal_entry(entry: Any) -> dict[str, Any]:
    """Score one manual-trade / decision journal entry for learning readiness.

    Parameters
    ----------
    entry : dict
        A flat dict. Known fields are listed in ``REQUIRED_FIELDS``. Missing
        fields are treated as not filled — they are *not* errors; the helper
        is reporting *what is there to learn from*.

    Returns
    -------
    dict
        ``journal_completeness_score`` (0..1, fraction of fields filled),
        ``learning_readiness_score`` (0..1, multiplicative across factors),
        ``learning_ready`` (bool, threshold at 0.70),
        ``missing_fields`` (list[str]),
        ``decision_quality_flags`` (list[str]),
        ``factor_scores`` (per-factor 0/1),
        plus the canonical safety stamps.
    """
    if not isinstance(entry, dict):
        out = {
            "diagnostic": "self_test_journal_quality",
            "journal_completeness_score": 0.0,
            "learning_readiness_score": 0.0,
            "learning_ready": False,
            "missing_fields": list(REQUIRED_FIELDS),
            "decision_quality_flags": ["entry_not_a_dict"],
            "factor_scores": {name: 0.0 for name, _ in LEARNING_FACTORS},
            "validation_status": "invalid",
        }
        out.update(_SAFETY_STAMPS)
        return out

    present: list[str] = []
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        if _is_filled(entry.get(field)):
            present.append(field)
        else:
            missing.append(field)

    completeness = len(present) / len(REQUIRED_FIELDS) if REQUIRED_FIELDS else 0.0

    factor_scores: dict[str, float] = {}
    for factor_name, fields in LEARNING_FACTORS:
        factor_scores[factor_name] = (
            1.0 if any(_is_filled(entry.get(f)) for f in fields) else 0.0
        )

    readiness = 1.0
    for value in factor_scores.values():
        readiness *= value

    learning_ready = readiness >= 0.70

    flags: list[str] = []
    if factor_scores["thesis"] < 1.0:
        flags.append("missing_thesis_or_entry_reason")
    if factor_scores["invalidation"] < 1.0:
        flags.append("no_invalidation_or_exit_plan")
    if factor_scores["horizon"] < 1.0:
        flags.append("no_expected_horizon")
    if factor_scores["risk_rationale"] < 1.0:
        flags.append("no_risk_reason_or_size")
    if factor_scores["outcome_log"] < 1.0:
        flags.append("no_outcome_or_reconciliation")
    if factor_scores["reflection"] < 1.0:
        flags.append("no_reflection_or_mistake_tags")

    # Bonus heads-up flags — these don't lower the score but help the
    # operator notice patterns that are easy to miss.
    if "emotional_state" in missing:
        flags.append("emotional_state_not_recorded")
    if "confidence_before" in missing:
        flags.append("pre_trade_confidence_not_recorded")
    if "source_references" in missing:
        flags.append("source_references_not_recorded")

    out = {
        "diagnostic": "self_test_journal_quality",
        "journal_completeness_score": round(completeness, 6),
        "learning_readiness_score": round(readiness, 6),
        "learning_ready": bool(learning_ready),
        "missing_fields": missing,
        "decision_quality_flags": flags,
        "factor_scores": factor_scores,
        "validation_status": "valid",
    }
    out.update(_SAFETY_STAMPS)
    return out


def score_journal_entries(entries: Any) -> dict[str, Any]:
    """Aggregate journal-quality stats across a list of entries.

    Returns
    -------
    dict
        ``entry_count``, ``learning_ready_count``,
        ``average_completeness``, ``average_learning_readiness``,
        ``factor_pass_rates`` (per-factor across entries), plus the safety
        stamps. The aggregate output never grants execution permission and
        cannot be turned into an action signal.
    """
    if not isinstance(entries, Iterable) or isinstance(entries, (str, bytes, dict)):
        out = {
            "diagnostic": "self_test_journal_quality_aggregate",
            "entry_count": 0,
            "learning_ready_count": 0,
            "average_completeness": 0.0,
            "average_learning_readiness": 0.0,
            "factor_pass_rates": {name: 0.0 for name, _ in LEARNING_FACTORS},
            "validation_status": "invalid",
        }
        out.update(_SAFETY_STAMPS)
        return out

    completeness_sum = 0.0
    readiness_sum = 0.0
    ready_count = 0
    factor_totals: dict[str, float] = {name: 0.0 for name, _ in LEARNING_FACTORS}
    total = 0

    for entry in entries:
        total += 1
        result = score_journal_entry(entry)
        completeness_sum += float(result["journal_completeness_score"])
        readiness_sum += float(result["learning_readiness_score"])
        if result["learning_ready"]:
            ready_count += 1
        for factor, score in result["factor_scores"].items():
            factor_totals[factor] += float(score)

    if total == 0:
        out = {
            "diagnostic": "self_test_journal_quality_aggregate",
            "entry_count": 0,
            "learning_ready_count": 0,
            "average_completeness": 0.0,
            "average_learning_readiness": 0.0,
            "factor_pass_rates": {name: 0.0 for name, _ in LEARNING_FACTORS},
            "validation_status": "not_applicable",
        }
        out.update(_SAFETY_STAMPS)
        return out

    out = {
        "diagnostic": "self_test_journal_quality_aggregate",
        "entry_count": total,
        "learning_ready_count": ready_count,
        "average_completeness": round(completeness_sum / total, 6),
        "average_learning_readiness": round(readiness_sum / total, 6),
        "factor_pass_rates": {
            name: round(value / total, 6) for name, value in factor_totals.items()
        },
        "validation_status": "valid",
    }
    out.update(_SAFETY_STAMPS)
    return out


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "REQUIRED_FIELDS",
    "LEARNING_FACTORS",
    "score_journal_entry",
    "score_journal_entries",
]
