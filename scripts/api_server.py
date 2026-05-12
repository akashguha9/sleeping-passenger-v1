"""
Signal Advisory API Server — local FastAPI server.

Exposes Signal Inbox, Reflection Desk, Moltbook, Manual Trade Log,
Reconciliation, and Google Sheet-compatible CSV exports through a local
read-only advisory HTTP interface.

Rules
-----
- ALL outputs are ADVISORY_ONLY.
- Execution is HUMAN_ONLY.
- AI execution count is always 0.
- No broker API connections.  No order placement.
- No buy/sell/execute endpoint exists.
- Manual trade log is record-keeping only — not order routing.

Start server
------------
  python scripts/api_server.py
  uvicorn scripts.api_server:app --reload
"""
from __future__ import annotations

import json

# FastAPI is an OPTIONAL dependency at import time.
#
# Why: the source-health classifier, sanitizer, and other pure helpers in
# this module are imported by tests that should not require a web framework
# to be installed.  GitHub Actions runners did not have fastapi installed,
# so an unconditional sys.exit(1) at import time was killing the entire
# pytest session.  Instead, we set a sentinel and let `if __name__ ==
# "__main__"` handle the user-facing install hint.
try:
    from fastapi import FastAPI, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
    _FASTAPI_IMPORT_ERROR: str | None = None
except ImportError as _exc:  # pragma: no cover — depends on env
    _FASTAPI_AVAILABLE = False
    _FASTAPI_IMPORT_ERROR = str(_exc)
    FastAPI = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]

    class BaseModel:  # type: ignore[no-redef]
        """Lightweight stand-in so module-level subclasses still parse."""

        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

try:
    from scripts.signal_inbox_api import (
        add_ai_discussion_summary,
        add_user_reflection,
        get_inbox_diagnostics,
        get_signal_detail,
        list_inbox_items,
        list_manual_trades,
        log_manual_trade,
        mark_signal,
        reconcile_trade,
        run_validation,
    )
    from scripts.moltbook_api import list_moltbook_entries, log_moltbook_entry
    from scripts.gsheet_export import (
        export_manual_trade_log,
        export_moltbook_mistake_log,
        export_reconciliation_log,
        export_reflection_log,
        export_signal_inbox_log,
        export_source_health_log,
    )
except ModuleNotFoundError:
    from signal_inbox_api import (  # type: ignore[no-redef]
        add_ai_discussion_summary,
        add_user_reflection,
        get_inbox_diagnostics,
        get_signal_detail,
        list_inbox_items,
        list_manual_trades,
        log_manual_trade,
        mark_signal,
        reconcile_trade,
        run_validation,
    )
    from moltbook_api import list_moltbook_entries, log_moltbook_entry  # type: ignore[no-redef]
    from gsheet_export import (  # type: ignore[no-redef]
        export_manual_trade_log,
        export_moltbook_mistake_log,
        export_reconciliation_log,
        export_reflection_log,
        export_signal_inbox_log,
        export_source_health_log,
    )

try:
    from scripts.chart_structure_api_context import _candles_from_market_events, _get_chart_structure
except ModuleNotFoundError:
    from chart_structure_api_context import _candles_from_market_events, _get_chart_structure  # type: ignore[no-redef]

try:
    from scripts.chart_symbol_bootstrap import bootstrap_symbol as _bootstrap_symbol
except ModuleNotFoundError:
    from chart_symbol_bootstrap import bootstrap_symbol as _bootstrap_symbol  # type: ignore[no-redef]


def _get_live_signals(source_name: str | None = None, limit: int = 100) -> dict:
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


def _get_source_run_log(limit: int = 50) -> list:
    try:
        try:
            from scripts.persistence import get_source_run_log
        except ModuleNotFoundError:
            from persistence import get_source_run_log  # type: ignore
        return get_source_run_log(limit=limit)
    except Exception:
        return []


# Source health summary helpers — classify ingestion run statuses for UI banners.
# Pure logic lives in scripts.source_health_summary so tests can exercise it
# without dragging in FastAPI.  We re-export the canonical helpers under the
# legacy `_`-prefixed names for backwards compatibility with existing tests.
try:
    from scripts.source_health_summary import (
        SOURCE_LABELS as _SOURCE_LABELS,
        build_source_health_summary as _build_source_health_summary,
        classify_source_status as _classify_source_status,
        empty_summary as _empty_source_health_summary,
        sanitize_error_text as _sanitize_error_text,
    )
