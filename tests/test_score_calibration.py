"""Behavioural tests for honest score calibration."""
from __future__ import annotations

from scripts import score_calibration as sc


def _recs(wins=0, losses=0, breakeven=0, unknown=0, pnl=0.0):
    rows = []
    rows += [{"outcome_status": "WIN", "pnl_estimate": pnl}] * wins
    rows += [{"outcome_status": "LOSS", "pnl_estimate": -pnl}] * losses
    rows += [{"outcome_status": "BREAKEVEN", "pnl_estimate": 0.0}] * breakeven
    rows += [{"outcome_status": "UNKNOWN", "pnl_estimate": 0.0}] * unknown
    return rows


def test_no_outcomes_is_uncalibrated():
    s = sc.compute_score_calibration([])
    assert s["calibration_status"] == sc.UNCALIBRATED
    assert s["sample_size"] == 0
    assert s["win_rate"] is None
    assert s["score_should_drive_sizing"] is False


def test_small_sample_is_low_sample():
    s = sc.compute_score_calibration(_recs(wins=3, losses=2))
    assert s["sample_size"] == 5
    assert s["calibration_status"] == sc.LOW_SAMPLE
    assert s["score_should_drive_sizing"] is False


def test_mid_sample_is_calibrating():
    s = sc.compute_score_calibration(_recs(wins=15, losses=10))  # 25 resolved
    assert s["calibration_status"] == sc.CALIBRATING
    assert s["score_should_drive_sizing"] is False


def test_large_sample_is_calibrated():
    s = sc.compute_score_calibration(_recs(wins=30, losses=25))  # 55 resolved
    assert s["calibration_status"] == sc.CALIBRATED
    assert s["score_should_drive_sizing"] is True


def test_unknown_rows_excluded_from_rates():
    s = sc.compute_score_calibration(_recs(wins=4, losses=1, unknown=100))
    assert s["sample_size"] == 5  # the 100 UNKNOWN do not count
    assert s["win_rate"] == 0.8
    assert s["false_positive_rate"] == 0.2


def test_false_positive_rate_is_loss_fraction():
    s = sc.compute_score_calibration(_recs(wins=2, losses=8))
    assert s["false_positive_rate"] == 0.8
    assert s["win_rate"] == 0.2


def test_average_realized_return_computed():
    rows = [
        {"outcome_status": "WIN", "pnl_estimate": 100.0},
        {"outcome_status": "LOSS", "pnl_estimate": -50.0},
    ]
    s = sc.compute_score_calibration(rows)
    assert s["average_realized_return"] == 25.0


def test_envelope_carries_status_and_warning():
    summary = sc.compute_score_calibration([])
    env = sc.score_calibration_envelope(0.91, summary, label="priority_score")
    assert env["score"] == 0.91
    assert env["score_calibration_status"] == sc.UNCALIBRATED
    assert env["score_should_drive_sizing"] is False
    assert "not" in env["warning"].lower()
    # never grants execution
    assert env["broker_api_called"] is False
    assert env["advisory_status"] == "ADVISORY_ONLY"


def test_envelope_with_no_summary_defaults_uncalibrated():
    env = sc.score_calibration_envelope(0.5)
    assert env["score_calibration_status"] == sc.UNCALIBRATED
    assert env["score_should_drive_sizing"] is False


def test_classify_boundaries():
    assert sc.classify_calibration_status(0) == sc.UNCALIBRATED
    assert sc.classify_calibration_status(1) == sc.LOW_SAMPLE
    assert sc.classify_calibration_status(19) == sc.LOW_SAMPLE
    assert sc.classify_calibration_status(20) == sc.CALIBRATING
    assert sc.classify_calibration_status(49) == sc.CALIBRATING
    assert sc.classify_calibration_status(50) == sc.CALIBRATED


def test_advisory_invariants_on_summary():
    s = sc.compute_score_calibration(_recs(wins=1))
    assert s["advisory_status"] == "ADVISORY_ONLY"
    assert s["broker_api_called"] is False
    assert s["ai_execution_count"] == 0
