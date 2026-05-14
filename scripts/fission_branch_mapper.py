"""Fission branch mapper — pure, deterministic, advisory-only.

Engineering translation of the reflection's "fission shock" metaphor.
An explosive event branches into many consequences. The MVP **maps**
those branches; it does not trade them and it does not authorize any
broker call.

Safety contract on every public output

    output["safety"]["advisory_status"]     == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]      == "LOCKED"
    output["safety"]["broker_api_called"]   is False
    output["safety"]["ai_execution_count"]  == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]         is False

Public API

    map_fission_branches(event)        -> dict
    score_branch_energy(event, branch) -> dict
    classify_fission_event(event)      -> dict
"""

from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

BRANCH_FAMILIES: tuple[str, ...] = (
    "equities",
    "sector",
    "rates",
    "fx",
    "commodities",
    "crypto",
    "policy",
    "geopolitics",
    "liquidity",
    "sentiment",
    "legal_regulatory",
    "operator_risk",
)

RECOMMENDED_STATES: tuple[str, ...] = (
    "map_only",
    "watch_branches",
    "review_after_confirmation",
    "do_not_promote",
    "human_review_only",
)

# Heuristic relevance of each branch family per event_type. Pure metadata.
_EVENT_FAMILY_RELEVANCE: dict[str, dict[str, float]] = {
    "central_bank": {
        "rates": 1.0, "fx": 0.9, "equities": 0.7, "sector": 0.6,
        "liquidity": 0.9, "commodities": 0.5, "crypto": 0.4,
        "sentiment": 0.6, "policy": 0.8, "operator_risk": 0.4,
    },
    "regulatory": {
        "legal_regulatory": 1.0, "sector": 0.8, "equities": 0.6,
        "policy": 0.7, "operator_risk": 0.5, "sentiment": 0.5,
    },
    "geopolitics": {
        "geopolitics": 1.0, "commodities": 0.8, "fx": 0.7,
        "equities": 0.6, "sentiment": 0.7, "policy": 0.6,
        "liquidity": 0.5, "operator_risk": 0.4,
    },
    "earnings": {
        "equities": 0.9, "sector": 0.8, "sentiment": 0.6,
        "operator_risk": 0.3,
    },
    "macro_print": {
        "rates": 0.9, "fx": 0.8, "equities": 0.7, "commodities": 0.5,
        "sentiment": 0.5, "liquidity": 0.6, "policy": 0.5,
    },
    "crypto_event": {
        "crypto": 1.0, "sentiment": 0.6, "liquidity": 0.5,
        "legal_regulatory": 0.5,
    },
    "operator_event": {
        "operator_risk": 1.0,
    },
    "unknown": {
        "sentiment": 0.4, "operator_risk": 0.3,
    },
}


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["safety"] = dict(SAFETY_STAMPS)
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if x != x:
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_event_type(event: dict[str, Any]) -> str:
    raw = _text(event.get("event_type"))
    return raw if raw in _EVENT_FAMILY_RELEVANCE else "unknown"


def score_branch_energy(event: Any, branch: Any) -> dict[str, Any]:
    event_data = event if isinstance(event, dict) else {}
    branch_data = branch if isinstance(branch, dict) else {}
    event_severity = _clamp(event_data.get("event_severity"))
    market_sensitivity = _clamp(event_data.get("market_sensitivity"))
    cross_asset_coupling = _clamp(event_data.get("cross_asset_coupling"))
    time_propagation = _clamp(event_data.get("time_propagation"), 0.0, 1.0)
    narrative_intensity = _clamp(event_data.get("narrative_intensity"))

    sector_sensitivity = _clamp(branch_data.get("sector_sensitivity"))
    narrative_fit = _clamp(branch_data.get("narrative_fit"))
    liquidity_transmission = _clamp(branch_data.get("liquidity_transmission"))
    relevance = _clamp(branch_data.get("relevance"))

    energy = _clamp(
        0.4 * event_severity * relevance
        + 0.2 * market_sensitivity * sector_sensitivity
        + 0.2 * cross_asset_coupling * liquidity_transmission
        + 0.1 * narrative_intensity * narrative_fit
        + 0.1 * time_propagation
    )

    return _stamp({
        "branch_family": _text(branch_data.get("branch_family")),
        "branch_energy": round(energy, 4),
        "event_severity": round(event_severity, 4),
        "market_sensitivity": round(market_sensitivity, 4),
        "relevance": round(relevance, 4),
    })


