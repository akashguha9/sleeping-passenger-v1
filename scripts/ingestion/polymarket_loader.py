"""Polymarket read-only public market data loader.

Uses the public Gamma API only:
    GET https://gamma-api.polymarket.com/markets

NO authentication. NO trading endpoints. NO order placement.
Only public market metadata + last-price probabilities are read.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.normalization.signal_event_schema import NumericSignal, SignalEvent
from scripts.normalization.signal_processor import process_signal

GAMMA_BASE = "https://gamma-api.polymarket.com"


class PolymarketLoader(BaseLoader):
    source_name = "polymarket"
    source_type = "prediction_market"

    def fetch(self, *, limit: int = 25, active_only: bool = True) -> LoaderResult:
        try:
            data = self._http_get(
                f"{GAMMA_BASE}/markets",
                params={
                    "limit": limit,
                    "active": "true" if active_only else "false",
                    "closed": "false",
                },
            )
        except Exception as exc:
            return self.fail(f"polymarket fetch failed: {exc}")

        if not isinstance(data, list):
            data = data.get("markets", []) if isinstance(data, dict) else []

        events = [self.normalize(row) for row in data if isinstance(row, dict)]
        return self.ok(events, endpoint=f"{GAMMA_BASE}/markets")

    def normalize(self, raw: dict[str, Any]) -> SignalEvent:
        question = raw.get("question") or raw.get("title") or raw.get("slug") or ""
        # Probability: gamma surfaces "lastTradePrice" or "outcomePrices".
        prob: float | None = None
        last_price = raw.get("lastTradePrice")
        if isinstance(last_price, (int, float)):
            prob = float(last_price)
        elif isinstance(raw.get("outcomePrices"), list) and raw["outcomePrices"]:
            try:
                prob = float(raw["outcomePrices"][0])
            except (TypeError, ValueError):
                prob = None

        volume_change: float | None = None
        try:
            volume_change = float(raw.get("volume24hr") or 0.0) or None
        except (TypeError, ValueError):
            volume_change = None

        slug = raw.get("slug") or ""
        url = f"https://polymarket.com/event/{slug}" if slug else None

        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": "GLOBAL",
            "headline_or_label": question,
            "raw_text_or_summary": raw.get("description") or question,
            "url": url,
            "event_type": "prediction_market_quote",
            "asset_tags": [],
            "numeric_signal": NumericSignal(probability=prob, volume_change=volume_change),
            "metadata": {"condition_id": raw.get("conditionId") or raw.get("id")},
        }
        return process_signal(raw_event)
