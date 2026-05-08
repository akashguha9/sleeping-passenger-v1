"""GDELT DOC API read-only loader.

Uses the public DOC 2.0 API:
    https://api.gdeltproject.org/api/v2/doc/doc

No authentication required. Network errors return error metadata, never crash.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.normalization.signal_event_schema import NumericSignal, SignalEvent
from scripts.normalization.signal_processor import process_signal

DOC_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


class GDELTLoader(BaseLoader):
    source_name = "gdelt"
    source_type = "news_event"

    def fetch(self, *, query: str, timespan: str = "24h", maxrecords: int = 25) -> LoaderResult:
        try:
            data = self._http_get(
                DOC_BASE,
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "timespan": timespan,
                    "maxrecords": maxrecords,
                },
            )
        except Exception as exc:
            return self.fail(f"gdelt fetch failed: {exc}", query=query, timespan=timespan)

        articles = data.get("articles", []) if isinstance(data, dict) else []
        events = [self.normalize(row, query=query) for row in articles if isinstance(row, dict)]
        return self.ok(events, query=query, timespan=timespan)

    def normalize(self, raw: dict[str, Any], *, query: str = "") -> SignalEvent:
        title = raw.get("title") or ""
        url = raw.get("url")
        seendate = raw.get("seendate")  # GDELT format e.g. "20251108T120000Z"
        ts = self._parse_seendate(seendate)
        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": "GLOBAL",
            "headline_or_label": title,
            "raw_text_or_summary": raw.get("excerpt") or title,
            "url": url,
            "event_type": "news_article",
            "asset_tags": [],
            "numeric_signal": NumericSignal(),
            "metadata": {"query": query, "domain": raw.get("domain")},
        }
        if ts:
            raw_event["timestamp_utc"] = ts
        return process_signal(raw_event)

    @staticmethod
    def _parse_seendate(value: str | None) -> str | None:
        if not value or len(value) < 15:
            return None
        # 20251108T120000Z -> 2025-11-08T12:00:00+00:00
        try:
            return (
                f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
                f"T{value[9:11]}:{value[11:13]}:{value[13:15]}+00:00"
            )
        except Exception:
            return None
