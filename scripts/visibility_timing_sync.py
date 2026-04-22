from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    from scripts.crowding_detector import compute_crowding_context
    from scripts.phase_classifier import classify_moon_phase
    from scripts.temporal_position_engine import compute_temporal_position
    from scripts.visibility_engine import compute_light_score, compute_shadow_score
except ModuleNotFoundError:
    from crowding_detector import compute_crowding_context
    from phase_classifier import classify_moon_phase
    from temporal_position_engine import compute_temporal_position
    from visibility_engine import compute_light_score, compute_shadow_score


VISIBILITY_TIMING_METHOD = "MVP_SYNCHRONIZATION_ENGINE_V1"


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(current: float, previous: float | None) -> float:
    if previous is None:
        return 0.0
    return round(float(current) - float(previous), 4)


def build_visibility_timing_context(
    *,
    signal_row: dict[str, Any],
    validation_score: float,
    cross_source_confirmation_score: float,
    source_quality_score: float,
    price_lead_score: float,
    novelty_score: float,
    blocker_clearance_score: float,
    crowding_state: str,
    pre_entry_state: str,
    status: str,
    validation_state: str,
    event_emergence_ts: str | None,
    persistence_count: int,
    as_of: datetime,
    previous_context: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous_context if isinstance(previous_context, dict) else {}
    vt_config = config if isinstance(config, dict) else {}

    light_context = compute_light_score(
        validation_score=validation_score,
        cross_source_confirmation_score=cross_source_confirmation_score,
        source_quality_score=source_quality_score,
        price_lead_score=price_lead_score,
        novelty_score=novelty_score,
        pre_entry_state=pre_entry_state,
        status=status,
        crowding_state=crowding_state,
        persistence_count=persistence_count,
        weights=vt_config.get("light_weights"),
        persistence_cap=int(vt_config.get("persistence_cap", 6) or 6),
    )
    shadow_context = compute_shadow_score(
        light_score=float(light_context["light_score"]),
        validation_state=validation_state,
        blocker_clearance_score=blocker_clearance_score,
    )
    temporal_context = compute_temporal_position(
        event_emergence_ts=event_emergence_ts,
        as_of=as_of,
        pre_entry_state=pre_entry_state,
        status=status,
        persistence_count=persistence_count,
        config=vt_config.get("temporal"),
    )

    previous_light = _coerce_float(previous.get("light_score"))
    previous_shadow = _coerce_float(previous.get("shadow_score"))
    previous_temporal = _coerce_float(previous.get("temporal_position"))

    light_velocity = _delta(float(light_context["light_score"]), previous_light)
    shadow_velocity = _delta(float(shadow_context["shadow_score"]), previous_shadow)
    temporal_velocity = _delta(
        float(temporal_context["temporal_position"]),
        previous_temporal,
    )
    velocity_method = (
        "PRIOR_SIGNAL_REFINERY_CONTEXT_DELTA_V1"
        if previous_light is not None or previous_temporal is not None
        else "NO_HISTORY_BASELINE"
    )

    phase_context = classify_moon_phase(
        light_score=float(light_context["light_score"]),
        light_velocity=light_velocity,
        previous_light_score=previous_light,
        thresholds=vt_config.get("phase_thresholds"),
    )
    crowding_context = compute_crowding_context(
        light_score=float(light_context["light_score"]),
        temporal_position=float(temporal_context["temporal_position"]),
        crowding_state=crowding_state,
        cross_source_confirmation_score=cross_source_confirmation_score,
        novelty_score=novelty_score,
        config=vt_config.get("crowding"),
    )

    visibility_balance = max(
        0.0,
        1.0 - (abs(float(light_context["light_score"]) - 0.45) / 0.55),
    )
    timing_window = max(
        0.0,
        1.0 - (abs(float(temporal_context["temporal_position"]) - 0.4) / 0.6),
    )
    edge_context_score = max(
        0.0,
        min(
            1.0,
            (0.35 * float(validation_score))
            + (0.25 * visibility_balance)
            + (0.20 * timing_window)
            + (0.20 * (1.0 - float(crowding_context["crowding_score"]))),
        ),
    )
    asymmetry_window_flag = (
        float(light_context["light_score"]) >= 0.18
        and float(light_context["light_score"]) <= 0.65
        and float(temporal_context["temporal_position"]) <= 0.65
        and float(crowding_context["crowding_score"]) < 0.6
        and float(validation_score) >= 0.55
    )
    late_obviousness_flag = bool(crowding_context["full_moon_trap_flag"]) or (
        float(light_context["light_score"]) >= 0.75
        and float(temporal_context["temporal_position"]) >= 0.75
    )

    return {
        **light_context,
        **shadow_context,
        **phase_context,
        **temporal_context,
        **crowding_context,
        "light_velocity": round(light_velocity, 4),
        "shadow_velocity": round(shadow_velocity, 4),
        "delta_temporal_position": round(temporal_velocity, 4),
        "velocity_method": velocity_method,
        "edge_context_score": round(edge_context_score, 4),
        "asymmetry_window_flag": asymmetry_window_flag,
        "late_obviousness_flag": late_obviousness_flag,
        "visibility_timing_method": VISIBILITY_TIMING_METHOD,
        "signal_context_id": str(signal_row.get("signal_id") or signal_row.get("ticker") or ""),
    }


def summarize_visibility_timing_context(
    signal_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not signal_rows:
        return {
            "average_light_score": None,
            "average_shadow_score": None,
            "average_temporal_position": None,
            "phase_distribution": {},
            "trap_flag_count": 0,
            "trap_flag_rate": None,
            "context_scored_count": 0,
            "full_context_signal_count": 0,
            "full_context_coverage_ratio": None,
        }

    light_scores = [
        float(row["light_score"])
        for row in signal_rows
        if _coerce_float(row.get("light_score")) is not None
    ]
    shadow_scores = [
        float(row["shadow_score"])
        for row in signal_rows
        if _coerce_float(row.get("shadow_score")) is not None
    ]
    temporal_scores = [
        float(row["temporal_position"])
        for row in signal_rows
        if _coerce_float(row.get("temporal_position")) is not None
    ]
    phase_distribution: dict[str, int] = {}
    trap_count = 0
    full_context_count = 0
    for row in signal_rows:
        phase = str(row.get("moon_phase") or "unknown")
        phase_distribution[phase] = phase_distribution.get(phase, 0) + 1
        if bool(row.get("full_moon_trap_flag")):
            trap_count += 1
        if (
            str(row.get("light_confidence_flag") or "").upper() != "LOW"
            and str(row.get("temporal_confidence_flag") or "").upper() != "LOW"
        ):
            full_context_count += 1

    total = len(signal_rows)
    return {
        "average_light_score": round(sum(light_scores) / len(light_scores), 4)
        if light_scores
        else None,
        "average_shadow_score": round(sum(shadow_scores) / len(shadow_scores), 4)
        if shadow_scores
        else None,
        "average_temporal_position": round(
            sum(temporal_scores) / len(temporal_scores), 4
        )
        if temporal_scores
        else None,
        "phase_distribution": phase_distribution,
        "trap_flag_count": trap_count,
        "trap_flag_rate": round(trap_count / total, 4) if total else None,
        "context_scored_count": total,
        "full_context_signal_count": full_context_count,
        "full_context_coverage_ratio": round(full_context_count / total, 4)
        if total
        else None,
    }
