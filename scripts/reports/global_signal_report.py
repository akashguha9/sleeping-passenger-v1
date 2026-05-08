"""Global signal report builder (advisory-only)."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from scripts.ingestion.base_loader import LoaderResult
from scripts.normalization.signal_event_schema import ADVISORY_ONLY, SignalEvent

REPORT_INVARIANTS = {
    "execution_permission": ADVISORY_ONLY,
    "human_review_required": True,
    "ai_executions": 0,
}


def _composite_score(event: SignalEvent) -> float:
    return (
        0.35 * event.source_reliability
        + 0.25 * event.freshness_score
        + 0.20 * event.narrative_intensity
        + 0.20 * event.market_confirmation
    )


def build_global_signal_report(
    events: Iterable[SignalEvent],
    *,
    loader_results: Iterable[LoaderResult] | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    events_list = list(events)
    by_source: Counter[str] = Counter(e.source_name for e in events_list)
    by_state: Counter[str] = Counter(e.mvp_state for e in events_list)
    perm_counter: Counter[str] = Counter(e.execution_permission for e in events_list)

    review_queue = [
        {
            "event_id": e.event_id,
            "source_name": e.source_name,
            "mvp_state": e.mvp_state,
            "headline_or_label": e.headline_or_label,
            "url": e.url,
        }
        for e in events_list
        if e.human_review_required
    ]

    top_signals = sorted(events_list, key=_composite_score, reverse=True)[:top_n]
    top_signals_payload = [
        {
            "event_id": e.event_id,
            "source_name": e.source_name,
            "mvp_state": e.mvp_state,
            "headline_or_label": e.headline_or_label,
            "score": round(_composite_score(e), 4),
        }
        for e in top_signals
    ]

    source_errors: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, Any]] = []
    if loader_results:
        for result in loader_results:
            if result.status == "error":
                source_errors.append(
                    {"source_name": result.source_name, "error": result.error}
                )
            elif result.status == "skipped":
                skipped_sources.append(
                    {"source_name": result.source_name, "reason": result.skipped_reason}
                )

    return {
        **REPORT_INVARIANTS,
        "total_signals": len(events_list),
        "signals_by_source": dict(by_source),
        "signals_by_state": dict(by_state),
        "human_review_queue": review_queue,
        "advisory_only_count": perm_counter.get(ADVISORY_ONLY, 0),
        "execution_permission_summary": dict(perm_counter),
        "source_errors": source_errors,
        "skipped_sources": skipped_sources,
        "top_signals": top_signals_payload,
    }