def _default_branches_for_event(event_type: str) -> list[dict[str, Any]]:
    relevance_map = _EVENT_FAMILY_RELEVANCE.get(event_type, _EVENT_FAMILY_RELEVANCE["unknown"])
    branches = []
    for family, relevance in relevance_map.items():
        branches.append({
            "branch_family": family,
            "relevance": relevance,
            "sector_sensitivity": relevance,
            "narrative_fit": relevance,
            "liquidity_transmission": relevance * 0.8,
        })
    return branches


def map_fission_branches(event: Any) -> dict[str, Any]:
    data = event if isinstance(event, dict) else {}
    event_type = _resolve_event_type(data)
    event_severity = _clamp(data.get("event_severity"))
    cross_asset_coupling = _clamp(data.get("cross_asset_coupling"))
    narrative_reach = _clamp(data.get("narrative_reach"))
    liquidity_sensitivity = _clamp(data.get("liquidity_sensitivity"))
    uncertainty = _clamp(data.get("uncertainty"))
    source_reliability = _clamp(data.get("source_reliability"))
    market_confirmation = _clamp(data.get("market_confirmation"))

    branches_input = data.get("branches")
    if not isinstance(branches_input, list) or not branches_input:
        branches_input = _default_branches_for_event(event_type)
    branch_scores: list[dict[str, Any]] = []
    for branch in branches_input:
        if not isinstance(branch, dict):
            continue
        scored = score_branch_energy(data, branch)
        scored.pop("safety", None)
        scored.pop("advisory_status", None)
        scored.pop("execution_gate", None)
        branch_scores.append(scored)

    branch_scores.sort(key=lambda b: b["branch_energy"], reverse=True)
    branch_count = len(branch_scores)

    radiation_radius = _clamp(
        0.4 * event_severity
        + 0.2 * cross_asset_coupling
        + 0.2 * narrative_reach
        + 0.2 * liquidity_sensitivity
    )

    # Branch clarity: do we have a few branches above 0.4 energy with low
    # uncertainty and decent reliability?
    energetic = sum(1 for b in branch_scores if b["branch_energy"] >= 0.4)
    if branch_count == 0:
        branch_clarity = 0.0
    else:
        clarity_raw = (energetic / max(branch_count, 1))
        clarity_raw *= (0.5 + 0.5 * source_reliability)
        clarity_raw *= (1.0 - 0.5 * uncertainty)
        branch_clarity = _clamp(clarity_raw)

    chaos_risk = _clamp(uncertainty * (1.0 - source_reliability) * (1.0 - market_confirmation))

    fission_event = bool(
        event_severity >= 0.5
        and (radiation_radius >= 0.4 or energetic >= 2)
    )

    if not fission_event:
        recommendation = "do_not_promote"
        reason = "below_fission_threshold"
    elif uncertainty >= 0.7 or branch_clarity < 0.3:
        recommendation = "map_only"
        reason = "high_uncertainty_or_low_branch_clarity"
    elif chaos_risk >= 0.6:
        recommendation = "map_only"
        reason = "high_chaos_risk"
    elif market_confirmation < 0.3 and source_reliability < 0.5:
        recommendation = "review_after_confirmation"
        reason = "awaiting_confirmation"
    elif branch_clarity >= 0.6:
        recommendation = "watch_branches"
        reason = "clear_branches_present"
    else:
        recommendation = "human_review_only"
        reason = "partial_clarity_requires_human_review"

    return _stamp({
        "event_type": event_type,
        "fission_event": fission_event,
        "branch_count": branch_count,
        "branches": branch_scores,
        "branch_clarity_score": round(branch_clarity, 4),
        "radiation_radius_score": round(radiation_radius, 4),
        "chaos_risk": round(chaos_risk, 4),
        "recommendation": recommendation,
        "recommended_state": recommendation,
        "operator_action": "map_branches" if fission_event else "observe",
        "reasons": [reason],
    })


def classify_fission_event(event: Any) -> dict[str, Any]:
    mapped = map_fission_branches(event)
    return _stamp({
        "fission_event": mapped["fission_event"],
        "branch_count": mapped["branch_count"],
        "branch_clarity_score": mapped["branch_clarity_score"],
        "radiation_radius_score": mapped["radiation_radius_score"],
        "chaos_risk": mapped["chaos_risk"],
        "recommendation": mapped["recommendation"],
        "operator_action": mapped["operator_action"],
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "BRANCH_FAMILIES",
    "RECOMMENDED_STATES",
    "map_fission_branches",
    "score_branch_energy",
    "classify_fission_event",
]
