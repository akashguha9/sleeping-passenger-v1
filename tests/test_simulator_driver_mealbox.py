"""Driver-license penalty system and meal-box completeness gate tests."""

from __future__ import annotations

import pytest

from src.simulator.driver_license import (
    PENALTY_HALF_LIFE_DAYS,
    decayed_violation_points,
    license_meets_circuit,
    score_driver,
    status_for_points,
)
from src.simulator.meal_box import check_meal_box

GOOD_PROCESS = dict(
    thesis_logging_quality=0.9,
    invalidation_compliance=0.9,
    position_sizing_discipline=0.8,
    confirmation_patience=0.8,
    replay_audit_completion=0.8,
    calibration_honesty=0.9,
)


def test_danger_points_decay_with_half_life() -> None:
    fresh = decayed_violation_points("revenge_trading", 0)
    halved = decayed_violation_points("revenge_trading", PENALTY_HALF_LIFE_DAYS)
    assert fresh == pytest.approx(20.0)
    assert halved == pytest.approx(10.0)


def test_status_bands_match_spec() -> None:
    assert status_for_points(5) == ("clean", 1.0)
    assert status_for_points(15) == ("caution", 0.85)
    assert status_for_points(30) == ("warning", 0.65)
    assert status_for_points(50) == ("probation", 0.40)
    assert status_for_points(70) == ("suspended", 0.15)
    assert status_for_points(90) == ("black_flag", 0.0)


def test_clean_driver_has_full_permission() -> None:
    driver = score_driver(license_level="pro_am", **GOOD_PROCESS)
    assert driver.status == "clean"
    assert driver.permission_multiplier == 1.0
    assert "DISCIPLINED_DRIVER" in driver.reason_codes


def test_danger_points_cap_permission() -> None:
    driver = score_driver(
        license_level="pro_am",
        violations=[
            {"type": "revenge_trading", "days_since": 0},
            {"type": "oversizing_under_crash_risk", "days_since": 0},
            {"type": "no_thesis_no_helmet", "days_since": 0},
        ],
        **GOOD_PROCESS,
    )
    # 20 + 12 + 15 = 47 points -> probation.
    assert driver.danger_points == pytest.approx(47.0)
    assert driver.status == "probation"
    assert driver.permission_multiplier == 0.40


def test_old_violations_fade() -> None:
    driver = score_driver(
        violations=[{"type": "revenge_trading", "days_since": 120}],
        **GOOD_PROCESS,
    )
    assert driver.danger_points < 2.0
    assert driver.status == "clean"


def test_three_revenge_flags_black_flag_the_driver() -> None:
    driver = score_driver(revenge_trading_flags=3, **GOOD_PROCESS)
    assert driver.black_flag
    assert driver.permission_multiplier == 0.0
    assert "BLACK_FLAG_NO_ACTION_PERMITTED" in driver.reason_codes


def test_license_must_meet_circuit_requirement() -> None:
    assert license_meets_circuit("pro_driver", "club_racer")
    assert not license_meets_circuit("learner", "pro_driver")
    assert license_meets_circuit("team_principal", "engineer")
    assert not license_meets_circuit("unknown_level", "rookie")


def test_discipline_score_never_negative() -> None:
    driver = score_driver(
        violations=[{"type": "revenge_trading", "days_since": 0}] * 5,
        override_abuse_level=1.0,
        revenge_trading_flags=5,
    )
    assert driver.discipline_score == 0.0
    assert driver.black_flag


# ---------------------------------------------------------------------------
# Meal box
# ---------------------------------------------------------------------------

COMPLETE_BOX = dict(
    thesis="Backlog inflecting on AI grid demand",
    evidence="Backlog +40% YoY per latest 10-Q",
    catalyst="Policy vote within 30 days",
    invalidation="Exit if backlog growth < 10% or bill fails",
)


def test_complete_meal_box_passes() -> None:
    status = check_meal_box(**COMPLETE_BOX)
    assert status.complete
    assert status.missing_items == []
    assert "MEAL_BOX_COMPLETE" in status.reason_codes


def test_missing_fire_extinguisher_blocks() -> None:
    incomplete = {**COMPLETE_BOX, "invalidation": None}
    status = check_meal_box(**incomplete)
    assert not status.complete
    assert status.missing_items == ["invalidation"]
    assert "NO_FIRE_EXTINGUISHER_NO_TRADE" in status.reason_codes


def test_whitespace_or_trivial_text_does_not_count() -> None:
    status = check_meal_box(
        thesis="   ", evidence="ok", catalyst=COMPLETE_BOX["catalyst"],
        invalidation=COMPLETE_BOX["invalidation"],
    )
    assert not status.thesis_present
    assert not status.evidence_present  # "ok" is below substance threshold
    assert set(status.missing_items) == {"thesis", "evidence"}


def test_boolean_components_taken_at_face_value() -> None:
    status = check_meal_box(thesis=True, evidence=True, catalyst=True, invalidation=True)
    assert status.complete
