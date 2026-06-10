"""Advisory backtester proofs (Pass 4, Phase 5) — synthetic data, known answers."""
from __future__ import annotations

import datetime as dt
import math

import pytest

from scripts import backtest_advisory_signals as bt

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
NO_COST = bt.Assumptions(transaction_cost=0.0, slippage=0.0)


def _sample(i: int, entry: float, exit_: float, **kw) -> dict:
    base = {
        "signal_id": f"S{i}", "symbol": "SYN",
        "t_decision": (T0 + dt.timedelta(days=i)).isoformat(),
        "t_outcome": (T0 + dt.timedelta(days=i + 5)).isoformat(),
        "entry_price": entry, "exit_price": exit_,
    }
    base.update(kw)
    return base


def test_return_and_cost_formulas_exact():
    a = bt.Assumptions(transaction_cost=0.001, slippage=0.0005)
    # R = (110-100)/100 = 0.10; net = 0.10 - 0.0015
    assert bt.net_return(100.0, 110.0, a) == pytest.approx(0.0985)
    with pytest.raises(ValueError):
        bt.net_return(0.0, 110.0, a)


def test_metrics_on_known_dataset():
    # Net returns: +0.10, -0.05, +0.02, -0.01  (no costs)
    rets = [0.10, -0.05, 0.02, -0.01]
    m = bt.compute_metrics(rets, NO_COST)
    assert m["n"] == 4
    assert m["hit_rate"] == pytest.approx(0.5)
    assert m["expectancy"] == pytest.approx(0.015)
    mean = 0.015
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / 4)
    assert m["sharpe"] == pytest.approx(mean / std)
    dstd = math.sqrt((0.05 ** 2 + 0.01 ** 2) / 4)
    assert m["sortino"] == pytest.approx(mean / dstd)
    assert m["small_sample_warning"] is True


def test_max_drawdown_known_path():
    # equity: 1.10 → 0.88 (peak 1.10): MDD = (1.10-0.88)/1.10 = 0.2
    assert bt.max_drawdown([0.10, -0.20]) == pytest.approx(0.2)
    assert bt.max_drawdown([0.05, 0.05]) == 0.0


def test_zero_variance_yields_no_sharpe_claim():
    m = bt.compute_metrics([0.01], NO_COST)
    assert m["sharpe"] is None  # never divide-by-zero into a fake number


def test_walk_forward_split_is_chronological():
    samples = [_sample(i, 100, 101) for i in range(10)]
    split = bt.walk_forward_split(
        samples,
        t1=(T0 + dt.timedelta(days=3)).isoformat(),
        t2=(T0 + dt.timedelta(days=6)).isoformat(),
    )
    assert [s["signal_id"] for s in split["train"]] == ["S0", "S1", "S2", "S3"]
    assert [s["signal_id"] for s in split["validation"]] == ["S4", "S5", "S6"]
    assert [s["signal_id"] for s in split["test"]] == ["S7", "S8", "S9"]
    with pytest.raises(ValueError):
        bt.walk_forward_split(samples, t1=T0 + dt.timedelta(days=6), t2=T0)


def test_headline_is_test_split_only():
    # Train wins big; test loses — the headline must show the test loss.
    samples = [_sample(i, 100, 120) for i in range(6)]          # train+val
    samples += [_sample(i, 100, 95) for i in range(7, 10)]      # test
    report = bt.run_backtest(
        samples, assumptions=NO_COST,
        t1=(T0 + dt.timedelta(days=4)).isoformat(),
        t2=(T0 + dt.timedelta(days=6)).isoformat(),
    )
    assert report["headline_basis"] == "out_of_sample_test_split"
    assert report["headline"]["expectancy"] == pytest.approx(-0.05)
    assert report["walk_forward"]["train"]["expectancy"] == pytest.approx(0.20)


def test_in_sample_only_is_loudly_labeled():
    report = bt.run_backtest([_sample(1, 100, 110)], assumptions=NO_COST)
    assert "IN_SAMPLE_ONLY" in report["headline_basis"]
    assert "assumptions" in report and report["assumptions"]["note"]


def test_temporal_guard_rejects_are_reported_not_dropped():
    leaky = _sample(1, 100, 110)
    leaky["t_outcome"] = leaky["t_decision"]  # target leakage
    report = bt.run_backtest([leaky, _sample(2, 100, 110)], assumptions=NO_COST)
    assert report["samples_rejected_by_temporal_guard"] == 1
    assert report["rejection_reasons"][0]["reasons"]
    assert report["headline"]["n"] == 1


def test_abstention_rate_and_advisory_stamps():
    samples = [_sample(1, 100, 110), _sample(2, 100, 110, side="ABSTAIN")]
    report = bt.run_backtest(samples, assumptions=NO_COST)
    assert report["abstention_rate"] == pytest.approx(0.5)
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0


def test_benchmark_comparison_known_answer():
    s = _sample(1, 100, 110, benchmark_entry=200, benchmark_exit=210)
    report = bt.run_backtest([s], assumptions=NO_COST)
    # signal 10% vs benchmark 5% → excess 5%
    assert report["headline"]["mean_excess_vs_benchmark"] == pytest.approx(0.05)


def test_regime_segmentation():
    samples = [_sample(1, 100, 110, regime="bull"), _sample(2, 100, 90, regime="bear")]
    report = bt.run_backtest(samples, assumptions=NO_COST)
    assert report["regimes"]["bull"]["expectancy"] == pytest.approx(0.10)
    assert report["regimes"]["bear"]["expectancy"] == pytest.approx(-0.10)


def test_empty_input_claims_nothing():
    report = bt.run_backtest([], assumptions=NO_COST)
    assert report["headline"]["n"] == 0
    assert "no metrics claimed" in report["headline"]["warning"]
