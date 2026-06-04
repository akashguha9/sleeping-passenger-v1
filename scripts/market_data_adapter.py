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
        # Honest source-chain disclosure so no consumer can infer live
        # redundancy that does not exist. See market_data_source_chain().
        "source_chain": market_data_source_chain(),
        "note": "Intentional placeholder contract. The active quote adapter is scripts/yahoo_market_data_adapter.py; core Moltbook and SCM runtime remain independent from market-data ingestion.",
    }


# --------------------------------------------------------------------------
# Truthful single-source live facade.
#
# The seeded default (create_market_data_adapter / describe_market_data_adapter)
# stays a placeholder — that is correct for seeded mode. The facade below gives
# a REAL, callable, never-raising quote path that delegates to the active
# scripts/yahoo_market_data_adapter.py, plus an honest source-chain descriptor.
#
# No redundancy is claimed: there is exactly ONE live source (Yahoo via
# yfinance), no urllib fallback, and no stale-cache tertiary. Do not add any of
# those to the descriptor unless they are actually implemented and tested.
# --------------------------------------------------------------------------

PRIMARY_LIVE_SOURCE = "yahoo_finance"


def market_data_source_chain() -> dict:
    """Return the truthful market-data source chain.

    Single live source, no fallback, no stale cache. This is the honest state
    of the implementation today — it deliberately does NOT advertise live
    redundancy that does not exist.
    """
    return {
        "primary_source": PRIMARY_LIVE_SOURCE,
        "live_source_count": 1,
        "fallback_sources": [],
        "stale_cache_enabled": False,
        "failure_mode": "structured_non_raising",  # ok=False, quote=None on failure
        # Honest disclosure: optional paid providers exist ONLY as disabled,
        # credential-gated skeletons (scripts/ingestion/market_data_loader.py).
        # They are NOT active fallbacks and do NOT count toward live_source_count.
        "optional_disabled_sources": ["alpha_vantage", "twelve_data", "polygon"],
        "optional_sources_active": False,
        "optional_sources_note": (
            "Disabled skeletons; require API keys/credentials. Not wired, not "
            "tested as live, and not counted as redundancy."
        ),
    }


class YahooMarketDataAdapter:
    """Real quote adapter facade delegating to yahoo_market_data_adapter.

    Never raises: any fetch failure (including an empty symbol) is mapped to a
    structured ``MarketDataFetchResult`` with ``ok=False`` and ``quote=None``.
    """

    provider = PRIMARY_LIVE_SOURCE

    def __init__(self, fetcher=None) -> None:
        # Optional injected fetcher(symbol)->dict for tests; defaults to the
        # adapter's yfinance fetch when None.
        self._fetcher = fetcher

    def fetch_latest_quote(self, symbol: str) -> MarketDataFetchResult:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            return MarketDataFetchResult(
                requested_provider=self.provider,
                resolved_provider=self.provider,
                symbol="",
                ok=False,
                quote=None,
                error="symbol must be a non-empty string",
                retriable=False,
            )
        try:
            # Lazy import: avoids any import-time coupling with runtime_common.
            try:
                from scripts.yahoo_market_data_adapter import fetch_yahoo_mark_row
            except ModuleNotFoundError:
                from yahoo_market_data_adapter import fetch_yahoo_mark_row

            row = fetch_yahoo_mark_row(
                ticker=normalized_symbol,
                runtime_state={},
                fetcher=self._fetcher,
            )
        except Exception as exc:  # never raise out of the facade
            return MarketDataFetchResult(
                requested_provider=self.provider,
                resolved_provider=self.provider,
                symbol=normalized_symbol,
                ok=False,
                quote=None,
                error=f"market data fetch failed: {exc}",
                retriable=True,
            )

        ok = bool(row.get("ok"))
        last_price = row.get("last_price")
        quote = None
        if ok and last_price is not None:
            quote = MarketDataQuote(
                symbol=normalized_symbol,
                price=float(last_price),
                currency=str(row.get("currency") or "USD"),
                source=str(row.get("source_name") or PRIMARY_LIVE_SOURCE),
                as_of=row.get("observed_at"),
            )
        return MarketDataFetchResult(
            requested_provider=self.provider,
            resolved_provider=str(row.get("source_name") or PRIMARY_LIVE_SOURCE),
            symbol=normalized_symbol,
            ok=ok and last_price is not None,
            quote=quote,
            error=row.get("retrieval_error"),
            retriable=True,
        )


def create_live_market_data_adapter(fetcher=None) -> YahooMarketDataAdapter:
    """Construct the REAL single-source live adapter facade (Yahoo/yfinance).

    Distinct from ``create_market_data_adapter`` (which stays the seeded
    placeholder). Callable behavior is real; failures are structured.
    """
    return YahooMarketDataAdapter(fetcher=fetcher)
