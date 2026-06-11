"""Threshold ladder (hysteresis), triple-blind review, and telemetry tests."""

from __future__ import annotations

import json

import pytest

from src.simulator.threshold_ladder import (
    STATE_ACTIVE_WATCH,
    STATE_BLACK_FLAG,
    STATE_BUY_CANDIDATE,
    STATE_PIT_STOP,
    STATE_WATCHLIST,
    resolve_ladder_state,
    score_inflection,
)
from src.simulator.triple_blind import (
    build_triple_blind_review,
    identity_blind_score,
    measure_agreement,
)
from src.simulator.telemetry import (
    OUTCOME_BAD_PROCESS_GOOD_RESULT,
    OUTCOME_CORRECT_THESIS_BAD_TIMING,
    OUTCOME_FALSE_NEGATIVE,
    OUTCOME_GOOD_PROCESS_BAD_RESULT,
    OUTCOME_WRONG_THESIS_LUCKY_EXIT,
    DecisionTelemetry,
    append_telemetry,
    classify_outcome,
    load_telemetry_rows,
    resolve_telemetry_outcome,
)

ALL_GATES_OPEN = dict(
    meal_box_complete=True,
    crash_gate_passed=True,
    grip_gate_passed=True,
    data_quality_gate_passed=True,
    hard_conviction_allowed=True,
)


def test_score_buckets_to_expected_states() -> None:
    assert resolve_ladder_state(score=10, **ALL_GATES_OPEN).state == "reject"
    assert resolve_ladder_state(score=40, **ALL_GATES_OPEN).state == STATE_WATCHLIST
    assert resolve_ladder_state(score=70, **ALL_GATES_OPEN).state == STATE_BUY_CANDIDATE
    assert (
        resolve_ladder_state(score=90, **ALL_GATES_OPEN).state
        == "high_conviction_candidate"
    )


def test_hysteresis_holds_promotion_near_threshold() -> None:
    # buy_candidate threshold is 65; from active_watch, 66 is within the
    # 3-point hysteresis margin so promotion is held.
    held = resolve_ladder_state(
        score=66, previous_state=STATE_ACTIVE_WATCH, **ALL_GATES_OPEN
    )
    assert held.state == STATE_ACTIVE_WATCH
    assert "HYSTERESIS_HELD_PROMOTION" in held.reason_codes

    promoted = resolve_ladder_state(
        score=69, previous_state=STATE_ACTIVE_WATCH, **ALL_GATES_OPEN
    )
    assert promoted.state == STATE_BUY_CANDIDATE


def test_hysteresis_holds_demotion_near_threshold() -> None:
    held = resolve_ladder_state(
        score=63, previous_state=STATE_BUY_CANDIDATE, **ALL_GATES_OPEN
    )
    assert held.state == STATE_BUY_CANDIDATE
    assert "HYSTERESIS_HELD_DEMOTION" in held.reason_codes

    demoted = resolve_ladder_state(
        score=50, previous_state=STATE_BUY_CANDIDATE, **ALL_GATES_OPEN
    )
    assert demoted.state != STATE_BUY_CANDIDATE


def test_missing_meal_box_caps_at_active_watch() -> None:
    decision = resolve_ladder_state(
        score=95, **{**ALL_GATES_OPEN, "meal_box_complete": False}
    )
    assert decision.state == STATE_ACTIVE_WATCH
    assert "meal_box_gate" in decision.gate_caps


def test_crash_gate_caps_at_watchlist() -> None:
    decision = resolve_ladder_state(
        score=95, **{**ALL_GATES_OPEN, "crash_gate_passed": False}
    )
    assert decision.state == STATE_WATCHLIST
    assert "crash_gate" in decision.gate_caps


def test_hard_conviction_gate_caps_at_buy_candidate() -> None:
    decision = resolve_ladder_state(
        score=95, **{**ALL_GATES_OPEN, "hard_conviction_allowed": False}
    )
    assert decision.state == STATE_BUY_CANDIDATE


def test_interrupt_states_override_everything() -> None:
    pit = resolve_ladder_state(score=95, thesis_damaged=True, **ALL_GATES_OPEN)
    assert pit.state == STATE_PIT_STOP
    flag = resolve_ladder_state(score=95, driver_black_flag=True, **ALL_GATES_OPEN)
    assert flag.state == STATE_BLACK_FLAG


def test_circuit_multiplier_raises_thresholds() -> None:
    easy = resolve_ladder_state(
        score=70, circuit_threshold_multiplier=1.0, **ALL_GATES_OPEN
    )
    hard = resolve_ladder_state(
        score=70, circuit_threshold_multiplier=1.5, **ALL_GATES_OPEN
    )
    assert easy.state == STATE_BUY_CANDIDATE
    assert hard.state in (STATE_WATCHLIST, "archive")


def test_inflection_score_combines_deltas() -> None:
    inflection = score_inflection(
        delta_narrative_velocity=0.5,
        delta_source_diversity=0.4,
        delta_volume_quality=0.3,
        delta_estimate_revision=0.4,
        delta_filing_evidence=0.3,
        delta_contradiction_pressure=0.2,
    )
    assert inflection.score == pytest.approx(0.5 + 0.4 + 0.3 + 0.4 + 0.3 - 0.2)
    assert "POSITIVE_INFLECTION" in inflection.reason_codes