except ModuleNotFoundError:
    from source_health_summary import (  # type: ignore[no-redef]
        SOURCE_LABELS as _SOURCE_LABELS,
        build_source_health_summary as _build_source_health_summary,
        classify_source_status as _classify_source_status,
        empty_summary as _empty_source_health_summary,
        sanitize_error_text as _sanitize_error_text,
    )


def _get_source_health_summary() -> dict:
    try:
        try:
            from scripts.persistence import (
                get_latest_source_run_per_source,
                count_signal_events_by_source,
            )
        except ModuleNotFoundError:
            from persistence import (  # type: ignore[no-redef]
                get_latest_source_run_per_source,
                count_signal_events_by_source,
            )
        latest_rows = get_latest_source_run_per_source()
        event_counts = count_signal_events_by_source()
    except Exception as exc:
        return _empty_source_health_summary(error=str(exc))

    return _build_source_health_summary(latest_rows, event_counts)


# DB status helper — imported lazily so server starts even if persistence unavailable
def _get_db_status() -> dict:
    try:
        try:
            from scripts.persistence import get_db_status
        except ModuleNotFoundError:
            from persistence import get_db_status  # type: ignore
        return get_db_status()
    except Exception as exc:
        return {
            "db_status": "unavailable",
            "error": str(exc),
            "advisory_status": _ADVISORY_STATUS,
            "ai_execution_count": _AI_EXECUTION_COUNT,
        }


def _log_source_health(stats: dict, bull_state: str) -> None:
    try:
        try:
            from scripts.persistence import insert_source_health
        except ModuleNotFoundError:
            from persistence import insert_source_health  # type: ignore
        insert_source_health(
            snapshot_count=int(stats.get("total_snapshot_rows", 0)),
            signal_event_count=int(stats.get("total_signal_events", 0)),
            ticker_count=int(stats.get("total_tickers_observed", 0)),
            killed_count=int(stats.get("killed_signal_count", 0)),
            blocked_count=int(stats.get("blocked_signal_count", 0)),
            fabric_bull_state=str(bull_state),
        )
    except Exception:
        pass

_CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0
_VERSION = "1.0.0"


class _NoopApp:
    """No-op stand-in for FastAPI() when the framework is unavailable.

    Lets module-level ``@app.get(...)`` / ``@app.post(...)`` decorators stay
    in place during import without actually registering any routes.  The
    ``__main__`` block below refuses to start the server in this mode.
    """

    routes: list = []

    def add_middleware(self, *_args, **_kwargs) -> None:
        return None

    def _decorator(self, *_args, **_kwargs):
        def wrap(fn):
            return fn

        return wrap

    get = _decorator
    post = _decorator
    put = _decorator
    delete = _decorator
    patch = _decorator


if _FASTAPI_AVAILABLE:
    app = FastAPI(
        title="Signal Advisory API",
        description=(
            "Local advisory signal surface. "
            "ALL outputs are ADVISORY_ONLY. "
            "Execution is HUMAN_ONLY. "
            "AI execution count is always 0. "
            "No broker API connections. "
            "No order placement."
        ),
        version=_VERSION,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://sleepingpassenger",
            "http://sleepingpassenger.local",
            "http://sleepingpassenger:80",
            "http://sleepingpassenger.local:80",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Origin"],
    )
else:
    app = _NoopApp()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class ReflectionBody(BaseModel):
    reflection_text: str
    author: str = "human"
    conviction_level: str = "MODERATE"


class AISummaryBody(BaseModel):
    summary_text: str
    model_label: str = "AI_ADVISORY"


class DecisionBody(BaseModel):
    status: str


class ManualTradeBody(BaseModel):
    event_id: str
    ticker: str
    side: str
    quantity: float
    price: float
    thesis: str
    notes: str = ""
    logged_by: str = "human"
    leverage: float = 1.0


class ReconcileBody(BaseModel):
    actual_fill_price: float
    actual_quantity: float
    outcome_notes: str = ""
    pnl_estimate: float = 0.0
    outcome_status: str = "UNKNOWN"


class ChartBootstrapBody(BaseModel):
    symbol: str
    period: str = "max"
    interval: str = "1d"


class MoltbookEntryBody(BaseModel):
    event_id: str
    ticker: str
    original_signal_thesis: str
    ai_interpretation: str
    user_reflection: str
    final_human_decision: str
    manual_trade_log_id: str = ""
    outcome: str = ""
    mistake_type: str
    lesson_learned: str
    bias_detected: str = ""
    recalibration_note: str = ""
    future_rule_update: str = ""


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
        "version": _VERSION,
    }


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@app.get("/signals")
def get_signals(limit: int = 100, hours: int = 72) -> dict:
    """Return Signal Inbox candidates derived from fresh signal_events.

    Query params:
      - limit: max items returned (clamped server-side)
      - hours: freshness window (defaults to 72)
    """
    return list_inbox_items(limit=limit, hours=hours)


