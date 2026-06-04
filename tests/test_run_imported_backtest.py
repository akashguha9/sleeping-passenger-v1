"""Tests for the imported-OHLCV backtest runner (no-lookahead, provenance)."""
from __future__ import annotations

import math

from scripts import outcome_evidence as oe
from scripts import run_imported_backtest as rib


def _bars(ticker, start="2026-01-01", n=60, base=100.0, step=1.0, source="YFINANCE_IMPORTED"):
    from datetime import datetime, timedelta
    d0 = datetime.strptime(start, "%Y-%m-%d")
    bars = []
    for i in range(n):
        c = base + i * step
        d = (d0 + timedelta(days=i)).strftime("%Y-%m-%d")
        bars.append({"ticker": ticker, "date": d, "open": c, "high": c + 1,
                     "low": c - 1, "close": c, "volume": 1000, "source": source})
    return bars


def test_imported_ohlcv_creates_backtest_evidence():
    bars = {"AAA": _bars("AAA")}
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-05", "score": 0.8}]
    outs = rib.backtest_signals(sigs, bars, horizon_days=20)
    assert len(outs) == 1
    assert outs[0].source_type == oe.IMPORTED_BACKTEST
    assert outs[0].is_calibration_eligible is True


def test_return_formula_exact_long():
    # linear closes from 100 step 1. entry at first bar >= 2026-01-05 -> 2026-01-05.
    # That is index 4 (close 104). exit first bar >= +20 days = 2026-01-25 -> index 24 (close 124).
    bars = {"AAA": _bars("AAA")}
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-05", "score": 0.8}]
    o = rib.backtest_signals(sigs, bars, horizon_days=20)[0]
    assert math.isclose(o.entry_price, 104.0)
    assert math.isclose(o.exit_price, 124.0)
    # LONG return = (124-104)/104
    assert math.isclose(o.realized_return, (124.0 - 104.0) / 104.0)


def test_short_direction_return():
    bars = {"AAA": _bars("AAA")}
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-05", "score": 0.8, "direction": "SHORT"}]
    o = rib.backtest_signals(sigs, bars, horizon_days=20)[0]
    # price rose -> short loses
    assert o.realized_return < 0
    assert o.outcome_label == "LOSS"


def test_no_lookahead_entry_is_on_or_after_signal():
    bars = {"AAA": _bars("AAA")}
    # signal on a non-bar gap still maps to first bar >= signal date
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-05", "score": 0.7}]
    o = rib.backtest_signals(sigs, bars, horizon_days=20)[0]
    assert o.opened_at >= "2026-01-05"
    assert o.closed_at > o.opened_at


def test_missing_exit_bar_marks_open_ineligible():
    # horizon beyond available data -> no exit bar -> OPEN, ineligible
    bars = {"AAA": _bars("AAA", n=30)}
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-25", "score": 0.8}]  # near the end
    outs = rib.backtest_signals(sigs, bars, horizon_days=20)
    assert outs and outs[0].outcome_label == oe.OPEN
    assert outs[0].is_calibration_eligible is False


def test_synthetic_bars_refused_in_runtime():
    bars = {"AAA": _bars("AAA", source=oe.SYNTHETIC_FIXTURE)}
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-05", "score": 0.8}]
    outs = rib.backtest_signals(sigs, bars, horizon_days=20, runtime_mode=True)
    assert outs == []  # synthetic bars refused -> no outcomes


def test_synthetic_bars_allowed_in_test_mode_but_ineligible():
    bars = {"AAA": _bars("AAA", source=oe.SYNTHETIC_FIXTURE)}
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-05", "score": 0.8}]
    outs = rib.backtest_signals(sigs, bars, horizon_days=20, runtime_mode=False)
    assert outs and outs[0].source_type == oe.SYNTHETIC_FIXTURE
    assert outs[0].is_calibration_eligible is False


def test_backtest_n_increases_real_n_zero():
    bars = {"AAA": _bars("AAA")}
    sigs = [{"ticker": "AAA", "timestamp": d, "score": 0.6}
            for d in ("2026-01-05", "2026-01-06", "2026-01-07")]
    outs = rib.backtest_signals(sigs, bars, horizon_days=10)
    prov = oe.provenance_counts(outs)
    assert prov["backtest_n"] == 3
    assert prov["real_n"] == 0


def test_readiness_not_lifted_by_backtest(tmp_path, monkeypatch):
    from scripts import pre_real_money_preflight as prm
    monkeypatch.setattr(prm, "_calibration_probe",
                        lambda db: {"calibration_status": "CALIBRATED", "real_n": 0,
                                    "paper_n": 0, "n": 300})
    monkeypatch.setattr(prm, "_execution_surface_present", lambda: False)
    monkeypatch.setattr(prm, "_leverage_governance_active", lambda: True)
    monkeypatch.setattr(prm, "_securities_coverage_score", lambda db: 1.0)
    out = prm.assess_real_money_readiness(
        tmp_path / "x.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight={"ok": True})
    assert out["readiness_score"] <= 7.0
    assert out["broker_api_called"] is False


def test_db_runner_reads_ohlcv(tmp_path):
    from scripts import persistence
    from scripts import ohlcv_import_contract as contract
    db = tmp_path / "bt.db"
    rows = [contract.validate_row(b)[2] for b in _bars("AAA")]
    persistence.insert_ohlcv_bars(rows, db_path=db)
    sigs = [{"ticker": "AAA", "timestamp": "2026-01-05", "score": 0.8}]
    rep = rib.run_imported_backtest_from_db(sigs, db_path=db, horizon_days=20)
    assert rep["backtest_n"] == 1
    assert rep["broker_api_called"] is False
