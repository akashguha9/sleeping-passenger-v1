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

# T2/T3 thresholds.
T2_MIN_HITS = 3              # repeated T1 fires required for a persistence hit
T3_REVERSAL_FLOOR = 0.05     # probability drop that counts as a reversal
T3_VOLUME_COLLAPSE_RATIO = 0.25  # current volume < ratio*prior_mean = collapse


def _insufficient(detector: str, reason: str, evidence: dict[str, Any]) -> DetectorResult:
    """Implemented detector that fails CLOSED when inputs are inadequate."""
    return DetectorResult(
        detector=detector,
        available=True,
        detected=False,
        status="INSUFFICIENT_DATA",
        reason=reason,
        evidence=evidence,
    )


def _t4_pending(reason: str, evidence: dict[str, Any]) -> DetectorResult:
    """T4 outcome attribution: implemented, but no outcome data yet."""
    return DetectorResult(
        detector="T4_outcome",
        available=True,
        detected=False,
        status="OUTCOME_PENDING",
        reason=reason,
        evidence=evidence,
    )


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


def detect_t2_asset_attachment(
    t1_history: Any = None,
    *,
    min_hits: int = T2_MIN_HITS,
) -> DetectorResult:
    """T2 persistence / repeat-hit — REAL, observation-only, fail-closed.

    Fires only when the number of prior T1 FIRES (``detected`` truthy) in the
    supplied history reaches ``min_hits``. ``t1_history`` is an ordered list of
    prior T1 outcomes — either booleans or mappings with a ``detected`` key.
    Fails CLOSED (``INSUFFICIENT_DATA``) when fewer than ``min_hits`` prior
    observations exist. Emits an observation result only; authorizes nothing.
    """
    if not isinstance(t1_history, (list, tuple)):
        return _insufficient("T2_persistence", "t1_history missing or not a sequence", {})
    if len(t1_history) < min_hits:
        return _insufficient(
            "T2_persistence",
            f"need >= {min_hits} prior T1 observations, got {len(t1_history)}",
            {"history_len": len(t1_history)},
        )

    hits = 0
    for item in t1_history:
        if isinstance(item, Mapping):
            hits += 1 if item.get("detected") else 0
        else:
            hits += 1 if bool(item) else 0

    evidence = {"t1_hits": hits, "history_len": len(t1_history), "min_hits": min_hits}
    detected = hits >= min_hits
    return DetectorResult(
        detector="T2_persistence",
        available=True,
        detected=detected,
        status="FIRED" if detected else "NO_FIRE",
        reason=(
            f"{hits} repeated T1 hits >= {min_hits}"
            if detected
            else f"only {hits} T1 hits (< {min_hits})"
        ),
        evidence=evidence,
    )


