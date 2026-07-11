"""Tests for scripts/titration_outcome_contract.py — versioned transition labels.

Covers: forward returns at bar-indexed horizons, sigma_pre leakage boundary,
maturation states, MFE/MAE/time-to-transition, stale-entry and synthetic
refusals, direction honesty, benchmark-relative labels, config fallback.
"""

from __future__ import annotations

import json

from scripts.titration_outcome_contract import (
    DATA_MISSING,
    DEFAULT_OUTCOME_CONFIG,
    EXCLUDED,
    INVALID,
    MATURED,
    NOT_YET_MATURED,
    compute_forward_responses,
    compute_sigma_pre,
    load_outcome_config,
    locate_entry_index,
    prepare_bars,
)


def _bars(closes: list[float], start_day: int = 1, source: str = "MANUAL_CSV_IMPORT"):
    return [
        {"date": f"2026-03-{start_day + i:02d}", "close": c, "source": source}
        for i, c in enumerate(closes)
    ]


def _flat_history(n: int = 30, price: float = 100.0):
    # Slightly varying pre-history so sigma_pre is positive but tiny.
    return [price + (0.2 if i % 2 else -0.2) for i in range(n)]


EVENT_TS = "2026-03-25T10:00:00+00:00"


def test_forward_return_and_maturation():
    closes = _flat_history(24) + [100.0, 101.0, 102.0, 103.0, 105.0, 110.0]
    # entry bar = first bar >= 2026-03-25 -> index 24 (day 25), close 100.
    result = compute_forward_responses(_bars(closes, 1), EVENT_TS)
    assert result["entry_bar_date"] == "2026-03-25"
    assert result["reference_price"] == 100.0
    rows = {r["horizon"]: r for r in result["horizons"]}
    assert rows[1]["maturation"] == MATURED
    assert abs(rows[1]["r_raw"] - 0.01) < 1e-9
    assert rows[5]["maturation"] == MATURED
    assert abs(rows[5]["r_raw"] - 0.10) < 1e-9
    # Horizons beyond available bars are honestly immature.
    assert rows[10]["maturation"] == NOT_YET_MATURED
    assert rows[20]["maturation"] == NOT_YET_MATURED
    assert rows[10]["r_raw"] is None


def test_sigma_pre_uses_only_pre_entry_bars():
    # Pre-entry: tiny oscillation. Post-entry: huge moves. If sigma leaked
    # forward data it would be large; it must be small.
    closes = _flat_history(24) + [100.0, 200.0, 50.0, 300.0, 25.0, 400.0]
    bars, _ = prepare_bars(_bars(closes, 1), runtime_mode=True)
    entry_idx, _ = locate_entry_index(bars, EVENT_TS)
    assert entry_idx == 24
    sigma, reason = compute_sigma_pre(bars, entry_idx)
    assert reason is None
    assert sigma is not None and sigma < 0.02, "sigma_pre must not see forward bars"


def test_z_scaling_and_absolute_label():
    closes = _flat_history(24) + [100.0, 101.0, 102.0, 103.0, 104.0, 130.0]
    result = compute_forward_responses(_bars(closes, 1), EVENT_TS)
    rows = {r["horizon"]: r for r in result["horizons"]}
    # +30% on ~0.4% daily sigma is a massive z -> absolute transition = 1.
    assert rows[5]["y_absolute"] == 1
    # +1% over 1 day on that sigma: z = .01/.004 = 2.5 >= 1.0 -> also 1;
    # verify the z value itself is positive and finite.
    assert rows[1]["z"] is not None and rows[1]["z"] > 0


def test_mfe_mae_and_time_to_transition():
    closes = _flat_history(24) + [100.0, 99.0, 104.0, 98.0, 101.0, 100.5]
    result = compute_forward_responses(_bars(closes, 1), EVENT_TS)
    rows = {r["horizon"]: r for r in result["horizons"]}
    row5 = rows[5]
    assert abs(row5["mfe"] - 0.04) < 1e-9   # best close 104
    assert abs(row5["mae"] - (-0.02)) < 1e-9  # worst close 98
    # First |z_tau| >= 1.0 happens on day 1 (-1% on tiny sigma).
    assert row5["time_to_transition_days"] == 1


