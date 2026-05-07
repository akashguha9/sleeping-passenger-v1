"""Snapshot writers for raw JSON market payloads."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.market import MarketSnapshot


def write_snapshot_file(snapshots: list[MarketSnapshot], path: str | Path) -> Path:
    """Write normalized market snapshots to a JSON file."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps([snapshot.to_dict() for snapshot in snapshots], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return resolved
