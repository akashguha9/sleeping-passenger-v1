"""Decision telemetry / replay / calibration: telemetry is truth.

Every promoted candidate persists its decision-time state so the decision
can later be replayed against reality and classified by process quality:

    Calibration Error = predicted_probability - actual_outcome
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.simulator.cherry_pick import CherryPickDecision
from src.utils.math_utils import clamp01
from src.utils.time_utils import utc_now_iso

OUTCOME_GOOD_PROCESS_GOOD_RESULT = "good_process_good_result"
OUTCOME_GOOD_PROCESS_BAD_RESULT = "good_process_bad_result"
OUTCOME_BAD_PROCESS_GOOD_RESULT = "bad_process_good_result"
OUTCOME_BAD_PROCESS_BAD_RESULT = "bad_process_bad_result"
OUTCOME_CORRECT_THESIS_BAD_TIMING = "correct_thesis_bad_timing"
OUTCOME_WRONG_THESIS_LUCKY_EXIT = "wrong_thesis_lucky_exit"
OUTCOME_FALSE_POSITIVE = "false_positive"
OUTCOME_FALSE_NEGATIVE = "false_negative"

OUTCOME_CLASSES: tuple[str, ...] = (
    OUTCOME_GOOD_PROCESS_GOOD_RESULT,
    OUTCOME_GOOD_PROCESS_BAD_RESULT,
    OUTCOME_BAD_PROCESS_GOOD_RESULT,
    OUTCOME_BAD_PROCESS_BAD_RESULT,
    OUTCOME_CORRECT_THESIS_BAD_TIMING,
    OUTCOME_WRONG_THESIS_LUCKY_EXIT,
    OUTCOME_FALSE_POSITIVE,
    OUTCOME_FALSE_NEGATIVE,
)

CALIBRATION_PENDING = "pending"
CALIBRATION_RESOLVED = "resolved"


@dataclass(slots=True)
class DecisionTelemetry:
    """Replayable decision-time snapshot for one candidate."""

    ticker: str
    decision_time: str
    final_state: str
    decision_reason: str
    score_at_decision: float
    signal_grip_at_decision: float
    crash_risk_at_decision: float
    crash_density_at_decision: float
    driver_score_at_decision: float
    driver_permission_at_decision: float
    meal_box_status: dict[str, object] = field(default_factory=dict)
    aero_metrics_at_decision: dict[str, float] = field(default_factory=dict)
    # Calibration segmentation keys captured at decision time so replay can
    # compute error by circuit / compound / exposure class / crash bucket /
    # license / narrative state.
    segments: dict[str, str] = field(default_factory=dict)
    # "caller_payload" for live use, "fixture_replay" for seeded test data —
    # calibration must never present fixture replay as empirical evidence.
    data_source: str = "caller_payload"
    expected_time_window_days: float = 90.0
    predicted_probability: float | None = None
    actual_outcome_placeholder: float | None = None
    outcome_class: str | None = None
    calibration_error: float | None = None
    calibration_status: str = CALIBRATION_PENDING
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def crash_density_bucket(crash_density: float) -> str:
    """Coarse crash-density bucket label for calibration segmentation."""
    if crash_density < 0.10:
        return "low"
    if crash_density < 0.35:
        return "moderate"
    if crash_density < 0.60:
        return "high"
    return "extreme"


def build_decision_telemetry(
    decision: CherryPickDecision,
    *,
    driver_discipline_score: float,
    expected_time_window_days: float = 90.0,
    predicted_probability: float | None = None,
    decision_time: str | None = None,
    driver_license_level: str = "",
    narrative_state: str = "",
    dominant_game: str = "",
    data_source: str = "caller_payload",
) -> DecisionTelemetry:
    """Snapshot a cherry-pick decision for later replay. No candidate is
    promoted without telemetry — the pipeline calls this unconditionally."""
    segments = {
        "circuit": decision.circuit,
        "signal_compound": decision.signal_compound,
        "exposure_class": decision.exposure_class,
        "crash_density_bucket": crash_density_bucket(decision.crash_density),
        "driver_license": driver_license_level,
        "narrative_state": narrative_state,
        "dominant_game": dominant_game,
    }
    return DecisionTelemetry(
        ticker=decision.ticker,
        decision_time=decision_time or utc_now_iso(),
        final_state=decision.final_state,
        decision_reason=decision.decision_reason,
        score_at_decision=decision.final_candidate_score,
        signal_grip_at_decision=decision.signal_grip,
        crash_risk_at_decision=decision.crash_risk,
        crash_density_at_decision=decision.crash_density,
        driver_score_at_decision=float(driver_discipline_score),
        driver_permission_at_decision=decision.driver_permission,
        meal_box_status=dict(decision.meal_box_status),
        aero_metrics_at_decision={
            "downforce": decision.downforce,
            "drag": decision.drag,
            "aero_efficiency": decision.aero_efficiency,
            "dirty_air": decision.dirty_air,
        },
        segments=segments,
        data_source=str(data_source),
        expected_time_window_days=float(expected_time_window_days),
        predicted_probability=(
            clamp01(predicted_probability)
            if predicted_probability is not None
            else None
        ),
    )


def classify_outcome(
    *,
    process_was_good: bool,
    result_was_good: bool,
    thesis_was_correct: bool | None = None,
    timing_was_wrong: bool = False,
    was_rejected_candidate: bool = False,
) -> str:
    """Classify a resolved decision into one of the eight outcome classes."""
    if was_rejected_candidate:
        return OUTCOME_FALSE_NEGATIVE if result_was_good else OUTCOME_FALSE_POSITIVE
    if thesis_was_correct is True and timing_was_wrong and not result_was_good:
        return OUTCOME_CORRECT_THESIS_BAD_TIMING
    if thesis_was_correct is False and result_was_good:
        return OUTCOME_WRONG_THESIS_LUCKY_EXIT
    if process_was_good and result_was_good:
        return OUTCOME_GOOD_PROCESS_GOOD_RESULT
    if process_was_good and not result_was_good:
        return OUTCOME_GOOD_PROCESS_BAD_RESULT
    if not process_was_good and result_was_good:
        return OUTCOME_BAD_PROCESS_GOOD_RESULT
    return OUTCOME_BAD_PROCESS_BAD_RESULT


def resolve_telemetry_outcome(
    telemetry: DecisionTelemetry,
    *,
    actual_outcome: float,
    outcome_class: str,
) -> DecisionTelemetry:
    """Fill in reality: actual outcome in [0, 1], outcome class, calibration."""
    if outcome_class not in OUTCOME_CLASSES:
        raise ValueError(f"unknown outcome class: {outcome_class!r}")
    telemetry.actual_outcome_placeholder = clamp01(actual_outcome)
    telemetry.outcome_class = outcome_class
    if telemetry.predicted_probability is not None:
        telemetry.calibration_error = (
            telemetry.predicted_probability - telemetry.actual_outcome_placeholder
        )
    telemetry.calibration_status = CALIBRATION_RESOLVED
    return telemetry


def append_telemetry(telemetry: DecisionTelemetry, path: str | Path) -> Path:
    """Append one telemetry row to a local JSONL replay log."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(telemetry.to_json() + "\n")
    return target


def load_telemetry_rows(path: str | Path) -> list[dict[str, object]]:
    """Load all replay rows from a JSONL telemetry log (missing file -> [])."""
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
