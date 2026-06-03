"""walk_position: deterministic replay of TP1/TP2/runner/stop against true OHLCV.

These exercise the pure-logic path; the xlsx parsing and yfinance fetch are
verified in the operator-run integration (out of scope for unit tests).
"""
from __future__ import annotations

from scripts.backtest_entry_quality import walk_position, to_yf_symbol


_ASSUMPTIONS = {"tp1": 0.05, "tp1_book": 0.50,
                "tp2": 0.08, "tp2_book": 0.30,
                "runner": 0.20,
                "stop": -0.05,
                "alloc_eur": 50.0}


def _c(hi: float, lo: float, close: float) -> dict:
    return {"high": hi, "low": lo, "close": close, "open": close, "volume": 0}


def test_tp1_then_tp2_then_runner_marked() -> None:
    # Buy at 100. Day1: high tags +5% (TP1). Day2: high tags +8% (TP2).
    # Day3..5: runner walks to +12% close.
    candles = [
        _c(hi=105.5, lo=99.5, close=104),   # TP1
        _c(hi=109.0, lo=103.0, close=108),  # TP2
        _c(hi=110.0, lo=107.0, close=110),
        _c(hi=112.0, lo=109.0, close=112),
    ]
    out = walk_position(candles, buy_price=100.0, assumptions=_ASSUMPTIONS)
    assert out["tp1_hit"] is True
    assert out["tp2_hit"] is True
    assert out["stopped"] is False
    assert out["status_real"] == "Win"
    # Realized = 0.5*0.05 + 0.3*0.08 = 0.025 + 0.024 = 0.049
    assert abs(out["realized_pct"] - 0.049) < 1e-6
    # Runner = 0.20, final ret = 0.12 → 0.024
    assert abs(out["unrealized_pct"] - 0.024) < 1e-6


def test_stop_hits_full_remaining_fraction() -> None:
    # Day1 tags TP1 then later hits -5%; remaining 50% stopped at -5%.
    candles = [
        _c(hi=106.0, lo=99.0, close=104),     # TP1 fires
        _c(hi=104.0, lo=94.0, close=95),      # stop (low at -6%)
    ]
    out = walk_position(candles, buy_price=100.0, assumptions=_ASSUMPTIONS)
    assert out["tp1_hit"] is True
    assert out["stopped"] is True
    assert out["status_real"] == "Loss"
    # Realized = 0.5*0.05 + (remaining 0.5)*-0.05 = 0
    assert abs(out["realized_pct"] - 0.0) < 1e-6
    assert out["unrealized_pct"] == 0.0


def test_intra_day_both_stop_wins() -> None:
    # Day1: high tags +5% AND low tags -5% on the same day. Conservatively, the
    # stop wins (we can't infer intraday order).
    candles = [_c(hi=106.0, lo=94.0, close=95)]
    out = walk_position(candles, buy_price=100.0, assumptions=_ASSUMPTIONS)
    assert out["stopped"] is True
    assert out["tp1_hit"] is False
    assert out["status_real"] == "Loss"


def test_no_movement_marks_runner_at_final_close() -> None:
    candles = [_c(hi=101, lo=99, close=100.5), _c(hi=101.2, lo=99.8, close=100.2)]
    out = walk_position(candles, buy_price=100.0, assumptions=_ASSUMPTIONS)
    assert out["tp1_hit"] is False
    assert out["stopped"] is False
    assert out["status_real"] == "Win"  # +0.2% close
    assert abs(out["unrealized_pct"] - 0.002) < 1e-3


def test_to_yf_symbol_handles_known_exchanges() -> None:
    assert to_yf_symbol("NASDAQ:AAPL") == ("AAPL", "US")
    assert to_yf_symbol("NSE:BHARTIARTL") == ("BHARTIARTL.NS", "IN")
    assert to_yf_symbol("ETR:SAP") == ("SAP.DE", "DE")
    assert to_yf_symbol("KRX:003550") == ("003550.KS", "KR")
    assert to_yf_symbol("EPA:AIR") == ("AIR.PA", "FR")
    assert to_yf_symbol("LON:HSBA") == ("HSBA.L", "GB")
    assert to_yf_symbol("TYO:8306") == ("8306.T", "JP")
