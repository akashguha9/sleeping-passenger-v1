"""Triple-blind stage 3: automated reality replay.

Stage 1 hid the company. Stage 2 wrote the model thesis before reading the
human one. Stage 3 — automated here — replays the decision against the
realized outcome and asks the only question that improves the system:
WAS THE PROCESS RIGHT, and if not, was the failure knowable at decision
time?

A failure is *knowable* when the decision-time telemetry already contained
the warning (stale tyres, missing fire extinguisher, exposure mismatch,
driver violation) and the verdict went forward anyway. A failure with a
clean process is *unknowable* — variance, not error. The distinction feeds
both the calibration bridge (which segments drifted) and driver derivation
(process failures become violations).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.simulator.triple_blind import (
    REALITY_REVIEW_CONFIRMED,
    REALITY_REVIEW_REFUTED,
    TripleBlindReview,
)

REPLAY_RIGHT_RIGHT = "right_for_right_reason"
REPLAY_RIGHT_WRONG = "right_for_wrong_reason"
REPLAY_WRONG_CLEAN = "wrong_but_process_clean"
REPLAY_WRONG_STALE = "wrong_due_to_stale_signal"
REPLAY_WRONG_NO_INVALIDATION = "wrong_due_to_missing_invalidation"
REPLAY_WRONG_EXPOSURE = "wrong_due_to_exposure_mismatch"
REPLAY_WRONG_DRIVER = "wrong_due_to_driver_violation"
REPLAY_INSUFFICIENT = "insufficient_data"

REPLAY_CLASSES: tuple[str, ...] = (
    REPLAY_RIGHT_RIGHT,
    REPLAY_RIGHT_WRONG,
    REPLAY_WRONG_CLEAN,
    REPLAY_WRONG_STALE,
    REPLAY_WRONG_NO_INVALIDATION,
    REPLAY_WRONG_EXPOSURE,
    REPLAY_WRONG_DRIVER,
    REPLAY_INSUFFICIENT,
)

# Replay classes that indicate a knowable process failure (these feed
# driver derivation as violations).
PROCESS_FAILURE_CLASSES: tuple[str, ...] = (
    REPLAY_WRONG_STALE,
    REPLAY_WRONG_NO_INVALIDATION,
    REPLAY_WRONG_DRIVER,
)


@dataclass(slots=True)
class RealityReplayResult:
    """Stage-3 verdict for one resolved decision."""

    ticker: str
    replay_class: str
    outcome_was_good: bool | None
    failure_was_knowable: bool | None
    knowable_warnings_at_decision: list[str] = field(default_factory=list)
    model_agreed_with_human: bool | None = None
    reality_review_status: str = "pending"
    explanation: str = ""
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _decision_time_warnings(decision: dict[str, Any]) -> list[str]:
    """Warnings that were ALREADY VISIBLE in the decision snapshot."""
    warnings: list[str] = []
    gates = decision.get("gate_results") or {}
    meal = decision.get("meal_box_status") or {}
    if not gates.get("grip_gate", True):
        warnings.append("stale_signal")
    if "invalidation" in (meal.get("missing_items") or []):
        warnings.append("missing_invalidation")
    if not gates.get("driver_license_gate", True) or not gates.get(
        "driver_not_black_flagged", True
    ):
        warnings.append("driver_violation")
    if float(decision.get("driver_permission", 1.0)) < 0.65:
        warnings.append("driver_violation")
    if decision.get("exposure_class") in ("narrative_passenger", "false_positive"):
        warnings.append("exposure_mismatch")
    if not gates.get("scrutineering_gate", True):
        warnings.append("scrutineering_failure")
    return sorted(set(warnings))


def replay_reality(
    *,
    decision: dict[str, Any],
    outcome_was_good: bool | None,
    review: TripleBlindReview | dict[str, Any] | None = None,
    thesis_was_correct: bool | None = None,
) -> RealityReplayResult:
    """Replay one resolved decision against reality.

    ``decision`` is the cherry-pick decision dict captured at decision time;
    ``outcome_was_good`` is the realized result (None = not yet resolved).
    """
    ticker = str(decision.get("ticker", "UNKNOWN"))
    review_dict = (
        review.to_dict() if isinstance(review, TripleBlindReview) else (review or {})
    )
    agreement = review_dict.get("human_model_agreement")
    model_agreed = (
        bool(agreement >= 0.5) if isinstance(agreement, (int, float)) else None
    )

    if outcome_was_good is None:
        return RealityReplayResult(
            ticker=ticker,
            replay_class=REPLAY_INSUFFICIENT,
            outcome_was_good=None,
            failure_was_knowable=None,
            model_agreed_with_human=model_agreed,
            reality_review_status="pending",
            explanation="Outcome not yet resolved; stage 3 stays pending.",
        )

    warnings = _decision_time_warnings(decision)

    if outcome_was_good:
        if thesis_was_correct is False or warnings:
            replay_class = REPLAY_RIGHT_WRONG
            explanation = (
                "Result was good but the decision carried ignored warnings "
                f"({', '.join(warnings) or 'thesis judged incorrect'}) — "
                "luck, not process. Do not reinforce."
            )
        else:
            replay_class = REPLAY_RIGHT_RIGHT
            explanation = "Result and process both clean."
        status = REALITY_REVIEW_CONFIRMED
        knowable = None
    else:
        status = REALITY_REVIEW_REFUTED
        # Attribute the failure to the most specific knowable warning.
        if "stale_signal" in warnings:
            replay_class = REPLAY_WRONG_STALE
        elif "missing_invalidation" in warnings:
            replay_class = REPLAY_WRONG_NO_INVALIDATION
        elif "driver_violation" in warnings:
            replay_class = REPLAY_WRONG_DRIVER
        elif "exposure_mismatch" in warnings or "scrutineering_failure" in warnings:
            replay_class = REPLAY_WRONG_EXPOSURE
        else:
            replay_class = REPLAY_WRONG_CLEAN
        knowable = replay_class != REPLAY_WRONG_CLEAN
        explanation = (
            f"Failure was {'knowable' if knowable else 'not knowable'} at "
            f"decision time; decision-snapshot warnings: "
            f"{', '.join(warnings) or 'none'}."
        )

    return RealityReplayResult(
        ticker=ticker,
        replay_class=replay_class,
        outcome_was_good=outcome_was_good,
        failure_was_knowable=knowable,
        knowable_warnings_at_decision=warnings,
        model_agreed_with_human=model_agreed,
        reality_review_status=status,
        explanation=explanation + " ADVISORY_ONLY.",
    )


def replay_to_driver_violation(result: RealityReplayResult) -> dict[str, Any] | None:
    """Convert a knowable process failure into a driver-violation record."""
    mapping = {
        REPLAY_WRONG_STALE: "chasing_stale_signal",
        REPLAY_WRONG_NO_INVALIDATION: "entered_without_invalidation",
        REPLAY_WRONG_DRIVER: "ignoring_thesis_damage",
    }
    violation_type = mapping.get(result.replay_class)
    if violation_type is None:
        return None
    return {"type": violation_type, "days_since": 0.0}
