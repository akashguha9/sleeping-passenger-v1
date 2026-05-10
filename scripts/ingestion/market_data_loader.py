"""
Generic market-data read-only loader — Phase C.5 Global Signal Fabric.

Wraps yfinance (if available) to pull OHLCV data for a configurable list of
symbols. No API key required for Yahoo; skips cleanly if yfinance is unavailable.

Optional paid-provider hooks (Alpha Vantage, Twelve Data, Polygon) are disabled
skeletons — they skip cleanly when their env var keys are absent.

All outputs carry advisory_status="ADVISORY_ONLY". No execution. No broker APIs.
No order placement. No private keys. No wallet operations.
"""
from __future__ import annotations

import os
from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_DEFAULT_TICKERS = ["SPY", "QQQ", "GLD", "TLT"]
_DEFAULT_PERIOD = "5d"
_DEFAULT_INTERVAL = "1d"
_PROVIDER_YAHOO = "yahoo"

# Disabled paid-provider stubs — skip cleanly without their API keys.
_OPTIONAL_PROVIDERS: dict[str, str] = {
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
    "twelve_data": "TWELVE_DATA_API_KEY",
    "polygon": "POLYGON_API_KEY",
}


def _compute_market_confirmation_score(
    price_change_pct: float | None,
    volume_change_ratio: float | None,
) -> float:
    """
    Deterministic advisory-only confirmation score bounded to [0.0, 1.0].

    Price component (0–0.6): |price_change_pct| capped at ±3% → 0.6 max.
    Volume component (0–0.4): volume_change_ratio capped at 2× average → 0.4 max.
    Only contributes when volume is above average (ratio > 1.0).
    Returns 0.0 when price_change_pct is None (insufficient data).
    """
    if price_change_pct is None:
        return 0.0
    price_component = min(abs(price_change_pct) / 3.0, 1.0) * 0.6
    vol_component = 0.0
    if volume_change_ratio is not None and volume_change_ratio > 1.0:
        vol_component = min(volume_change_ratio - 1.0, 1.0) * 0.4
    return round(min(price_component + vol_component, 1.0), 4)


class MarketDataLoader(BaseSourceLoader):
    source_name = "market_data"
    requires_key = False

    def __init__(
        self,
        tickers: list[str] | None = None,
        period: str = _DEFAULT_PERIOD,
        interval: str = _DEFAULT_INTERVAL,
        provider: str = _PROVIDER_YAHOO,
    ) -> None:
        self._tickers = tickers or list(_DEFAULT_TICKERS)
        self._period = period
        self._interval = interval
        self._provider = provider

    def fetch(self) -> LoaderResult:
        """Fetch OHLCV market data (read-only, advisory-only, no execution)."""
        if self._provider in _OPTIONAL_PROVIDERS:
            return self._fetch_optional_provider()
        return self._fetch_yahoo()

    def _fetch_yahoo(self) -> LoaderResult:
        """Fetch via yfinance (no API key required)."""
        try:
            import yfinance as yf  # lazy import — skip cleanly if unavailable
        except ImportError:
            raise SkipLoader("yfinance not installed — market_data loader skipped")

        records: list[dict[str, Any]] = []
        for ticker in self._tickers:
            try:
                hist = yf.Ticker(ticker).history(period=self._period, interval=self._interval)
                if hist.empty:
                    continue

                latest = hist.iloc[-1]
                previous = hist.iloc[-2] if len(hist) >= 2 else None

                close = float(latest.get("Close", 0.0) or 0.0)
                open_ = float(latest.get("Open", 0.0) or 0.0)
                high = float(latest.get("High", 0.0) or 0.0)
                low = float(latest.get("Low", 0.0) or 0.0)
                volume = float(latest.get("Volume", 0.0) or 0.0)

                prev_close: float | None = None
                if previous is not None:
                    prev_close = float(previous.get("Close", 0.0) or 0.0)

                price_change: float | None = None
                price_change_pct: float | None = None
                if prev_close is not None and prev_close != 0.0:
                    price_change = round(close - prev_close, 6)
                    price_change_pct = round((price_change / prev_close) * 100.0, 6)

                avg_volume: float | None = None
                volume_change_ratio: float | None = None
                if len(hist) >= 2:
                    prior_vols = [float(v or 0.0) for v in hist["Volume"].tolist()[:-1]]
                    if prior_vols:
                        avg_volume = round(sum(prior_vols) / len(prior_vols), 2)
                    if avg_volume and avg_volume > 0 and volume > 0:
                        volume_change_ratio = round(volume / avg_volume, 4)

                score = _compute_market_confirmation_score(price_change_pct, volume_change_ratio)

                try:
                    ts = str(hist.index[-1])
                except Exception:
                    ts = ""

                rec: dict[str, Any] = {
                    "symbol": ticker.upper(),
                    "provider": "yahoo",
                    "period": self._period,
                    "interval": self._interval,
                    "latest_price": close,
                    "previous_close": prev_close,
                    "price_change": price_change,
                    "price_change_pct": price_change_pct,
                    "volume": volume,
                    "average_volume": avg_volume,
                    "volume_change_ratio": volume_change_ratio,
                    "high": high,
                    "low": low,
                    "open": open_,
                    "close": close,
                    "timestamp": ts,
                    "market_confirmation_score": score,
                    "source": "market_data_yahoo",
                    "ticker": ticker.upper(),
                }
                self._stamp_record(rec)
                records.append(rec)
            except Exception:
                continue

        return LoaderResult(source_name=self.source_name, records=records)

    def _fetch_optional_provider(self) -> LoaderResult:
        """
        Disabled skeleton for paid providers (Alpha Vantage / Twelve Data / Polygon).
        Skips cleanly when the relevant API key is absent. Phase C.5 only activates Yahoo.
        """
        env_key = _OPTIONAL_PROVIDERS.get(self._provider)
        if not env_key or not os.environ.get(env_key, "").strip():
            raise SkipLoader(
                f"market_data provider '{self._provider}' requires {env_key!r} "
                "env var which is not set — skipped"
            )
        raise SkipLoader(
            f"market_data provider '{self._provider}' is a disabled skeleton in Phase C.5 — skipped"
        )


__all__ = [
    "MarketDataLoader",
    "_compute_market_confirmation_score",
    "_DEFAULT_TICKERS",
    "_DEFAULT_PERIOD",
    "_DEFAULT_INTERVAL",
    "_OPTIONAL_PROVIDERS",
]
