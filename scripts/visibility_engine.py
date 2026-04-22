from __future__ import annotations

from typing import Any


DEFAULT_LIGHT_WEIGHTS: dict[str, float] = {
    "validation_score": 0.28,
    "cross_source_confirmation": 0.12,
    "source_quality": 0.08,
    "price_lead": 0.12,
    "narrative_visibility": 0.15,
    "stage_visibility": 0.15,
    "crowding_visibility": 0.10,
}
DEFAULT_PERSISTENCE_CAP = 6
LIGHT_METHOD = "VISIBILITY_PROXY_BLEND_V1"

_STAGE_VISIBILITY_MAP: dict[str, float] = {
    "NONE": 0.12,
    "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE": 0.28,
    "CLEAN_READY_PENDING_TRIGGER": 0.48,
    "CLEAN_ENTRY_ELIGIBLE": 0.68,
    "EXECUTED_CLEAN": 0.82,
    "EXECUTED_CHAOS": 0.78,
}
_CROWDING_VISIBILITY_MAP: dict[str, float] = {
    "OPEN": 0.2,
    "HEATING_UP": 0.45,
    "CROWDED": 0.82,
    "ALREADY_EXTENDED": 0.95,
    "EXISTING_EXPOSURE": 0.7,
}


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def stage_visibility_proxy(pre_entry_state: str, status: str) -> float:
    normalized_status = str(status or "").upper()
    if normalized_status in {"EXECUTED_CLEAN", "EXECUTED_CHAOS"}:
        return _STAGE_VISIBILITY_MAP[normalized_status]
    normalized_state = str(pre_entry_state or "NONE").upper()
    return _STAGE_VISIBILITY_MAP.get(normalized_state, _STAGE_VISIBILITY_MAP["NONE"])


def crowding_visibility_proxy(crowding_state: str) -> float:
    return _CROWDING_VISIBILITY_MAP.get(
        str(crowding_state or "OPEN").upper(),
        _CROWDING_VISIBILITY_MAP["OPEN"],
    )


def compute_light_score(
    *,
    validation_score: float | None,
    cross_source_confirmation_score: float | None,
    source_quality_score: float | None,
    price_lead_score: float | None,
    novelty_score: float | None,
    pre_entry_state: str,
    status: str,
    crowding_state: str,
    persistence_count: int,
    weights: dict[str, float] | None = None,
    persistence_cap: int = DEFAULT_PERSISTENCE_CAP,
) -> dict[str, Any]:
    active_weights = dict(DEFAULT_LIGHT_WEIGHTS)
    if isinstance(weights, dict):
        active_weights.update(
            {
                key: float(value)
                for key, value in weights.items()
                if key in active_weights
            }
        )

    stage_visibility = stage_visibility_proxy(pre_entry_state, status)
    crowding_visibility = crowding_visibility_proxy(crowding_state)
    narrative_visibility = clamp(1.0 - float(novelty_score or 0.0))
    persistence_visibility = clamp(
        float(max(0, int(persistence_count))) / max(1, int(persistence_cap))
    )

    components = {
        "validation_score": clamp(float(validation_score or 0.0)),
        "cross_source_confirmation": clamp(
            float(cross_source_confirmation_score or 0.0)
        ),
        "source_quality": clamp(float(source_quality_score or 0.0)),
        "price_lead": clamp(float(price_lead_score or 0.0)),
        "narrative_visibility": clamp(
            (0.65 * narrative_visibility) + (0.35 * persistence_visibility)
        ),
        "stage_visibility": stage_visibility,
        "crowding_visibility": crowding_visibility,
    }

    weighted_sum = 0.0
    used_inputs: list[str] = []
    for name, value in components.items():
        weighted_sum += active_weights[name] * value
        used_inputs.append(name)

    input_count = len(used_inputs)
    if input_count >= 6:
        confidence_flag = "HIGH"
    elif input_count >= 4:
        confidence_flag = "MEDIUM"
    else:
        confidence_flag = "LOW"

    return {
        "light_score": round(clamp(weighted_sum), 4),
        "light_inputs_used": used_inputs,
        "light_method": LIGHT_METHOD,
        "light_confidence_flag": confidence_flag,
        "light_components": {
            key: round(value, 4) for key, value in components.items()
        },
    }


def compute_shadow_score(
    *,
    light_score: float,
    validation_state: str,
    blocker_clearance_score: float | None,
) -> dict[str, Any]:
    hidden_risk_flag = (
        str(validation_state or "").upper() != "VALIDATED"
        or float(blocker_clearance_score or 0.0) < 1.0
    )
    return {
        "shadow_score": round(clamp(1.0 - float(light_score)), 4),
        "shadow_method": "INVERSE_LIGHT_V1",
        "hidden_risk_flag": hidden_risk_flag,
    }
