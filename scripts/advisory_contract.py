"""Centralized advisory-safety contract for the local advisory MVP.

Single source of truth for the safety vocabulary that EVERY new and active
module emits, so the MVP cannot quietly drift into N slightly-different,
inconsistent safety dicts.  Before this module, each layer hand-rolled its
own ``{"advisory_status": "ADVISORY_ONLY", ...}`` literal; a typo or a
forgotten key in any one of them would be a silent safety hole.  This module
makes the stamp a function call so the values are defined once.

Four stamp surfaces are centralised here:

* :func:`advisory_safety_stamps`   — the canonical advisory-only safety dict.
* :func:`human_only_stamp`         — "a human makes the final decision".
* :func:`execution_lock_stamp`     — "the execution gate is LOCKED".
* :func:`canonical_truth_declaration` — "SQLite is canonical, JSONL is audit-only".

Plus the explicit set of *safe degradation states* an advisory layer may fall
back to when data is missing — never a BUY / EXECUTE.

Contract — pure module
----------------------
No DB, no filesystem, no network, no broker calls, no AI execution.  Importing
this module has no side effects.  It only returns constant data structures.
``jsonl_is_canonical`` is **always** False; ``sqlite_is_canonical`` is always
True; ``execution_permission`` / ``can_execute`` / ``broker_api_called`` are
always False; ``ai_execution_count`` is always 0.
"""
from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_MODE_HUMAN_ONLY = "HUMAN_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"
BROKER_ORDER_NONE = "NONE"
AI_EXECUTION_COUNT = 0

# Truth model — SQLite is canonical; JSONL is an audit-only mirror.  This is a
# hard product invariant: nothing in this repo may flip JSONL to canonical.
CANONICAL_STORE = "sqlite"
AUDIT_ONLY_STORE = "jsonl"

# The only states an advisory layer may degrade *to* when inputs are missing
# or invalid.  None of these is an execution instruction.  A normaliser /
# diagnostic that cannot honestly produce a confident read must land on one
# of these, never on a BUY/SELL/EXECUTE.
SAFE_DEGRADATION_STATES: tuple[str, ...] = (
    "REVIEW",
    "INSUFFICIENT_DATA",
    "WAIT",
    "HUMAN_REVIEW_ONLY",
    "AVOID",
)

# Tokens that must never appear as an *active* instruction in any advisory
# output.  Used by contract self-tests and module audits.  ``broker_order_id``
# is intentionally excluded because the value "NONE" is the safe sentinel.
FORBIDDEN_EXECUTION_TOKENS: tuple[str, ...] = (
    "place_order",
    "submit_order",
    "execute_trade",
    "execute order",
    "place order",
    "submit order",
    "broker_execute",
    "auto-trading",
    "auto_execute",
    "permission to trade",
)


def advisory_safety_stamps() -> dict[str, Any]:
    """Return the canonical advisory-only safety dict.

    A fresh dict each call so callers may mutate their own copy without
    corrupting the shared contract.
    """
    return {
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": AI_EXECUTION_COUNT,
        "execution_permission": False,
        "can_execute": False,
        "broker_order_id": BROKER_ORDER_NONE,
        "human_review_required": True,
    }


def human_only_stamp() -> dict[str, Any]:
    """Return the "a human makes the final decision" stamp."""
    return {
        "execution_mode": EXECUTION_MODE_HUMAN_ONLY,
        "human_review_required": True,
        "human_final_decision_required": True,
    }


def execution_lock_stamp() -> dict[str, Any]:
    """Return the "execution gate is LOCKED" stamp."""
    return {
        "execution_gate": EXECUTION_GATE_LOCKED,
        "execution_permission": False,
        "can_execute": False,
        "broker_api_called": False,
        "broker_order_id": BROKER_ORDER_NONE,
        "ai_execution_count": AI_EXECUTION_COUNT,
    }


def canonical_truth_declaration() -> dict[str, Any]:
    """Return the canonical/audit-only storage declaration.

    SQLite is canonical; JSONL is an audit-only mirror.  ``jsonl_is_canonical``
    is always False — flipping it is a product-invariant violation.
    """
    return {
        "canonical_store": CANONICAL_STORE,
        "audit_only_store": AUDIT_ONLY_STORE,
        "sqlite_is_canonical": True,
        "jsonl_is_canonical": False,
    }


def is_safe_degradation(state: Any) -> bool:
    """True if ``state`` is one of the approved safe-degradation states."""
    if state is None:
        return False
    return str(state).strip().upper() in SAFE_DEGRADATION_STATES


def stamp(
    payload: Any,
    *,
    include_human_only: bool = False,
    include_truth_model: bool = False,
) -> dict[str, Any]:
    """Attach the canonical safety stamps to ``payload`` and return it.

    Mirrors the ``_stamp`` helper used across the diagnostic layers: the
    advisory-only safety dict goes under ``payload["safety"]`` and the three
    top-level shorthands (``advisory_status`` / ``execution_gate`` /
    ``human_review_required``) are set if absent.  Optionally also attaches the
    human-only and canonical-truth declarations.
    """
    out = dict(payload) if isinstance(payload, dict) else {}
    out["safety"] = advisory_safety_stamps()
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    out.setdefault("human_review_required", True)
    if include_human_only:
        out["execution"] = human_only_stamp()
    if include_truth_model:
        out["truth_model"] = canonical_truth_declaration()
    return out


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_MODE_HUMAN_ONLY",
    "EXECUTION_GATE_LOCKED",
    "BROKER_ORDER_NONE",
    "AI_EXECUTION_COUNT",
    "CANONICAL_STORE",
    "AUDIT_ONLY_STORE",
    "SAFE_DEGRADATION_STATES",
    "FORBIDDEN_EXECUTION_TOKENS",
    "advisory_safety_stamps",
    "human_only_stamp",
    "execution_lock_stamp",
    "canonical_truth_declaration",
    "is_safe_degradation",
    "stamp",
]
