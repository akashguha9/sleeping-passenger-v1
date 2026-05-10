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

try:
    from fastapi import FastAPI, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError as _exc:  # pragma: no cover
    import sys

    print(
        f"FastAPI is not installed ({_exc}).\n"
        "Install it with:  pip install fastapi uvicorn\n"
        "Then re-run:      python scripts/api_server.py"
    )
    sys.exit(1)

try:
    from scripts.signal_inbox_api import (
        add_ai_discussion_summary,
        add_user_reflection,
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

def _candles_from_market_events(events: list[dict]) -> list[dict]:
    """Extract OHLCV candle dicts from market_data signal_events raw_payload.

    Each event's raw_payload may already be a dict (parsed by get_signal_events)
    or a JSON string. Missing or non-numeric fields are silently skipped.
    """
    candles: list[dict] = []
    for ev in events:
        payload = ev.get("raw_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(payload, dict):
            continue
        o = payload.get("open")
        h = payload.get("high")
        lo = payload.get("low")
        c = payload.get("close") if payload.get("close") is not None else payload.get("latest_price")
        v = payload.get("volume")
        ts = payload.get("timestamp") or ev.get("fetched_at", "")
        if any(x is None for x in (o, h, lo, c, v)) or not ts:
            continue
        candles.append({
            "timestamp": str(ts),
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v,
        })
    return candles


def _get_chart_structure(
    symbol: str,
    source_event_id: str | None = None,
    limit: int = 100,
) -> dict:
    """Fetch market_data signal events for *symbol*, adapt to candles, run engine.

    Returns an advisory-only chart structure report. Never places orders.
    Safety invariants are always present in the returned dict.
    """
    _safe_base = {
        "advisory_status": _ADVISORY_STATUS,
        "execution_gate": "LOCKED",
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }
    try:
        try:
            from scripts.persistence import get_signal_events
        except ModuleNotFoundError:
            from persistence import get_signal_events  # type: ignore

        try:
            from scripts.chart_structure_engine import analyze_chart_structure
        except ModuleNotFoundError:
            from chart_structure_engine import analyze_chart_structure  # type: ignore

        symbol_upper = symbol.strip().upper()
        all_events = get_signal_events(source_name="market_data", limit=limit)

        events = [
            ev for ev in all_events
            if (
                ev.get("raw_payload")
                if isinstance(ev.get("raw_payload"), dict)
                else {}
            ).get("symbol", "").upper() == symbol_upper
        ]

        linked_event_id: str | None = None
        if source_event_id:
            matched = [ev for ev in events if ev.get("event_id") == source_event_id]
            if not matched:
                broader = get_signal_events(limit=limit * 5)
                matched = [ev for ev in broader if ev.get("event_id") == source_event_id]
            if matched:
                linked_event_id = matched[0].get("event_id")

        candles = _candles_from_market_events(events)

        if not candles:
            return {
                **_safe_base,
                "symbol": symbol_upper,
                "source_event_id": linked_event_id,
                "candle_count": 0,
                "chart_state": "INSUFFICIENT_DATA",
                "advisory_summary": (
                    "No OHLCV candle data available for this symbol. "
                    "Run market_data ingestion first: "
                    "python scripts/run_live_sources_phase2.py --source market_data --write"
                ),
                "report": None,
            }

        report = analyze_chart_structure(
            candles, symbol=symbol_upper, source="market_data"
        )
        report_dict = report.to_dict()

        return {
            **_safe_base,
            "symbol": symbol_upper,
            "source_event_id": linked_event_id,
            "candle_count": len(candles),
            "report": report_dict,
        }

    except Exception as exc:
        return {
            **_safe_base,
            "symbol": symbol,
            "source_event_id": source_event_id,
            "candle_count": 0,
            "chart_state": "ERROR",
            "error": str(exc),
            "report": None,
        }


_CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0
_VERSION = "1.0.0"

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
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


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


class ReconcileBody(BaseModel):
    actual_fill_price: float
    actual_quantity: float
    outcome_notes: str = ""
    pnl_estimate: float = 0.0
    outcome_status: str = "UNKNOWN"


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
def get_signals() -> dict:
    return list_inbox_items()


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
    try:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)
    except ImportError:
        print("uvicorn not installed.  Run: pip install uvicorn")
