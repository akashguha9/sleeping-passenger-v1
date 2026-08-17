"""Canonical calibration honesty layer.

Most numeric scores in this MVP are not calibrated against external
outcome labels. This module names that fact precisely so callers
cannot accidentally treat a heuristic threshold as decision-ready.

States — exactly:

    CALIBRATED                 — empirical labels + out-of-sample check
    UNCALIBRATED_HEURISTIC     — heuristic only, no outcome backing
    ARBITRARY_THRESHOLD        — threshold chosen by hand
    INSUFFICIENT_SAMPLES       — labels exist but sample size is too low
    REQUIRES_EXTERNAL_LABELS   — labels are explicitly missing
    DEMO_ONLY                  — applies to seeded/demo runtimes only

Rules — enforced in ``classify_calibration_status``:

    * A score with no outcome labels at all is ``UNCALIBRATED_HEURISTIC``.
    * A threshold without sample/outcome backing is ``ARBITRARY_THRESHOLD``.
    * A score with labels but below the minimum sample size is
      ``INSUFFICIENT_SAMPLES``.
    * Only ``CALIBRATED`` may support capital permission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class CalibrationStatus(str, Enum):
    CALIBRATED = "CALIBRATED"
    UNCALIBRATED_HEURISTIC = "UNCALIBRATED_HEURISTIC"
    ARBITRARY_THRESHOLD = "ARBITRARY_THRESHOLD"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    REQUIRES_EXTERNAL_LABELS = "REQUIRES_EXTERNAL_LABELS"
    DEMO_ONLY = "DEMO_ONLY"


CALIBRATION_DEFAULT_MIN_SAMPLES: int = 30
CALIBRATION_DEFAULT_THRESHOLD_MIN_SAMPLES: int = 50


def _allows_capital(status: CalibrationStatus) -> bool:
    return status == CalibrationStatus.CALIBRATED


@dataclass(frozen=True)
class CalibrationReport:
    score_name: str
    status: CalibrationStatus
    sample_count: int
    has_outcome_labels: bool
    is_threshold: bool
    threshold_value: float | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def supports_capital_permission(self) -> bool:
        return _allows_capital(self.status)

    @property
    def supports_decision_ready_claim(self) -> bool:
        return self.status == CalibrationStatus.CALIBRATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "score_name": self.score_name,
            "status": self.status.value,
            "sample_count": int(self.sample_count),
            "has_outcome_labels": bool(self.has_outcome_labels),
            "is_threshold": bool(self.is_threshold),
            "threshold_value": (
                None if self.threshold_value is None else float(self.threshold_value)
            ),
            "notes": list(self.notes),
            "supports_capital_permission": self.supports_capital_permission,
            "supports_decision_ready_claim": self.supports_decision_ready_claim,
        }


def classify_calibration_status(
    *,
    score_name: str,
    has_outcome_labels: bool,
    sample_count: int = 0,
    is_threshold: bool = False,
    threshold_value: float | None = None,
    runtime_mode: str = "",
    min_samples: int = CALIBRATION_DEFAULT_MIN_SAMPLES,
    min_threshold_samples: int = CALIBRATION_DEFAULT_THRESHOLD_MIN_SAMPLES,
) -> CalibrationReport:
    """Classify a single score / threshold by its calibration state."""

    notes: list[str] = []
    sample_count = int(max(0, sample_count))
    runtime_mode_upper = str(runtime_mode or "").strip().upper()

    if runtime_mode_upper in {"SEEDED", "DEMO"}:
        notes.append(
            f"runtime_mode={runtime_mode_upper}: scores tagged DEMO_ONLY because no"
            " external outcomes are available."
        )
        status = CalibrationStatus.DEMO_ONLY
    elif is_threshold and not has_outcome_labels:
        notes.append("threshold has no outcome backing")
        status = CalibrationStatus.ARBITRARY_THRESHOLD
    elif is_threshold and sample_count < min_threshold_samples:
        notes.append(
            f"threshold backed by only {sample_count} samples (< {min_threshold_samples})"
        )
        status = CalibrationStatus.INSUFFICIENT_SAMPLES
    elif not has_outcome_labels and sample_count == 0:
        notes.append("no outcome labels and no samples — heuristic only")
        status = CalibrationStatus.UNCALIBRATED_HEURISTIC
    elif not has_outcome_labels:
        notes.append("samples present but no outcome labels — labels required")
        status = CalibrationStatus.REQUIRES_EXTERNAL_LABELS
    elif sample_count < min_samples:
        notes.append(
            f"only {sample_count} labeled samples (< {min_samples})"
        )
        status = CalibrationStatus.INSUFFICIENT_SAMPLES
    else:
        status = CalibrationStatus.CALIBRATED
        notes.append(
            f"calibrated against {sample_count} labeled samples (>= {min_samples})"
        )

    return CalibrationReport(
        score_name=str(score_name),
        status=status,
        sample_count=sample_count,
        has_outcome_labels=bool(has_outcome_labels),
        is_threshold=bool(is_threshold),
        threshold_value=threshold_value,
        notes=tuple(notes),
    )


def aggregate_calibration_status(
    reports: Iterable[CalibrationReport],
) -> dict[str, Any]:
    """Aggregate per-score reports into a single canonical summary."""

    reports = list(reports)
    if not reports:
        return {
            "calibration_status": CalibrationStatus.UNCALIBRATED_HEURISTIC.value,
            "calibrated_score_count": 0,
            "score_count": 0,
            "supports_capital_permission": False,
            "supports_decision_ready_claim": False,
            "warnings": [
                "no calibration reports produced — treat all scores as uncalibrated"
            ],
            "score_breakdown": [],
        }

    calibrated = [r for r in reports if r.status == CalibrationStatus.CALIBRATED]
    if not calibrated:
        # Pick the most informative non-calibrated label.
        if any(r.status == CalibrationStatus.DEMO_ONLY for r in reports):
            top = CalibrationStatus.DEMO_ONLY
        elif any(r.status == CalibrationStatus.ARBITRARY_THRESHOLD for r in reports):
            top = CalibrationStatus.ARBITRARY_THRESHOLD
        elif any(r.status == CalibrationStatus.INSUFFICIENT_SAMPLES for r in reports):
            top = CalibrationStatus.INSUFFICIENT_SAMPLES
        elif any(
            r.status == CalibrationStatus.REQUIRES_EXTERNAL_LABELS for r in reports
        ):
            top = CalibrationStatus.REQUIRES_EXTERNAL_LABELS
        else:
            top = CalibrationStatus.UNCALIBRATED_HEURISTIC
        supports = False
    else:
        top = (
            CalibrationStatus.CALIBRATED
            if len(calibrated) == len(reports)
            else CalibrationStatus.INSUFFICIENT_SAMPLES
        )
        supports = top == CalibrationStatus.CALIBRATED

    warnings: list[str] = []
    if top != CalibrationStatus.CALIBRATED:
        warnings.append(
            f"calibration_status={top.value}: scores are not decision-ready and"
            " cannot support capital permission."
        )

    return {
        "calibration_status": top.value,
        "calibrated_score_count": len(calibrated),
        "score_count": len(reports),
        "supports_capital_permission": supports,
        "supports_decision_ready_claim": supports,
        "warnings": warnings,
        "score_breakdown": [r.to_dict() for r in reports],
    }


__all__ = [
    "CALIBRATION_DEFAULT_MIN_SAMPLES",
    "CALIBRATION_DEFAULT_THRESHOLD_MIN_SAMPLES",
    "CalibrationReport",
    "CalibrationStatus",
    "aggregate_calibration_status",
    "classify_calibration_status",
]
