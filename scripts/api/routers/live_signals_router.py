"""Live signals router — read-only, advisory-only.

Calibration Corpus + Hosted Canary sprint, Phase 3.

Extracts ``GET /live-signals`` and its helper ``_get_live_signals``
from ``scripts/api_server.py``.  The helper is re-exported back so
existing imports (``from scripts.api_server import _get_live_signals``)
and patches keep working; the route handler resolves the helper via
``scripts.api_server`` at request time.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def get(self, *_a: Any, **_kw: Any):
            def decorator(fn):
                return fn

            return decorator


_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0


def _get_live_signals(source_name: str | None = None, limit: int = 100) -> dict:
    """Return the persisted live-signal events for the given source.

    Read-only.  Errors are caught and surfaced in the response rather
    than raised so the API never 500s on a transient DB issue.
    """
    try:
        try:
            from scripts.persistence import get_signal_events
        except ModuleNotFoundError:
            from persistence import get_signal_events  # type: ignore
        events = get_signal_events(source_name=source_name, limit=limit)
        return {
            "live_signal_events": events,
            "count": len(events),
            "advisory_status": _ADVISORY_STATUS,
            "execution_mode": _EXECUTION_MODE,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "human_review_required": True,
        }
    except Exception as exc:
        return {
            "live_signal_events": [],
            "count": 0,
            "error": str(exc),
            "advisory_status": _ADVISORY_STATUS,
            "ai_execution_count": _AI_EXECUTION_COUNT,
        }


def get_live_signals(source: str | None = None, limit: int = 100) -> dict:
    """Route handler — resolves helper via ``scripts.api_server`` so
    patches on ``scripts.api_server._get_live_signals`` bite."""
    import scripts.api_server as _srv

    fn = getattr(_srv, "_get_live_signals", _get_live_signals)
    return fn(source_name=source, limit=limit)


def build_router():
    router = APIRouter()
    router.get("/live-signals")(get_live_signals)
    return router
