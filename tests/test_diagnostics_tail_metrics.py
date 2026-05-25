"""Tests for diagnostics tail metrics + performance_tail_score."""
from __future__ import annotations

from scripts import diagnostics_tail_metrics as tail_mod


def test_percentile_basic():
    assert tail_mod.percentile([], 0.95) == 0.0
    assert tail_mod.percentile([10.0], 0.95) == 10.0
    assert tail_mod.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


def test_release_thresholds_pass_for_healthy_distribution():
    # 1000 samples; p99 ~ 200, max ~ 300; tail ratio < 2.5 so all budgets pass.
    samples = [100.0] * 980 + [200.0] * 19 + [300.0]
    metrics = tail_mod.compute_tail_metrics(
        samples, cold_recompute_count_after_prewarm=0,
    )
    assert metrics["release_thresholds_ok"] is True
    assert metrics["p95_ms"] <= tail_mod.DEFAULT_HOT_P95_BUDGET_MS
    assert metrics["p99_ms"] <= tail_mod.DEFAULT_HOT_P99_BUDGET_MS
    assert metrics["max_ms"] <= tail_mod.DEFAULT_HOT_MAX_BUDGET_MS
    assert metrics["thresholds"]["tail_ratio_ok"] is True
    assert metrics["performance_tail_score"] > 9.0


def test_release_thresholds_fail_when_max_blows_budget():
    # p95/p99 fine, but a 50_000 ms tail blows the max budget.
    samples = [50.0] * 99 + [50_000.0]
    metrics = tail_mod.compute_tail_metrics(samples)
    assert metrics["release_thresholds_ok"] is False
    assert metrics["thresholds"]["hot_path_max_ms_ok"] is False
    # Tail ratio also balloons.
    assert metrics["thresholds"]["tail_ratio_ok"] is False


def test_release_thresholds_fail_when_cold_recompute_after_prewarm():
    samples = [50.0] * 100
    metrics = tail_mod.compute_tail_metrics(
        samples, cold_recompute_count_after_prewarm=3,
    )
    assert metrics["release_thresholds_ok"] is False
    assert metrics["thresholds"]["cold_recompute_count_after_prewarm_ok"] is False


def test_release_thresholds_fail_when_stale_snapshot_count_nonzero():
    samples = [50.0] * 100
    metrics = tail_mod.compute_tail_metrics(samples, stale_snapshot_count=1)
    assert metrics["release_thresholds_ok"] is False
    assert metrics["thresholds"]["stale_snapshot_count_ok"] is False


def test_sample_count_zero_marks_thresholds_invalid():
    metrics = tail_mod.compute_tail_metrics([])
    assert metrics["release_thresholds_ok"] is False
    assert metrics["thresholds"]["sample_count_ok"] is False


def test_performance_tail_score_bounded():
    metrics = tail_mod.compute_tail_metrics([100.0] * 100)
    assert 0.0 <= metrics["performance_tail_score"] <= 10.0
