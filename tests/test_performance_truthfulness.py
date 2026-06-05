"""Tests for sample-gated performance truthfulness (Phase 12 items 12-13).

Metrics must suppress below sample thresholds, never fabricate when empty, and
always carry provenance + sample size + mode + a finite display state.
"""
from __future__ import annotations

import importlib

import pytest

pt = importlib.import_module("scripts.performance_truthfulness")


def test_empty_inputs_are_no_data_not_zero():
    wr = pt.win_rate([], provenance_type="NO_DATA", mode="LIVE_MANUAL")
    assert wr.status == pt.NO_DATA and wr.value is None
    sh = pt.sharpe_ratio([], provenance_type="NO_DATA", mode="LIVE_MANUAL")
    assert sh.status == pt.NO_DATA and sh.value is None


def test_win_rate_suppressed_below_threshold():
    wr = pt.win_rate(["WIN", "LOSS", "WIN"], provenance_type="PAPER", mode="PAPER")
    assert wr.status == pt.INSUFFICIENT_SAMPLE and wr.value is None
    assert wr.expected_min_n == pt.WIN_RATE_MIN_N


def test_win_rate_shown_with_enough_samples():
    labels = ["WIN"] * 7 + ["LOSS"] * 3
    wr = pt.win_rate(labels, provenance_type="PAPER", mode="PAPER")
    assert wr.status == pt.SUCCESS
    assert wr.value == pytest.approx(0.7)
    assert wr.sample_size == 10
    assert wr.provenance_type == "PAPER" and wr.mode == "PAPER"


def test_sharpe_requires_30_samples():
    assert pt.sharpe_ratio([0.01] * 29, provenance_type="PAPER", mode="PAPER").status == pt.INSUFFICIENT_SAMPLE
    ok = pt.sharpe_ratio([0.01, -0.02] * 20, provenance_type="PAPER", mode="PAPER")
    assert ok.status == pt.SUCCESS and ok.value is not None


def test_sortino_requires_downside_points():
    # 30 all-positive returns -> no downside -> suppressed even at N>=30.
    s = pt.sortino_ratio([0.01] * 30, provenance_type="PAPER", mode="PAPER")
    assert s.status == pt.INSUFFICIENT_SAMPLE
    mixed = [0.02, -0.01, -0.03, 0.01, -0.02] * 8  # 40 points, many downside
    s2 = pt.sortino_ratio(mixed, provenance_type="PAPER", mode="PAPER")
    assert s2.status == pt.SUCCESS


def test_max_drawdown_gated_on_points():
    assert pt.max_drawdown([1, 2, 3], provenance_type="PAPER", mode="PAPER").status == pt.INSUFFICIENT_SAMPLE
    curve = [100, 110, 105, 120, 90, 95, 130, 125, 140, 100, 150]
    dd = pt.max_drawdown(curve, provenance_type="PAPER", mode="PAPER")
    assert dd.status == pt.SUCCESS and dd.value is not None and dd.value <= 0


def test_panel_never_displayable_when_empty():
    panel = pt.build_performance_panel(
        labels=[], returns=[], equity_curve=[], n_calibration_eligible=0,
        provenance_type="NO_DATA", mode="LIVE_MANUAL")
    assert panel["any_displayable"] is False
    for m in panel["metrics"]:
        assert m["value"] is None
        assert m["status"] in {pt.NO_DATA, pt.INSUFFICIENT_SAMPLE}


def test_every_metric_carries_provenance_and_mode():
    panel = pt.build_performance_panel(
        labels=["WIN"] * 12, returns=[0.01, -0.02] * 20,
        equity_curve=list(range(20)), n_calibration_eligible=40,
        provenance_type="PAPER", mode="PAPER")
    for m in panel["metrics"]:
        assert m["provenance_type"] == "PAPER"
        assert m["mode"] == "PAPER"
        assert "sample_size" in m
        assert m["status"] in pt.DISPLAY_STATES


def test_bad_display_state_rejected():
    with pytest.raises(ValueError):
        pt.GatedMetric("x", 1.0, "SPINNING_FOREVER", "PAPER", 10, "PAPER", 10)