@app.get("/signals/diagnostics")
def get_signals_diagnostics(hours: int = 72) -> dict:
    """Freshness + source-count diagnostic for the Signal Inbox bridge.

    Advisory-only — does not authorize any execution.
    """
    return get_inbox_diagnostics(hours=hours)


@app.get("/signals/{event_id}")
def get_signal(event_id: str) -> dict:
    return get_signal_detail(event_id)


@app.post("/signals/{event_id}/validate")
def validate_signal(event_id: str) -> dict:
    return run_validation(event_id)


@app.post("/signals/{event_id}/reflection")
def post_reflection(event_id: str, body: ReflectionBody) -> dict:
    return add_user_reflection(
        event_id,
        body.reflection_text,
        author=body.author,
        conviction_level=body.conviction_level,
    )


@app.post("/signals/{event_id}/ai-summary")
def post_ai_summary(event_id: str, body: AISummaryBody) -> dict:
    return add_ai_discussion_summary(
        event_id,
        body.summary_text,
        model_label=body.model_label,
    )


@app.post("/signals/{event_id}/decision")
def post_decision(event_id: str, body: DecisionBody) -> dict:
    return mark_signal(event_id, body.status)


# ---------------------------------------------------------------------------
# Manual trades
# ---------------------------------------------------------------------------


@app.post("/manual-trades")
def post_manual_trade(body: ManualTradeBody) -> dict:
    return log_manual_trade(
        event_id=body.event_id,
        ticker=body.ticker,
        side=body.side,
        quantity=body.quantity,
        price=body.price,
        thesis=body.thesis,
        notes=body.notes,
        logged_by=body.logged_by,
        leverage=body.leverage,
    )


@app.post("/manual-trades/{trade_id}/reconcile")
def post_reconcile(trade_id: str, body: ReconcileBody) -> dict:
    return reconcile_trade(
        trade_id,
        actual_fill_price=body.actual_fill_price,
        actual_quantity=body.actual_quantity,
        outcome_notes=body.outcome_notes,
        pnl_estimate=body.pnl_estimate,
        outcome_status=body.outcome_status,
    )


# ---------------------------------------------------------------------------
# Manual trades — list all
# ---------------------------------------------------------------------------


@app.get("/manual-trades")
def get_manual_trades() -> dict:
    return list_manual_trades()


# ---------------------------------------------------------------------------
# Source health
# ---------------------------------------------------------------------------


@app.get("/source-health")
def get_source_health() -> dict:
    result = list_inbox_items(write_runtime=False)
    stats = result.get("fabric_stats", {})
    bull_state = result.get("fabric_bull_state", "UNKNOWN")
    _log_source_health(stats, bull_state)
    return {
        "operation": "get_source_health",
        "fabric_stats": stats,
        "fabric_bull_state": bull_state,
        "source_run_log": _get_source_run_log(limit=20),
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
        "generated_at": result.get("generated_at", ""),
    }


@app.get("/source-health/summary")
def get_source_health_summary() -> dict:
    """Per-source classified health summary.

    Each entry exposes a sanitized human_message and a category code
    (e.g. CREDITS_EXHAUSTED, RATE_LIMITED, TIMEOUT, PLACEHOLDER) so the
    frontend can render a clear warning banner without leaking secrets.
    Advisory-only — no execution implications.
    """
    return _get_source_health_summary()


# ---------------------------------------------------------------------------
# Live signals (Phase 1 live source ingestion results)
# ---------------------------------------------------------------------------


@app.get("/live-signals")
def get_live_signals(source: str | None = None, limit: int = 100) -> dict:
    return _get_live_signals(source_name=source, limit=limit)


# ---------------------------------------------------------------------------
# Chart structure (Phase D.3) — advisory-only, read-only, no execution
# ---------------------------------------------------------------------------


@app.get("/chart-structure")
def get_chart_structure(
    symbol: str,
    source_event_id: str | None = None,
    limit: int = 100,
) -> dict:
    return _get_chart_structure(symbol=symbol, source_event_id=source_event_id, limit=limit)


