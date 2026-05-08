"""Advisory-action report (advisory-only).

Maps mvp_state to the *suggested* human action. NEVER returns an executable
action — every payload is stamped ADVISORY_ONLY with ai_executions=0.
"""
from __future__ import annotations

from typing import Any, Iterable

from scripts.normalization.signal_event_schema import ADVISORY_ONLY, SignalEvent

ADVISORY_INVARIANTS = {
    "execution_permission": ADVISORY_ONLY,
    "human_review_required": True,
    "ai_executions": 0,
}

STATE_TO_SUGGESTED_ACTION = {
    "MIURA": "OBSERVE",
    "MURCIELAGO": "REVIEW",
    "AVENTADOR": "HUMAN_REVIEW_REQUIRED",
    "GALLARDO": "MANUAL_CHECKLIST_ONLY",
    "ISLERO": "SHOCK_REVIEW",
    "DIABLO": "NO_NEW_RISK",
    "HURACAN": "FAST_TRACK_HUMAN_REVIEW",
}


def build_advisory_action_report(events: Iterable[SignalEvent]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for event in events:
        rows.append(
            {
                "event_id": event.event_id,
                "source_name": event.source_name,
                "mvp_state": event.mvp_state,
                "suggested_action": STATE_TO_SUGGESTED_ACTION.get(event.mvp_state, "OBSERVE"),
                "headline_or_label": event.headline_or_label,
                "execution_permission": ADVISORY_ONLY,
                "human_review_required": True,
            }
        )
    return {**ADVISORY_INVARIANTS, "items": rows, "item_count": len(rows)}
