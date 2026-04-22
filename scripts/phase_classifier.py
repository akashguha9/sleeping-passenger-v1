from __future__ import annotations

from typing import Any


DEFAULT_PHASE_THRESHOLDS: dict[str, float] = {
    "new_moon_max": 0.10,
    "crescent_max": 0.30,
    "quarter_max": 0.55,
    "gibbous_max": 0.80,
    "full_moon_max": 1.00,
    "waning_decline_min": 0.05,
    "waning_peak_min": 0.55,
}
PHASE_THRESHOLDS_VERSION = "MOON_PHASE_THRESHOLDS_V1"


def classify_moon_phase(
    *,
    light_score: float,
    light_velocity: float | None = None,
    previous_light_score: float | None = None,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    active = dict(DEFAULT_PHASE_THRESHOLDS)
    if isinstance(thresholds, dict):
        active.update(
            {
                key: float(value)
                for key, value in thresholds.items()
                if key in active
            }
        )

    current = float(light_score)
    prior = None if previous_light_score is None else float(previous_light_score)
    velocity = None if light_velocity is None else float(light_velocity)

    if (
        prior is not None
        and prior >= active["waning_peak_min"]
        and (prior - current) >= active["waning_decline_min"]
    ) or (
        velocity is not None
        and velocity <= -active["waning_decline_min"]
        and current < active["full_moon_max"]
    ):
        return {
            "moon_phase": "waning",
            "phase_reason": "visibility_declining_from_prior_peak",
            "phase_thresholds_version": PHASE_THRESHOLDS_VERSION,
        }

    if current < active["new_moon_max"]:
        phase = "new_moon"
    elif current < active["crescent_max"]:
        phase = "crescent"
    elif current < active["quarter_max"]:
        phase = "quarter"
    elif current < active["gibbous_max"]:
        phase = "gibbous"
    else:
        phase = "full_moon"

    return {
        "moon_phase": phase,
        "phase_reason": "static_light_threshold",
        "phase_thresholds_version": PHASE_THRESHOLDS_VERSION,
    }
