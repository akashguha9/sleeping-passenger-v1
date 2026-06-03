"""T5 (C5) — backfill_ohlcv_history must store both raw OHLC and Adj Close,
plus an adjustment_ratio, so a later corporate action can be detected and
operator stop/TP levels can be re-adjusted instead of leaving a frozen
snapshot that produces the ~5x price glitch from the audit.
"""
from __future__ import annotations

from scripts.backfill_ohlcv_history import _build_candle


class _Row:
    """Stub mimicking a yfinance history-row attribute access surface."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._dict = kwargs

    def get(self, key, default=None):
        return self._dict.get(key, default)


def test_candle_includes_raw_and_adjusted_close_with_ratio():
    """A row where the company has split 5:1 since the bar printed:
    Close = 500 (raw, pre-split tape), Adj Close = 100 (post-split).
    """
    row = _Row(Open=505.0, High=510.0, Low=495.0, Close=500.0,
               Volume=1_000_000)
    # Adj Close needs a space in the attribute name -- set it on the
    # backing dict and access via .get so the candle builder reads it.
    row._dict["Adj Close"] = 100.0
    c = _build_candle("FOO", "1d", "2026-01-15T16:00:00Z", row)
    assert c["close"] == 500.0, "raw close (the printed price) must survive"
    assert c["adj_close"] == 100.0, "adjusted close must be captured"
    assert abs(c["adjustment_ratio"] - (100.0 / 500.0)) < 1e-9
    assert c["price_space"] == "raw_ohlc+adj_close"


def test_candle_with_no_adjustment_has_ratio_one():
    """A clean unadjusted row (no corporate action history) yields a ratio of 1."""
    row = _Row(Open=100.0, High=101.0, Low=99.0, Close=100.0, Volume=1)
    c = _build_candle("FOO", "1d", "2026-01-15T16:00:00Z", row)
    assert c["adj_close"] == 100.0
    assert c["adjustment_ratio"] == 1.0


def test_fetch_passes_auto_adjust_false():
    """yfinance returns ``Adj Close`` only when ``auto_adjust=False``. Pin
    that the fetcher passes the right flag so the C5 detection path is
    actually populated."""
    from pathlib import Path
    src = Path("scripts/backfill_ohlcv_history.py").read_text(encoding="utf-8")
    assert "auto_adjust=False" in src, (
        "yfinance.history must be called with auto_adjust=False so the raw "
        "OHLC + 'Adj Close' come back side-by-side (T5/C5)."
    )