@app.post("/chart-structure/bootstrap-symbol")
def post_chart_structure_bootstrap(body: ChartBootstrapBody) -> dict:
    """Discover + backfill OHLCV for a missing symbol on demand.

    Read-only market-data ingestion. Never places orders, never connects to
    a broker, never increments ai_execution_count. Returns sanitized status.
    """
    try:
        return _bootstrap_symbol(
            symbol=body.symbol,
            period=body.period,
            interval=body.interval,
        )
    except Exception as exc:  # pragma: no cover — belt-and-braces; bootstrap never raises
        return {
            "ok": False,
            "symbol": str(getattr(body, "symbol", "")).strip().upper(),
            "period": body.period,
            "interval": body.interval,
            "discovery_status": "ERROR",
            "backfill_status": "SKIPPED",
            "candles_written": None,
            "message": f"Unexpected error: {str(exc)[:200]}",
            "advisory_status": _ADVISORY_STATUS,
            "execution_mode": _EXECUTION_MODE,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "broker_order_id": "NONE",
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "human_review_required": True,
        }


# ---------------------------------------------------------------------------
# Global Securities (Phase F) — advisory-only, read-only
# ---------------------------------------------------------------------------

_SEC_SAFE_BASE = {
    "advisory_status": _ADVISORY_STATUS,
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "ai_execution_count": _AI_EXECUTION_COUNT,
    "broker_api_called": False,
    "broker_order_id": "NONE",
}


def _sec_persistence():
    try:
        from scripts.persistence import (
            search_global_securities,
            get_global_security,
            get_security_coverage,
        )
        return search_global_securities, get_global_security, get_security_coverage
    except ModuleNotFoundError:
        from persistence import (  # type: ignore[no-redef]
            search_global_securities,
            get_global_security,
            get_security_coverage,
        )
        return search_global_securities, get_global_security, get_security_coverage


@app.get("/securities/search")
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


@app.get("/securities/{symbol}")
def get_security(symbol: str) -> dict:
    try:
        try:
            from scripts.symbol_normalizer import normalize_symbol
        except ModuleNotFoundError:
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


@app.get("/securities/{symbol}/coverage")
def get_security_coverage_endpoint(symbol: str) -> dict:
    try:
        try:
            from scripts.symbol_normalizer import normalize_symbol
        except ModuleNotFoundError:
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


# ---------------------------------------------------------------------------
# DB status
# ---------------------------------------------------------------------------


@app.get("/db/status")
def get_db_status() -> dict:
    return _get_db_status()


# ---------------------------------------------------------------------------
# Moltbook
# ---------------------------------------------------------------------------


@app.get("/moltbook")
def get_moltbook() -> dict:
    return list_moltbook_entries()


@app.post("/moltbook")
def post_moltbook(body: MoltbookEntryBody) -> dict:
    return log_moltbook_entry(
        event_id=body.event_id,
        ticker=body.ticker,
        original_signal_thesis=body.original_signal_thesis,
        ai_interpretation=body.ai_interpretation,
        user_reflection=body.user_reflection,
        final_human_decision=body.final_human_decision,
        manual_trade_log_id=body.manual_trade_log_id,
        outcome=body.outcome,
        mistake_type=body.mistake_type,
        lesson_learned=body.lesson_learned,
        bias_detected=body.bias_detected,
        recalibration_note=body.recalibration_note,
        future_rule_update=body.future_rule_update,
    )


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------


@app.get("/exports/signal-inbox.csv")
def export_signal_inbox() -> Response:
    return Response(content=export_signal_inbox_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/reflections.csv")
def export_reflections() -> Response:
    return Response(content=export_reflection_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/manual-trades.csv")
def export_manual_trades() -> Response:
    return Response(content=export_manual_trade_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/reconciliation.csv")
def export_reconciliation() -> Response:
    return Response(content=export_reconciliation_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/moltbook.csv")
def export_moltbook() -> Response:
    return Response(content=export_moltbook_mistake_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/source-health.csv")
def export_source_health() -> Response:
    return Response(content=export_source_health_log(), media_type=_CSV_MEDIA_TYPE)


if __name__ == "__main__":  # pragma: no cover
    import sys

    if not _FASTAPI_AVAILABLE:
        print(
            f"FastAPI is not installed ({_FASTAPI_IMPORT_ERROR}).\n"
            "Install it with:  pip install fastapi uvicorn\n"
            "Then re-run:      python scripts/api_server.py"
        )
        sys.exit(1)
    try:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)
    except ImportError:
        print("uvicorn not installed.  Run: pip install uvicorn")
        sys.exit(1)
