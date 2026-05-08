"""
Broker CSV read-only loader — Phase 2 Global Signal Fabric.

Manual CSV import only. No broker API connection whatsoever.
Accepts a file path and returns parsed records as advisory observations.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader


class BrokerCSVLoader(BaseSourceLoader):
    source_name = "broker_csv"
    requires_key = False

    def __init__(self, csv_path: str | Path | None = None) -> None:
        self._csv_path = Path(csv_path) if csv_path else None

    def fetch(self) -> LoaderResult:
        """Parse a broker-exported CSV file (read-only, no API connection)."""
        if self._csv_path is None:
            raise SkipLoader("No CSV path provided to BrokerCSVLoader")
        path = Path(self._csv_path)
        if not path.exists():
            raise SkipLoader(f"CSV file not found: {path}")

        records: list[dict[str, Any]] = []
        try:
            with path.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rec: dict[str, Any] = dict(row)
                    rec["source"] = "broker_csv"
                    self._stamp_record(rec)
                    records.append(rec)
        except OSError as exc:
            raise SkipLoader(f"Cannot read CSV {path}: {exc}") from exc

        return LoaderResult(source_name=self.source_name, records=records)
