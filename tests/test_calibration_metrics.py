"""Exact-math tests for compute_calibration_metrics (ECE/Brier/Wilson/Bayes)."""
from __future__ import annotations

import math

from scripts import outcome_evidence as oe
from scripts import score_calibration as sc


def _outcome(label, score, source=oe.REAL_MANUAL_TRADE, ret=None, oid=None):
    """A calibration-eligible outcome with a given label + score."""
    # Drive label via override; provide entry/exit so quality is high + eligible.
    entry, exit_ = 100.0, (110.0 if label == "WIN" else 90.0 if label == "LOSS" else 100.0)
    return oe.build_outcome(
        outcome_id=oid or f"O{id(object())}",
        source_type=source, ticker="X", direction="LONG",
        entry_price=entry, exit_price=exit_, score_at_entry=score,
        opened_at="a", closed_at="b", outcome_label_override=label,
        realized_return=ret,
    )


def _many(label, score, count, source=oe.REAL_MANUAL_TRADE):
    return [_outcome(label, score, source, oid=f"{label}{score}_{i}") for i in range(count)]


def test_no_eligible_outcomes_is_no_data():
    m = sc.compute_calibration_metrics([])
    assert m["calibration_status"] == sc.NO_DATA
    assert m["should_drive_sizing"] is False


def test_only_synthetic_is_fixture_only():
    outs = _many("WIN", 0.8, 5, source=oe.SYNTHETIC_FIXTURE)
    m = sc.compute_calibration_metrics(outs)
    assert m["calibration_status"] == sc.FIXTURE_ONLY
    assert m["synthetic_n"] == 5
    assert m["eligible_n"] == 0
    assert m["should_drive_sizing"] is False


def test_n10_low_sample():
    m = sc.compute_calibration_metrics(_many("WIN", 0.8, 10))
    assert m["n"] == 10
    assert m["calibration_status"] == sc.LOW_SAMPLE


def test_n30_calibrating():
    outs = _many("WIN", 0.8, 15) + _many("LOSS", 0.8, 15)
    m = sc.compute_calibration_metrics(outs)
    assert m["n"] == 30
    assert m["calibration_status"] == sc.CALIBRATING


def test_n60_low_ece_calibrated():
    # score 0.5, half win half loss -> accuracy 0.5 == confidence 0.5 -> ECE 0.
    outs = _many("WIN", 0.5, 30) + _many("LOSS", 0.5, 30)
    m = sc.compute_calibration_metrics(outs)
    assert m["n"] == 60
    assert m["ece"] < 0.10
    assert m["calibration_status"] == sc.CALIBRATED


def test_n60_high_ece_miscalibrated():
    # score 0.9 but everything loses -> accuracy 0 vs confidence 0.9 -> ECE 0.9.
    outs = _many("LOSS", 0.9, 60)
    m = sc.compute_calibration_metrics(outs)
    assert m["n"] == 60
    assert m["ece"] > 0.10
    assert m["calibration_status"] == sc.MIS_CALIBRATED


def test_brier_exact_tiny_sample():
    # 2 outcomes: WIN@0.8 (y=1), LOSS@0.3 (y=0).
    # Brier = ((0.8-1)^2 + (0.3-0)^2)/2 = (0.04 + 0.09)/2 = 0.065
    outs = [_outcome("WIN", 0.8, oid="a"), _outcome("LOSS", 0.3, oid="b")]
    m = sc.compute_calibration_metrics(outs)
    assert math.isclose(m["brier"], 0.065, abs_tol=1e-9)


def test_ece_exact_known_buckets():
    # Bucket [0.75,0.90): 10 outcomes @0.8, 8 wins -> acc 0.8, conf 0.8 -> gap 0.
    # Bucket [0.40,0.60): 10 outcomes @0.5, all win -> acc 1.0, conf 0.5 -> gap 0.5.
    # ECE = (10/20)*0 + (10/20)*0.5 = 0.25
    b1 = _many("WIN", 0.8, 8) + _many("LOSS", 0.8, 2)
    b2 = _many("WIN", 0.5, 10)
    m = sc.compute_calibration_metrics(b1 + b2)
    assert math.isclose(m["ece"], 0.25, abs_tol=1e-9)
    assert math.isclose(m["mce"], 0.5, abs_tol=1e-9)


def test_wilson_interval_exact():
    # 60 wins of 60? use 30 win 30 loss @0.5 -> p_hat 0.5, n 60.
    outs = _many("WIN", 0.5, 30) + _many("LOSS", 0.5, 30)
    m = sc.compute_calibration_metrics(outs)
    z, n, p = 1.96, 60, 0.5
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) / n + z * z / (4 * n * n))) / denom
    assert math.isclose(m["wilson_lower"], center - half, abs_tol=1e-9)
    assert math.isclose(m["wilson_upper"], center + half, abs_tol=1e-9)


def test_bayesian_posterior_exact():
    # 7 wins, 3 losses -> alpha=1+7=8, beta=1+3=4, mean=8/12.
    outs = _many("WIN", 0.7, 7) + _many("LOSS", 0.7, 3)
    m = sc.compute_calibration_metrics(outs)
    alpha, beta = 8.0, 4.0
    assert math.isclose(m["posterior_mean"], alpha / (alpha + beta), abs_tol=1e-9)
    var = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1))
    assert math.isclose(m["posterior_var"], var, abs_tol=1e-12)


def test_breakeven_handled_as_half():
    # 2 breakevens @0.5 -> y=0.5. Brier = ((0.5-0.5)^2)*2/2 = 0. wins=0 losses=0 be=2.
    outs = _many("BREAKEVEN", 0.5, 2)
    m = sc.compute_calibration_metrics(outs)
    assert m["breakevens"] == 2
    assert math.isclose(m["brier"], 0.0, abs_tol=1e-9)
    # Bayesian: alpha=1+0.5*2=2, beta=1+0.5*2=2 -> mean 0.5
    assert math.isclose(m["posterior_mean"], 0.5, abs_tol=1e-9)


def test_should_drive_sizing_requires_real_n_and_approval():
    # 60 CALIBRATED real outcomes but human not approved -> False.
    outs = _many("WIN", 0.5, 30) + _many("LOSS", 0.5, 30)
    m = sc.compute_calibration_metrics(outs, human_approved=False)
    assert m["calibration_status"] == sc.CALIBRATED
    assert m["real_n"] == 60
    assert m["should_drive_sizing"] is False
    m2 = sc.compute_calibration_metrics(outs, human_approved=True)
    assert m2["should_drive_sizing"] is True


def test_paper_calibrated_not_sizing_grade():
    # 60 paper outcomes, CALIBRATED, human approved -> still not sizing (real_n<50).
    outs = _many("WIN", 0.5, 30, source=oe.PAPER_TRADE) + _many("LOSS", 0.5, 30, source=oe.PAPER_TRADE)
    m = sc.compute_calibration_metrics(outs, human_approved=True)
    assert m["calibration_status"] == sc.CALIBRATED
    assert m["real_n"] == 0
    assert m["paper_n"] == 60
    assert m["should_drive_sizing"] is False


def test_advisory_invariants_present():
    m = sc.compute_calibration_metrics(_many("WIN", 0.8, 3))
    assert m["advisory_status"] == "ADVISORY_ONLY"
    assert m["broker_api_called"] is False
    assert m["human_review_required"] is True
