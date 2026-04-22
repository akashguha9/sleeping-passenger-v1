from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DEFAULT_TEMPORAL_CONFIG: dict[str, float] = {
    "age_days_cap": 30.0,
    "persistence_cap": 6.0,
    "age_weight": 0.45,
    "stage_weight": 0.35,
    "persistence_weight": 0.20,
}
TEMPORAL_METHOD = "SUNDIAL_PROXY_BLEND_V1"

_STAGE_PROGRESS_MAP: dict[str, float] = {
    "NONE": 0.10,
    "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE": 0.30,
    "CLEAN_READY_PENDING_TRIGGER": 0.52,
    "CLEAN_ENTRY_ELIGIBLE": 0.68,
    "EXECUTED_CLEAN": 0.88,
    "EXECUTED_CHAOS": 0.92,
}


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def stage_progress_proxy(pre_entry_state: str, status: str) -> float:
    normalized_status = str(status or "").upper()
    if normalized_status in {"EXECUTED_CLEAN", "EXECUTED_CHAOS"}:
        return _STAGE_PROGRESS_MAP[normalized_status]
    normalized_state = str(pre_entry_state or "NONE").upper()
    return _STAGE_PROGRESS_MAP.get(normalized_state, _STAGE_PROGRESS_MAP["NONE"])


def compute_temporal_position(
    *,
    event_emergence_ts: str | None,
    as_of: datetime,
    pre_entry_state: str,
    status: str,
    persistence_count: int,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    active = dict(DEFAULT_TEMPORAL_CONFIG)
    if isinstance(config, dict):
        active.update(
            {
                key: float(value)
                for key, value in config.items()
                if key in active
            }
        )

    age_dt = _parse_dt(event_emergence_ts)
    if age_dt is not None and age_dt.tzinfo is None:
        age_dt = age_dt.replace(tzinfo=timezone.utc)
    age_days = None
    age_component = 0.0
    if age_dt is not None:
        age_days = max(0.0, (as_of - age_dt).total_seconds() / 86400.0)
        age_component = clamp(age_days / max(1.0, active["age_days_cap"]))

    stage_component = stage_progress_proxy(pre_entry_state, status)
    persistence_component = clamp(
        float(max(0, int(persistence_count))) / max(1.0, active["persistence_cap"])
    )
    temporal_position = clamp(
        (active["age_weight"] * age_component)
        + (active["stage_weight"] * stage_component)
        + (active["persistence_weight"] * persistence_component)
    )

    if age_dt is not None and persistence_count > 0:
        confidence_flag = "HIGH"
    elif age_dt is not None:
        confidence_flag = "MEDIUM"
    else:
        confidence_flag = "LOW"

    return {
        "temporal_position": round(temporal_position, 4),
        "temporal_method": TEMPORAL_METHOD,
        "temporal_confidence_flag": confidence_flag,
        "temporal_components": {
            "age_component": round(age_component, 4),
            "stage_component": round(stage_component, 4),
            "persistence_component": round(persistence_component, 4),
        },
        "signal_age_days": round(age_days, 3) if age_days is not None else None,
    }