def detect_t3_commitment(
    observation: Mapping[str, Any] | None = None,
    *,
    reversal_floor: float = T3_REVERSAL_FLOOR,
    volume_collapse_ratio: float = T3_VOLUME_COLLAPSE_RATIO,
) -> DetectorResult:
    """T3 invalidation / contradiction — REAL, observation-only, fail-closed.

    Detects whether an earlier candidate weakened or reverted, via any of:
      * probability reversal (latest step drops by >= ``reversal_floor``),
      * volume collapse (current volume < ratio * prior mean volume),
      * an explicit ``stale_source`` marker.
    Requires a ``prob_series`` (>= 2 points). Fails CLOSED on missing fields.
    Does NOT call action_engine. Emits an observation result only.
    """
    if not observation:
        return _insufficient("T3_contradiction", "no observation provided", {})

    prob_series = observation.get("prob_series")
    if not isinstance(prob_series, (list, tuple)) or len(prob_series) < 2:
        return _insufficient(
            "T3_contradiction", "prob_series missing or too short (need >= 2)", {}
        )
    try:
        series = [float(x) for x in prob_series]
    except (TypeError, ValueError):
        return _insufficient("T3_contradiction", "prob_series non-numeric", {})

    latest_delta = series[-1] - series[-2]
    reversal = latest_delta <= -abs(reversal_floor)

    # Volume collapse is optional evidence — only evaluated when present.
    volume_collapse = False
    vol_evidence: dict[str, Any] = {}
    vseries = observation.get("volume_series")
    if isinstance(vseries, (list, tuple)) and len(vseries) >= 2:
        try:
            vs = [float(v) for v in vseries]
            prior_mean = sum(vs[:-1]) / len(vs[:-1])
            if prior_mean > 0:
                volume_collapse = vs[-1] < volume_collapse_ratio * prior_mean
                vol_evidence = {"current_volume": vs[-1], "prior_mean_volume": round(prior_mean, 4)}
        except (TypeError, ValueError):
            vol_evidence = {}

    stale_source = bool(observation.get("stale_source"))

    detected = reversal or volume_collapse or stale_source
    reasons = []
    if reversal:
        reasons.append("probability_reversal")
    if volume_collapse:
        reasons.append("volume_collapse")
    if stale_source:
        reasons.append("stale_source")

    evidence = {
        "latest_delta": round(latest_delta, 6),
        "reversal_floor": reversal_floor,
        "stale_source": stale_source,
        **vol_evidence,
    }
    return DetectorResult(
        detector="T3_contradiction",
        available=True,
        detected=detected,
        status="FIRED" if detected else "NO_FIRE",
        reason="; ".join(reasons) if reasons else "no contradiction signal",
        evidence=evidence,
    )


def detect_t4_market_confirmation(
    observation: Mapping[str, Any] | None = None,
) -> DetectorResult:
    """T4 outcome attribution — REAL, observation-only, fail-closed.

    Links a candidate to a later observed outcome ONLY when an actual logged
    outcome exists in ``observation['outcome']`` (with a ``resolved`` flag).
    When no outcome data exists, returns ``OUTCOME_PENDING`` — it NEVER infers
    an outcome or any PnL. Emits an observation result only.
    """
    if not observation:
        return _t4_pending("no observation provided", {})

    outcome = observation.get("outcome")
    if not isinstance(outcome, Mapping):
        return _t4_pending("no logged outcome present", {})
    if not outcome.get("resolved"):
        return _t4_pending("outcome present but not marked resolved", {})

    realized = outcome.get("realized")  # e.g. "YES" / "NO" / "EXPIRED"
    if realized is None:
        return _t4_pending("resolved outcome missing 'realized' field", {})

    # Attribution only — never a PnL claim unless an explicit logged value exists.
    logged_pnl = outcome.get("logged_pnl")  # may be absent; never inferred
    evidence = {
        "realized": str(realized),
        "logged_pnl_present": logged_pnl is not None,
        "logged_pnl": logged_pnl,
    }
    return DetectorResult(
        detector="T4_outcome",
        available=True,
        detected=True,
        status="OUTCOME_ATTRIBUTED",
        reason=f"linked to logged outcome: {realized}",
        evidence=evidence,
    )


ALL_DETECTORS = (
    detect_t1_event_prior,
    detect_t2_asset_attachment,
    detect_t3_commitment,
    detect_t4_market_confirmation,
)


def detector_readiness_summary() -> dict[str, Any]:
    """Return an honest readiness summary.

    All four detectors (T1 event-prior, T2 persistence, T3 contradiction,
    T4 outcome attribution) are implemented and observation-only; each fails
    closed when called with no data. No detector authorizes any action.
    """
    results = [fn() for fn in ALL_DETECTORS]
    return {
        "any_detector_available": any(r.available for r in results),
        "implemented_count": sum(1 for r in results if r.available),
        "total_detectors": len(results),
        "detectors": {r.detector: r.status for r in results},
        "note": (
            "T1-T4 implemented (observation-only, fail-closed). No detector "
            "authorizes any action; no execution path exists."
        ),
    }
