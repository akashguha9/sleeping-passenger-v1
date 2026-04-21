from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class MarketDataQuote:
    symbol: str
    price: float
    currency: str
    source: str
    as_of: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MarketDataFetchResult:
    requested_provider: str
    resolved_provider: str
    symbol: str
    ok: bool
    quote: MarketDataQuote | None
    error: str | None
    retriable: bool

    def to_dict(self) -> dict:
        return {
            "requested_provider": self.requested_provider,
            "resolved_provider": self.resolved_provider,
            "symbol": self.symbol,
            "ok": self.ok,
            "quote": self.quote.to_dict() if self.quote else None,
            "error": self.error,
            "retriable": self.retriable,
        }


class MarketDataAdapter(Protocol):
    provider: str

    def fetch_latest_quote(self, symbol: str) -> MarketDataFetchResult:
        ...


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UnsupportedMarketDataAdapter:
    def __init__(self, requested_provider: str) -> None:
        self.requested_provider = requested_provider
        self.provider = f"{requested_provider}_unsupported"

    def fetch_latest_quote(self, symbol: str) -> MarketDataFetchResult:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol must be a non-empty string")

        return MarketDataFetchResult(
            requested_provider=self.requested_provider,
            resolved_provider=self.provider,
            symbol=normalized_symbol,
            ok=False,
            quote=None,
            error=f"Unsupported provider: {self.requested_provider}",
            retriable=False,
        )


class YahooFinanceMarketDataAdapter:
    """
    Thin live adapter with deterministic failure states.

    V1 goals:
    - preserve existing public interface
    - avoid placeholder contamination
    - support a basic cache path
    - return structured failures instead of raising for upstream/import issues
    """

    def __init__(self, requested_provider: str = "yahoo") -> None:
        self.requested_provider = requested_provider
        self.provider = "yahoo_finance"
        self._cache: dict[str, MarketDataFetchResult] = {}

    def fetch_latest_quote(self, symbol: str) -> MarketDataFetchResult:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol must be a non-empty string")

        cached = self._cache.get(normalized_symbol)
        if cached is not None:
            return cached

        try:
            quote = self._download_quote(normalized_symbol)
        except ImportError as exc:
            result = MarketDataFetchResult(
                requested_provider=self.requested_provider,
                resolved_provider=self.provider,
                symbol=normalized_symbol,
                ok=False,
                quote=None,
                error=f"yfinance import unavailable: {exc}",
                retriable=False,
            )
            self._cache[normalized_symbol] = result
            return result
        except Exception as exc:
            result = MarketDataFetchResult(
                requested_provider=self.requested_provider,
                resolved_provider=self.provider,
                symbol=normalized_symbol,
                ok=False,
                quote=None,
                error=f"quote fetch failed: {type(exc).__name__}: {exc}",
                retriable=True,
            )
            self._cache[normalized_symbol] = result
            return result

        result = MarketDataFetchResult(
            requested_provider=self.requested_provider,
            resolved_provider=self.provider,
            symbol=normalized_symbol,
            ok=True,
            quote=quote,
            error=None,
            retriable=False,
        )
        self._cache[normalized_symbol] = result
        return result

    def _download_quote(self, symbol: str) -> MarketDataQuote:
        import yfinance as yf  # type: ignore

        ticker = yf.Ticker(symbol)
        fast_info = getattr(ticker, "fast_info", None)

        price = None
        currency = "USD"

        if fast_info:
            price = (
                fast_info.get("lastPrice")
                or fast_info.get("regularMarketPrice")
                or fast_info.get("previousClose")
            )
            currency = fast_info.get("currency") or currency

        if price is None:
            info = getattr(ticker, "info", {}) or {}
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            currency = info.get("currency") or currency

        if price is None:
            raise RuntimeError(f"No quote available for symbol {symbol}")

        return MarketDataQuote(
            symbol=symbol,
            price=float(price),
            currency=str(currency),
            source=self.provider,
            as_of=_utc_now_iso(),
        )


def create_market_data_adapter(provider: str | None = None) -> MarketDataAdapter:
    requested_provider = (provider or "yahoo").strip().lower()

    if requested_provider in {"yahoo", "yfinance"}:
        return YahooFinanceMarketDataAdapter(requested_provider=requested_provider)

    return UnsupportedMarketDataAdapter(requested_provider=requested_provider)


def describe_market_data_adapter(provider: str | None = None) -> dict:
    adapter = create_market_data_adapter(provider)
    sample = adapter.fetch_latest_quote("TLT").to_dict()
    return {
        "requested_provider": sample["requested_provider"],
        "resolved_provider": sample["resolved_provider"],
        "live_quotes_available": sample["ok"],
        "contract_sample": sample,
        "note": "Live adapter returns structured failures when imports or upstream quotes are unavailable.",
    }