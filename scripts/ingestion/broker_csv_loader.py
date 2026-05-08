"""Broker CSV loader.

Manual file import only. NEVER connects to a broker API. NEVER places trades.
The CSV is treated as a portfolio-truth journal (one row per fill / position).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.normalization.signal_event_schema import NumericSignal, SignalEvent
from scripts.normalization.signal_processor import process_signal


class BrokerCSVLoader(BaseLoader):
    source_name = "broker_csv"
    source_type = "portfolio_truth"

    def fetch(self, *, csv_path: str | Path | None = None) -> LoaderResult:
        return self.read(csv_path=csv_path)

    def read(self, *, csv_path: str | Path | None = None) -> LoaderResult:
        if csv_path is None:
            return self.skip("no csv_path provided; manual import only")
        path = Path(csv_path)
        if not path.exists():
            return self.fail(f"csv not found: {path}")
        rows: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rows.append({k: (v or "").strip() for k, v in row.items()})
        except Exception as exc:
            return self.fail(f"csv read failed: {exc}", csv_path=str(path))

        events = [self.normalize(row) for row in rows]
        return self.ok(events, csv_path=str(path), row_count=len(rows))

    def normalize(self, raw: dict[str, Any]) -> SignalEvent:
        ticker = raw.get("ticker") or raw.get("symbol") or "UNKNOWN"
        side = (raw.get("side") or raw.get("action") or "").upper()
        qty = raw.get("quantity") or raw.get("qty") or "0"
        price = raw.get("price") or "0"
        ts = raw.get("timestamp") or raw.get("date") or None
        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": raw.get("jurisdiction") or "US",
            "headline_or_label": f"{ticker} {side} {qty} @ {price} (manual journal)",
            "raw_text_or_summary": "Manual broker CSV journal entry — advisory only.",
            "url": None,
            "event_type": "portfolio_journal_entry",
            "asset_tags": [ticker],
            "numeric_signal": NumericSignal(),
            "metadata": {"row": raw},
        }
        if ts:
            raw_event["timestamp_utc"] = self._coerce_ts(ts)
        return process_signal(raw_event)

    @staticmethod
    def _coerce_ts(value: str) -> str:
        if "T" in value:
            return value
        return f"{value}T00:00:00+00:00"
