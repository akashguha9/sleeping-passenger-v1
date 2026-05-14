"""Signal field geometry diagnostic — pure, deterministic, advisory-only.

This module is the engineering translation of the reflection's
"pendulum field" + "digital signs" metaphors. It does **not** predict
the future and it does **not** claim that a pattern is the truth. It
labels the observable trace and the geometry of a small collection of
signals so the operator can decide whether to look closer.

Safety contract (every public output)

    output["safety"]["advisory_status"]     == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]      == "LOCKED"
    output["safety"]["broker_api_called"]   is False
    output["safety"]["ai_execution_count"]  == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]         is False

Public API

    classify_signal_trace(trace)             -> dict
    compute_phase_alignment(signals)         -> dict
    compute_resonance_score(signals)         -> dict
    compute_damping_score(signal)            -> dict
    classify_field_geometry(signals)         -> dict

The module is pure: no DB, no live API, no filesystem writes, no
imports of broker or AI execution code.
"""

from __future__ import annotations

from typing import Any, Iterable

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

FIELD_GEOMETRY_LABELS: tuple[str, ...] = (
    "CONVERGENT",
    "DIVERGENT",
    "RESONANT",
    "DAMPING",
    "SPIKING",
    "ECHOING",
    "FAN_OUT",
    "COMPRESSING",
    "CHAOTIC",
    "INSUFFICIENT_DATA",
)

