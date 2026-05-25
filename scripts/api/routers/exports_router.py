"""CSV export routes.

Identity Collapse + First-Day Operator sprint, Phase 9.

The six CSV export endpoints are GET-only and return text/csv bodies.
They are advisory-only — the audit row written by ``scripts.gsheet_export``
carries the safety stamp set; the CSV body itself does not (no JSON
keys to attach stamps to).

Patch compatibility
-------------------
Existing tests patch ``scripts.api_server.export_<name>_log`` to inject
fake CSV content (see ``tests/test_api_server.py:227-232``).  To preserve
those patches, this router does **not** import the export functions at
load time.  It resolves them via ``scripts.api_server`` at request time
so the patch bites the symbol the test actually replaces.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, Response
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

    class Response:  # type: ignore[no-redef]
        def __init__(self, content: str = "", media_type: str = "") -> None:
            self.content = content
            self.media_type = media_type


_CSV_MEDIA_TYPE = "text/csv"


def _call_export(symbol_name: str) -> str:
    """Resolve and call an export function via ``scripts.api_server``.

    This indirection is deliberate.  Tests patch
    ``scripts.api_server.export_signal_inbox_log`` (etc.) to inject fake
    CSV bodies, so this router must look up the symbol on that module at
    request time, not capture an import-time binding.
    """
    import scripts.api_server as _srv  # late import — patches must apply

    fn = getattr(_srv, symbol_name, None)
    if fn is None:
        # Fallback to a direct import.  Loud failure beats silent CSV.
        from scripts.gsheet_export import (
            export_signal_inbox_log,
            export_reflection_log,
            export_manual_trade_log,
            export_reconciliation_log,
            export_moltbook_mistake_log,
            export_source_health_log,
        )
        table = {
            "export_signal_inbox_log": export_signal_inbox_log,
            "export_reflection_log": export_reflection_log,
            "export_manual_trade_log": export_manual_trade_log,
            "export_reconciliation_log": export_reconciliation_log,
            "export_moltbook_mistake_log": export_moltbook_mistake_log,
            "export_source_health_log": export_source_health_log,
        }
        fn = table[symbol_name]
    return fn()


def build_router():
    router = APIRouter()

    @router.get("/exports/signal-inbox.csv")
    def export_signal_inbox() -> Response:
        return Response(content=_call_export("export_signal_inbox_log"), media_type=_CSV_MEDIA_TYPE)

    @router.get("/exports/reflections.csv")
    def export_reflections() -> Response:
        return Response(content=_call_export("export_reflection_log"), media_type=_CSV_MEDIA_TYPE)

    @router.get("/exports/manual-trades.csv")
    def export_manual_trades() -> Response:
        return Response(content=_call_export("export_manual_trade_log"), media_type=_CSV_MEDIA_TYPE)

    @router.get("/exports/reconciliation.csv")
    def export_reconciliation() -> Response:
        return Response(content=_call_export("export_reconciliation_log"), media_type=_CSV_MEDIA_TYPE)

    @router.get("/exports/moltbook.csv")
    def export_moltbook() -> Response:
        return Response(content=_call_export("export_moltbook_mistake_log"), media_type=_CSV_MEDIA_TYPE)

    @router.get("/exports/source-health.csv")
    def export_source_health() -> Response:
        return Response(content=_call_export("export_source_health_log"), media_type=_CSV_MEDIA_TYPE)

    return router
