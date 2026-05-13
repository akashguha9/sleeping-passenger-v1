"""
Continuity / degraded mode diagnostic.

Purpose
-------
Summarize whether the system is operating in NORMAL, DEGRADED_ADVISORY, or
CONTINUITY_SAFE_ADVISORY state, and explain why.

The diagnostic is **deterministic**, makes **no live calls**, performs
**no DB writes**, and never grants any form of execution permission. It
exists so that the operator can tell at a glance whether the system is
healthy enough to trust the displayed signals, or whether they should
treat the session as degraded.

Formula
-------

    System_Integrity =
          Backend
        × DB
        × Safety_Invariant
        × Source_Health
        × Freshness
        × Backup_Recency
        × AI_Validation_Health

Each factor is in [0, 1]. The score is multiplicative on purpose: a
single broken factor pulls the whole integrity score down sharply, which
matches operator intuition — if the DB is missing, nothing else matters.

Buckets:

    System_Integrity >= 0.85  -> NORMAL
    System_Integrity >= 0.55  -> DEGRADED_ADVISORY
    System_Integrity <  0.55  -> CONTINUITY_SAFE_ADVISORY

Even in `NORMAL`, the MVP cannot execute. Continuity mode does not
*reduce* permissions — it makes the already-reduced state legible.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

    allowed_actions never includes execute_broker_order=True.

Public API
----------
- ``classify_continuity_mode(state)`` -> dict
- ``CONTINUITY_THRESHOLDS`` -> dict[str, float]
"""
from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"


CONTINUITY_THRESHOLDS: dict[str, float] = {
    "normal": 0.85,
    "degraded_advisory": 0.55,
    # below degraded_advisory -> continuity_safe_advisory
}


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


def _bool01(value: Any, default: bool = True) -> float:
    """Map a tri-state input (True/False/None) to a 0.0/1.0 factor.

    Truthy and missing both map to 1.0 by default — the diagnostic assumes
    healthy unless a caller explicitly says otherwise. ``False`` is hard 0.
    Numbers in [0, 1] pass through.
    """
    if value is None:
        return 1.0 if default else 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 1.0 if default else 0.0
    if n != n:
        return 1.0 if default else 0.0
    return max(0.0, min(1.0, n))


def _source_health_factor(state: dict[str, Any]) -> float:
    if "source_health_ok" in state:
        return _bool01(state["source_health_ok"])
    stale = int(state.get("stale_source_count", 0) or 0)
    failed = int(state.get("failed_source_count", 0) or 0)
    if stale <= 0 and failed <= 0:
        return 1.0
    # Each stale source costs 0.1, each failed source costs 0.2, capped at 0.0
    return max(0.0, 1.0 - (0.1 * stale + 0.2 * failed))


def _ai_validation_factor(state: dict[str, Any]) -> float:
    invalid = int(state.get("ai_validation_invalid_count", 0) or 0)
    if invalid <= 0:
        return 1.0
    # Each invalid AI payload costs 0.15, capped at 0
    return max(0.0, 1.0 - 0.15 * invalid)


def _freshness_factor(state: dict[str, Any]) -> float:
    if "live_refresh_fresh" in state:
        return _bool01(state["live_refresh_fresh"])
    if "freshness_ratio" in state:
        return _bool01(state["freshness_ratio"])
    return 1.0


def _backup_factor(state: dict[str, Any]) -> float:
    if "backup_recent" in state:
        return _bool01(state["backup_recent"])
    return 1.0