def test_no_transition_when_flat():
    closes = _flat_history(24) + [100.0] * 6
    result = compute_forward_responses(_bars(closes, 1), EVENT_TS)
    rows = {r["horizon"]: r for r in result["horizons"]}
    # sigma is small but returns are ~0.2% oscillation vs history: compute
    # honest labels: r_raw for h=5 is 0 -> y_absolute 0.
    assert rows[5]["y_absolute"] in (0, 1)  # deterministic given data
    assert rows[5]["r_raw"] == 0.0
    assert rows[5]["y_absolute"] == 0
    assert rows[5]["time_to_transition_days"] is None


def test_direction_never_fabricated():
    closes = _flat_history(24) + [100.0, 110.0, 120.0, 125.0, 130.0, 140.0]
    result = compute_forward_responses(_bars(closes, 1), EVENT_TS, direction=None)
    rows = {r["horizon"]: r for r in result["horizons"]}
    assert result["direction_used"] is None
    assert rows[5]["y_directional"] is None
    # With a real direction, the directional label appears.
    result_dir = compute_forward_responses(_bars(closes, 1), EVENT_TS, direction="LONG")
    rows_dir = {r["horizon"]: r for r in result_dir["horizons"]}
    assert result_dir["direction_used"] == 1
    assert rows_dir[5]["y_directional"] == 1


