"""Calibration metric unit tests — proof_loop_hardening_sprint, Phase 3.

These tests pin the mathematical contracts for Brier, ECE, MCE, and
clipped LogLoss as defined in the sprint spec.  They are pure-Python:
no DB, no network, no broker calls, no fixtures.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from scripts.calibration_report import (
    Observation,
    brier_score,
    classify_n_real_status,
    expected_calibration_error,
    log_loss,
    maximum_calibration_error,
    reliability_buckets,
)


pytestmark = [
    pytest.mark.calibration,
    pytest.mark.safety_floor,
]


def _obs(p_y_pairs):
    return [Observation(p=float(p), y=int(y)) for p, y in p_y_pairs]


def test_brier_perfect_calibration_zero():
    obs = _obs([(0.0, 0), (1.0, 1), (0.0, 0), (1.0, 1)])
    assert brier_score(obs) == pytest.approx(0.0)


def test_brier_worst_calibration_one():
    obs = _obs([(1.0, 0), (0.0, 1)])
    assert brier_score(obs) == pytest.approx(1.0)


def test_brier_handles_midpoint():
    # p=0.5, mixed outcome.  (0.5-0)^2 = 0.25, (0.5-1)^2 = 0.25 -> mean = 0.25
    obs = _obs([(0.5, 0), (0.5, 1), (0.5, 0), (0.5, 1)])
    assert brier_score(obs) == pytest.approx(0.25)


def test_brier_empty_is_nan():
    assert math.isnan(brier_score([]))


def test_ece_zero_when_each_bin_is_perfectly_calibrated():
    # All p=1 observations are y=1, all p=0 observations are y=0.
    obs = _obs([(1.0, 1)] * 5 + [(0.0, 0)] * 5)
    assert expected_calibration_error(obs, n_buckets=10) == pytest.approx(0.0)


def test_ece_handles_p0_and_p1_binning():
    # p=0 must land in the first bin; p=1 must land in the last bin.
    # If both bins are perfectly calibrated, ECE = 0.
    obs = _obs([(0.0, 0), (1.0, 1)])
    buckets = reliability_buckets(obs, n_buckets=10)
    occupied = [b for b in buckets if b["count"] > 0]
    indices = sorted(b["bucket_index"] for b in occupied)
    assert indices == [0, 9]
    assert expected_calibration_error(obs, n_buckets=10) == pytest.approx(0.0)


def test_mce_max_bin_error():
    # Bin around 0.9 carries 0 successes -> calibration_error = 0.9.
    # Bin around 0.1 carries 1.0 success -> calibration_error = 0.9.
    # Other bins empty.  MCE = 0.9.
    obs = _obs([(0.9, 0), (0.1, 1)])
    mce = maximum_calibration_error(obs, n_buckets=10)
    assert mce == pytest.approx(0.9, abs=1e-6)


def test_log_loss_clips_extremes_so_it_never_returns_inf():
    obs = _obs([(0.0, 1), (1.0, 0)])
    ll = log_loss(obs, eps=1e-15)
    # With eps=1e-15 the clipped probability is ~1e-15, so each term is
    # -ln(1e-15) ~ 34.5.  Mean = 34.5.  Finite, large, but finite.
    assert math.isfinite(ll)
    assert ll > 30.0


def test_log_loss_zero_when_perfect():
    obs = _obs([(1.0, 1), (0.0, 0)] * 3)
    assert log_loss(obs) == pytest.approx(0.0, abs=1e-9)


def test_log_loss_empty_is_nan():
    assert math.isnan(log_loss([]))


def test_classify_n_real_status_table():
    assert classify_n_real_status(0) == "INSUFFICIENT_EVIDENCE"
    assert classify_n_real_status(1) == "TOO_FEW_OUTCOMES"
    assert classify_n_real_status(19) == "TOO_FEW_OUTCOMES"
    assert classify_n_real_status(20) == "MEASURABLE_WITH_WARNING"
    assert classify_n_real_status(199) == "MEASURABLE_WITH_WARNING"
    assert classify_n_real_status(200) == "MEASURED"
    assert classify_n_real_status(5000) == "MEASURED"


def test_classify_n_real_status_rejects_negative_as_insufficient():
    # Defensive: negative inputs (corrupted artifact) collapse to insufficient.
    assert classify_n_real_status(-1) == "INSUFFICIENT_EVIDENCE"