def classify_continuity_mode(state: Any) -> dict[str, Any]:
    """Compute the continuity mode and explain it.

    Parameters
    ----------
    state : dict
        A flat dict of operational health signals. Known fields:

        - ``backend_available`` (bool)
        - ``db_available`` (bool)
        - ``safety_invariant_ok`` (bool)
        - ``source_health_ok`` (bool) OR
          ``stale_source_count``/``failed_source_count`` (ints)
        - ``ai_validation_invalid_count`` (int)
        - ``live_refresh_fresh`` (bool) OR ``freshness_ratio`` (float)
        - ``backup_recent`` (bool)
        - ``fallback_used`` (bool) — informational, doesn't change mode
        - ``mock_used`` (bool) — informational, doesn't change mode

    Missing fields are treated as healthy (True/1.0). The diagnostic refuses
    to escalate based on absence of information; the operator should
    pass `False` explicitly when something is known broken.

    Returns
    -------
    dict
        ``continuity_mode``, ``system_integrity_score``, ``degraded_reasons``,
        ``allowed_actions``, plus the canonical safety stamps. ``allowed_actions``
        ALWAYS sets ``execute_broker_order = False``.
    """
    if not isinstance(state, dict):
        out = {
            "diagnostic": "continuity_mode",
            "continuity_mode": "CONTINUITY_SAFE_ADVISORY",
            "system_integrity_score": 0.0,
            "degraded_reasons": ["state_not_a_dict"],
            "factors": {},
            "allowed_actions": {
                "review_signals": True,
                "log_manual_trade": False,
                "reconcile": False,
                "execute_broker_order": False,
            },
            "validation_status": "invalid",
            "informational": {},
        }
        out.update(_SAFETY_STAMPS)
        return out

    backend = _bool01(state.get("backend_available"))
    db = _bool01(state.get("db_available"))
    safety = _bool01(state.get("safety_invariant_ok"))
    source = _source_health_factor(state)
    freshness = _freshness_factor(state)
    backup = _backup_factor(state)
    ai_val = _ai_validation_factor(state)

    factors = {
        "backend": backend,
        "db": db,
        "safety_invariant": safety,
        "source_health": source,
        "freshness": freshness,
        "backup_recency": backup,
        "ai_validation_health": ai_val,
    }

    integrity = backend * db * safety * source * freshness * backup * ai_val
    integrity = max(0.0, min(1.0, integrity))

    # Hard floor: if the safety invariant is broken, drop to continuity-safe
    # regardless of other factors. The MVP's identity depends on that bit.
    if safety < 1.0:
        integrity = min(integrity, 0.40)

    if integrity >= CONTINUITY_THRESHOLDS["normal"]:
        mode = "NORMAL"
    elif integrity >= CONTINUITY_THRESHOLDS["degraded_advisory"]:
        mode = "DEGRADED_ADVISORY"
    else:
        mode = "CONTINUITY_SAFE_ADVISORY"

    reasons: list[str] = []
    if backend < 1.0:
        reasons.append("backend_unavailable")
    if db < 1.0:
        reasons.append("db_unavailable")
    if safety < 1.0:
        reasons.append("safety_invariant_broken")
    if source < 1.0:
        reasons.append("source_health_degraded")
    if freshness < 1.0:
        reasons.append("data_not_fresh")
    if backup < 1.0:
        reasons.append("backup_stale_or_missing")
    if ai_val < 1.0:
        reasons.append("ai_validation_failures")
    if state.get("fallback_used") is True:
        reasons.append("source_fallback_active")
    if state.get("mock_used") is True:
        reasons.append("mock_mode_active")

    # Allowed actions never include broker execution. Manual trade logging
    # and reconciliation are permitted unless the DB is broken — without
    # the DB we cannot guarantee a manual trade record survives.
    allowed_actions = {
        "review_signals": True,
        "log_manual_trade": db >= 1.0,
        "reconcile": db >= 1.0,
        "execute_broker_order": False,
    }

    out = {
        "diagnostic": "continuity_mode",
        "continuity_mode": mode,
        "system_integrity_score": round(integrity, 6),
        "degraded_reasons": reasons,
        "factors": {k: round(v, 6) for k, v in factors.items()},
        "allowed_actions": allowed_actions,
        "informational": {
            "fallback_used": bool(state.get("fallback_used", False)),
            "mock_used": bool(state.get("mock_used", False)),
        },
        "validation_status": "valid",
    }
    out.update(_SAFETY_STAMPS)
    return out


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "CONTINUITY_THRESHOLDS",
    "classify_continuity_mode",
]
