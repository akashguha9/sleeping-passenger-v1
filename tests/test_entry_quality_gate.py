"""Entry-quality gate — unit tests on deterministic synthetic OHLCV.

These exercise the pure-module path so the gate can be verified without any
network access. The downstream backtest harness (which calls yfinance for real
prices) is tested separately.
"""
from __future__ import annotations

from scripts.entry_quality_gate import compute_entry_quality, load_entry_quality_config


def _candle(c: float, h: float | None = None, l: float | None = None, v: float = 1_000_000) -> dict:
    return {
        "close": c,
        "high": h if h is not None else c * 1.005,
        "low": l if l is not None else c * 0.995,
        "volume": v,
    }


def _uptrend_series(
    n: int = 260, start: float = 100.0, daily_drift: float = 0.0015,
    end_pullback_pct: float = 0.02, pullback_bars: int = 3,
) -> list[dict]:
    """Synthetic uptrend with a small pullback at the very end so the last close
    sits comfortably below the recent high (passes extension_vs_52w_high) but
    still above SMA50 (passes trend_50)."""
    candles: list[dict] = []
    p = start
    for _ in range(n - pullback_bars):
        p *= 1 + daily_drift
        candles.append(_candle(p, p * 1.005, p * 0.995, 50_000_000))
    peak = p * (1 + 0.01)  # synthetic high a bit above last close
    for k in range(pullback_bars):
        p *= 1 - (end_pullback_pct / pullback_bars)
        candles.append(_candle(p, peak if k == 0 else p * 1.005, p * 0.99, 50_000_000))
    return candles


def _downtrend_series(n: int = 260, start: float = 100.0, daily_drift: float = -0.0020) -> list[dict]:
    candles: list[dict] = []
    p = start
    for _ in range(n):
        p *= 1 + daily_drift
        candles.append(_candle(p, p * 1.01, p * 0.99, 50_000_000))
    return candles


def test_clean_uptrend_passes() -> None:
    candles = _uptrend_series()
    out = compute_entry_quality(candles=candles, universe_mom_20d=[0.0] * 10)
    assert out["entry_quality_pass"] is True
    assert out["entry_quality_score"] > 0.5
    # all hard components must be pass
    for k, v in out["components"].items():
        assert v["pass"] is True, f"{k} unexpectedly failed: {v}"


def test_falling_knife_fails_with_trend_and_mom_reasons() -> None:
    candles = _downtrend_series()
    out = compute_entry_quality(candles=candles, universe_mom_20d=[-0.01] * 10)
    assert out["entry_quality_pass"] is False
    reasons = " ".join(out["reasons"]).lower()
    assert "trend_50" in reasons or "trend_200" in reasons
    assert "mom_20d" in reasons or "dist_from_sma50" in reasons


def test_buy_right_at_52w_high_is_blocked_by_extension_rule() -> None:
    # Uptrend; force the last close to equal the max high seen so ext == 0%.
    candles = _uptrend_series(n=260)
    max_h = max(c["high"] for c in candles)
    candles[-1]["close"] = max_h
    candles[-1]["high"] = max_h
    out = compute_entry_quality(candles=candles, universe_mom_20d=[0.0] * 10)
    assert out["components"]["extension_vs_52w_high"]["pass"] is False
    assert out["entry_quality_pass"] is False


def test_extension_rule_is_configurable() -> None:
    candles = _uptrend_series(n=260)
    max_h = max(c["high"] for c in candles)
    candles[-1]["close"] = max_h
    candles[-1]["high"] = max_h
    cfg = dict(load_entry_quality_config())
    cfg["extension_vs_52w_high_max"] = 0.0  # allow buying right at the high
    out = compute_entry_quality(
        candles=candles, universe_mom_20d=[0.0] * 10, config=cfg
    )
    assert out["components"]["extension_vs_52w_high"]["pass"] is True


def test_insufficient_history_blocks() -> None:
    candles = _uptrend_series(n=20)
    out = compute_entry_quality(candles=candles)
    assert out["entry_quality_pass"] is False
    assert any("insufficient_history" in r for r in out["reasons"])


def test_disabled_gate_is_bypassed() -> None:
    cfg = load_entry_quality_config()
    cfg = dict(cfg); cfg["enabled"] = False
    candles = _downtrend_series()
    out = compute_entry_quality(candles=candles, config=cfg)
    assert out["entry_quality_pass"] is True
    assert out["entry_quality_score"] == 1.0


def test_rs_check_skipped_without_index_data() -> None:
    candles = _uptrend_series()
    out = compute_entry_quality(candles=candles, universe_mom_20d=[0.0] * 10)
    rs = out["components"]["rs_vs_index"]
    assert rs["pass"] is True
    assert "skipped" in (rs.get("note") or "")


def test_strong_outperformer_passes_rs() -> None:
    stock = _uptrend_series(n=260, daily_drift=0.0030)
    index = _uptrend_series(n=260, daily_drift=0.0005)
    out = compute_entry_quality(
        candles=stock, index_candles=index, universe_mom_20d=[0.01] * 10
    )
    assert out["components"]["rs_vs_index"]["pass"] is True
    assert out["entry_quality_pass"] is True


def test_underperformer_fails_rs() -> None:
    stock = _uptrend_series(n=260, daily_drift=0.0005)
    index = _uptrend_series(n=260, daily_drift=0.0030)
    out = compute_entry_quality(
        candles=stock, index_candles=index, universe_mom_20d=[0.01] * 10
    )
    assert out["components"]["rs_vs_index"]["pass"] is False
    assert out["entry_quality_pass"] is False


def test_low_liquidity_fails_adv() -> None:
    candles = _uptrend_series()
    # Knock volume way down on the most recent 30 bars.
    for c in candles[-30:]:
        c["volume"] = 100
    out = compute_entry_quality(candles=candles, universe_mom_20d=[0.0] * 10)
    assert out["components"]["adv_local"]["pass"] is False
    assert out["entry_quality_pass"] is False