def test_velocity_without_evidence_flags_false_inflection() -> None:
    inflection = score_inflection(
        delta_narrative_velocity=0.8, delta_filing_evidence=-0.2
    )
    assert "POSSIBLE_FALSE_INFLECTION" in inflection.reason_codes


# ---------------------------------------------------------------------------
# Triple-blind review
# ---------------------------------------------------------------------------

METRICS = {
    "growth_quality": 0.7,
    "margin_trend": 0.6,
    "balance_sheet_strength": 0.7,
    "valuation_discount": 0.5,
    "evidence_strength": 0.8,
}


def test_triple_blind_review_exists_and_is_serializable() -> None:
    review = build_triple_blind_review(
        blinded_metrics=METRICS,
        user_thesis="Backlog growth with valuation support; key risk is margin pressure.",
    )
    payload = review.to_dict()
    serialized = json.dumps(payload)
    assert "identity_blind_score" in payload
    assert payload["model_thesis_written_before_user_thesis"] is True
    assert payload["reality_review_status"] == "pending"
    assert isinstance(serialized, str)


def test_model_thesis_contains_no_identity() -> None:
    review = build_triple_blind_review(blinded_metrics=METRICS)
    assert "anonymized" in review.model_thesis
    assert "ADVISORY_ONLY" in review.model_thesis
    assert not review.user_thesis_seen
    assert "USER_THESIS_NOT_PROVIDED" in review.reason_codes


def test_agreement_measures_topic_overlap() -> None:
    high = measure_agreement(
        "growth and margins with balance sheet strength",
        "revenue growth, margin expansion, low debt",
    )
    low = measure_agreement(
        "growth and margins", "pure catalyst timing play on policy approval"
    )
    assert high > low


def test_identity_blind_score_bounded() -> None:
    assert identity_blind_score({}) == 0.0
    assert identity_blind_score({k: 1.0 for k in METRICS}) <= 1.0


# ---------------------------------------------------------------------------
# Telemetry / calibration
# ---------------------------------------------------------------------------


def _telemetry(**overrides) -> DecisionTelemetry:
    base = dict(
        ticker="GRIDCO",
        decision_time="2026-06-11T00:00:00+00:00",
        final_state="buy_candidate",
        decision_reason="test",
        score_at_decision=70.0,
        signal_grip_at_decision=80.0,
        crash_risk_at_decision=0.3,
        crash_density_at_decision=0.1,
        driver_score_at_decision=75.0,
        driver_permission_at_decision=1.0,
        predicted_probability=0.7,
    )
    base.update(overrides)
    return DecisionTelemetry(**base)


def test_outcome_classification_matrix() -> None:
    assert classify_outcome(process_was_good=True, result_was_good=True) == (
        "good_process_good_result"
    )
    assert (
        classify_outcome(process_was_good=True, result_was_good=False)
        == OUTCOME_GOOD_PROCESS_BAD_RESULT
    )
    assert (
        classify_outcome(process_was_good=False, result_was_good=True)
        == OUTCOME_BAD_PROCESS_GOOD_RESULT
    )
    assert classify_outcome(process_was_good=False, result_was_good=False) == (
        "bad_process_bad_result"
    )
    assert (
        classify_outcome(
            process_was_good=True,
            result_was_good=False,
            thesis_was_correct=True,
            timing_was_wrong=True,
        )
        == OUTCOME_CORRECT_THESIS_BAD_TIMING
    )
    assert (
        classify_outcome(
            process_was_good=False, result_was_good=True, thesis_was_correct=False
        )
        == OUTCOME_WRONG_THESIS_LUCKY_EXIT
    )
    assert (
        classify_outcome(
            process_was_good=True, result_was_good=True, was_rejected_candidate=True
        )
        == OUTCOME_FALSE_NEGATIVE
    )


def test_calibration_error_is_predicted_minus_actual() -> None:
    telemetry = resolve_telemetry_outcome(
        _telemetry(),
        actual_outcome=0.0,
        outcome_class=OUTCOME_GOOD_PROCESS_BAD_RESULT,
    )
    assert telemetry.calibration_error == pytest.approx(0.7)
    assert telemetry.calibration_status == "resolved"


def test_unknown_outcome_class_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_telemetry_outcome(
            _telemetry(), actual_outcome=1.0, outcome_class="vibes"
        )


def test_telemetry_round_trips_through_jsonl(tmp_path) -> None:
    path = tmp_path / "replay" / "telemetry.jsonl"
    append_telemetry(_telemetry(), path)
    append_telemetry(_telemetry(ticker="OTHER"), path)
    rows = load_telemetry_rows(path)
    assert len(rows) == 2
    assert rows[0]["ticker"] == "GRIDCO"
    assert rows[0]["advisory_status"] == "ADVISORY_ONLY"
    assert load_telemetry_rows(tmp_path / "missing.jsonl") == []
