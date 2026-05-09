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

try:
    from fastapi import FastAPI, Response
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
