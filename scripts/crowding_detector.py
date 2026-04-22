from __future__ import annotations

from typing import Any


DEFAULT_CROWDING_CONFIG: dict[str, float] = {
    "full_moon_light_min": 0.80,
    "late_temporal_min": 0.72,
    "trap_score_min": 0.75,
}
CROWDING_METHOD = "FULL_MOON_TRAP_PROXY_V1"

_CROWDING_STATE_SCORE: dict[str, float] = {
    "OPEN": 0.15,
    "HEATING_UP": 0.45,
    "CROWDED": 0.82,
    "ALREADY_EXTENDED": 0.95,
    "EXISTING_EXPOSURE": 0.75,
}


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def compute_crowding_context(
    *,
    light_score: float,
    temporal_position: float,
    crowding_state: str,
    cross_source_confirmation_score: float | None,
    novelty_score: float | None,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    active = dict(DEFAULT_CROWDING_CONFIG)
    if isinstance(config, dict):
        active.update(
            {
                key: float(value)
                for key, value in config.items()
                if key in active
            }
        )

    consensus_proxy = clamp(
        (
            float(cross_source_confirmation_score or 0.0)
            + clamp(1.0 - float(novelty_score or 0.0))
        )
        / 2.0
    )
    state_proxy = _CROWDING_STATE_SCORE.get(
        str(crowding_state or "OPEN").upper(),
        _CROWDING_STATE_SCORE["OPEN"],
    )
    crowding_score = clamp(
        (0.35 * float(light_score))
        + (0.30 * float(temporal_position))
        + (0.20 * state_proxy)
        + (0.15 * consensus_proxy)
    )
    trap_flag = (
        float(light_score) >= active["full_moon_light_min"]
        and float(temporal_position) >= active["late_temporal_min"]
        and crowding_score >= active["trap_score_min"]
    )
    if trap_flag:
        reason = "high_visibility_late_cycle_consensus"
    elif state_proxy >= 0.8:
        reason = "crowding_state_elevated_without_full_trap"
    else:
        reason = "crowding_not_elevated"

    return {
        "crowding_score": round(crowding_score, 4),
        "full_moon_trap_flag": trap_flag,
        "crowding_reason": reason,
        "crowding_method": CROWDING_METHOD,
        "consensus_proxy": round(consensus_proxy, 4),
    }
