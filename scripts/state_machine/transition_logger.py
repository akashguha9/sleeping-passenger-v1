"""In-memory transition logger.

This is intentionally a tiny structure: real persistence (JSONL on disk) is a
follow-up. The MVP just needs an audit trail callers can inspect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TransitionLog:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, event_id: str, from_state: str, to_state: str, reason: str) -> None:
        self.entries.append(
            {
                "event_id": event_id,
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
                "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
        )

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.entries)
