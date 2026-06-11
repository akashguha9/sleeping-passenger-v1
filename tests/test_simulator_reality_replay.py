"""Triple-blind stage-3 reality replay tests: knowable vs unknowable failure."""

from __future__ import annotations

from src.simulator.reality_replay import (
    REPLAY_INSUFFICIENT,
    REPLAY_RIGHT_RIGHT,
    REPLAY_RIGHT_WRONG,
    REPLAY_WRONG_CLEAN,
    REPLAY_WRONG_DRIVER,
    REPLAY_WRONG_EXPOSURE,
    REPLAY_WRONG_NO_INVALIDATION,
    REPLAY_WRONG_STALE,
    replay_reality,
    replay_to_driver_violation,
)

CLEAN_DECISION = {
    "ticker": "GRIDCO",
    "exposure_class": "direct_beneficiary",
    "driver_permission": 1.0,
    "gate_results": {
        "grip_gate": True,
        "driver_license_gate": True,
        "driver_not_black_flagged": True,
        "scrutineering_gate": True,
    },
    "meal_box_status": {"missing_items": []},
}


def _decision(**overrides) -> dict:
    decision = {**CLEAN_DECISION}
    decision["gate_results"] = dict(CLEAN_DECISION["gate_results"])
    decision["meal_box_status"] = dict(CLEAN_DECISION["meal_box_status"])
    for key, value in overrides.items():
        if key in ("gate_results", "meal_box_status"):
            decision[key].update(value)
        else:
            decision[key] = value
    return decision


def test_unresolved_outcome_stays_pending() -> None:
    result = replay_reality(decision=CLEAN_DECISION, outcome_was_good=None)
    assert result.replay_class == REPLAY_INSUFFICIENT
    assert result.reality_review_status == "pending"


def test_clean_process_good_result_is_right_for_right_reason() -> None:
    result = replay_reality(decision=CLEAN_DECISION, outcome_was_good=True)
    assert result.replay_class == REPLAY_RIGHT_RIGHT
    assert result.reality_review_status == "confirmed"


def test_good_result_with_ignored_warnings_is_right_for_wrong_reason() -> None:
    decision = _decision(gate_results={"grip_gate": False})
    result = replay_reality(decision=decision, outcome_was_good=True)
    assert result.replay_class == REPLAY_RIGHT_WRONG
    assert "stale_signal" in result.knowable_warnings_at_decision
    assert "Do not reinforce" in result.explanation


def test_wrong_with_clean_snapshot_is_unknowable_variance() -> None:
    result = replay_reality(decision=CLEAN_DECISION, outcome_was_good=False)
    assert result.replay_class == REPLAY_WRONG_CLEAN
    assert result.failure_was_knowable is False
    assert result.reality_review_status == "refuted"


def test_stale_signal_failure_is_knowable() -> None:
    decision = _decision(gate_results={"grip_gate": False})
    result = replay_reality(decision=decision, outcome_was_good=False)
    assert result.replay_class == REPLAY_WRONG_STALE
    assert result.failure_was_knowable is True


def test_missing_invalidation_failure_classified() -> None:
    decision = _decision(meal_box_status={"missing_items": ["invalidation"]})
    result = replay_reality(decision=decision, outcome_was_good=False)
    assert result.replay_class == REPLAY_WRONG_NO_INVALIDATION


def test_driver_violation_failure_classified() -> None:
    decision = _decision(driver_permission=0.4)
    result = replay_reality(decision=decision, outcome_was_good=False)
    assert result.replay_class == REPLAY_WRONG_DRIVER


def test_exposure_mismatch_failure_classified() -> None:
    decision = _decision(exposure_class="narrative_passenger")
    result = replay_reality(decision=decision, outcome_was_good=False)
    assert result.replay_class == REPLAY_WRONG_EXPOSURE


def test_failure_attribution_prefers_most_specific_warning() -> None:
    # Stale signal outranks exposure mismatch in attribution order.
    decision = _decision(
        gate_results={"grip_gate": False},
        exposure_class="narrative_passenger",
    )
    result = replay_reality(decision=decision, outcome_was_good=False)
    assert result.replay_class == REPLAY_WRONG_STALE
    assert set(result.knowable_warnings_at_decision) >= {
        "stale_signal",
        "exposure_mismatch",
    }


def test_replay_feeds_driver_derivation() -> None:
    stale = replay_reality(
        decision=_decision(gate_results={"grip_gate": False}),
        outcome_was_good=False,
    )
    violation = replay_to_driver_violation(stale)
    assert violation == {"type": "chasing_stale_signal", "days_since": 0.0}

    clean = replay_reality(decision=CLEAN_DECISION, outcome_was_good=False)
    assert replay_to_driver_violation(clean) is None


def test_replay_uses_model_agreement_from_review() -> None:
    result = replay_reality(
        decision=CLEAN_DECISION,
        outcome_was_good=True,
        review={"human_model_agreement": 0.8},
    )
    assert result.model_agreed_with_human is True
    result = replay_reality(
        decision=CLEAN_DECISION,
        outcome_was_good=True,
        review={"human_model_agreement": 0.1},
    )
    assert result.model_agreed_with_human is False


def test_replay_result_serializable_and_advisory() -> None:
    result = replay_reality(decision=CLEAN_DECISION, outcome_was_good=True)
    payload = result.to_dict()
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert "ADVISORY_ONLY" in payload["explanation"]
