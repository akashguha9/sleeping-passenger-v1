"""DISC-B2/B3/B4/B5 regression: bias guards, coverage honesty, determinism.

All fixture-based — no network, per the sandbox constraint.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from scripts.discovery_bias_guards import (
    LookaheadError,
    assert_entry_no_lookahead,
    check_series_quality,
)
from scripts.run_discovery_backtest import EDGE_CAVEAT, run_discovery_backtest


def _bars(start: str, days: int, *, price=100.0, skip: set[int] = frozenset(),
          split_on: int | None = None) -> list[dict]:
    out = []
    d0 = datetime.strptime(start, "%Y-%m-%d")
    p = price
    for i in range(days):
        if i in skip:
            continue
        if split_on is not None and i == split_on:
            p = p / 3  # unadjusted 3:1 split jump (>50% move)
        dt = d0 + timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        out.append({"date": dt.strftime("%Y-%m-%d"), "close": str(round(p, 2)),
                    "open": str(round(p, 2)), "high": str(round(p, 2)),
                    "low": str(round(p, 2)), "volume": "1000",
                    "source": "YFINANCE_SNAPSHOT"})
        p += 0.5
    return out


def _snapshot(bars_by_symbol: dict, start="2026-01-01", end="2026-03-31") -> dict:
    return {
        "start": start,
        "end": end,
        "requested_symbols": list(bars_by_symbol),
        "resolved": [{"yahoo_symbol": s} for s in bars_by_symbol],
        "bars_by_symbol": bars_by_symbol,
        "snapshot_sha256": "fixture",
    }


# ---------------------------------------------------------------------------
# B2 — guards
# ---------------------------------------------------------------------------


def test_lookahead_assertion_raises():
    with pytest.raises(LookaheadError):
        assert_entry_no_lookahead(
            datetime(2026, 2, 1), datetime(2026, 1, 31)
        )
    assert_entry_no_lookahead(datetime(2026, 2, 1), datetime(2026, 2, 1))


def test_quality_flags_gap_split_and_delisting():
    bars = _bars("2026-01-01", 40, skip=set(range(10, 20)), split_on=25)
    q = check_series_quality(bars, window_end=datetime(2026, 3, 31))
    assert "gaps" in q["flags"]
    assert "suspected_splits" in q["flags"]
    assert q["delisting_suspected"] is True  # series ends well before 3/31
    assert q["clean"] is False


def test_quality_clean_series():
    bars = _bars("2026-01-01", 95)
    q = check_series_quality(bars, window_end=datetime(2026, 3, 31))
    assert q["clean"] is True
    assert q["flags"] == []


# ---------------------------------------------------------------------------
# B3/B5 — coverage honesty + survivorship accounting
# ---------------------------------------------------------------------------


def test_report_counts_truncated_series_instead_of_forgetting(tmp_path):
    snap = _snapshot({
        "GOODCO": _bars("2026-01-01", 95),
        "DELISTCO": _bars("2026-01-01", 20),  # ends mid-window
    })
    signals = [
        {"ticker": "GOODCO", "timestamp": "2026-01-10", "score": 0.8,
         "signal_id": "S1"},
        {"ticker": "DELISTCO", "timestamp": "2026-01-10", "score": 0.8,
         "signal_id": "S2"},
    ]
    report = run_discovery_backtest(snap, signals, horizon_days=10)
    cov = report["coverage"]
    assert cov["statement"] == "2 requested → 2 validated → 1 with clean data"
    assert "DELISTCO" in cov["flagged_symbols"]
    sg = report["survivorship_guard"]
    assert sg["count"] == 1
    assert sg["signals_on_truncated_series"][0]["ticker"] == "DELISTCO"


def test_missing_snapshot_series_fails_loud():
    snap = _snapshot({"GOODCO": _bars("2026-01-01", 95)})
    signals = [{"ticker": "GHOSTCO", "timestamp": "2026-01-10", "score": 0.5}]
    with pytest.raises(ValueError) as exc:
        run_discovery_backtest(snap, signals)
    assert "GHOSTCO" in str(exc.value)
    assert "refusing to run" in str(exc.value)


def test_report_leads_with_methodology_and_carries_caveats():
    snap = _snapshot({"GOODCO": _bars("2026-01-01", 95)})
    signals = [{"ticker": "GOODCO", "timestamp": "2026-01-10", "score": 0.8,
                "signal_id": "S1"}]
    report = run_discovery_backtest(snap, signals, horizon_days=10)
    keys = list(report.keys())
    assert keys[0] == "methodology"
    assert report["methodology"]["caveat"] == EDGE_CAVEAT
    assert report["results"]["caveat"] == EDGE_CAVEAT
    assert report["results_firewall"] == EDGE_CAVEAT
    assert "not evidence of forward edge" in EDGE_CAVEAT.lower()
    # advisory stamps
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False


def test_outcomes_are_no_lookahead_and_win_loss_counted():
    snap = _snapshot({"GOODCO": _bars("2026-01-01", 95)})  # rising series
    signals = [{"ticker": "GOODCO", "timestamp": "2026-01-10", "score": 0.8,
                "signal_id": "S1"}]
    report = run_discovery_backtest(snap, signals, horizon_days=10)
    res = report["results"]
    assert res["outcomes_produced"] == 1
    assert res["wins"] == 1  # monotonically rising fixture
    out = res["outcomes"][0]
    assert out["opened_at"] >= "2026-01-10"  # entry never precedes signal


# ---------------------------------------------------------------------------
# B4 — determinism
# ---------------------------------------------------------------------------


def test_same_inputs_produce_byte_identical_reports():
    snap = _snapshot({
        "GOODCO": _bars("2026-01-01", 95),
        "DELISTCO": _bars("2026-01-01", 20),
    })
    signals = [
        {"ticker": "GOODCO", "timestamp": "2026-01-10", "score": 0.8,
         "signal_id": "S1"},
    ]
    r1 = run_discovery_backtest(snap, signals, horizon_days=10)
    r2 = run_discovery_backtest(
        json.loads(json.dumps(snap)), json.loads(json.dumps(signals)),
        horizon_days=10,
    )
    b1 = json.dumps(r1, indent=2, sort_keys=True)
    b2 = json.dumps(r2, indent=2, sort_keys=True)
    assert b1 == b2, "same inputs must produce byte-identical reports"
    # run identity derives from inputs, not wall clock
    assert "generated_at" not in b1
    assert r1["run_metadata"]["run_id_sha256"] == r2["run_metadata"]["run_id_sha256"]


def test_run_metadata_records_hashes_and_range():
    snap = _snapshot({"GOODCO": _bars("2026-01-01", 95)})
    signals = [{"ticker": "GOODCO", "timestamp": "2026-01-10", "score": 0.8,
                "signal_id": "S1"}]
    meta = run_discovery_backtest(snap, signals, horizon_days=10)["run_metadata"]
    assert meta["tool_version"]
    assert meta["date_range"] == {"start": "2026-01-01", "end": "2026-03-31"}
    assert len(meta["universe_sha256"]) == 64
    assert len(meta["signals_sha256"]) == 64
