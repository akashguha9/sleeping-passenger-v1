"""
Generic market-data read-only loader — Phase 2 Global Signal Fabric.

Wraps yfinance (if available) to pull OHLCV data for a list of tickers.
No API key required; skips cleanly if yfinance is unavailable.
All outputs are ADVISORY_ONLY.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_DEFAULT_TICKERS = ["SPY", "QQQ", "GLD", "TLT"]
_DEFAULT_PERIOD = "5d"
_DEFAULT_INTERVAL = "1d"


class MarketDataLoader(BaseSourceLoader):
    source_name = "market_data"
    requires_key = False

    def __init__(
        self,
        tickers: list[str] | None = None,
        period: str = _DEFAULT_PERIOD,
        interval: str = _DEFAULT_INTERVAL,
    ) -> None:
        self._tickers = tickers or _DEFAULT_TICKERS
        self._period = period
        self._interval = interval

    def fetch(self) -> LoaderResult:
        """Fetch OHLCV market data via yfinance (read-only)."""
        try:
            import yfinance as yf  # lazy import
        except ImportError:
            raise SkipLoader("yfinance not installed — market_data loader skipped")

        records: list[dict[str, Any]] = []
        for ticker in self._tickers:
            try:
                hist = yf.Ticker(ticker).history(
                    period=self._period, interval=self._interval
                )
                if hist.empty:
                    continue
                latest = hist.iloc[-1]
                rec: dict[str, Any] = {
                    "ticker": ticker.upper(),
                    "close": float(latest.get("Close", 0.0)),
                    "volume": float(latest.get("Volume", 0.0)),
                    "period": self._period,
                    "interval": self._interval,
                    "source": "market_data_yfinance",
                }
                self._stamp_record(rec)
                records.append(rec)
            except Exception:
                continue

        return LoaderResult(source_name=self.source_name, records=records)
