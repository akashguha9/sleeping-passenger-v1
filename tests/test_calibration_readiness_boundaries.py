"""Calibration provenance boundaries (Phase 12 items 5-11).

Synthetic outcomes can never be calibration-eligible or produce a MEASURED
mode; imported backtest is not LIVE_MANUAL; paper is not real. Also exercises
the existing, tested Brier/ECE machinery to confirm the audit leverages real
math rather than reimplementing it. Deterministic.
"""
from __future__ import annotations

import importlib

import pytest

oe = importlib.import_module("scripts.outcome_evidence")
sc = importlib.import_module("scripts.score_calibration")
ora = importlib.import_module("scripts.operational_readiness_audit")


def _outcome(label, score, source=oe.REAL_MANUAL_TRADE, oid="x"):
    return oe.build_outcome(outcome_id=oid, source_type=source, ticker="NSE:RELIANCE",
                            direction="LONG", entry_price=100.0,
                            exit_price=110.0 if label == "WIN" else 90.0,
                            score_at_entry=score, outcome_label_override=label)


# --- synthetic can never be eligible / MEASURED (6) ------------------------
def test_synthetic_fixture_never_calibration_eligible():
    out = _outcome("WIN", 0.8, source=oe.SYNTHETIC_FIXTURE)
    assert out.is_calibration_eligible is False
    assert out.ineligible_reason == "synthetic_fixture_never_calibration_eligible"


def test_synthetic_only_counts_do_not_make_measured_mode():
    r = ora.build_report(commit="X",
                         outcome_counts=ora.OutcomeCounts(synthetic_n=1000, real_n=0))
    assert r.mode != "MEASURED"
    assert "_NO_REAL_OUTCOMES" in r.readiness_grade


def test_provenance_counts_keep_classes_separate():
    outs = [
        _outcome("WIN", 0.8, oe.REAL_MANUAL_TRADE, "r1"),
        _outcome("LOSS", 0.3, oe.PAPER_TRADE, "p1"),
        _outcome("WIN", 0.7, oe.IMPORTED_BACKTEST, "b1"),
        _outcome("WIN", 0.9, oe.SYNTHETIC_FIXTURE, "s1"),
    ]
    counts = oe.provenance_counts(outs)
    assert counts["real_n"] == 1
    assert counts["paper_n"] == 1
    assert counts["backtest_n"] == 1
    assert counts["synthetic_n"] == 1
    assert counts["eligible_n"] == 3  # synthetic excluded


# --- imported is not live, paper is not real (7, 8) ------------------------
def test_imported_backtest_mode_label_is_not_live():
    cmode = next(m for m in ora.build_report(
        commit="X", outcome_counts=ora.OutcomeCounts(imported_n=200)
    ).sections["calibration_readiness"].metrics
        if m.name == "calibration_mode_assignment")
    assert cmode.value == "IMPORTED_BACKTEST_ONLY"
    assert cmode.provenance_type == "IMPORTED_BACKTEST"


def test_paper_outcomes_not_counted_as_real():
    r = ora.build_report(commit="X", outcome_counts=ora.OutcomeCounts(paper_n=200))
    assert r.real_outcome_count == 0


# --- audit leverages real Brier/ECE math (9, 10, 11) -----------------------
def test_brier_exact_small_sample():
    # WIN@0.8 (y=1), LOSS@0.3 (y=0): Brier = ((0.8-1)^2+(0.3-0)^2)/2 = 0.065
    outs = [_outcome("WIN", 0.8, oid="a"), _outcome("LOSS", 0.3, oid="b")]
    m = sc.compute_calibration_metrics(outs)
    assert m["brier"] == pytest.approx(0.065, abs=1e-9)


def test_low_sample_calibration_status_is_not_calibrated():
    outs = [_outcome("WIN", 0.8, oid=f"w{i}") for i in range(5)]
    m = sc.compute_calibration_metrics(outs)
    assert m["calibration_status"] in {sc.LOW_SAMPLE, sc.CALIBRATING, sc.MIS_CALIBRATED}
    assert m["calibration_status"] != sc.CALIBRATED


def test_no_eligible_outcomes_is_no_data():
    # All synthetic -> none eligible -> NO_DATA calibration.
    outs = [_outcome("WIN", 0.8, source=oe.SYNTHETIC_FIXTURE, oid=f"s{i}") for i in range(50)]
    m = sc.compute_calibration_metrics(outs)
    assert m["calibration_status"] in {sc.NO_DATA, sc.FIXTURE_ONLY}
