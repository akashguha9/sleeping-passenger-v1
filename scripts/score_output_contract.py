"""Shared score-output contract.

Any response that exposes a precise-looking score must attach this contract so
the score can never be read as validated/sizing-grade unless it truly is. The
contract is a small, uniform dict that calibration-aware UIs and tests can rely
on.

Contract fields:
    raw_score            — the model's raw score (or None)
    calibrated_score     — raw_score only when CALIBRATED + sizing-approved,
                           else None (we do not invent a calibrated number)
    calibration_status   — UNCALIBRATED | LOW_SAMPLE | CALIBRATING | CALIBRATED
    sample_size          — reconciled-outcome sample behind the status
    should_drive_sizing  — False unless CALIBRATED and human-approved
    warning              — plain-language caution when not sizing-grade
    human_review_required— always True
    advisory_only        — always True

Pure module. No DB, no network, no broker calls. stdlib only.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.score_calibration import (
        CALIBRATED,
        UNCALIBRATED,
        score_calibration_envelope,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from score_calibration import (  # type: ignore[no-redef]
        CALIBRATED,
        UNCALIBRATED,
        score_calibration_envelope,
    )

# The keys every score contract must carry. Tests assert against this set.
REQUIRED_KEYS: tuple[str, ...] = (
    "raw_score",
    "calibrated_score",
    "calibration_status",
    "sample_size",
    "should_drive_sizing",
    "warning",
    "human_review_required",
    "advisory_only",
)


def build_score_contract(
    raw_score: Any,
    summary: dict[str, Any] | None = None,
    *,
    label: str = "score",
    human_sizing_approved: bool = False,
    calibration_map: Any = None,
) -> dict[str, Any]:
    """Wrap a raw score with calibration metadata.

    ``calibrated_score`` is populated only when the calibration status is
    CALIBRATED *and* a human has approved sizing — otherwise None. We never
    fabricate a calibrated number from an uncalibrated score.

    ``recalibrated_score`` is the OOS-validated recalibration of the raw score
    (isotonic/Platt) when a ``calibration_map`` that improved out of sample is
    supplied — an honest probability, but advisory: it does NOT by itself
    enable sizing (provenance gating still applies).
    """
    env = score_calibration_envelope(raw_score, summary, label=label)
    status = env["score_calibration_status"]
    # should_drive_sizing requires BOTH a calibrated status and explicit human
    # approval. Either alone is insufficient.
    should_drive = bool(env["score_should_drive_sizing"]) and bool(human_sizing_approved)
    calibrated_score = raw_score if (status == CALIBRATED and should_drive) else None

    recalibrated_score = None
    recalibration_method = None
    if calibration_map is not None and getattr(calibration_map, "improved", False):
        try:
            recalibrated_score = round(float(calibration_map.apply(float(raw_score))), 6)
            recalibration_method = getattr(calibration_map, "method", None)
        except (TypeError, ValueError):
            recalibrated_score = None

    return {
        "label": label,
        "raw_score": raw_score,
        "calibrated_score": calibrated_score,
        "recalibrated_score": recalibrated_score,
        "recalibration_method": recalibration_method,
        "calibration_status": status,
        "sample_size": env["score_sample_size"],
        "should_drive_sizing": should_drive,
        "warning": env["warning"],
        "human_review_required": True,
        "advisory_only": True,
        "broker_api_called": False,
    }


def has_score_contract(payload: Any) -> bool:
    """True iff ``payload`` is a dict carrying every required contract key."""
    return isinstance(payload, dict) and all(k in payload for k in REQUIRED_KEYS)


def assert_score_contract(payload: Any) -> None:
    """Raise AssertionError if the payload lacks the score contract."""
    assert isinstance(payload, dict), "score contract must be a dict"
    missing = [k for k in REQUIRED_KEYS if k not in payload]
    assert not missing, f"score output missing calibration contract keys: {missing}"
    assert payload["advisory_only"] is True
    assert payload["human_review_required"] is True
    # An uncalibrated/low-sample score must never claim to drive sizing.
    if payload["calibration_status"] != CALIBRATED:
        assert payload["should_drive_sizing"] is False
        assert payload["calibrated_score"] is None


__all__ = [
    "REQUIRED_KEYS",
    "build_score_contract",
    "has_score_contract",
    "assert_score_contract",
    "UNCALIBRATED",
    "CALIBRATED",
]
