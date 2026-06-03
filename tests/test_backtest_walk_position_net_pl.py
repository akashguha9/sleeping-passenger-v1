"""Integration test: ``walk_position`` must charge per-fill costs and report
gross vs net P/L side-by-side.

This pins audit findings C2 (real strategy simulation) and C3 (per-fill cost
model). Before the T3 fix, walk_position reported a single ``strategy_pl_pct``
gross figure; this test pins the new gross+net split and verifies the leg
ledger is the right shape (BUY + N SELLs).
"""
from __future__ import annotations

from scripts.backtest_entry_quality import walk_position


_ASSUMPTIONS = {
    "tp1": 0.05, "tp1_book": 0.50,
    "tp2": 0.08, "tp2_book": 0.30,
    "runner": 0.20,
    "stop": -0.05,
    "alloc_eur": 50.0,
}


def _candle(d: str, o: float, h: float, l: float, c: float, v: float = 1e6) -> dict:
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v}


# ---------------------------------------------------------------------------
# Winner that hits TP1 then TP2 then mark-out at as-of
# ---------------------------------------------------------------------------


def test_winner_charges_four_legs_and_net_lt_gross_us():
    buy = 100.0
    candles = [
        _candle("2026-05-04", 100, 102, 99,  101),  # nothing
        _candle("2026-05-05", 101, 106, 100, 105),  # TP1 (+5%)
        _candle("2026-05-06", 105, 109, 104, 108),  # TP2 (+8%)
        _candle("2026-05-07", 108, 110, 107, 109),  # runner marked here
    ]
    out = walk_position(candles, buy, _ASSUMPTIONS, market="US")
    assert out["tp1_hit"] is True
    assert out["tp2_hit"] is True
    assert out["stopped"] is False
    assert out["strategy_pl_eur_real_gross"] > out["strategy_pl_eur_real_net"], (
        "Net P/L must be strictly less than gross once costs are applied."
    )
    assert out["execution_cost_eur"] > 0.0
    # Leg ledger: BUY + 3 SELLs (TP1 50% + TP2 30% + runner 20%).
    legs = out["execution_cost_detail"]["fills"]
    assert len(legs) == 4
    sides = [f["side"] for f in legs]
    assert sides == ["BUY", "SELL", "SELL", "SELL"]
    fractions = [f["notional_eur"] / 50.0 for f in legs]
    assert abs(fractions[0] - 1.0) < 1e-6
    assert abs(fractions[1] - 0.50) < 1e-6
    assert abs(fractions[2] - 0.30) < 1e-6
    assert abs(fractions[3] - 0.20) < 1e-6


# ---------------------------------------------------------------------------
# Stopped trade — only BUY + one SELL leg
# ---------------------------------------------------------------------------


def test_stopped_trade_books_two_legs():
    buy = 100.0
    candles = [
        _candle("2026-05-04", 100, 101, 99, 100),   # nothing
        _candle("2026-05-05", 100, 100, 94, 95),    # low 94 → -6% triggers stop
    ]
    out = walk_position(candles, buy, _ASSUMPTIONS, market="US")
    assert out["stopped"] is True
    assert out["tp1_hit"] is False
    legs = out["execution_cost_detail"]["fills"]
    assert len(legs) == 2
    assert [f["side"] for f in legs] == ["BUY", "SELL"]
    # Sold fraction at stop is 100% (nothing taken at TPs)
    assert abs(legs[1]["notional_eur"] / 50.0 - 1.0) < 1e-6
    # Net P/L is gross (-5% × 50 = -2.5) MINUS cost (positive).
    assert out["strategy_pl_eur_real_gross"] < 0
    assert out["strategy_pl_eur_real_net"] < out["strategy_pl_eur_real_gross"]


# ---------------------------------------------------------------------------
# Stop-after-TP1: BUY + TP1 SELL (50%) + stop SELL (50%) = 3 legs
# ---------------------------------------------------------------------------


def test_tp1_then_stop_books_three_legs():
    buy = 100.0
    candles = [
        _candle("2026-05-04", 100, 106, 100, 105),  # TP1 only
        _candle("2026-05-05", 105, 105, 94, 95),    # stop hits remainder
    ]
    out = walk_position(candles, buy, _ASSUMPTIONS, market="US")
    assert out["tp1_hit"] is True
    assert out["stopped"] is True
    legs = out["execution_cost_detail"]["fills"]
    assert len(legs) == 3
    # BUY 100%, SELL 50% (TP1), SELL 50% (stop)
    fractions = [f["notional_eur"] / 50.0 for f in legs]
    assert abs(fractions[0] - 1.0) < 1e-6
    assert abs(fractions[1] - 0.50) < 1e-6
    assert abs(fractions[2] - 0.50) < 1e-6


# ---------------------------------------------------------------------------
# Market-aware: India charges STT on sells that US doesn't; US charges
# bigger broker commission floors than Indian discount brokers. The audit
# point is per-market specificity, not "EM is always more expensive".
# ---------------------------------------------------------------------------


def test_india_charges_stt_on_sells_us_does_not():
    buy = 100.0
    candles = [
        _candle("2026-05-04", 100, 102, 99,  101),
        _candle("2026-05-05", 101, 106, 100, 105),  # TP1
        _candle("2026-05-06", 105, 109, 104, 108),  # TP2
        _candle("2026-05-07", 108, 110, 107, 109),  # runner mark
    ]
    us_out = walk_position(candles, buy, _ASSUMPTIONS, market="US")
    in_out = walk_position(candles, buy, _ASSUMPTIONS, market="IN")
    in_sell_fees = sum(
        f["exchange_fee_eur"] for f in in_out["execution_cost_detail"]["fills"]
        if f["side"] == "SELL"
    )
    us_sell_fees = sum(
        f["exchange_fee_eur"] for f in us_out["execution_cost_detail"]["fills"]
        if f["side"] == "SELL"
    )
    assert in_sell_fees > 0.0, "India must charge STT on SELLs"
    assert us_sell_fees == 0.0, "US must not charge a SELL exchange fee in this table"
    # FX round-trip: India (50 EUR <-> INR) > US (50 EUR <-> USD)
    assert in_out["execution_cost_detail"]["fx_rt_eur"] > us_out["execution_cost_detail"]["fx_rt_eur"]


# ---------------------------------------------------------------------------
# Default behaviour: no market → no cost (pure gross, back-compat)
# ---------------------------------------------------------------------------


def test_no_market_yields_zero_cost():
    """When called without a market (e.g. a unit test of the replay logic
    alone), cost is zero and gross/net agree."""
    buy = 100.0
    candles = [_candle("2026-05-04", 100, 106, 100, 105)]
    out = walk_position(candles, buy, _ASSUMPTIONS)
    assert out["execution_cost_eur"] == 0.0
    assert out["strategy_pl_eur_real_gross"] == out["strategy_pl_eur_real_net"]
