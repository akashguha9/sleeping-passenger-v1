"""Tests — quant statistics primitives + return engine.

Covers the hackathon testing contract: derivative/decay invariants,
UNKNOWN semantics (missing != zero), no-lookahead Z-scores, bootstrap
determinism, monotonicity, calibration metrics, BH-FDR.
"""
from __future__ import annotations

import math

import pytest

from scripts.quant_return_engine import (
    OK,
    UNKNOWN,
    abnormal_return,
    car,
    daily_volatility,
    forward_return,
    log_return,
)
from scripts.quant_statistics_engine import (
    INSUFFICIENT_DATA,
    benjamini_hochberg,
    bootstrap_ci,
    brier_score,
    fit_exponential_decay,
    information_coefficient,
    log_loss,
    mean_with_ci,
    quantile_monotonicity,
    reliability_buckets,
    standardized_shock,
    t_statistic,
)


def _series(vals, start=1):
    return {f"2026-01-{d:02d}": v for d, v in enumerate(vals, start)}


class TestReturns:
    def test_log_return_basic(self):
        s = _series([100.0, 110.0])
        assert log_return(s, "2026-01-01", "2026-01-02") == pytest.approx(
            math.log(1.1))

    def test_missing_bar_is_unknown_not_zero(self):
        s = _series([100.0, 110.0])
        assert log_return(s, "2026-01-01", "2026-01-03") is None
        fwd = forward_return(s, "2026-01-01", 5)
        assert fwd["status"] == UNKNOWN

    def test_abnormal_return_market_adjusted(self):
        si = _series([100, 105, 110, 115, 120])
        sm = _series([100, 101, 102, 103, 104])
        ar = abnormal_return(si, sm, "2026-01-01", 2)
        assert ar["status"] == OK
        assert ar["ar"] == pytest.approx(
            math.log(110 / 100) - math.log(102 / 100))

    def test_missing_benchmark_unknown_never_raw(self):
        si = _series([100, 105, 110])
        ar = abnormal_return(si, {}, "2026-01-01", 1)
        assert ar["status"] == UNKNOWN

    def test_car_sums_to_window_ar(self):
        si = _series([100, 105, 110, 118])
        sm = _series([100, 101, 103, 104])
        c = car(si, sm, "2026-01-01", 3)
        window = abnormal_return(si, sm, "2026-01-01", 3)
        assert c["status"] == OK
        assert c["car"] == pytest.approx(window["ar"])
        assert len(c["path"]) == 3

    def test_daily_volatility_gate(self):
        assert daily_volatility(_series([100, 101]))["status"] == \
            INSUFFICIENT_DATA


class TestStatistics:
    def test_mean_ci_gate(self):
        assert mean_with_ci([1.0, 2.0])["status"] == INSUFFICIENT_DATA
        out = mean_with_ci([1, 2, 3, 4, 5])
        assert out["status"] == OK and out["n"] == 5
        assert out["ci"][0] < out["mean"] < out["ci"][1]

    def test_t_statistic_zero_mean(self):
        out = t_statistic([-1.0, 1.0, -1.0, 1.0, 0.0])
        assert abs(out["t"]) < 0.1

    def test_bootstrap_deterministic_and_brackets_point(self):
        xs = [0.5, 1.5, 1.0, 2.0, 0.0, 1.2, 0.8, 1.7, 0.3, 1.1]
        a = bootstrap_ci(xs, seed=7)
        b = bootstrap_ci(xs, seed=7)
        assert a == b  # deterministic
        assert a["ci"][0] <= a["point"] <= a["ci"][1]

    def test_block_bootstrap_runs(self):
        xs = [float(i % 5) for i in range(30)]
        out = bootstrap_ci(xs, block=5)
        assert out["status"] == OK and out["block"] == 5

    def test_information_coefficient_perfect_and_gate(self):
        sig = list(range(20))
        fwd = [2.0 * s for s in sig]
        out = information_coefficient([float(s) for s in sig], fwd)
        assert out["ic"] == pytest.approx(1.0)
        assert out["rank_ic"] == pytest.approx(1.0)
        assert information_coefficient([1.0], [1.0])["status"] == \
            INSUFFICIENT_DATA

    def test_monotonicity_detects_true_and_absent_relationships(self):
        n = 60
        sig = [float(i) for i in range(n)]
        fwd_up = [0.001 * i for i in range(n)]
        mono = quantile_monotonicity(sig, fwd_up, k=5)
        assert mono["is_strictly_monotone"] is True
        assert mono["top_minus_bottom"] > 0
        fwd_flat = [0.0] * n
        flat = quantile_monotonicity(sig, fwd_flat, k=5)
        assert flat["is_strictly_monotone"] is False

    def test_brier_and_skill_vs_constant(self):
        ps = [0.9] * 10 + [0.1] * 10
        ys = [1] * 10 + [0] * 10
        out = brier_score(ps, ys)
        assert out["brier"] == pytest.approx(0.01)
        assert out["skill_vs_constant"] > 0
        assert log_loss(ps, ys)["log_loss"] < 0.2

    def test_log_loss_epsilon_no_math_domain_error(self):
        out = log_loss([0.0, 1.0] * 5, [0, 1] * 5)
        assert math.isfinite(out["log_loss"])

    def test_reliability_buckets_flag_small_buckets(self):
        ps = [0.05] * 8 + [0.95] * 8
        ys = [0] * 8 + [1] * 8
        out = reliability_buckets(ps, ys, k=5)
        statuses = [b["status"] for b in out["buckets"]]
        assert statuses.count(INSUFFICIENT_DATA) == 3  # empty middle buckets
        assert out["expected_calibration_error"] is not None

    def test_benjamini_hochberg(self):
        out = benjamini_hochberg([0.001, 0.011, 0.02, 0.8, 0.9])
        assert out["n_survive"] >= 1
        assert out["survives"][0] is True
        assert out["survives"][4] is False

    def test_standardized_shock_no_lookahead(self):
        # constant deltas then a jump: z should be large; moments exclude
        # the final delta itself.
        series = [(i, 0.30 + 0.005 * i) for i in range(12)] + [(12, 0.50)]
        out = standardized_shock(series)
        assert out["status"] == OK
        assert out["lookahead_free"] is True
        assert out["z"] > 3.0

    def test_decay_fit_half_life_invariant(self):
        lam = 0.1
        pts = [(t, 5.0 * math.exp(-lam * t)) for t in range(0, 40, 4)]
        out = fit_exponential_decay(pts)
        assert out["lambda"] == pytest.approx(lam, rel=1e-6)
        assert out["half_life"] == pytest.approx(math.log(2) / lam, rel=1e-6)
        assert out["fit_adequate"] is True

    def test_decay_fit_flags_bad_exponential(self):
        pts = [(t, 1.0 + 0.5 * math.sin(t)) for t in range(0, 20, 2)]
        out = fit_exponential_decay(pts)
        assert out["status"] == OK
        assert out["fit_adequate"] is False  # do not force exponential decay
