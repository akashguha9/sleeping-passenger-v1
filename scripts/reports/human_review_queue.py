"""Human-review queue builder (advisory-only)."""
from __future__ import annotations

from typing import Any, Iterable

from scripts.normalization.signal_event_schema import ADVISORY_ONLY, SignalEvent

QUEUE_INVARIANTS = {
    "execution_permission": ADVISORY_ONLY,
    "human_review_required": True,
    "ai_executions": 0,
}

PROMOTION_STATES = frozenset({"AVENTADOR", "GALLARDO", "ISLERO", "HURACAN"})


def build_human_review_queue(events: Iterable[SignalEvent]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for event in events:
        if not event.human_review_required:
            continue
        items.append(
            {
                "event_id": event.event_id,
                "source_name": event.source_name,
                "source_type": event.source_type,
                "mvp_state": event.mvp_state,
                "headline_or_label": event.headline_or_label,
                "needs_attention": event.mvp_state in PROMOTION_STATES,
                "url": event.url,
            }
        )
    items.sort(key=lambda r: (not r["needs_attention"], r["source_name"]))
    return {**QUEUE_INVARIANTS, "queue_size": len(items), "items": items}