def test_benchmark_relative_label():
    closes = _flat_history(24) + [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    bench = _flat_history(24) + [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    result = compute_forward_responses(
        _bars(closes, 1), EVENT_TS, benchmark_bars=_bars(bench, 1)
    )
    rows = {r["horizon"]: r for r in result["horizons"]}
    # Identical to benchmark -> relative z ~ 0 -> no relative transition.
    assert rows[5]["y_benchmark_relative"] == 0
    assert result["benchmark_used"] == "SPY"


def test_missing_benchmark_yields_none_not_zero_claim():
    closes = _flat_history(24) + [100.0, 105.0, 110.0, 112.0, 115.0, 120.0]
    result = compute_forward_responses(_bars(closes, 1), EVENT_TS, benchmark_bars=None)
    rows = {r["horizon"]: r for r in result["horizons"]}
    assert rows[5]["y_benchmark_relative"] is None
    assert result["benchmark_used"] is None


def test_synthetic_bars_refused_in_runtime():
    closes = _flat_history(24) + [100.0, 101.0]
    result = compute_forward_responses(
        _bars(closes, 1, source="SYNTHETIC_FIXTURE"), EVENT_TS
    )
    assert all(r["maturation"] == EXCLUDED for r in result["horizons"])
    # And accepted when runtime_mode=False (test fixtures).
    result2 = compute_forward_responses(
        _bars(closes, 1, source="SYNTHETIC_FIXTURE"), EVENT_TS, runtime_mode=False
    )
    assert any(r["maturation"] == MATURED for r in result2["horizons"])


def test_stale_entry_gap_is_data_missing():
    # Event in March; first bar in June -> stale entry.
    bars = [
        {"date": f"2026-06-{d:02d}", "close": 100.0, "source": "MANUAL_CSV_IMPORT"}
        for d in range(1, 20)
    ]
    result = compute_forward_responses(bars, EVENT_TS)
    assert all(r["maturation"] == DATA_MISSING for r in result["horizons"])


def test_unparseable_event_timestamp_is_invalid():
    closes = _flat_history(30)
    result = compute_forward_responses(_bars(closes, 1), "not-a-timestamp")
    assert all(r["maturation"] == INVALID for r in result["horizons"])


def test_no_bars_is_data_missing():
    result = compute_forward_responses([], EVENT_TS)
    assert all(r["maturation"] == DATA_MISSING for r in result["horizons"])
    result_none = compute_forward_responses(None, EVENT_TS)
    assert all(r["maturation"] == DATA_MISSING for r in result_none["horizons"])


def test_insufficient_pre_history_excluded_not_zero():
    closes = [100.0, 101.0, 100.5, 102.0, 103.0, 104.0, 105.0, 106.0]
    result = compute_forward_responses(_bars(closes, 20), "2026-03-24T10:00:00+00:00")
    rows = {r["horizon"]: r for r in result["horizons"]}
    matured_or_excluded = [r for r in result["horizons"] if r["maturation"] == EXCLUDED]
    assert matured_or_excluded, "short pre-history must EXCLUDE, not fabricate z"
    for r in matured_or_excluded:
        assert r["z"] is None
        assert r["y_absolute"] is None
    assert rows[1]["exclusion_reason"] in (
        "insufficient_pre_event_history", "no_pre_event_history",
    )


def test_duplicate_bar_dates_deduped_last_wins():
    bars = _bars(_flat_history(24) + [100.0, 101.0], 1)
    bars.append({"date": bars[-1]["date"], "close": 999.0, "source": "MANUAL_CSV_IMPORT"})
    clean, _ = prepare_bars(bars, runtime_mode=True)
    dates = [b["date"] for b in clean]
    assert len(dates) == len(set(dates))
    assert clean[-1]["close"] == 999.0


def test_adjusted_close_preferred_and_recorded():
    bars = _bars(_flat_history(24) + [100.0, 101.0], 1)
    for b in bars:
        b["adjusted_close"] = b["close"] * 0.5
    result = compute_forward_responses(bars, EVENT_TS)
    assert result["price_field"] == "adjusted_close"
    assert result["reference_price"] == 50.0


def test_zero_and_negative_prices_dropped():
    bars = _bars(_flat_history(24) + [100.0, 101.0], 1)
    bars[5]["close"] = 0.0
    bars[6]["close"] = -5.0
    clean, _ = prepare_bars(bars, runtime_mode=True)
    assert all((b.get("close") or 0) > 0 for b in clean)


def test_config_defaults_and_invalid_fallback(tmp_path):
    cfg = load_outcome_config(tmp_path / "missing.json")
    assert cfg["config_status"] == "defaults"
    assert cfg["primary_definition"] in cfg["outcome_definitions"]

    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    cfg2 = load_outcome_config(bad)
    assert cfg2["config_status"] == "invalid_file_fallback_defaults"

    hostile = tmp_path / "hostile.json"
    hostile.write_text(json.dumps({
        "horizons_trading_days": [0, -3, 9999],
        "sigma_min": -1.0,
        "outcome_definitions": {"weird": {"family": "NOT_A_FAMILY", "z_threshold": 99}},
        "primary_definition": "weird",
    }), encoding="utf-8")
    cfg3 = load_outcome_config(hostile)
    assert cfg3["horizons_trading_days"] == DEFAULT_OUTCOME_CONFIG["horizons_trading_days"]
    assert cfg3["sigma_min"] == DEFAULT_OUTCOME_CONFIG["sigma_min"]
    assert cfg3["primary_definition"] == DEFAULT_OUTCOME_CONFIG["primary_definition"]
    assert cfg3["config_problems"]


def test_repo_outcome_config_is_valid():
    cfg = load_outcome_config()
    assert cfg["config_status"] in ("file_merged", "defaults")
    assert cfg["config_problems"] == []


def test_timezone_z_suffix_equivalent():
    closes = _flat_history(24) + [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    a = compute_forward_responses(_bars(closes, 1), "2026-03-25T10:00:00Z")
    b = compute_forward_responses(_bars(closes, 1), "2026-03-25T10:00:00+00:00")
    assert a["entry_bar_date"] == b["entry_bar_date"]
    assert a["horizons"] == b["horizons"]
