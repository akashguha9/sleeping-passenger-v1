"""Adaptive signal router — pure, deterministic, advisory-only.

Professional engineering translation of the reflection's "slime-mold"
metaphor: explore broadly, reinforce evidence-rich routes, prune weak
routes, avoid hostile terrain, punish duplicate echo. The runtime
vocabulary is structural (nutrient value, terrain penalty, route
weight) rather than biological theatre.

Safety contract on every public output

    output["safety"]["advisory_status"]     == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]      == "LOCKED"
    output["safety"]["broker_api_called"]   is False
    output["safety"]["ai_execution_count"]  == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]         is False

Public API

    compute_nutrient_value(signal)        -> dict
    compute_terrain_penalty(signal)       -> dict
    update_route_weight(route, signal)    -> dict
    classify_route_state(route)           -> dict
    summarize_routes(routes)              -> dict
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

ROUTE_STATES: tuple[str, ...] = (
    "reinforce",
    "watch",
    "decay",
    "prune",
    "quarantine",
)


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


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_nutrient_value(signal: Any) -> dict[str, Any]:
    data = signal if isinstance(signal, dict) else {}
    reliability = _clamp(data.get("reliability"))
    relevance = _clamp(data.get("relevance"))
    freshness = _clamp(data.get("freshness"))
    independence = _clamp(data.get("independence"))
    predictive_history = _clamp(data.get("predictive_history"))
    contradiction = _clamp(data.get("contradiction"))
    echo_risk = _clamp(data.get("echo_risk"))

    raw = (
        0.25 * reliability
        + 0.20 * relevance
        + 0.15 * freshness
        + 0.15 * independence
        + 0.15 * predictive_history
        - 0.20 * contradiction
        - 0.10 * echo_risk
    )
    nutrient_value = _clamp(raw)

    return _stamp({
        "nutrient_value": round(nutrient_value, 4),
        "reliability": round(reliability, 4),
        "relevance": round(relevance, 4),
        "freshness": round(freshness, 4),
        "independence": round(independence, 4),
        "predictive_history": round(predictive_history, 4),
        "contradiction": round(contradiction, 4),
        "echo_risk": round(echo_risk, 4),
    })


def compute_terrain_penalty(signal: Any) -> dict[str, Any]:
    data = signal if isinstance(signal, dict) else {}
    legal_risk = _clamp(data.get("legal_risk"))
    liquidity_risk = _clamp(data.get("liquidity_risk"))
    operator_risk = _clamp(data.get("operator_risk"))
    source_risk = _clamp(data.get("source_risk"))

    raw = (
        0.3 * legal_risk
        + 0.2 * liquidity_risk
        + 0.25 * operator_risk
        + 0.25 * source_risk
    )
    terrain_penalty = _clamp(raw)

    return _stamp({
        "terrain_penalty": round(terrain_penalty, 4),
        "legal_risk": round(legal_risk, 4),
        "liquidity_risk": round(liquidity_risk, 4),
        "operator_risk": round(operator_risk, 4),
        "source_risk": round(source_risk, 4),
    })


def update_route_weight(route: Any, signal: Any) -> dict[str, Any]:
    route_data = route if isinstance(route, dict) else {}
    signal_data = signal if isinstance(signal, dict) else {}

    nutrient = compute_nutrient_value(signal_data)["nutrient_value"]
    terrain = compute_terrain_penalty(signal_data)["terrain_penalty"]
    echo_risk = _clamp(signal_data.get("echo_risk"))
    contradiction = _clamp(signal_data.get("contradiction"))

    old_weight = _clamp(route_data.get("current_weight") or route_data.get("old_weight"))
    explicit_reinforcement = _coerce_float(route_data.get("reinforcement"), float("nan"))
    if explicit_reinforcement != explicit_reinforcement:  # NaN: not provided
        reinforcement = nutrient * 0.4
    else:
        reinforcement = _clamp(explicit_reinforcement)

    decay = _clamp(route_data.get("decay"))

    raw_new = (
        old_weight
        + reinforcement
        - decay
        - terrain
        - echo_risk
        - contradiction
    )
    new_weight = _clamp(raw_new)

    return _stamp({
        "old_route_weight": round(old_weight, 4),
        "new_route_weight": round(new_weight, 4),
        "reinforcement": round(reinforcement, 4),
        "decay": round(decay, 4),
        "terrain_penalty": round(terrain, 4),
        "nutrient_value": round(nutrient, 4),
        "echo_risk": round(echo_risk, 4),
        "contradiction": round(contradiction, 4),
    })


def classify_route_state(route: Any, signal: Any | None = None) -> dict[str, Any]:
    route_data = route if isinstance(route, dict) else {}
    if signal is None:
        signal_data = {
            "reliability": route_data.get("reliability"),
            "relevance": route_data.get("relevance"),
            "freshness": route_data.get("freshness"),
            "independence": route_data.get("independence"),
            "predictive_history": route_data.get("predictive_history"),
            "contradiction": route_data.get("contradiction"),
            "echo_risk": route_data.get("echo_risk"),
            "legal_risk": route_data.get("legal_risk"),
            "liquidity_risk": route_data.get("liquidity_risk"),
            "operator_risk": route_data.get("operator_risk"),
            "source_risk": route_data.get("source_risk"),
        }
    else:
        signal_data = signal if isinstance(signal, dict) else {}

    update = update_route_weight(route_data, signal_data)
    nutrient = update["nutrient_value"]
    terrain = update["terrain_penalty"]
    new_weight = update["new_route_weight"]
    echo_risk = update["echo_risk"]
    contradiction = update["contradiction"]
    decay = update["decay"]

    reasons: list[str] = []
    if terrain >= 0.7:
        state = "quarantine"
        reasons.append("hostile_terrain")
    elif echo_risk >= 0.6 and nutrient < 0.4:
        state = "prune"
        reasons.append("echo_dominated_low_nutrient")
    elif contradiction >= 0.7:
        state = "prune"
        reasons.append("high_contradiction")
    elif decay >= 0.4 and nutrient < 0.4:
        state = "decay"
        reasons.append("decay_exceeds_nutrient")
    elif nutrient >= 0.6 and terrain <= 0.3 and echo_risk <= 0.4:
        state = "reinforce"
        reasons.append("high_nutrient_low_terrain")
    elif new_weight >= 0.5 and terrain <= 0.5:
        state = "watch"
        reasons.append("moderate_weight")
    elif new_weight < 0.2:
        state = "prune"
        reasons.append("low_weight")
    else:
        state = "watch"
        reasons.append("default_watch")

    route_confidence = _clamp(
        0.4 * nutrient
        + 0.3 * (1.0 - terrain)
        + 0.3 * (1.0 - max(echo_risk, contradiction))
    )

    operator_action_map = {
        "reinforce": "watch",
        "watch": "watch",
        "decay": "decay_archive",
        "prune": "decay_archive",
        "quarantine": "quarantine",
    }

    return _stamp({
        "route_id": route_data.get("route_id"),
        "route_state": state,
        "old_route_weight": update["old_route_weight"],
        "new_route_weight": update["new_route_weight"],
        "nutrient_value": nutrient,
        "terrain_penalty": terrain,
        "route_confidence": round(route_confidence, 4),
        "pruning_reason": reasons[0] if state in {"prune", "quarantine"} else None,
        "reasons": reasons,
        "operator_action": operator_action_map[state],
    })


def summarize_routes(routes: Any) -> dict[str, Any]:
    if not isinstance(routes, list):
        return _stamp({
            "route_count": 0,
            "state_counts": {s: 0 for s in ROUTE_STATES},
            "mean_route_weight": 0.0,
            "mean_route_confidence": 0.0,
            "reasons": ["no_routes"],
        })
    rows = [r for r in routes if isinstance(r, dict)]
    if not rows:
        return _stamp({
            "route_count": 0,
            "state_counts": {s: 0 for s in ROUTE_STATES},
            "mean_route_weight": 0.0,
            "mean_route_confidence": 0.0,
            "reasons": ["no_routes"],
        })

    classifications = [classify_route_state(r) for r in rows]
    state_counts = {s: 0 for s in ROUTE_STATES}
    weights: list[float] = []
    confidences: list[float] = []
    for c in classifications:
        state_counts[c["route_state"]] = state_counts.get(c["route_state"], 0) + 1
        weights.append(c["new_route_weight"])
        confidences.append(c["route_confidence"])

    mean_weight = sum(weights) / len(weights)
    mean_confidence = sum(confidences) / len(confidences)

    return _stamp({
        "route_count": len(rows),
        "state_counts": state_counts,
        "mean_route_weight": round(mean_weight, 4),
        "mean_route_confidence": round(mean_confidence, 4),
        "reasons": [],
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "ROUTE_STATES",
    "compute_nutrient_value",
    "compute_terrain_penalty",
    "update_route_weight",
    "classify_route_state",
    "summarize_routes",
]
