"""Global-securities routes (Phase F).

Identity Collapse + First-Day Operator sprint, Phase 9.

Read-only securities search / detail / coverage endpoints.  Persistence
helpers are looked up via ``scripts.api_server._sec_persistence`` at
request time so any future test that wants to patch them at the
``api_server`` module level continues to work.
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


_SEC_SAFE_BASE = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
}


def _sec_persistence():
    """Resolve via ``scripts.api_server._sec_persistence`` if available.

    Falls back to a direct import so the router still works when invoked
    in environments where ``api_server`` is the entry point and the
    helper has been moved away.
    """
    import scripts.api_server as _srv

    fn = getattr(_srv, "_sec_persistence", None)
    if callable(fn):
        return fn()
    try:
        from scripts.persistence import (
            search_global_securities,
            get_global_security,
            get_security_coverage,
        )
    except ModuleNotFoundError:  # pragma: no cover
        from persistence import (  # type: ignore[no-redef]
            search_global_securities,
            get_global_security,
            get_security_coverage,
        )
    return search_global_securities, get_global_security, get_security_coverage


def build_router():
    router = APIRouter()

    @router.get("/securities/search")
    def search_securities(q: str = "", limit: int = 20) -> dict:
        try:
            search_fn, _, _ = _sec_persistence()
            results = search_fn(q, limit=limit) if q.strip() else []
            return {
                **_SEC_SAFE_BASE,
                "query": q,
                "count": len(results),
                "results": results,
            }
        except Exception as exc:
            return {**_SEC_SAFE_BASE, "query": q, "count": 0, "results": [], "error": str(exc)}

    @router.get("/securities/{symbol}")
    def get_security(symbol: str) -> dict:
        try:
            try:
                from scripts.symbol_normalizer import normalize_symbol
            except ModuleNotFoundError:  # pragma: no cover
                from symbol_normalizer import normalize_symbol  # type: ignore[no-redef]

            norm = normalize_symbol(symbol)
            canonical = norm["canonical_symbol"]
            _, get_fn, _ = _sec_persistence()
            security = get_fn(canonical)

            if security is None and norm.get("unknown"):
                return {
                    **_SEC_SAFE_BASE,
                    "symbol": symbol.upper(),
                    "canonical_symbol": canonical,
                    "found": False,
                    "resolution": norm,
                    "error": "UNKNOWN_SYMBOL",
                    "discovery_command": norm.get("discovery_command"),
                    "backfill_command": norm.get("backfill_command"),
                }

            return {
                **_SEC_SAFE_BASE,
                "symbol": symbol.upper(),
                "canonical_symbol": canonical,
                "found": security is not None,
                "resolution": norm,
                "security": security,
            }
        except Exception as exc:
            return {**_SEC_SAFE_BASE, "symbol": symbol, "found": False, "error": str(exc)}

    @router.get("/securities/{symbol}/coverage")
    def get_security_coverage_endpoint(symbol: str) -> dict:
        try:
            try:
                from scripts.symbol_normalizer import normalize_symbol
            except ModuleNotFoundError:  # pragma: no cover
                from symbol_normalizer import normalize_symbol  # type: ignore[no-redef]

            norm = normalize_symbol(symbol)
            canonical = norm["canonical_symbol"]
            _, _, cov_fn = _sec_persistence()
            coverage = cov_fn(canonical)
            coverage["input_symbol"] = symbol.upper()
            coverage["resolution"] = norm
            return coverage
        except Exception as exc:
            return {
                **_SEC_SAFE_BASE,
                "canonical_symbol": symbol.upper(),
                "error": str(exc),
            }

    return router
