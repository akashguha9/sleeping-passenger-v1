"""Chronology T1–T4 detector interfaces — NOT IMPLEMENTED (fail-closed).

HONESTY NOTE:
    None of the specified chronology detectors (T1 event-prior, T2 asset
    attachment, T3 commitment, T4 market confirmation) is implemented. This
    module exists ONLY to give those detectors a typed, fail-closed interface
    so that:
      * no caller can mistake the existing time-clustering helper
        (scripts/event_prior_detector.py) for the specified T1 logic, and
      * any premature call returns a structured "unavailable" result instead
        of fabricating a detection.

    Each detector returns ``DetectorResult(available=False, ...)``. There is no
    synthetic fallback. Readiness is observation-gated — see
    docs/CHRONOLOGY_OBSERVATION_READINESS.md.

This module runs no inference, reads no data, and authorizes no action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class DetectorResult:
    """Structured detector outcome.

    ``available`` is False for every detector in this module today. ``detected``
    is therefore always False (a detector that cannot run never claims a hit).
    """

    detector: str
    available: bool
    detected: bool
    status: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

# T1 thresholds. Conservative defaults; tune only with forward-observed data.
T1_PROB_DELTA_FLOOR = 0.05   # minimum probability jump on the latest step
T1_Z_FLOOR = 2.0             # latest step must be >= 2 sigma vs prior steps
T1_VOLUME_FLOOR = 1.0        # minimum traded volume to consider the step real
T1_MIN_PRIOR_SAMPLE = 5      # prior step-changes needed to compute a z-score


def _unavailable(detector: str, spec: str) -> DetectorResult:
    return DetectorResult(
        detector=detector,
        available=False,
        detected=False,
        status=_NOT_IMPLEMENTED,
        reason=(
            f"{detector} ({spec}) is not implemented. Returns unavailable by "
            "design — no synthetic fallback. Readiness is observation-gated."
        ),
        evidence={},
    )


def _t1_insufficient(reason: str, evidence: dict[str, Any]) -> DetectorResult:
    """T1 is implemented but fails CLOSED when inputs are inadequate."""
    return DetectorResult(
        detector="T1_event_prior",
        available=True,
        detected=False,
        status="INSUFFICIENT_DATA",
        reason=reason,
        evidence=evidence,
    )


def detect_t1_event_prior(
    observation: Mapping[str, Any] | None = None,
    *,
    prob_delta_floor: float = T1_PROB_DELTA_FLOOR,
    z_floor: float = T1_Z_FLOOR,
    volume_floor: float = T1_VOLUME_FLOOR,
    min_prior_sample: int = T1_MIN_PRIOR_SAMPLE,
) -> DetectorResult:
    """T1 event-prior detector — REAL, observation-only, fail-closed.

    Fires only when the LATEST probability step in ``prob_series`` is both
    large (>= ``prob_delta_floor``) and statistically anomalous (z-score of the
    latest step vs the distribution of prior steps >= ``z_floor``) AND the
    observation clears the volume floor. Requires >= ``min_prior_sample`` prior
    step-changes; otherwise returns INSUFFICIENT_DATA. Never fabricates a
    detection, never authorizes any action, never emits BUY/ENTER.

    Expected ``observation`` fields:
        prob_series: list[float]  (chronological probabilities)
        volume:      float
    """
    if not observation:
        return _t1_insufficient("no observation provided", {})

    prob_series = observation.get("prob_series")
    if not isinstance(prob_series, (list, tuple)):
        return _t1_insufficient("prob_series missing or not a sequence", {})

    try:
        series = [float(x) for x in prob_series]
    except (TypeError, ValueError):
        return _t1_insufficient("prob_series contains non-numeric values", {})

    volume_raw = observation.get("volume")
    try:
        volume = float(volume_raw)
    except (TypeError, ValueError):
        return _t1_insufficient("volume missing or non-numeric", {"volume": volume_raw})

    # Successive step-changes; the last is the candidate step, the rest are the
    # prior baseline distribution.
    deltas = [series[i + 1] - series[i] for i in range(len(series) - 1)]
    if len(deltas) < min_prior_sample + 1:
        return _t1_insufficient(
            f"need >= {min_prior_sample + 1} steps for z-score, got {len(deltas)}",
            {"step_count": len(deltas)},
        )

    current = deltas[-1]
    prior = deltas[:-1]
    mean = sum(prior) / len(prior)
    variance = sum((d - mean) ** 2 for d in prior) / len(prior)
    std = variance ** 0.5
    if std == 0.0:
        return _t1_insufficient(
            "prior step variance is zero; z-score undefined", {"prior_mean": mean}
        )

    z_score = (current - mean) / std
    prob_delta = current

    evidence = {
        "prob_delta": round(prob_delta, 6),
        "z_score": round(z_score, 4),
        "volume": volume,
        "prob_delta_floor": prob_delta_floor,
        "z_floor": z_floor,
        "volume_floor": volume_floor,
        "prior_sample": len(prior),
    }

    detected = (
        prob_delta >= prob_delta_floor
        and z_score >= z_floor
        and volume >= volume_floor
    )
    if detected:
        return DetectorResult(
            detector="T1_event_prior",
            available=True,
            detected=True,
            status="FIRED",
            reason="probability step cleared delta, z-score, and volume floors",
            evidence=evidence,
        )

    failed = []
    if prob_delta < prob_delta_floor:
        failed.append("prob_delta_below_floor")
    if z_score < z_floor:
        failed.append("z_score_below_floor")
    if volume < volume_floor:
        failed.append("volume_below_floor")
    return DetectorResult(
        detector="T1_event_prior",
        available=True,
        detected=False,
        status="NO_FIRE",
        reason="; ".join(failed),
        evidence=evidence,
    )


def detect_t2_asset_attachment(*_args: Any, **_kwargs: Any) -> DetectorResult:
    """T2: asset attachment. NOT IMPLEMENTED. Fail-closed."""
    return _unavailable("T2_asset_attachment", "asset attachment")


def detect_t3_commitment(*_args: Any, **_kwargs: Any) -> DetectorResult:
    """T3: commitment. NOT IMPLEMENTED. Fail-closed."""
    return _unavailable("T3_commitment", "commitment")


def detect_t4_market_confirmation(*_args: Any, **_kwargs: Any) -> DetectorResult:
    """T4: market confirmation. NOT IMPLEMENTED. Fail-closed."""
    return _unavailable("T4_market_confirmation", "market confirmation")


ALL_DETECTORS = (
    detect_t1_event_prior,
    detect_t2_asset_attachment,
    detect_t3_commitment,
    detect_t4_market_confirmation,
)


def detector_readiness_summary() -> dict[str, Any]:
    """Return an honest readiness summary.

    T1 is implemented (observation-only, fails closed on inadequate data);
    T2/T3/T4 remain NOT_IMPLEMENTED. Calling each with no args exercises the
    fail-closed path for the summary.
    """
    results = [fn() for fn in ALL_DETECTORS]
    return {
        "any_detector_available": any(r.available for r in results),
        "implemented_count": sum(1 for r in results if r.available),
        "total_detectors": len(results),
        "detectors": {r.detector: r.status for r in results},
        "note": (
            "T1 implemented (observation-only, fail-closed); T2/T3/T4 "
            "NOT_IMPLEMENTED. No detector authorizes any action."
        ),
    }
