"""Ticker / asset-tag mapping placeholder."""
from __future__ import annotations

# Seed map for sanity tests; expand to real reference data in a later pass.
SEED_TICKER_MAP: dict[str, str] = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "bitcoin": "BTC",
    "ethereum": "ETH",
}


def asset_tags_for(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    return sorted({sym for kw, sym in SEED_TICKER_MAP.items() if kw in lowered})
