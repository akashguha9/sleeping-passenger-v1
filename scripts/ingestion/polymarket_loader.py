"""
Polymarket read-only loader — Phase 2 Global Signal Fabric.

Uses only public read-only endpoints (Gamma API and Data API).
No authenticated trading endpoints. No CLOB order submission.

Strategy for domain-relevant market retrieval:
1. Search the Gamma API with each domain keyword (politics, economy, crypto, etc.)
2. Fetch multiple pages of the default active markets listing for additional coverage
3. Deduplicate by market_id
4. Apply strict domain gate via classify_market_domain() — blocks sports/entertainment/meme
5. Normalize a 0..1 ``implied_probability`` from outcomePrices / yes_price /
   lastTradePrice / bestBid+bestAsk so the cross-venue disagreement scanner
   does not have to re-derive it at scan time.  The extraction logic is
   exported as :func:`extract_polymarket_implied_probability` so it can be
   reused (and tested) without instantiating the loader.
"""
from __future__ import annotations

import json
from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader


# ---------------------------------------------------------------------------
# Implied-probability extraction (kept in loader so ingestion is the
# single source of truth; the scanner imports it for parity).
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalise_probability(value: float | None) -> float | None:
    """Coerce a raw price into a 0..1 probability.

    Polymarket sometimes ships YES prices in cents (0..100) or as 0..1
    decimals — we accept both shapes and clamp.  Probabilities > 1 or
    < 0 are dropped (not silently clamped) so callers can see the gap.
    """
    if value is None:
        return None
    if 0.0 <= value <= 1.0:
        return value
    if 1.0 < value <= 100.0:
        return value / 100.0
    return None


def extract_polymarket_implied_probability(market: dict[str, Any]) -> tuple[float | None, str]:
    """Best-effort YES-side implied probability for a Polymarket market.

    Returns ``(probability, source_field_name)`` so downstream consumers
    can audit where the number came from.  ``probability`` is None when
    no field yields a valid 0..1 value.

    Field priority (each entry is checked once; first valid wins):

    1. ``implied_probability``           — already-normalised (canonical)
    2. ``outcomePrices``                  — Gamma list / JSON-string list
    3. ``outcome_prices``                 — alternate snake-case field
    4. ``yes_price``                      — explicit YES leg
    5. ``lastTradePrice``                 — Polymarket fallback
    6. ``bestAsk`` + ``bestBid`` midpoint — order-book midpoint as last
       resort; only when both legs are present and the spread is sane.
    """
    if not isinstance(market, dict):
        return None, ""

    # 1. Canonical.  The ``implied_probability`` field is contract-defined
    #    as a 0..1 decimal — anything outside that range is rejected
    #    (NOT silently re-interpreted as cents) so a corrupt upstream
    #    record cannot fake a probability via the canonical path.
    direct = _coerce_float(market.get("implied_probability"))
    if direct is not None and 0.0 <= direct <= 1.0:
        return direct, "implied_probability"

    # 2. outcomePrices (Gamma).
    for field in ("outcomePrices", "outcome_prices"):
        raw = market.get(field)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                raw = None
        if isinstance(raw, list) and raw:
            yes_candidate = _coerce_float(raw[0])
            norm = _normalise_probability(yes_candidate)
            if norm is not None:
                return norm, field

    # 3. Explicit YES leg.
    yes = _coerce_float(market.get("yes_price"))
    norm = _normalise_probability(yes)
    if norm is not None:
        return norm, "yes_price"

    # 4. lastTradePrice (Polymarket public).
    last = _coerce_float(market.get("lastTradePrice"))
    norm = _normalise_probability(last)
    if norm is not None:
        return norm, "lastTradePrice"

    # 5. Midpoint of bestBid / bestAsk when both are present.
    bid = _coerce_float(market.get("bestBid"))
    ask = _coerce_float(market.get("bestAsk"))
    if bid is not None and ask is not None and ask >= bid >= 0:
        mid = (bid + ask) / 2.0
        norm = _normalise_probability(mid)
        if norm is not None:
            return norm, "bestBid_bestAsk_midpoint"

    return None, ""

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
            implied, prob_source = extract_polymarket_implied_probability(m)
            rec: dict[str, Any] = {
                "market_id": str(m.get("id", "")),
                "question": str(m.get("question", "")),
                "title": str(m.get("question", "") or m.get("title", "") or ""),
                "volume": m.get("volume"),
                "liquidity": m.get("liquidity"),
                "end_date": m.get("endDate"),
                "active": m.get("active"),
                "category": m.get("category") or m.get("groupItemTitle") or "",
                "tags": tags,
                "description": str(m.get("description", "") or ""),
                "source": "polymarket",
                "implied_probability": implied,
                "implied_probability_source": prob_source or "missing",
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
