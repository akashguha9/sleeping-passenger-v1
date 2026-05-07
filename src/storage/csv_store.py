"""Optional CSV exports for the signal refinery MVP."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping


def write_csv_rows(path: str | Path, rows: Iterable[Mapping[str, object]]) -> Path:
    """Write dictionaries to CSV, inferring columns from the first row."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    row_list = list(rows)
    if not row_list:
        resolved.write_text("", encoding="utf-8")
        return resolved
    fieldnames = list(row_list[0].keys())
    with resolved.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(row_list)
    return resolved
