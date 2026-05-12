"""
Polymarket read-only loader — Phase 2 Global Signal Fabric.

Uses only public read-only endpoints (Gamma API and Data API).
No authenticated trading endpoints. No CLOB order submission.

Strategy for domain-relevant market retrieval:
1. Search the Gamma API with each domain keyword (politics, economy, crypto, etc.)
2. Fetch multiple pages of the default active markets listing for additional coverage
3. Deduplicate by market_id
4. Apply strict domain gate via classify_market_domain() — blocks sports/entertainment/meme
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_DATA_BASE = "https://data-api.polymarket.com"
_DEFAULT_LIMIT = 50
_DEFAULT_MAX_PAGES = 5
_TIMEOUT = 10

# Domain keyword searches — each is submitted as a separate query to maximise recall
_DOMAIN_KEYWORDS: list[str] = [
    "election", "president", "senate", "congress",
    "trump", "fed", "federal reserve", "inflation",
    "interest rate", "gdp", "recession",
    "bitcoin", "ethereum", "crypto",
    "oil", "gold", "china", "ukraine", "russia",
    "tariff", "trade", "iran", "israel",
    "economy", "market", "stock",
    "war", "ceasefire", "sanctions",
]


class PolymarketLoader(BaseSourceLoader):
    source_name = "polymarket"
    requires_key = False  # public endpoints only

    def __init__(
        self,
        limit: int = _DEFAULT_LIMIT,
        max_pages: int = _DEFAULT_MAX_PAGES,
        gamma_base: str = _GAMMA_BASE,
        data_base: str = _DATA_BASE,
        timeout: int = _TIMEOUT,
        use_keyword_search: bool = True,
    ) -> None:
        self._limit = limit
        self._max_pages = max(1, max_pages)
        self._gamma_base = gamma_base.rstrip("/")
        self._data_base = data_base.rstrip("/")
        self._timeout = timeout
        self._use_keyword_search = use_keyword_search

    def _fetch_page(
        self,
        requests_mod: Any,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Fetch one page from /markets. Returns list of raw market dicts."""
        url = f"{self._gamma_base}/markets"
        try:
            resp = requests_mod.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None  # None = network error; [] = successful but empty
        if isinstance(data, list):
            return data
        return data.get("markets", []) if isinstance(data, dict) else []

    def _raw_markets_to_records(
        self, markets: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert raw market dicts to loader record dicts."""
        records = []
        for m in markets:
            if not isinstance(m, dict):
                continue
            raw_tags = m.get("tags") or []
            if isinstance(raw_tags, list):
                tags = [
                    t.get("label", "") if isinstance(t, dict) else str(t)
                    for t in raw_tags
                ]
            else:
                tags = []
            rec: dict[str, Any] = {
                "market_id": str(m.get("id", "")),
                "question": str(m.get("question", "")),
                "volume": m.get("volume"),
                "liquidity": m.get("liquidity"),
                "end_date": m.get("endDate"),
                "active": m.get("active"),
                "category": m.get("category") or m.get("groupItemTitle") or "",
                "tags": tags,
                "description": str(m.get("description", "") or ""),
                "source": "polymarket",
            }
            self._stamp_record(rec)
            records.append(rec)
        return records

    def fetch(self) -> LoaderResult:
        """Fetch public market summaries from Polymarket Gamma API (read-only)."""
        try:
            import requests  # lazy import — no network on module load
        except ImportError:
            raise SkipLoader("requests library not installed")

        seen_ids: set[str] = set()
        all_markets: list[dict[str, Any]] = []
        fetch_succeeded = False

        # Step 1: keyword-targeted searches for domain-relevant markets
        if self._use_keyword_search:
            for keyword in _DOMAIN_KEYWORDS:
                params: dict[str, Any] = {
                    "limit": self._limit,
                    "active": "true",
                    "query": keyword,
                }
                page_markets = self._fetch_page(requests, params)
                if page_markets is None:
                    continue  # network error — try next keyword
                fetch_succeeded = True
                for m in page_markets:
                    if not isinstance(m, dict):
                        continue
                    mid = str(m.get("id", ""))
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        all_markets.append(m)

        # Step 2: paginated broad fetch (catches markets not reached by keyword search)
        for page_num in range(self._max_pages):
            params = {
                "limit": self._limit,
                "active": "true",
                "offset": page_num * self._limit,
            }
            page_markets = self._fetch_page(requests, params)
            if page_markets is None:
                break  # network error — stop pagination
            fetch_succeeded = True
            if not page_markets:
                break
            for m in page_markets:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id", ""))
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    all_markets.append(m)

        if not fetch_succeeded:
            raise SkipLoader("Polymarket API unreachable: all requests failed")

        records = self._raw_markets_to_records(all_markets)
        return LoaderResult(source_name=self.source_name, records=records)
