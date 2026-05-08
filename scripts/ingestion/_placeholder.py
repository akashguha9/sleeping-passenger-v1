"""Shared placeholder skeleton for not-yet-wired loaders.

All placeholder loaders are advisory-only and read-only by construction.
They expose ``fetch``/``read``/``normalize`` and return a clean skipped result
when the relevant API key / dependency is missing. They never crash.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.normalization.signal_event_schema import NumericSignal, SignalEvent
from scripts.normalization.signal_processor import process_signal


class PlaceholderLoader(BaseLoader):
    """Subclass and override ``source_name``/``source_type``/``required_env``."""

    source_name: str = "placeholder"
    source_type: str = "unknown"
    required_env: tuple[str, ...] = ()
    jurisdiction: str = "GLOBAL"

    def fetch(self, **_: Any) -> LoaderResult:
        for name in self.required_env:
            if not self.env(name):
                return self.skip(f"{name} not set; {self.source_name} placeholder")
        # No real implementation yet — return ok with no events so callers can
        # still treat the source as "wired but quiet".
        return self.ok([], note="placeholder loader; no upstream wired yet")

    def normalize(self, raw: dict[str, Any]) -> SignalEvent:
        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": self.jurisdiction,
            "headline_or_label": str(raw.get("title") or raw.get("headline") or self.source_name),
            "raw_text_or_summary": str(raw.get("summary") or raw.get("text") or ""),
            "url": raw.get("url"),
            "event_type": "placeholder_event",
            "asset_tags": list(raw.get("asset_tags") or []),
            "numeric_signal": NumericSignal(),
            "metadata": {"placeholder": True, "raw": raw},
        }
        return process_signal(raw_event)
