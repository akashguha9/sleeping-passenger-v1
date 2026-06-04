"""Backtest harness: provenance honesty, no-lookahead, end-to-end calibration."""
from __future__ import annotations

import math

from scripts import outcome_evidence as oe
from scripts import backtest_calibration as bt
from scripts import score_calibration as sc
from scripts import calibration_map as cm


def _trend_series(n=120, start=100.0, drift=0.01):
    # deterministic up-trend with small oscillation
    closes = []
    p = start
    for i in range(n):
        p = p * (1 + drift) + (1.0 if i % 2 == 0 else -1.0) * 0.05
        closes.append(round(p, 4))
    return [{"date": f"2026-01-{i+1:03d}", "close": c} for i, c in enumerate(closes)]


def test_imported_provenance_is_backtest_eligible():
    outs = bt.backtest_symbol("AAA", _trend_series(), price_provenance=bt.PROV_IMPORTED, horizon=5)
    assert outs, "should produce outcomes"
    assert all(o.source_type == oe.IMPORTED_BACKTEST for o in outs)
    assert any(o.is_calibration_eligible for o in outs)


def test_synthetic_provenance_never_eligible():
    outs = bt.backtest_symbol("AAA", _trend_series(), price_provenance=bt.PROV_SYNTHETIC, horizon=5)
    assert all(o.source_type == oe.SYNTHETIC_FIXTURE for o in outs)
    assert all(not o.is_calibration_eligible for o in outs)


def test_no_lookahead_return_uses_future_bar_only():
    bars = [{"date": f"d{i}", "close": float(i + 1)} for i in range(40)]  # 1,2,...,40
    outs = bt.backtest_symbol("LIN", bars, price_provenance=bt.PROV_IMPORTED,
                              horizon=5, min_history=20)
    # entry at index 19 (close=20), exit index 24 (close=25): LONG return = 5/20 = 0.25
    o0 = outs[0]
    assert math.isclose(o0.entry_price, 20.0)
    assert math.isclose(o0.exit_price, 25.0)
    assert math.isclose(o0.realized_return, 0.25)


def test_no_lookahead_score_uses_only_history():
    # A score fn that returns the LAST close it is given; must never see future.
    seen_max = {"v": -1.0}

    def probe(closes):
        seen_max["v"] = max(seen_max["v"], closes[-1])
        return 0.5

    bars = [{"date": f"d{i}", "close": float(i)} for i in range(40)]
    outs = bt.backtest_symbol("X", bars, price_provenance=bt.PROV_IMPORTED,
                              horizon=5, min_history=20, score_fn=probe)
    # last entry index is n-horizon-1 = 34 -> max close the scorer ever sees is 34,
    # never the final bars 35..39.
    assert seen_max["v"] == 34.0


def test_run_backtest_summary_counts():
    series = {"A": _trend_series(), "B": _trend_series(start=50.0)}
    rep = bt.run_backtest(series, price_provenance=bt.PROV_IMPORTED, horizon=5)
    assert rep["backtest_n"] > 0
    assert rep["real_n"] == 0
    assert rep["broker_api_called"] is False
    assert "Real-money readiness keys on real_n" in rep["note"]


def test_end_to_end_backtest_feeds_calibration_pipeline():
    # A series where momentum genuinely predicts forward returns -> eligible
    # backtest outcomes -> metrics compute -> recalibration map fits.
    import random
    random.seed(42)
    closes = [100.0]
    for _ in range(400):
        closes.append(round(closes[-1] * (1 + random.uniform(-0.03, 0.035)), 4))
    bars = [{"date": f"d{i}", "close": c} for i, c in enumerate(closes)]
    outs = bt.backtest_symbol("MOM", bars, price_provenance=bt.PROV_IMPORTED, horizon=5)
    eligible = [o for o in outs if o.is_calibration_eligible]
    assert len(eligible) >= 50
    metrics = sc.compute_calibration_metrics(outs)
    assert metrics["backtest_n"] > 0
    assert metrics["real_n"] == 0
    # status is a real calibration verdict on backtest data (not NO_DATA/FIXTURE)
    assert metrics["calibration_status"] in {
        sc.LOW_SAMPLE, sc.CALIBRATING, sc.CALIBRATED, sc.MIS_CALIBRATED
    }
    # backtest never grants sizing (real_n == 0)
    assert metrics["should_drive_sizing"] is False
    # a recalibration map can be fit from the backtest outcomes
    m = cm.fit_from_outcomes(outs)
    assert m.train_n + m.test_n == len(eligible)


def test_backtest_does_not_lift_real_money_readiness(tmp_path, monkeypatch):
    # Even a fully-calibrated BACKTEST must not move the real-money gate past
    # its uncalibrated cap, because the gate keys on real outcomes.
    from scripts import pre_real_money_preflight as prm
    monkeypatch.setattr(prm, "_calibration_probe",
                        lambda db: {"calibration_status": "CALIBRATED", "real_n": 0, "paper_n": 0, "n": 200})
    monkeypatch.setattr(prm, "_execution_surface_present", lambda: False)
    monkeypatch.setattr(prm, "_leverage_governance_active", lambda: True)
    monkeypatch.setattr(prm, "_securities_coverage_score", lambda db: 1.0)
    out = prm.assess_real_money_readiness(
        tmp_path / "x.db", backend_tests_passing=True, frontend_tests_passing=True,
        preflight={"ok": True},
    )
    # CALIBRATED but real_n=0 -> paper/backtest grade -> capped at 7.0, small-only at most
    assert out["readiness_score"] <= 7.0
    assert out["allowed_mode"] in {prm.MODE_TINY_PROBE, prm.MODE_MANUAL_SMALL}