TRACE_LABELS: tuple[str, ...] = (
    "frequency_spike",
    "velocity_spike",
    "acceleration_spike",
    "repetition_echo",
    "absence_gap",
    "timing_anomaly",
    "directional_move",
    "low_signal",
    "unknown",
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
    if x != x:  # NaN guard
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


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _direction(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"up", "bull", "bullish", "long", "+", "1"}:
            return 1
        if lowered in {"down", "bear", "bearish", "short", "-", "-1"}:
            return -1
        return 0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def classify_signal_trace(trace: dict[str, Any] | None) -> dict[str, Any]:
    """Classify a single observable trace.

    The function never raises on bad input. Missing fields default to
    neutral values and the function returns ``"low_signal"`` rather
    than guessing.
    """
    data = trace if isinstance(trace, dict) else {}

    narrative_intensity = _clamp(data.get("narrative_intensity"))
    attention_velocity = _clamp(data.get("attention_velocity"))
    price_velocity = _clamp(data.get("price_velocity"))
    acceleration = _clamp(data.get("acceleration"))
    mention_count = _coerce_int(data.get("mention_count"))
    repetition_count = _coerce_int(data.get("repetition_count"))
    independent_source_count = _coerce_int(data.get("independent_source_count"))
    expected_confirmation_count = _coerce_int(
        data.get("expected_confirmation_count")
    )
    actual_confirmation_count = _coerce_int(data.get("actual_confirmation_count"))
    emotional_language_score = _clamp(data.get("emotional_language_score"))
    source_reliability = _clamp(data.get("source_reliability"), 0.0, 1.0)
    freshness_score = _clamp(data.get("freshness_score"), 0.0, 1.0)
    contradiction_score = _clamp(data.get("contradiction_score"), 0.0, 1.0)
    market_confirmation = _clamp(data.get("market_confirmation"), 0.0, 1.0)

    timestamp = _coerce_float(data.get("timestamp"))
    previous_timestamp = _coerce_float(data.get("previous_timestamp"))
    timing_gap = abs(timestamp - previous_timestamp) if timestamp and previous_timestamp else 0.0

    reasons: list[str] = []

    # Repetition echo: many mentions, few independent sources
    if mention_count >= 3 and independent_source_count <= 1:
        label = "repetition_echo"
        reasons.append("high_mentions_low_independent_sources")
    # Absence gap: expected confirmation but missing
    elif expected_confirmation_count > 0 and actual_confirmation_count < expected_confirmation_count:
        label = "absence_gap"
        reasons.append("expected_confirmation_not_observed")
    # Acceleration spike
    elif acceleration >= 0.7:
        label = "acceleration_spike"
        reasons.append("acceleration_above_threshold")
    # Velocity spike (price + confirmation)
    elif price_velocity >= 0.6 and market_confirmation >= 0.5:
        label = "velocity_spike"
        reasons.append("price_velocity_with_confirmation")
    # Frequency spike (attention/mentions)
    elif attention_velocity >= 0.7 or (mention_count >= 5 and narrative_intensity >= 0.5):
        label = "frequency_spike"
        reasons.append("attention_or_mention_surge")
    # Timing anomaly
    elif timing_gap > 0 and previous_timestamp and timing_gap < 1e-6:
        label = "timing_anomaly"
        reasons.append("simultaneous_timestamps")
    # Directional move
    elif _direction(data.get("direction")) != 0 and price_velocity >= 0.3:
        label = "directional_move"
        reasons.append("clear_direction_with_movement")
    # Low signal fallback
    elif (
        mention_count == 0
        and price_velocity == 0
        and attention_velocity == 0
        and narrative_intensity == 0
    ):
        label = "low_signal"
        reasons.append("no_observable_inputs")
    else:
        label = "unknown"
        reasons.append("inputs_inconclusive")

    persistence = _clamp(data.get("persistence_score"), 0.0, 1.0)
    source_diversity = _clamp(
        independent_source_count / 5.0 if independent_source_count else 0.0
    )
    digital_sign_strength = _clamp(
        max(narrative_intensity, attention_velocity, price_velocity)
        * (0.5 + 0.5 * source_reliability)
        * (0.5 + 0.5 * freshness_score)
        * (0.5 + 0.5 * source_diversity)
        * (0.5 + 0.5 * persistence)
    )
    signal_energy = _clamp(
        0.5 * max(narrative_intensity, attention_velocity, price_velocity)
        + 0.25 * source_reliability
        + 0.25 * freshness_score
        - 0.25 * contradiction_score
    )

    absence_signal = 0.0
    if expected_confirmation_count > 0:
        gap = expected_confirmation_count - actual_confirmation_count
        absence_signal = _clamp(gap / max(expected_confirmation_count, 1))

    timing_integrity_score = 1.0
    if previous_timestamp and timestamp and timing_gap < 1e-6:
        timing_integrity_score = 0.0
        reasons.append("timing_integrity_risk")
    timing_integrity_score = _clamp(timing_integrity_score)

    pattern_overfit_risk = _clamp(
        emotional_language_score
        * (1.0 - source_reliability)
        * (1.0 - source_diversity)
    )

    evidence_quality_score = _clamp(
        0.4 * source_reliability
        + 0.3 * source_diversity
        + 0.2 * market_confirmation
        + 0.1 * freshness_score
        - 0.2 * contradiction_score
        - 0.2 * pattern_overfit_risk
    )

    hypothesis_only = (
        evidence_quality_score < 0.5
        or pattern_overfit_risk >= 0.5
        or independent_source_count <= 1
        or label in {"repetition_echo", "absence_gap", "low_signal", "unknown"}
    )

    if label == "repetition_echo":
        operator_action = "decay_archive"
    elif label == "absence_gap":
        operator_action = "review_later"
    elif label in {"velocity_spike", "acceleration_spike"} and not hypothesis_only:
        operator_action = "review_candidate"
    elif label == "low_signal":
        operator_action = "observe"
    elif hypothesis_only:
        operator_action = "watch"
    else:
        operator_action = "watch"

    return _stamp({
        "digital_sign_type": label,
        "digital_sign_strength": round(digital_sign_strength, 4),
        "signal_energy": round(signal_energy, 4),
        "absence_confirmation_gap": round(absence_signal, 4),
        "timing_integrity_score": round(timing_integrity_score, 4),
        "hypothesis_only": bool(hypothesis_only),
        "evidence_quality_score": round(evidence_quality_score, 4),
        "pattern_overfit_risk": round(pattern_overfit_risk, 4),
        "operator_action": operator_action,
        "reasons": reasons,
    })


def _collect_signals(signals: Any) -> list[dict[str, Any]]:
    if not isinstance(signals, list):
        return []
    return [s for s in signals if isinstance(s, dict)]


def compute_phase_alignment(signals: Any) -> dict[str, Any]:
    rows = _collect_signals(signals)
    if not rows:
        return _stamp({
            "phase_alignment_score": 0.0,
            "signal_count": 0,
            "direction_balance": 0.0,
            "reasons": ["no_signals"],
        })
    directions = [_direction(s.get("direction")) for s in rows]
    nonzero = [d for d in directions if d != 0]
    if not nonzero:
        return _stamp({
            "phase_alignment_score": 0.0,
            "signal_count": len(rows),
            "direction_balance": 0.0,
            "reasons": ["no_directional_signals"],
        })
    pos = sum(1 for d in nonzero if d > 0)
    neg = sum(1 for d in nonzero if d < 0)
    total = pos + neg
    balance = abs(pos - neg) / total
    intensities = [_clamp(s.get("intensity")) for s in rows]
    mean_intensity = sum(intensities) / len(intensities) if intensities else 0.0
    alignment = _clamp(balance * (0.5 + 0.5 * mean_intensity))
    return _stamp({
        "phase_alignment_score": round(alignment, 4),
        "signal_count": len(rows),
        "direction_balance": round(balance, 4),
        "mean_intensity": round(mean_intensity, 4),
        "reasons": [],
    })


def compute_resonance_score(signals: Any) -> dict[str, Any]:
    rows = _collect_signals(signals)
    if not rows:
        return _stamp({
            "resonance_score": 0.0,
            "signal_count": 0,
            "reasons": ["no_signals"],
        })
    alignment = compute_phase_alignment(rows)["phase_alignment_score"]
    narrative_charges = [_clamp(s.get("narrative_charge")) for s in rows]
    intensities = [_clamp(s.get("intensity")) for s in rows]
    confirmations = [_clamp(s.get("confirmation")) for s in rows]
    mean_charge = sum(narrative_charges) / len(narrative_charges)
    mean_intensity = sum(intensities) / len(intensities) if intensities else 0.0
    mean_confirmation = sum(confirmations) / len(confirmations) if confirmations else 0.0
    resonance = _clamp(
        alignment
        * (0.4 + 0.3 * mean_charge + 0.3 * max(mean_intensity, mean_confirmation))
    )
    return _stamp({
        "resonance_score": round(resonance, 4),
        "signal_count": len(rows),
        "mean_narrative_charge": round(mean_charge, 4),
        "mean_intensity": round(mean_intensity, 4),
        "mean_confirmation": round(mean_confirmation, 4),
        "reasons": [],
    })


def compute_damping_score(signal: Any) -> dict[str, Any]:
    data = signal if isinstance(signal, dict) else {}
    age_hours = _coerce_float(data.get("age_hours"))
    freshness = _clamp(data.get("freshness_score"), 0.0, 1.0)
    contradiction = _clamp(data.get("contradiction_score"), 0.0, 1.0)
    confirmation = _clamp(data.get("confirmation"), 0.0, 1.0)
    half_life_hours = max(_coerce_float(data.get("half_life_hours"), 24.0), 0.1)
    # signal strength decays like exp(-ln(2) * age / halflife)
    import math
    decay_factor = math.exp(-math.log(2.0) * (age_hours / half_life_hours)) if age_hours else 1.0
    damping = _clamp(
        (1.0 - decay_factor)
        * (1.0 - 0.5 * confirmation)
        + 0.5 * contradiction
        - 0.25 * freshness
    )
    return _stamp({
        "damping_score": round(damping, 4),
        "decay_factor": round(decay_factor, 4),
        "age_hours": round(age_hours, 4),
        "half_life_hours": round(half_life_hours, 4),
        "reasons": [],
    })


def classify_field_geometry(signals: Any) -> dict[str, Any]:
    rows = _collect_signals(signals)
    if not rows:
        return _stamp({
            "field_geometry_label": "INSUFFICIENT_DATA",
            "geometry_confidence": 0.0,
            "signal_count": 0,
            "phase_alignment_score": 0.0,
            "resonance_score": 0.0,
            "damping_score": 0.0,
            "operator_action": "observe",
            "reasons": ["no_signals"],
            "recommendation": "observe",
        })

    if len(rows) == 1:
        single = rows[0]
        intensity = _clamp(single.get("intensity"))
        narrative = _clamp(single.get("narrative_charge"))
        label = "SPIKING" if (intensity >= 0.7 or narrative >= 0.7) else "INSUFFICIENT_DATA"
        damping = compute_damping_score(single)
        return _stamp({
            "field_geometry_label": label,
            "geometry_confidence": round(_clamp(0.3 + 0.4 * intensity), 4),
            "signal_count": 1,
            "phase_alignment_score": 0.0,
            "resonance_score": 0.0,
            "damping_score": damping["damping_score"],
            "operator_action": "watch" if label == "SPIKING" else "observe",
            "reasons": ["single_signal"],
            "recommendation": "watch" if label == "SPIKING" else "observe",
        })

    alignment = compute_phase_alignment(rows)
    resonance = compute_resonance_score(rows)
    damping_scores = [compute_damping_score(s)["damping_score"] for s in rows]
    mean_damping = sum(damping_scores) / len(damping_scores) if damping_scores else 0.0

    directions = [_direction(s.get("direction")) for s in rows]
    nonzero = [d for d in directions if d != 0]
    pos = sum(1 for d in nonzero if d > 0)
    neg = sum(1 for d in nonzero if d < 0)

    intensities = [_clamp(s.get("intensity")) for s in rows]
    mean_intensity = sum(intensities) / len(intensities) if intensities else 0.0
    intensity_spread = (max(intensities) - min(intensities)) if intensities else 0.0

    sources = [str(s.get("source_name") or s.get("source") or "") for s in rows]
    unique_sources = len({s for s in sources if s})
    repetition_ratio = (
        1.0 - (unique_sources / len(rows)) if rows else 0.0
    )

    reasons: list[str] = []

    if repetition_ratio >= 0.6 and unique_sources <= 1:
        label = "ECHOING"
        reasons.append("low_source_diversity")
    elif mean_damping >= 0.6 and mean_intensity <= 0.3:
        label = "DAMPING"
        reasons.append("high_damping_low_intensity")
    elif resonance["resonance_score"] >= 0.6 and alignment["phase_alignment_score"] >= 0.6:
        label = "RESONANT"
        reasons.append("aligned_high_resonance")
    elif alignment["phase_alignment_score"] >= 0.6:
        label = "CONVERGENT"
        reasons.append("directional_agreement")
    elif pos > 0 and neg > 0 and abs(pos - neg) <= 1:
        label = "DIVERGENT"
        reasons.append("opposing_directions")
    elif mean_intensity >= 0.7 and intensity_spread >= 0.4:
        label = "SPIKING"
        reasons.append("high_intensity_with_spread")
    elif intensity_spread >= 0.5 and len(rows) >= 3:
        label = "FAN_OUT"
        reasons.append("dispersed_intensities")
    elif intensity_spread <= 0.1 and mean_intensity >= 0.4:
        label = "COMPRESSING"
        reasons.append("tight_intensity_band")
    elif mean_intensity == 0.0 and alignment["phase_alignment_score"] == 0.0:
        label = "INSUFFICIENT_DATA"
        reasons.append("no_directional_or_intensity_information")
    else:
        label = "CHAOTIC"
        reasons.append("mixed_signals_without_clear_geometry")

    geometry_confidence = _clamp(
        0.3
        + 0.3 * alignment["phase_alignment_score"]
        + 0.2 * resonance["resonance_score"]
        + 0.2 * (unique_sources / max(len(rows), 1))
    )

    recommendation = {
        "RESONANT": "review_candidate",
        "CONVERGENT": "watch",
        "DIVERGENT": "watch",
        "ECHOING": "decay_archive",
        "DAMPING": "decay_archive",
        "SPIKING": "watch",
        "FAN_OUT": "watch",
        "COMPRESSING": "watch",
        "CHAOTIC": "observe",
        "INSUFFICIENT_DATA": "observe",
    }.get(label, "observe")

    return _stamp({
        "field_geometry_label": label,
        "geometry_confidence": round(geometry_confidence, 4),
        "signal_count": len(rows),
        "phase_alignment_score": alignment["phase_alignment_score"],
        "resonance_score": resonance["resonance_score"],
        "damping_score": round(mean_damping, 4),
        "operator_action": recommendation,
        "recommendation": recommendation,
        "reasons": reasons,
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "FIELD_GEOMETRY_LABELS",
    "TRACE_LABELS",
    "classify_signal_trace",
    "compute_phase_alignment",
    "compute_resonance_score",
    "compute_damping_score",
    "classify_field_geometry",
]
