"""Intentional placeholder quote-contract — NOT the active market-data adapter.

The live, working, never-raising quote/volume adapter is
``scripts/yahoo_market_data_adapter.py``. Read that file for real fetches.

This stub exists only so ``runtime_common`` / ``repo_operating_mode`` can stamp
``quote_provider_state=placeholder`` in runtime and operating-mode metadata
while the seeded pipeline runs independently of any market-data ingestion. It
returns a structured, never-live contract (``ok=False``, ``quote=None``) and
deliberately advertises itself as a placeholder; do not mistake it for the
canonical adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


class PlaceholderMarketDataAdapter:
    def __init__(self, requested_provider: str) -> None:
        self.requested_provider = requested_provider
        self.provider = f"{requested_provider}_placeholder"

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
            error=f"{self.requested_provider} adapter is an intentional placeholder; the active adapter is scripts/yahoo_market_data_adapter.py.",
            retriable=True,
        )


def create_market_data_adapter(provider: str | None = None) -> MarketDataAdapter:
    requested_provider = (provider or "yahoo").strip().lower()
    return PlaceholderMarketDataAdapter(requested_provider=requested_provider)


def describe_market_data_adapter(provider: str | None = None) -> dict:
    adapter = create_market_data_adapter(provider)
    sample = adapter.fetch_latest_quote("TLT").to_dict()
    return {
        "requested_provider": sample["requested_provider"],
        "resolved_provider": sample["resolved_provider"],
        "live_quotes_available": False,
        "contract_state": "placeholder",
        "truth_origin_tags": ["placeholder"],
        "contract_sample": sample,
        "note": "Intentional placeholder contract. The active quote adapter is scripts/yahoo_market_data_adapter.py; core Moltbook and SCM runtime remain independent from market-data ingestion.",
    }
