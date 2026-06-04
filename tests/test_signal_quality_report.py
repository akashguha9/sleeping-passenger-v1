"""Tests for the outcome-backed signal quality report."""
from __future__ import annotations

import math

from scripts import outcome_evidence as oe
from scripts import score_calibration as sc
from scripts import signal_quality_report as sq


def _o(label, score, count, source=oe.REAL_MANUAL_TRADE):
    out = []
    for i in range(count):
        ex = 110.0 if label == "WIN" else 90.0 if label == "LOSS" else 100.0
        out.append(oe.build_outcome(
            outcome_id=f"{label}{score}_{i}_{id(object())}", source_type=source,
            ticker="X", direction="LONG", entry_price=100.0, exit_price=ex,
            score_at_entry=score, opened_at="a", closed_at="b",
            outcome_label_override=label,
        ))
    return out


def test_no_data_caps_at_7():
    m = sc.compute_calibration_metrics([])
    r = sq.build_signal_quality_report(m, coverage_score=1.0)
    assert r["signal_quality_score"] <= 7.0
    assert "calibration_no_data" in r["caps_applied"]


def test_fixture_only_caps_at_7():
    m = sc.compute_calibration_metrics(_o("WIN", 0.8, 60, source=oe.SYNTHETIC_FIXTURE))
    r = sq.build_signal_quality_report(m, coverage_score=1.0)
    assert r["calibration_status"] == "FIXTURE_ONLY"
    assert r["signal_quality_score"] <= 7.0
    assert "fixtures_only" in r["caps_applied"]


def test_calibrated_good_metrics_can_exceed_7_5():
    # 60 real outcomes @0.5 split 30/30 -> ECE 0, Brier 0.25 boundary.
    # Use score 0.5 wins half -> accuracy 0.5 == conf -> ECE 0; Brier=0.25.
    # Brier_score = 1 - 0.25/0.25 = 0 -> hurts. Use a sharper sample:
    # WIN@0.9 x54 + LOSS@0.9 x6 -> conf 0.9, acc 0.9 -> ECE 0; Brier=(0.1^2*54+0.9^2*6)/60
    m = sc.compute_calibration_metrics(_o("WIN", 0.9, 54) + _o("LOSS", 0.9, 6))
    r = sq.build_signal_quality_report(
        m, coverage_score=1.0,
        recommendation={"sample_size": 60}, feedback_human_reviewed=True,
        behavioral_tests_passed=1, behavioral_tests_expected=1,
    )
    assert m["ece"] < 0.10
    assert r["signal_quality_score"] > 7.5


def test_miscalibrated_caps():
    m = sc.compute_calibration_metrics(_o("LOSS", 0.9, 60))  # ECE high
    r = sq.build_signal_quality_report(m, coverage_score=1.0)
    assert m["ece"] > 0.20
    assert r["signal_quality_score"] <= 6.5
    assert "high_ece_large_sample" in r["caps_applied"]


def test_no_score_contract_caps_at_6():
    m = sc.compute_calibration_metrics(_o("WIN", 0.9, 54) + _o("LOSS", 0.9, 6))
    r = sq.build_signal_quality_report(m, coverage_score=1.0, score_contract_present=False)
    assert r["signal_quality_score"] <= 6.0
    assert "no_score_contract" in r["caps_applied"]


def test_formula_exact_on_known_sample():
    # Construct components deterministically and check SQ_raw.
    # WIN@0.9 x54 + LOSS@0.9 x6: conf 0.9 acc 0.9 -> ECE 0 -> ECE_score 1.0.
    # Brier = (0.01*54 + 0.81*6)/60 = (0.54 + 4.86)/60 = 0.09 -> Brier_score = 1 - 0.09/0.25 = 0.64
    m = sc.compute_calibration_metrics(_o("WIN", 0.9, 54) + _o("LOSS", 0.9, 6))
    assert math.isclose(m["brier"], 0.09, abs_tol=1e-9)
    r = sq.build_signal_quality_report(
        m, coverage_score=1.0, recommendation={"sample_size": 60},
        feedback_human_reviewed=True, behavioral_tests_passed=1, behavioral_tests_expected=1,
    )
    # C: CALIBRATED real_n=60 -> 0.8; ECE_score 1.0; Brier_score 0.64; cov 1.0;
    # feedback 0.9; bt 1.0
    # SQ_raw = 10*(0.25*0.8 + 0.20*1.0 + 0.15*0.64 + 0.15*1.0 + 0.15*0.9 + 0.10*1.0)
    #        = 10*(0.20 + 0.20 + 0.096 + 0.15 + 0.135 + 0.10) = 10*0.881 = 8.81
    assert math.isclose(r["signal_quality_raw"], 8.81, abs_tol=0.02)


def test_bucket_analysis_fields_present():
    m = sc.compute_calibration_metrics(_o("WIN", 0.9, 30) + _o("LOSS", 0.3, 30))
    r = sq.build_signal_quality_report(m, coverage_score=1.0)
    assert "strongest_bucket" in r
    assert "overconfident_buckets" in r
    assert "underconfident_buckets" in r


def test_advisory_stamps():
    m = sc.compute_calibration_metrics([])
    r = sq.build_signal_quality_report(m)
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["broker_api_called"] is False
    assert r["human_review_required"] is True
