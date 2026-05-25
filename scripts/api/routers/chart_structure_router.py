"""Chart-structure routes (Phase D.3).

Identity Collapse + First-Day Operator sprint, Phase 9.

These routes are read-only.  Existing tests patch
``scripts.api_server._get_chart_structure`` to inject fake structures
(see ``tests/test_chart_structure_api.py:170``), so this router resolves
the underlying helper via ``scripts.api_server`` at request time rather
than at import time.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, Depends
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

        def post(self, *_a: Any, **_kw: Any):
            def decorator(fn):
                return fn

            return decorator

    def Depends(*_a: Any, **_kw: Any):  # type: ignore[no-redef]
        return None


def build_router(require_api_token, chart_bootstrap_body_type):
    """Build the chart-structure router.

    ``chart_bootstrap_body_type`` is the Pydantic ``ChartBootstrapBody``
    class defined in ``scripts.api_server`` (kept there so the request
    body schema and validation stay together).
    """
    router = APIRouter()

    @router.get("/chart-structure")
    def get_chart_structure(
        symbol: str,
        source_event_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        import scripts.api_server as _srv

        return _srv._get_chart_structure(
            symbol=symbol, source_event_id=source_event_id, limit=limit
        )

    @router.post("/chart-structure/bootstrap-symbol")
    def post_chart_structure_bootstrap(
        body: chart_bootstrap_body_type,
        _auth: None = Depends(require_api_token),
    ) -> dict:
        """Discover + backfill OHLCV for a missing symbol on demand.

        Read-only market-data ingestion.  Never places orders, never
        connects to a broker, never increments ai_execution_count.
        """
        import scripts.api_server as _srv

        try:
            return _srv._bootstrap_symbol(
                symbol=body.symbol,
                period=body.period,
                interval=body.interval,
            )
        except Exception as exc:  # pragma: no cover — belt-and-braces
            return {
                "ok": False,
                "symbol": str(getattr(body, "symbol", "")).strip().upper(),
                "period": body.period,
                "interval": body.interval,
                "discovery_status": "ERROR",
                "backfill_status": "SKIPPED",
                "candles_written": None,
                "message": f"Unexpected error: {str(exc)[:200]}",
                "advisory_status": "ADVISORY_ONLY",
                "execution_mode": "HUMAN_ONLY",
                "execution_gate": "LOCKED",
                "broker_api_called": False,
                "broker_order_id": "NONE",
                "ai_execution_count": 0,
                "human_review_required": True,
            }

    return router
