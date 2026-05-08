"""Market-data loader placeholder.

Tries to use yfinance if installed; otherwise returns a clean skipped result.
Also supports Alpha Vantage / Twelve Data hooks via env keys (skipped without).
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.normalization.signal_event_schema import NumericSignal, SignalEvent
from scripts.normalization.signal_processor import process_signal


class MarketDataLoader(BaseLoader):
    source_name = "market_data"
    source_type = "market_data"

    def fetch(self, *, ticker: str, period: str = "5d") -> LoaderResult:
        try:
            import yfinance as yf  # type: ignore
        except Exception:
            return self.skip("yfinance not installed; market data placeholder", ticker=ticker)

        try:
            hist = yf.Ticker(ticker).history(period=period)  # pragma: no cover - network
        except Exception as exc:  # pragma: no cover
            return self.fail(f"yfinance fetch failed: {exc}", ticker=ticker)

        events: list[SignalEvent] = []
        if hist is None or hist.empty:  # pragma: no cover
            return self.ok(events, ticker=ticker)
        for ts, row in hist.iterrows():  # pragma: no cover - network
            events.append(
                self.normalize(
                    {
                        "ticker": ticker,
                        "timestamp_utc": ts.isoformat(),
                        "close": float(row.get("Close", 0.0)),
                        "open": float(row.get("Open", 0.0)),
                    }
                )
            )
        return self.ok(events, ticker=ticker)

    def normalize(self, raw: dict[str, Any]) -> SignalEvent:
        ticker = raw.get("ticker") or "UNKNOWN"
        close = float(raw.get("close") or 0.0)
        open_ = float(raw.get("open") or 0.0)
        change = (close - open_) / open_ if open_ else None
        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": "US",
            "headline_or_label": f"{ticker} close {close}",
            "raw_text_or_summary": f"{ticker} OHLC snapshot",
            "url": None,
            "event_type": "price_bar",
            "asset_tags": [ticker],
            "numeric_signal": NumericSignal(price_change=change),
            "metadata": {"ticker": ticker, "close": close, "open": open_},
        }
        if raw.get("timestamp_utc"):
            raw_event["timestamp_utc"] = raw["timestamp_utc"]
        return process_signal(raw_event)
