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
from typing import Any


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


def detect_t1_event_prior(*_args: Any, **_kwargs: Any) -> DetectorResult:
    """T1: probability delta + z-score + volume floor. NOT IMPLEMENTED.

    The existing scripts/event_prior_detector.py performs time-clustering only;
    it does NOT satisfy this T1 specification. Fail-closed.
    """
    return _unavailable("T1_event_prior", "prob delta + z-score + volume floor")


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
    """Return an honest readiness summary: every detector unavailable."""
    results = [fn() for fn in ALL_DETECTORS]
    return {
        "any_detector_available": any(r.available for r in results),
        "implemented_count": sum(1 for r in results if r.available),
        "total_detectors": len(results),
        "detectors": {r.detector: r.status for r in results},
        "note": "All chronology detectors are NOT_IMPLEMENTED and fail closed.",
    }
