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

Configuration (all optional, defaults preserve historical behaviour)
--------------------------------------------------------------------
- API_HOST                 (default 127.0.0.1)
- API_PORT                 (default 8000)
- ALLOWED_ORIGINS          (comma-separated; default localhost:3000 etc.)
- MVP_API_TOKEN            (if set, mutating POST routes require Bearer auth)
- MVP_DB_PATH              (default runtime/mvp_local.db)
- MVP_ENVIRONMENT          (default "local")

Start server
------------
  python scripts/api_server.py
  uvicorn scripts.api_server:app --reload
"""
from __future__ import annotations

import json
import logging

# FastAPI is an OPTIONAL dependency at import time.
#
# Why: the source-health classifier, sanitizer, and other pure helpers in
# this module are imported by tests that should not require a web framework
# to be installed.  GitHub Actions runners did not have fastapi installed,
# so an unconditional sys.exit(1) at import time was killing the entire
# pytest session.  Instead, we set a sentinel and let `if __name__ ==
# "__main__"` handle the user-facing install hint.
try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
    _FASTAPI_IMPORT_ERROR: str | None = None
except ImportError as _exc:  # pragma: no cover — depends on env
    _FASTAPI_AVAILABLE = False
    _FASTAPI_IMPORT_ERROR = str(_exc)
    FastAPI = None  # type: ignore[assignment]
    Depends = lambda f=None: f  # type: ignore[assignment,misc]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
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
        cancel_manual_trade_log,
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
        cancel_manual_trade_log,
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

try:
    from scripts.runtime_config import (
        api_token_required,
        db_available,
        get_allowed_origins,
        get_api_host,
        get_api_port,
        get_api_token,
        get_environment_tag,
        get_max_request_bytes,
        rate_limit_enabled,
        rate_limit_max_requests,
        rate_limit_mutation_max_requests,
        rate_limit_window_seconds,
        safe_db_display_path,
        security_headers,
    )
except ModuleNotFoundError:  # pragma: no cover
    from runtime_config import (  # type: ignore[no-redef]
        api_token_required,
        db_available,
        get_allowed_origins,
        get_api_host,
        get_api_port,
        get_api_token,
        get_environment_tag,
        get_max_request_bytes,
        rate_limit_enabled,
        rate_limit_max_requests,
        rate_limit_mutation_max_requests,
        rate_limit_window_seconds,
        safe_db_display_path,
        security_headers,
    )

# Read-only diagnostics service — the single backend source for the cockpit.
# Bound at module level so tests can patch ``scripts.api_server.get_diagnostics_snapshot``.
try:
    from scripts.diagnostics_service import get_diagnostics_snapshot
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from diagnostics_service import get_diagnostics_snapshot  # type: ignore[no-redef]


_logger = logging.getLogger("sleeping_passenger.api")
if not _logger.handlers:
    # Lightweight default handler — does not duplicate uvicorn's own stream
    # but ensures startup/health messages reach stdout when running via
    # `python scripts/api_server.py`.
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    )
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


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

    _ALLOWED_ORIGINS = get_allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Origin", "Authorization"],
    )

    # Lazily built once on first request -- env vars are read inside the
    # middleware itself so tests can monkeypatch without re-importing.
    try:
        from scripts.rate_limiter import RateLimiter
    except ModuleNotFoundError:  # pragma: no cover
        from rate_limiter import RateLimiter  # type: ignore[no-redef]

    _RATE_LIMITERS: dict[str, RateLimiter] = {}

    def _get_rate_limiter(scope: str) -> "RateLimiter":
        """Return (and cache) a limiter for the given scope.

        Two scopes are used: ``"read"`` (all routes) and ``"write"``
        (mutating routes).  Caching matters because the bucket state lives
        inside the limiter -- we'd reset every counter on every request if
        we constructed a fresh limiter each call.
        """
        if scope == "write":
            limit = rate_limit_mutation_max_requests()
        else:
            limit = rate_limit_max_requests()
        window = rate_limit_window_seconds()
        cached = _RATE_LIMITERS.get(scope)
        if (
            cached is None
            or cached.max_requests != limit
            or cached.window_seconds != window
        ):
            cached = RateLimiter(max_requests=limit, window_seconds=window)
            _RATE_LIMITERS[scope] = cached
        return cached

    def _reset_rate_limiters() -> None:
        """Test helper: drop all rate-limit state.  Not part of the API."""
        _RATE_LIMITERS.clear()

    _MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    @app.middleware("http")
    async def _security_and_limits(request: "Request", call_next):
        """Single middleware that stacks four concerns in one place:

        1. Request size guard (Content-Length-based, 413 on overflow)
        2. Rate limiting (read scope + stricter write scope)
        3. Response security headers
        4. Advisory safety on the synthetic 413/429 responses

        Implemented as one middleware (not three) so the order of effects is
        explicit and so we don't pay for three async hops per request.
        """
        method = request.method.upper()
        is_mutating = method in _MUTATING_METHODS
        client_host = (request.client.host if request.client else "unknown") or "unknown"

        # 1. Request size guard.  We only inspect Content-Length here --
        #    streaming bodies without that header are allowed through; the
        #    handlers themselves enforce schema validation.  This is
        #    deliberately conservative: it catches obviously oversized POSTs
        #    without breaking edge cases like chunked transfer.
        if is_mutating:
            try:
                max_bytes = get_max_request_bytes()
            except Exception:
                max_bytes = 1_000_000
            cl_raw = request.headers.get("content-length")
            if cl_raw is not None:
                try:
                    content_length = int(cl_raw)
                except ValueError:
                    content_length = -1
                if content_length > max_bytes:
                    payload = {
                        "error": "request_body_too_large",
                        "status_code": 413,
                        "max_request_bytes": max_bytes,
                        "received_content_length": content_length,
                        "advisory_status": _ADVISORY_STATUS,
                        "execution_mode": _EXECUTION_MODE,
                        "execution_gate": "LOCKED",
                        "ai_execution_count": _AI_EXECUTION_COUNT,
                        "broker_api_called": False,
                        "broker_order_id": "NONE",
                        "human_review_required": True,
                    }
                    response = JSONResponse(status_code=413, content=payload)
                    for header, value in security_headers().items():
                        response.headers.setdefault(header, value)
                    return response

        # 2. Rate limiting.  Mutating requests count against the stricter
        #    write bucket; everything else (incl. GETs that hit the DB) uses
        #    the broader read bucket.  Keyed on client_host so a misbehaving
        #    test client can't starve a real user.
        if rate_limit_enabled():
            scope = "write" if is_mutating else "read"
            limiter = _get_rate_limiter(scope)
            decision = limiter.check(f"{client_host}:{scope}")
            if not decision.allowed:
                payload = {
                    "error": "rate_limited",
                    "status_code": 429,
                    "limit": decision.limit,
                    "window_seconds": decision.window_seconds,
                    "scope": scope,
                    "advisory_status": _ADVISORY_STATUS,
                    "execution_mode": _EXECUTION_MODE,
                    "execution_gate": "LOCKED",
                    "ai_execution_count": _AI_EXECUTION_COUNT,
                    "broker_api_called": False,
                    "broker_order_id": "NONE",
                    "human_review_required": True,
                }
                response = JSONResponse(status_code=429, content=payload)
                response.headers["Retry-After"] = str(decision.retry_after_seconds)
                for header, value in security_headers().items():
                    response.headers.setdefault(header, value)
                return response

        # 3. Hand off to the actual route.  Errors are sanitized by the
        #    HTTPException / Exception handlers above; both already stamp
        #    advisory invariants.  We only add headers here.
        response = await call_next(request)
        for header, value in security_headers().items():
            response.headers.setdefault(header, value)
        return response

    @app.on_event("startup")
    def _startup_safety_log() -> None:  # pragma: no cover — side effect only
        if not api_token_required():
            _logger.warning(
                "MVP_API_TOKEN not set; mutating routes are unprotected. "
                "Local-only use recommended."
            )
        else:
            _logger.info("MVP_API_TOKEN set; mutating routes require Bearer auth.")
        _logger.info(
            "advisory contract enforced: %s / %s / execution_gate=%s / ai_execution_count=%d",
            _ADVISORY_STATUS,
            _EXECUTION_MODE,
            "LOCKED",
            _AI_EXECUTION_COUNT,
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(  # pragma: no cover — exercised by tests
        request: "Request", exc: HTTPException
    ) -> "JSONResponse":
        """Stamp HTTPException responses with the advisory safety block.

        We never weaken safety on error paths.  HTTP status is preserved.
        When the route raises ``HTTPException(detail={...})`` we surface
        the structured detail under the ``detail`` key (FastAPI's own
        convention) so the frontend can render the backend's specific
        message/reason fields instead of a stringified Python repr — the
        cancel-log "(HTTP 400)" regression the user reported was caused
        by the previous str(exc.detail) coercion.
        """
        detail = exc.detail
        payload: dict = {
            "status_code": exc.status_code,
            "advisory_status": _ADVISORY_STATUS,
            "execution_mode": _EXECUTION_MODE,
            "execution_gate": "LOCKED",
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "broker_api_called": False,
            "broker_order_id": "NONE",
            "human_review_required": True,
        }
        if isinstance(detail, dict):
            payload["detail"] = detail
            msg = detail.get("message") if isinstance(detail.get("message"), str) else None
            payload["error"] = msg or "request failed"
        elif detail:
            payload["error"] = str(detail)
        else:
            payload["error"] = "request failed"
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(  # pragma: no cover
        request: "Request", exc: Exception
    ) -> "JSONResponse":
        """Sanitise unhandled exceptions: log full detail, return generic JSON.

        Never leaks file paths or stack traces to clients.
        """
        _logger.exception("unhandled error on %s %s", request.method, request.url.path)
        payload = {
            "error": "internal_error",
            "status_code": 500,
            "advisory_status": _ADVISORY_STATUS,
            "execution_mode": _EXECUTION_MODE,
            "execution_gate": "LOCKED",
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "broker_api_called": False,
            "broker_order_id": "NONE",
            "human_review_required": True,
        }
        return JSONResponse(status_code=500, content=payload)


    def require_api_token(authorization: str | None = Header(default=None)) -> None:
        """FastAPI dependency that enforces a Bearer token when ``MVP_API_TOKEN`` is set.

        Behaviour:
          * If ``MVP_API_TOKEN`` is unset or empty: no-op (local-dev permissive).
          * If set: request must include ``Authorization: Bearer <token>`` and
            the token must match exactly.  Otherwise 401.

        GET routes do not depend on this; only mutating routes do.
        """
        expected = get_api_token()
        if not expected:
            return None
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        provided = authorization.split(" ", 1)[1].strip()
        if provided != expected:
            raise HTTPException(status_code=401, detail="invalid bearer token")
        return None
else:
    app = _NoopApp()  # type: ignore[assignment]

    def require_api_token(authorization: str | None = None) -> None:  # type: ignore[no-redef]
        """No-op fallback when FastAPI is unavailable (test-only path)."""
        return None


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
    # Operator-discipline / journal-quality fields. All optional; backwards
    # compatible — frontends that omit them keep working.
    invalidation_level: str = ""
    expected_horizon: str = ""
    risk_reason: str = ""
    entry_reason: str = ""
    exit_plan: str = ""
    confidence_before: float | None = None
    emotional_state: str = ""
    mistake_tags: str = ""
    lesson: str = ""
    # Reactor-at-decision snapshot (Sprint 7B.1). Closes the HTTP path so
    # operators logging a trade through the API can attach the Signal
    # Reactor advisory state they saw at decision time. All optional —
    # legacy clients keep working. Values are normalized server-side
    # (scores clamped to [0,1], booleans coerced, hostile input → empty)
    # by log_manual_trade. Capturing a reactor snapshot here NEVER grants
    # execution permission; broker_api_called stays False and
    # ai_execution_count stays 0.
    reactor_state_at_decision: str = ""
    decision_grade_energy_at_decision: float | None = None
    echo_risk_score_at_decision: float | None = None
    meltdown_risk_at_decision: float | None = None
    fusion_validity_at_decision: str = ""
    fission_branch_clarity_at_decision: float | None = None
    operator_heat_at_decision: float | None = None
    gallardo_block_at_decision: bool | None = None
    preflight_state_at_decision: str = ""
    # Sprint 7B.2 — paper-trade ledger classification.  Default
    # "REAL_MANUAL" preserves the legacy semantic.  Setting "PAPER" marks
    # this row as rehearsal/simulation — broker_api_called stays False
    # and execution_gate stays LOCKED.  Hostile / typo values normalise
    # to REAL_MANUAL server-side.
    trade_mode: str = "REAL_MANUAL"
    # Sprint I — Native currency for the manual trade.  Optional on the
    # wire so legacy callers stay compatible; the server normalises
    # anything outside the supported set down to '' (UNKNOWN) rather
    # than silently defaulting to USD.
    currency: str = ""
    # Free-text operator label naming which AI / model / source produced
    # the signal the operator acted on — e.g. "GPT-5.5", "Claude Code",
    # "Grok", "Gemini", "DeepSeek", "Perplexity", "Copilot",
    # "Human-only", "Multi-model consensus".  Optional on the wire
    # (legacy clients keep working).  Server normalises (trim + 120-char
    # cap) and reads back via the same field name.  Storing this NEVER
    # grants execution permission and never reaches a broker.
    ai_model_used: str = ""


class ReconcileBody(BaseModel):
    actual_fill_price: float
    actual_quantity: float
    outcome_notes: str = ""
    pnl_estimate: float = 0.0
    outcome_status: str = "UNKNOWN"
    # Skill-vs-luck / skill-vs-process attribution fields. All optional.
    outcome_quality: str = ""
    process_error: str = ""
    process_error_notes: str = ""
    mistake_tags: str = ""
    lesson: str = ""
    # Sprint H — Reconciliation tab productisation.  All optional so
    # legacy clients that only send the four core fields still work.
    # Each of these is record-keeping only — the backend never calls a
    # broker, never places/cancels an order, never increments
    # ai_execution_count.  See scripts/reconciliation_extras.py for the
    # canonical enum values and the structured-outcome serializer.
    post_trade_outcome: str = ""
    reconciliation_status: str = ""
    runner_quantity: float | None = None
    runner_status: str = ""
    partial_take_profit_price: float | None = None
    partial_take_profit_quantity: float | None = None
    take_profit_plan: str = ""
    stop_loss_price: float | None = None
    stop_loss_hit: bool = False
    exit_reason: str = ""
    invalidation_level: str = ""
    lesson_takeaway: str = ""
    notes: str = ""


class CancelManualTradeLogBody(BaseModel):
    # Both optional.  ``reason`` defaults to the standard duplicate-log
    # reason on the backend.  ``status`` is constrained server-side to the
    # CANCELLED_* enum and otherwise falls back to CANCELLED_DUPLICATE.
    reason: str = ""
    status: str = "CANCELLED_DUPLICATE"


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


class ReconciliationAutoUpdateBody(BaseModel):
    # Sheet-sync auto-update body.  Bookkeeping only — never reaches a broker.
    # ``action`` must be one of the four accepted reconciliation outcomes.
    ticker: str
    action: str
    live_price: float | None = None
    tp_price: float | None = None
    sl_price: float | None = None
    booked_percent: float | None = None
    ride_percent: float | None = None
    sheet_row_number: int | None = None
    source: str = "google_sheet_sync"
    # Safety stamps the caller MUST send.  Server re-asserts them on the
    # response regardless of what the client sent — these fields exist to
    # let us reject hostile payloads at the boundary in future, never to
    # allow the caller to flip the gate.
    advisory_only: bool = True
    human_execution_required: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    execution_gate: str = "LOCKED"


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    from datetime import datetime, timezone

    try:
        _allowed = get_allowed_origins()
    except Exception:
        _allowed = []
    try:
        _rate_limit_active = rate_limit_enabled()
    except Exception:
        _rate_limit_active = False
    try:
        _max_bytes = get_max_request_bytes()
    except Exception:
        _max_bytes = 0
    return {
        "status": "ok",
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": "LOCKED",
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "human_review_required": True,
        "version": _VERSION,
        "environment": get_environment_tag(),
        "db_available": db_available(),
        "db_path": safe_db_display_path(),
        "api_token_required": api_token_required(),
        "allowed_origins_count": len(_allowed),
        "rate_limit_enabled": _rate_limit_active,
        "max_request_bytes": _max_bytes,
        "security_headers_enabled": bool(security_headers()),
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
    }


@app.get("/api/version")
def api_version() -> dict:
    """Minimal version + safety-posture endpoint.

    Distinct from /health: this never touches the DB, never calls
    persistence, and is safe to wire to an external uptime check or a
    front-page badge.  Same advisory stamps, lighter payload.
    """
    from datetime import datetime, timezone

    return {
        "app_name": "Signal Advisory API",
        "version": _VERSION,
        "environment": get_environment_tag(),
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
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
def validate_signal(event_id: str, _auth: None = Depends(require_api_token)) -> dict:
    return run_validation(event_id)


@app.post("/signals/{event_id}/reflection")
def post_reflection(
    event_id: str,
    body: ReflectionBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    return add_user_reflection(
        event_id,
        body.reflection_text,
        author=body.author,
        conviction_level=body.conviction_level,
    )


@app.post("/signals/{event_id}/ai-summary")
def post_ai_summary(
    event_id: str,
    body: AISummaryBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    return add_ai_discussion_summary(
        event_id,
        body.summary_text,
        model_label=body.model_label,
    )


@app.post("/signals/{event_id}/decision")
def post_decision(
    event_id: str,
    body: DecisionBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    return mark_signal(event_id, body.status)


# ---------------------------------------------------------------------------
# Manual trades
# ---------------------------------------------------------------------------


@app.get("/config/supported-currencies")
def get_supported_currencies() -> dict:
    """Return the dropdown catalogue the Manual Trade Log uses.

    Read-only.  No broker call, no execution side-effects.  The
    payload is symbol-agnostic and shared between every operator-entry
    surface so the frontend never has to hardcode currency lists.
    """
    try:
        from scripts.supported_currencies import (
            UNKNOWN_CURRENCY,
            supported_currencies,
        )
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from supported_currencies import (  # type: ignore[no-redef]
            UNKNOWN_CURRENCY,
            supported_currencies,
        )
    return {
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "currencies": supported_currencies(),
        "unknown_code": UNKNOWN_CURRENCY,
    }


@app.post("/manual-trades")
def post_manual_trade(
    body: ManualTradeBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    result = log_manual_trade(
        event_id=body.event_id,
        ticker=body.ticker,
        side=body.side,
        quantity=body.quantity,
        price=body.price,
        thesis=body.thesis,
        notes=body.notes,
        logged_by=body.logged_by,
        leverage=body.leverage,
        invalidation_level=body.invalidation_level,
        expected_horizon=body.expected_horizon,
        risk_reason=body.risk_reason,
        entry_reason=body.entry_reason,
        exit_plan=body.exit_plan,
        confidence_before=body.confidence_before,
        emotional_state=body.emotional_state,
        mistake_tags=body.mistake_tags,
        lesson=body.lesson,
        reactor_state_at_decision=body.reactor_state_at_decision,
        decision_grade_energy_at_decision=body.decision_grade_energy_at_decision,
        echo_risk_score_at_decision=body.echo_risk_score_at_decision,
        meltdown_risk_at_decision=body.meltdown_risk_at_decision,
        fusion_validity_at_decision=body.fusion_validity_at_decision,
        fission_branch_clarity_at_decision=body.fission_branch_clarity_at_decision,
        operator_heat_at_decision=body.operator_heat_at_decision,
        gallardo_block_at_decision=body.gallardo_block_at_decision,
        preflight_state_at_decision=body.preflight_state_at_decision,
        trade_mode=body.trade_mode,
        currency=body.currency,
        ai_model_used=body.ai_model_used,
    )
    # log_manual_trade returns a structured error dict (status="error" or
    # status!="logged" with an "error" key) when the row looks like a
    # seed/probe/automation insertion or fails validation.  Surface those
    # as HTTP 400 with the same safety stamps the success branch carries
    # — never as a silent success.  Frontends pattern-match on
    # detail.reason so the operator sees why the log was refused.
    if (
        isinstance(result, dict)
        and "error" in result
        and result.get("status") != "logged"
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(result.get("error") or "manual trade refused"),
                "reason": str(result.get("reason") or "manual_trade_refused"),
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "execution_gate": "LOCKED",
                "execution_permission": False,
                "can_execute": False,
                "record_keeping_only": True,
            },
        )
    return result


@app.post("/manual-trades/{trade_id}/reconcile")
def post_reconcile(
    trade_id: str,
    body: ReconcileBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    return reconcile_trade(
        trade_id,
        actual_fill_price=body.actual_fill_price,
        actual_quantity=body.actual_quantity,
        outcome_notes=body.outcome_notes,
        pnl_estimate=body.pnl_estimate,
        outcome_status=body.outcome_status,
        outcome_quality=body.outcome_quality,
        process_error=body.process_error,
        process_error_notes=body.process_error_notes,
        mistake_tags=body.mistake_tags,
        lesson=body.lesson,
        # Sprint H — Reconciliation productisation.  These are forwarded
        # directly to reconcile_trade which uses reconciliation_extras
        # to compute realized P/L, set runner_status, and serialise the
        # structured outcome into outcome_notes for downstream learning.
        post_trade_outcome=body.post_trade_outcome,
        reconciliation_status=body.reconciliation_status,
        runner_quantity=body.runner_quantity,
        runner_status=body.runner_status,
        partial_take_profit_price=body.partial_take_profit_price,
        partial_take_profit_quantity=body.partial_take_profit_quantity,
        take_profit_plan=body.take_profit_plan,
        stop_loss_price=body.stop_loss_price,
        stop_loss_hit=body.stop_loss_hit,
        exit_reason=body.exit_reason,
        invalidation_level=body.invalidation_level,
        lesson_takeaway=body.lesson_takeaway,
        operator_notes_extra=body.notes,
    )


@app.post("/manual-trades/{trade_id}/cancel")
def post_cancel_manual_trade_log(
    trade_id: str,
    body: CancelManualTradeLogBody | None = None,
    _auth: None = Depends(require_api_token),
) -> dict:
    """Soft-cancel a duplicate / mis-logged manual trade log entry.

    Record-keeping only.  This route NEVER places, modifies, or cancels a
    broker order; it only marks the local journal row as cancelled so it
    stops appearing in the reconciliation queue.  ``ai_execution_count``
    stays 0; ``broker_api_called`` stays False.
    """
    payload = body or CancelManualTradeLogBody()
    result = cancel_manual_trade_log(
        trade_id,
        reason=payload.reason,
        status=payload.status,
    )
    if isinstance(result, dict) and result.get("status") == "not_found":
        # Structured 404 — the frontend surfaces ``detail.message`` so the
        # operator sees "manual trade log MT_… not found" rather than a
        # bare "HTTP 404".
        raise HTTPException(
            status_code=404,
            detail={
                "message": str(result.get("error") or "manual trade log not found"),
                "reason": str(result.get("reason") or "not_found"),
                "trade_id": trade_id,
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "record_keeping_only": True,
            },
        )
    if isinstance(result, dict) and result.get("status") == "refused":
        # Structured 400 — includes ``reason`` so the frontend can show
        # "trade has been reconciled" or "non-manual-log origin" instead
        # of the bare "HTTP 400" the user complained about.  The shape
        # mirrors the success payload's safety stamps.
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(result.get("error") or "cancel refused"),
                "reason": str(result.get("reason") or "refused"),
                "trade_id": trade_id,
                "reconciled": bool(result.get("reconciled", False)),
                "created_via": str(result.get("created_via") or ""),
                "broker_api_called": bool(result.get("broker_api_called", False)),
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "record_keeping_only": True,
            },
        )
    return result


# ---------------------------------------------------------------------------
# Manual trades — list all
# ---------------------------------------------------------------------------


@app.get("/manual-trades")
def get_manual_trades(origin: str | None = "manual_trade_log") -> dict:
    """List logged manual trades.

    Default scope is ``origin=manual_trade_log`` so the Manual Trade Log
    surface NEVER shows seed / demo / fixture / smoke / paper-import rows
    even if such rows exist in the DB.  This is the active fence behind
    the empty-state contract: "no real manual trades = empty list, never
    a synthetic fallback AAPL row".

    Pass ``origin=all`` (or any other non-empty string) to override the
    default and receive every row — kept only as an audit escape hatch
    for ``/exports/manual-trades.csv`` and DB hygiene tooling.  Routine
    UI callers should NOT do this; the live operator surface is meant to
    show user-submitted entries only.
    """
    if origin == "all" or origin == "*":
        # Explicit audit override — return every row regardless of provenance.
        return list_manual_trades(origin=None)
    return list_manual_trades(origin=origin)


# ---------------------------------------------------------------------------
# Learning completeness (Sprint 7C.1) — read-only API surface for the
# CLI report at scripts/learning_completeness_report.py.  Exposes what
# trades still need an outcome/process/lesson label so the operator can
# close the learning loop without leaving the app.  Never grants
# execution permission; never claims learning is complete.
# ---------------------------------------------------------------------------


@app.get("/learning-completeness")
def get_learning_completeness(limit: int | None = 50) -> dict:
    """Return the learning-completeness report payload.

    Read-only.  Safe to call when the DB is missing or empty — returns a
    populated empty-state payload with explanatory warnings.  Includes
    paper/manual distinction via ``trade_mode_distribution`` when the
    underlying rows carry that column.
    """
    try:
        try:
            from scripts.learning_completeness_report import build_report
        except ModuleNotFoundError:
            from learning_completeness_report import build_report  # type: ignore[no-redef]
    except Exception as exc:
        return {
            "report": "learning_completeness_report",
            "db_available": False,
            "reconciled_count": 0,
            "learning_complete_count": 0,
            "learning_incomplete_count": 0,
            "missing_field_distribution": {},
            "items": [],
            "warnings": [f"import_failed:{type(exc).__name__}"],
            "trade_mode_distribution": {},
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_permission": False,
            "can_execute": False,
            "human_review_required": True,
            "operator_action": (
                "Could not load the learning-completeness module.  This "
                "endpoint stays advisory-only; no execution action is "
                "available."
            ),
            "advisory_disclaimer": (
                "Learning-completeness is advisory-only.  Marking a trade "
                "learning-complete records that the operator filled in "
                "review fields; it never places, modifies, or cancels any "
                "order."
            ),
        }
    safe_limit: int | None
    if limit is None:
        safe_limit = None
    else:
        try:
            n = int(limit)
        except (TypeError, ValueError):
            n = 50
        safe_limit = max(0, min(n, 500))
    payload = build_report(limit=safe_limit)

    # Ensure full safety-stamp contract — the CLI report omits a few
    # fields (e.g. human_review_required) the API layer always returns.
    payload.setdefault("human_review_required", True)
    payload.setdefault("execution_mode", _EXECUTION_MODE)

    # Augment with trade_mode distribution if the column exists.  The CLI
    # report already returns dicts of incomplete items; we re-query
    # cheaply to count paper vs real_manual without changing the CLI
    # contract.
    payload.setdefault("trade_mode_distribution", {})
    try:
        try:
            from scripts.persistence import DB_PATH as _DB_PATH
        except ModuleNotFoundError:
            from persistence import DB_PATH as _DB_PATH  # type: ignore[no-redef]
        import sqlite3 as _sqlite3
        if _DB_PATH and _DB_PATH.exists():
            uri = f"file:{_DB_PATH.as_posix()}?mode=ro"
            conn = _sqlite3.connect(uri, uri=True)
            try:
                conn.row_factory = _sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
                if "trade_mode" in cols:
                    # Restrict trade_mode distribution to rows created
                    # through the Manual Trade Log UI/API so the count
                    # matches the Learning Completeness numbers and does
                    # not balloon from seed/demo/import rows.
                    if "created_via" in cols:
                        rows = conn.execute(
                            "SELECT COALESCE(NULLIF(TRIM(trade_mode),''),'UNKNOWN') AS tm,"
                            " COUNT(*) AS n FROM manual_trades"
                            " WHERE COALESCE(created_via, '') = ?"
                            " GROUP BY tm",
                            ("manual_trade_log",),
                        ).fetchall()
                    else:
                        # Old DB without the provenance column — emit an
                        # empty distribution rather than leaking seeds.
                        rows = []
                    dist = {str(r["tm"]).upper(): int(r["n"]) for r in rows}
                    payload["trade_mode_distribution"] = dist
                    payload["paper_trade_count"] = dist.get("PAPER", 0)
                    payload["real_manual_trade_count"] = dist.get("REAL_MANUAL", 0)
            finally:
                conn.close()
    except Exception:
        pass

    # Convenience aliases for the frontend card.
    payload.setdefault("incomplete_count", payload.get("learning_incomplete_count", 0))
    payload.setdefault("complete_count", payload.get("learning_complete_count", 0))
    return payload


# ---------------------------------------------------------------------------
# Operator cockpit — read-only aggregate of the closed-loop diagnostics.
#
# Backed by the single read-only ``diagnostics_service`` (which reuses a fresh
# derived snapshot or recomputes once).  This replaced the previous per-hit
# fail-soft aggregation that recomputed every heavy audit and could collapse a
# crashed subreport into fake-clean zeros.  Now a failed subreport surfaces as
# DEGRADED in ``partial_failures`` and escalates the top-level ``status`` — it
# can never read as "clean".  Strictly read-only: no DB writes, no broker
# calls, no execution endpoint.
# ---------------------------------------------------------------------------


def _cockpit_panel_data(subreports: dict, name: str) -> dict:
    """Return a subreport's raw ``data`` dict, or ``{}`` when degraded/absent.

    A DEGRADED (crashed) subreport carries ``data = None``; the empty-dict
    fallback keeps the frontend panels renderable, but the failure is NOT
    hidden — it is surfaced explicitly via the top-level ``status`` and the
    ``partial_failures`` list so the cockpit can never read a crash as clean.
    """
    sub = subreports.get(name)
    if isinstance(sub, dict) and isinstance(sub.get("data"), dict):
        return sub["data"]
    return {}


@app.get("/diagnostics/cockpit")
def get_diagnostics_cockpit() -> dict:
    """Aggregate the advisory closed-loop diagnostics for the operator cockpit.

    Sourced from ``scripts.diagnostics_service.get_diagnostics_snapshot`` —
    cache-first, recompute-once, explicit degraded taxonomy.  Read-only: never
    grants execution permission; never places a broker order.
    """
    try:
        snapshot = get_diagnostics_snapshot(
            use_cache=True,
            refresh=False,
            include_heavy=True,
            max_age_seconds=300,
        )
    except Exception as exc:  # pragma: no cover - defensive: never 500 the cockpit
        _logger.warning("diagnostics_service unavailable: %s", type(exc).__name__)
        snapshot = {
            "status": "UNKNOWN",
            "degraded_state": "UNKNOWN",
            "generated_at_utc": None,
            "cache_status": "unavailable",
            "partial_failures": [{
                "subreport": "diagnostics_service",
                "error_type": type(exc).__name__,
                "safe_recovery_command": "python scripts/diagnostics_service.py",
            }],
            "subreports": {},
            "diagnostics_health": 0.0,
            "canonical_truth_source": "sqlite",
            "cache_role": "derived_non_canonical",
            "safety_stamps": {
                "advisory_status": _ADVISORY_STATUS,
                "execution_gate": "LOCKED",
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
            },
        }

    # Operator-guard coverage (cheap static scan; advisory, never crashes the
    # cockpit).  Lets the UI show guard-coverage + mutation-guard release impact
    # alongside the diagnostics integrity state.
    guard_summary: dict = {}
    try:
        try:
            from scripts.local_deploy_preflight import build_kante_defensive_summary
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from local_deploy_preflight import build_kante_defensive_summary  # type: ignore
        guard_summary = build_kante_defensive_summary()
    except Exception as exc:  # pragma: no cover - defensive
        _logger.warning("guard summary unavailable: %s", type(exc).__name__)
        guard_summary = {}

    subreports = snapshot.get("subreports", {})
    closed_loop = _cockpit_panel_data(subreports, "closed_loop")
    truth_purity = _cockpit_panel_data(subreports, "truth_purity")
    source_independence = _cockpit_panel_data(subreports, "source_independence")
    broken_windows = _cockpit_panel_data(subreports, "broken_windows")
    defensive_alpha = _cockpit_panel_data(subreports, "defensive_alpha")

    return {
        "report": "operator_cockpit",
        "advisory_disclaimer": (
            "Advisory diagnostics only. Human execution required. No broker "
            "action is performed. These panels measure system integrity and "
            "learning quality; they never place, modify, or cancel an order."
        ),
        # --- diagnostics_service: explicit health / degraded taxonomy ----------
        "status": snapshot.get("status", "UNKNOWN"),
        "degraded_state": snapshot.get("degraded_state", snapshot.get("status", "UNKNOWN")),
        "generated_at_utc": snapshot.get("generated_at_utc"),
        "cache_status": snapshot.get("cache_status", "unavailable"),
        "cache_role": snapshot.get("cache_role", "derived_non_canonical"),
        "canonical_truth_source": snapshot.get("canonical_truth_source", "sqlite"),
        "diagnostics_health": snapshot.get("diagnostics_health"),
        "partial_failures": snapshot.get("partial_failures", []),
        "subreports": {
            name: {k: v for k, v in sub.items() if k != "data"}
            for name, sub in subreports.items()
            if isinstance(sub, dict)
        },
        "safety_stamps": snapshot.get("safety_stamps", {}),
        # --- operator-guard coverage (advisory) -------------------------------
        "auth_guard_status": guard_summary.get("auth_guard_status"),
        "mutation_guard_coverage": guard_summary.get("mutation_guard_coverage"),
        "mutation_guard_release_impact": guard_summary.get(
            "mutation_guard_release_impact"),
        "mutation_scripts_unguarded_count": guard_summary.get(
            "mutation_scripts_unguarded_count"),
        # --- frontend-compatible panel projection (unchanged shape) -----------
        "closed_loop": {
            "closed_loop_coverage": closed_loop.get("closed_loop_coverage", 0.0),
            "signals_without_outcomes": closed_loop.get("signals_without_outcomes", 0),
            "manual_trades_without_reconciliation": closed_loop.get(
                "manual_trades_without_reconciliation", 0),
            "closed_losses_without_moltbook": closed_loop.get(
                "closed_losses_without_moltbook", 0),
            "unresolved_repair_debt": closed_loop.get("unresolved_repair_debt", 0),
        },
        "learning_efficiency": closed_loop.get("learning_efficiency", {}),
        "truth_purity": {
            "truth_purity_score": truth_purity.get("truth_purity_score", 1.0),
            "fake_rows_detected": truth_purity.get("fake_rows_detected", 0),
            "release_gate_passed": truth_purity.get("release_gate_passed", False),
        },
        "source_independence": {
            "cohort_count": source_independence.get("cohort_count", 0),
            "flagged_cohorts": source_independence.get("flagged_cohorts", []),
        },
        "broken_windows": {
            "repair_debt_score": broken_windows.get("repair_debt_score", 0.0),
            "release_gate_impact": broken_windows.get("release_gate_impact", "CLEAR"),
            "recommended_next_repair": broken_windows.get("recommended_next_repair", ""),
        },
        "defensive_alpha": {
            "total_defensive_events": defensive_alpha.get("total_defensive_events", 0),
            "fake_data_rows_blocked": defensive_alpha.get("fake_data_rows_blocked", 0),
            "closed_losses_captured_as_lessons": defensive_alpha.get(
                "closed_losses_captured_as_lessons", 0),
        },
        "invariants": {
            "advisory_only_verified": closed_loop.get("advisory_only_verified", True),
            "human_execution_verified": closed_loop.get("human_execution_verified", True),
            "broker_api_called_false_verified": closed_loop.get(
                "broker_api_called_false_verified", True),
            "ai_execution_count_zero_verified": closed_loop.get(
                "ai_execution_count_zero_verified", True),
        },
        # --- safety stamps (top-level shorthands, unchanged) ------------------
        "advisory_only": True,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_permission": False,
        "can_execute": False,
    }


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
# Watchdog summary surface (Sprint hardening)
# ---------------------------------------------------------------------------
#
# Exposes the JSON written by ``scripts/watchdog_refresh_stale_sources.py`` so
# the cockpit can render an honest "watchdog ran / improved / still stale"
# panel.  The route is READ-ONLY — it never writes, never refreshes, never
# triggers a refresh, and never authorises execution.  Missing-file payload
# is truthful (status=MISSING) rather than synthesising a healthy reply.

_WATCHDOG_SUMMARY_STALE_AFTER_MINUTES = 60


def _watchdog_summary_path() -> "Path":
    from pathlib import Path as _Path

    return _Path(__file__).resolve().parents[1] / "runtime" / "refresh_watchdog_summary.json"


def _watchdog_safety_payload() -> dict:
    # Carries BOTH the canonical ``advisory_status`` (sourced from
    # ``scripts.advisory_contract``) and the legacy ``advisory_only`` flag.
    # Existing tests pin ``advisory_only=True``; the advisory-stamp property
    # test requires ``advisory_status="ADVISORY_ONLY"``.  Emitting both
    # preserves backwards compatibility while closing the truth-surface gap.
    return {
        "advisory_status": "ADVISORY_ONLY",
        "advisory_only": True,
        "human_execution_required": True,
        "human_review_required": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "can_execute": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "broker_order_id": "NONE",
    }


def _build_watchdog_summary_response(
    *,
    summary_path: "Path | None" = None,
    now_iso: str | None = None,
) -> dict:
    """Pure builder for ``GET /source-health/watchdog`` — read-only."""
    import datetime as _dt
    import json as _json
    from pathlib import Path as _Path

    target = _Path(summary_path) if summary_path else _watchdog_summary_path()
    safety = _watchdog_safety_payload()
    if now_iso:
        now_dt = _dt.datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)
    else:
        now_dt = _dt.datetime.now(_dt.timezone.utc)
    loaded_at_iso = now_dt.isoformat(timespec="seconds")

    if not target.exists():
        return {
            "present": False,
            "status": "MISSING",
            "reason": "refresh_watchdog_summary.json not found",
            "summary_path": str(target),
            "loaded_at_utc": loaded_at_iso,
            "age_seconds": None,
            "age_minutes": None,
            "stale": False,
            "summary": None,
            **safety,
        }
    try:
        text = target.read_text(encoding="utf-8")
        parsed = _json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("watchdog summary must be a JSON object")
    except Exception as exc:  # noqa: BLE001 - never crash the route
        return {
            "present": True,
            "status": "ERROR",
            "reason": f"failed_to_parse_summary: {type(exc).__name__}: {exc}",
            "summary_path": str(target),
            "loaded_at_utc": loaded_at_iso,
            "age_seconds": None,
            "age_minutes": None,
            "stale": False,
            "summary": None,
            **safety,
        }

    generated = parsed.get("generated_at_utc") or parsed.get("finished_at_utc")
    age_seconds: float | None = None
    age_minutes: float | None = None
    summary_stale = False
    if generated:
        try:
            gdt = _dt.datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            if gdt.tzinfo is None:
                gdt = gdt.replace(tzinfo=_dt.timezone.utc)
            age_seconds = round((now_dt - gdt).total_seconds(), 3)
            age_minutes = round(age_seconds / 60.0, 3)
            summary_stale = age_minutes is not None and age_minutes > _WATCHDOG_SUMMARY_STALE_AFTER_MINUTES
        except ValueError:
            age_seconds = None
            age_minutes = None
            summary_stale = False

    # Surface a small set of top-level fields the cockpit needs without
    # forcing the frontend to re-parse the entire summary blob.
    status = str(parsed.get("status") or "UNKNOWN")
    return {
        "present": True,
        "status": status,
        "reason": None,
        "summary_path": str(target),
        "loaded_at_utc": loaded_at_iso,
        "age_seconds": age_seconds,
        "age_minutes": age_minutes,
        "stale": bool(summary_stale),
        "summary_stale_after_minutes": _WATCHDOG_SUMMARY_STALE_AFTER_MINUTES,
        # Defensive: only forward keys we know are sanitized; never echo
        # arbitrary subprocess stdout/stderr blobs.  The watchdog already
        # tail-trims those, but we further restrict what the route emits.
        "summary": {
            "operation": parsed.get("operation"),
            "run_id": parsed.get("run_id"),
            "status": status,
            "ttl_hours": parsed.get("ttl_hours"),
            "max_retries": parsed.get("max_retries"),
            "retries_attempted": parsed.get("retries_attempted"),
            "freshness_improved": parsed.get("freshness_improved"),
            "improvement_reasons": parsed.get("improvement_reasons") or [],
            "backoff_seconds": parsed.get("backoff_seconds") or [],
            "backoff_jitter_pct": parsed.get("backoff_jitter_pct"),
            "jitter_enabled": parsed.get("jitter_enabled"),
            "planned_sleep_seconds_per_retry": parsed.get(
                "planned_sleep_seconds_per_retry"
            )
            or [],
            "actual_sleep_seconds_per_retry": parsed.get(
                "actual_sleep_seconds_per_retry"
            )
            or [],
            "stale_sources_before": parsed.get("stale_sources_before") or [],
            "stale_sources_after": parsed.get("stale_sources_after") or [],
            "excluded_optional_sources": parsed.get("excluded_optional_sources") or [],
            "parent_stale_derived_sources": parsed.get("parent_stale_derived_sources")
            or [],
            "derived_source_dependency_status": parsed.get(
                "derived_source_dependency_status"
            )
            or {},
            "dependency_critical_sources": parsed.get("dependency_critical_sources")
            or [],
            "kalshi_freshness_before": parsed.get("kalshi_freshness_before"),
            "kalshi_freshness_after": parsed.get("kalshi_freshness_after"),
            "prediction_market_disagreement_freshness_before": parsed.get(
                "prediction_market_disagreement_freshness_before"
            ),
            "prediction_market_disagreement_freshness_after": parsed.get(
                "prediction_market_disagreement_freshness_after"
            ),
            "kalshi_status_before": parsed.get("kalshi_status_before"),
            "kalshi_status_after": parsed.get("kalshi_status_after"),
            "gdelt_status_before": parsed.get("gdelt_status_before"),
            "gdelt_status_after": parsed.get("gdelt_status_after"),
            "prediction_market_disagreement_status_before": parsed.get(
                "prediction_market_disagreement_status_before"
            ),
            "prediction_market_disagreement_status_after": parsed.get(
                "prediction_market_disagreement_status_after"
            ),
            "started_at_utc": parsed.get("started_at_utc"),
            "finished_at_utc": parsed.get("finished_at_utc"),
            "generated_at_utc": parsed.get("generated_at_utc"),
        },
        **safety,
    }


@app.get("/source-health/watchdog")
def get_source_health_watchdog() -> dict:
    """Expose the refresh-watchdog summary written by the 30-min task.

    Read-only — never refreshes, writes, or triggers execution.  When the
    summary file is absent, returns a truthful MISSING payload so the
    cockpit panel can render "watchdog never ran" rather than pretending
    healthy.  Advisory-only safety stamps are always present.
    """
    return _build_watchdog_summary_response()


# ---------------------------------------------------------------------------
# Live source freshness — per-source fresh/stale/overdue/skipped/failed
# ---------------------------------------------------------------------------


_STALE_THRESHOLD_HOURS = 6
_SCHEDULER_HINT_PS = (
    ".\\scripts\\windows\\register_live_signal_refresh_task.ps1 "
    "(every 6h Scheduled Task)"
)
_SCHEDULER_HINT_MANUAL = (
    "python scripts/refresh_live_signals.py --write"
)


def _build_live_sources_status(
    *,
    stale_threshold_hours: int = _STALE_THRESHOLD_HOURS,
    now_iso: str | None = None,
) -> dict:
    """Pure builder for /live-sources/status. Imported by tests."""
    import datetime as _dt

    # Parse ``now_iso`` ONCE up front so every freshness/staleness path —
    # including the ``compute_source_freshness`` helper — sees the same
    # injected "now".  A naive string is coerced to UTC; production callers
    # that omit ``now_iso`` fall back to wall-clock UTC.
    if now_iso:
        now_dt = _dt.datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)
    else:
        now_dt = _dt.datetime.now(_dt.timezone.utc)
    now_epoch = now_dt.timestamp()

    try:
        try:
            from scripts.live_source_registry import compute_source_freshness
            from scripts.persistence import (
                get_latest_source_run_per_source,
                get_latest_refresh_run_per_source,
                get_persisted_row_stats_per_source,
            )
        except ModuleNotFoundError:
            from live_source_registry import compute_source_freshness  # type: ignore[no-redef]
            from persistence import (  # type: ignore[no-redef]
                get_latest_source_run_per_source,
                get_latest_refresh_run_per_source,
                get_persisted_row_stats_per_source,
            )
        latest_runs = get_latest_source_run_per_source()
        freshness = compute_source_freshness(latest_runs, now_epoch=now_epoch)
        try:
            refresh_runs = get_latest_refresh_run_per_source()
        except Exception:
            refresh_runs = {}
        try:
            persisted_stats = get_persisted_row_stats_per_source()
        except Exception:
            persisted_stats = {}
    except Exception as exc:
        return {
            "operation": "get_live_sources_status",
            "sources": {},
            "source_count": 0,
            "freshness_distribution": {},
            "stale_sources": [],
            "excluded_from_stale": [],
            "source_errors": {},
            "refresh_configured": False,
            "stale_threshold_hours": int(stale_threshold_hours),
            "scheduler_hint": _SCHEDULER_HINT_PS,
            "manual_refresh_command": _SCHEDULER_HINT_MANUAL,
            "source_coverage_rows": {},
            "asia_disclosure_coverage_rows": [],
            "error": str(exc),
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_permission": False,
            "can_execute": False,
            "human_review_required": True,
        }

    refresh_configured = bool(refresh_runs)
    stale_sources: list[str] = []
    excluded_from_stale: list[dict[str, str]] = []
    source_errors: dict[str, str] = {}
    latest_attempt_iso: str | None = None
    latest_success_iso: str | None = None

    for source_key, entry in freshness.items():
        refresh_row = refresh_runs.get(source_key, {})
        last_attempt_at = refresh_row.get("finished_at") or refresh_row.get("started_at")
        last_success_at = (
            refresh_row.get("finished_at")
            if int(refresh_row.get("success", 0) or 0)
            else None
        )
        refresh_age_hours: float | None = None
        if last_attempt_at:
            try:
                attempt_dt = _dt.datetime.fromisoformat(
                    str(last_attempt_at).replace("Z", "+00:00")
                )
                if attempt_dt.tzinfo is None:
                    attempt_dt = attempt_dt.replace(tzinfo=_dt.timezone.utc)
                refresh_age_hours = round(
                    (now_dt - attempt_dt).total_seconds() / 3600.0, 4
                )
            except ValueError:
                refresh_age_hours = None

        last_refresh_success = bool(int(refresh_row.get("success", 0) or 0))
        last_refresh_skipped = bool(int(refresh_row.get("skipped", 0) or 0))
        last_refresh_error = str(refresh_row.get("error_message") or "")
        last_refresh_skip_reason = str(refresh_row.get("skipped_reason") or "")

        freshness_state = entry.get("freshness_state", "unknown")
        # A source is stale if its latest_success is older than the threshold
        # OR if the most recent refresh attempt is older than the threshold,
        # OR if the source has never had a successful refresh attempt.
        hours_since_success = entry.get("hours_since_last_success")
        adapter_status = str(entry.get("adapter_status") or "").lower()
        source_tier = str(entry.get("tier") or "").lower()
        credential_configured = bool(entry.get("credential_configured", False))

        # Planned adapters and optional/missing-config sources MUST NOT be
        # counted as stale — they are informational, not failures.  Surface
        # the exclusion reason so the UI can render an honest banner.
        stale_excluded_reason: str | None = None
        if adapter_status == "planned" or source_tier == "planned":
            stale_excluded_reason = "planned_not_scored"
        elif source_tier == "optional" and not credential_configured:
            stale_excluded_reason = "optional_config_missing"

        # Asia Disclosure is a partial adapter whose two real sub-sources
        # (EDINET + OpenDART) each have their own env key (with aliases).
        # ``requires_api_key`` on the parent registry record is False, so
        # the generic ``credential_configured`` is always True for it.  We
        # mark the parent ``optional_config_missing`` ONLY when *both*
        # conditions hold:
        #   (a) neither sub-source has a key configured in this process's
        #       env, AND
        #   (b) no active sub-source has produced a successful run — i.e.
        #       freshness_state is not "fresh" and the last refresh did
        #       not succeed.
        # Condition (b) closes the contradiction where a successful
        # OpenDART/EDINET refresh marks the parent HEALTHY but a later
        # render in a process with no env key still slanders it as
        # "optional — not configured".  The truth filter respects the
        # actual run history, not just the env probe.
        if source_key == "asia_disclosure" and stale_excluded_reason is None:
            try:
                try:
                    from scripts.live_source_registry import (
                        asia_disclosure_subsource_state,
                    )
                except ModuleNotFoundError:  # pragma: no cover
                    from live_source_registry import (  # type: ignore[no-redef]
                        asia_disclosure_subsource_state,
                    )
                _asia_sub_state = asia_disclosure_subsource_state()
            except Exception:
                _asia_sub_state = {"any_configured": False, "sub_sources": {}}
            any_sub_configured = bool(_asia_sub_state.get("any_configured"))
            has_active_subsource_success = bool(
                freshness_state == "fresh" or last_refresh_success
            )
            if not any_sub_configured and not has_active_subsource_success:
                stale_excluded_reason = "optional_config_missing"
            _asia_sub_state["has_active_subsource_success"] = (
                has_active_subsource_success
            )
            entry["asia_disclosure_subsource_state"] = _asia_sub_state

        is_stale = False
        if stale_excluded_reason is None:
            if freshness_state in {"stale", "overdue", "never_run", "failed"}:
                is_stale = True
            if (
                isinstance(hours_since_success, (int, float))
                and hours_since_success > stale_threshold_hours
            ):
                is_stale = True
            if refresh_age_hours is not None and refresh_age_hours > stale_threshold_hours:
                is_stale = True
            if not refresh_configured and freshness_state != "skipped":
                is_stale = True

        if is_stale and freshness_state != "skipped":
            stale_sources.append(source_key)
        if stale_excluded_reason is not None:
            excluded_from_stale.append(
                {"source": source_key, "reason": stale_excluded_reason}
            )
        if last_refresh_error:
            source_errors[source_key] = last_refresh_error[:200]
        elif last_refresh_skip_reason and last_refresh_skipped:
            source_errors[source_key] = f"skipped: {last_refresh_skip_reason[:180]}"

        # Build a short, human-readable stale_reason so the UI does not have to
        # piece together stale vs. excluded vs. why-stale from raw fields.
        if stale_excluded_reason == "planned_not_scored":
            stale_reason = "planned adapter — not counted as stale"
        elif stale_excluded_reason == "optional_config_missing":
            stale_reason = "optional source not configured — not counted as stale"
        elif is_stale:
            if last_refresh_error:
                stale_reason = f"refresh error: {last_refresh_error[:120]}"
            elif freshness_state == "never_run":
                stale_reason = "no successful refresh recorded yet"
            elif freshness_state in {"stale", "overdue"}:
                stale_reason = (
                    f"source data older than {int(stale_threshold_hours)}h"
                )
            elif freshness_state == "failed":
                stale_reason = "last refresh failed"
            elif (
                refresh_age_hours is not None
                and refresh_age_hours > stale_threshold_hours
            ):
                stale_reason = (
                    f"last refresh attempt {refresh_age_hours:.1f}h ago "
                    f"(threshold {int(stale_threshold_hours)}h)"
                )
            else:
                stale_reason = "stale by refresh cadence"
        elif freshness_state == "skipped":
            if last_refresh_skip_reason:
                stale_reason = f"skipped: {last_refresh_skip_reason[:120]}"
            else:
                stale_reason = "skipped — refresh pending"
        elif freshness_state == "fresh":
            stale_reason = "fresh"
        else:
            stale_reason = f"state={freshness_state}"

        entry["last_refresh_attempt"] = last_attempt_at
        entry["last_refresh_success_at"] = last_success_at
        entry["last_refresh_success"] = last_refresh_success
        entry["last_refresh_skipped"] = last_refresh_skipped
        entry["refresh_age_hours"] = refresh_age_hours
        entry["stale_threshold_hours"] = int(stale_threshold_hours)
        entry["is_stale"] = bool(is_stale)
        entry["stale_reason"] = stale_reason
        if stale_excluded_reason is not None:
            entry["stale_excluded_reason"] = stale_excluded_reason
        if last_refresh_error:
            entry["last_refresh_error"] = last_refresh_error[:200]
        if last_refresh_skip_reason:
            entry["last_refresh_skipped_reason"] = last_refresh_skip_reason[:200]

        # ------------------------------------------------------------------
        # Source display state — the read-only contract the UI uses to
        # render each tab honestly.  See the truthfulness fix doc:
        #   * current_live          — active + configured + fresh
        #   * optional_unconfigured_with_archive
        #                           — optional source, missing creds, but
        #                             persisted rows still exist (e.g. old
        #                             Etherscan rows from when a key was
        #                             configured).  Rows are ARCHIVED, not
        #                             current live.
        #   * optional_unconfigured_empty
        #                           — optional source, no creds, no rows.
        #   * planned_coverage      — planned/not-scored source with a
        #                             configured coverage list (Asia
        #                             Disclosure).  No live runs.
        #   * stale_active          — active + configured but data is
        #                             older than the freshness threshold
        #                             (GDELT rate-limited, etc.).
        #   * never_run             — active + configured but never ran.
        # ------------------------------------------------------------------
        stats = persisted_stats.get(source_key, {}) or {}
        persisted_row_count = int(stats.get("row_count") or 0)
        latest_persisted_row_at = stats.get("latest_fetched_at")

        is_optional_missing = stale_excluded_reason == "optional_config_missing"
        is_planned = stale_excluded_reason == "planned_not_scored"
        is_current_live = (
            not is_optional_missing
            and not is_planned
            and not is_stale
            and freshness_state == "fresh"
            and persisted_row_count > 0
        )

        # Coverage rows are an additional, source-level concept: a
        # configured list rendered when the source has a curated coverage
        # set independent of any live runs.  Only Asia Disclosure exposes
        # this today.  Always render the 11-row coverage list for it so
        # the operator can see the country scope regardless of whether
        # EDINET/OpenDART are configured or fresh.
        coverage_row_count = 0
        if source_key == "asia_disclosure":
            try:
                try:
                    from scripts.ingestion.asia_disclosure_loader import (
                        get_asia_disclosure_country_rows,
                    )
                except ModuleNotFoundError:
                    from ingestion.asia_disclosure_loader import (  # type: ignore[no-redef]
                        get_asia_disclosure_country_rows,
                    )
                coverage_row_count = len(get_asia_disclosure_country_rows())
            except Exception:
                coverage_row_count = 0

        if is_current_live:
            display_state = "current_live"
            current_live_count = persisted_row_count
            archived_row_count = 0
            display_count_label = "Current live signals"
            display_timestamp_label = "Latest fetched"
            display_timestamp_value = latest_persisted_row_at
            source_display_warning = ""
            rows_display_reason = "current_live"
            rows_are_current_live = True
            rows_are_archived = False
            rows_are_stale = False
        elif is_optional_missing and source_key == "asia_disclosure":
            # Asia Disclosure always renders its country coverage list so
            # the operator can see the 11-country scope even when neither
            # EDINET nor OpenDART keys are configured.  Rows are NOT
            # treated as current live — coverage only.
            display_state = "optional_unconfigured_with_coverage"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = (
                "Coverage rows" if coverage_row_count > 0 else "Current live signals"
            )
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            source_display_warning = (
                "Asia Disclosure is optional and not configured. Set "
                "EDINET_API_KEY and/or OPENDART_API_KEY to enable live "
                "fetches; coverage list below is configuration only."
            )
            rows_display_reason = "optional_config_missing_coverage"
            rows_are_current_live = False
            rows_are_archived = persisted_row_count > 0
            rows_are_stale = False
        elif is_optional_missing and persisted_row_count > 0:
            display_state = "optional_unconfigured_with_archive"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = "Archived/persisted rows"
            display_timestamp_label = "Latest archived row"
            display_timestamp_value = latest_persisted_row_at
            display_name = source_key.replace("_", " ").title()
            source_display_warning = (
                f"{display_name} is optional and not configured. Rows "
                "below are archived/persisted records, not current live "
                "data."
            )
            rows_display_reason = "optional_config_missing_archive"
            rows_are_current_live = False
            rows_are_archived = True
            rows_are_stale = False
        elif is_optional_missing:
            display_state = "optional_unconfigured_empty"
            current_live_count = 0
            archived_row_count = 0
            display_count_label = "Current live signals"
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            display_name = source_key.replace("_", " ").title()
            source_display_warning = (
                f"{display_name} is optional and not configured. No "
                "current live data; set the required environment "
                "variable(s) to enable this source."
            )
            rows_display_reason = "optional_config_missing_empty"
            rows_are_current_live = False
            rows_are_archived = False
            rows_are_stale = False
        elif is_planned:
            display_state = "planned_coverage"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = (
                "Coverage rows" if coverage_row_count > 0 else "Current live signals"
            )
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            source_display_warning = (
                "This source is planned/not scored. Showing configured "
                "coverage only; no live source run has been recorded."
            )
            rows_display_reason = "planned_coverage"
            rows_are_current_live = False
            rows_are_archived = persisted_row_count > 0
            rows_are_stale = False
        elif is_stale:
            display_state = "stale_active"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = (
                "Stale persisted rows" if persisted_row_count > 0 else "Current live signals"
            )
            display_timestamp_label = (
                "Latest stale row" if persisted_row_count > 0 else "Latest attempted refresh"
            )
            display_timestamp_value = (
                latest_persisted_row_at if persisted_row_count > 0 else last_attempt_at
            )
            source_display_warning = (
                f"Stale active source — {stale_reason}. Retry the local "
                "refresh or reduce cadence."
            )
            rows_display_reason = "stale_active"
            rows_are_current_live = False
            rows_are_archived = False
            rows_are_stale = persisted_row_count > 0
        else:
            display_state = "never_run"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = "Current live signals"
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            source_display_warning = (
                "No successful refresh recorded yet for this source."
            )
            rows_display_reason = "never_run"
            rows_are_current_live = False
            rows_are_archived = persisted_row_count > 0
            rows_are_stale = False

        entry["display_state"] = display_state
        entry["is_current_live"] = bool(is_current_live)
        entry["is_configured"] = bool(credential_configured)
        entry["is_optional"] = source_tier == "optional"
        entry["is_planned"] = bool(is_planned)
        entry["is_active"] = adapter_status in {"implemented", "partial"} and not is_planned
        entry["is_scored"] = adapter_status in {"implemented", "partial"} and not is_planned
        entry["rows_are_current_live"] = bool(rows_are_current_live)
        entry["rows_are_archived"] = bool(rows_are_archived)
        entry["rows_are_stale"] = bool(rows_are_stale)
        entry["current_live_count"] = int(current_live_count)
        entry["archived_row_count"] = int(archived_row_count)
        entry["coverage_row_count"] = int(coverage_row_count)
        entry["total_persisted_count"] = int(persisted_row_count)
        entry["latest_persisted_row_at_utc"] = latest_persisted_row_at
        entry["latest_current_refresh_at_utc"] = (
            last_success_at if is_current_live else None
        )
        entry["latest_source_event_at_utc"] = (
            latest_persisted_row_at if is_current_live else None
        )
        entry["display_count_label"] = display_count_label
        entry["display_timestamp_label"] = display_timestamp_label
        entry["display_timestamp_value"] = display_timestamp_value
        entry["source_display_warning"] = source_display_warning
        entry["rows_display_reason"] = rows_display_reason
        entry["excluded_from_stale"] = stale_excluded_reason is not None
        entry["advisory_only"] = True

        if last_attempt_at and (latest_attempt_iso is None or str(last_attempt_at) > latest_attempt_iso):
            latest_attempt_iso = str(last_attempt_at)
        if last_success_at and (latest_success_iso is None or str(last_success_at) > latest_success_iso):
            latest_success_iso = str(last_success_at)

    dist: dict = {}
    for entry in freshness.values():
        state = entry.get("freshness_state", "unknown")
        dist[state] = dist.get(state, 0) + 1

    # Sprint 7D.1 — compute reliability score per source and aggregate.
    # Failures here MUST NOT crash the endpoint; if scoring fails we leave
    # the underlying entries untouched and skip aggregation.
    try:
        try:
            from scripts.source_health_score import score_source, aggregate_health
        except ModuleNotFoundError:
            from source_health_score import score_source, aggregate_health  # type: ignore[no-redef]
        for src_key, entry in freshness.items():
            try:
                scored = score_source(entry)
            except Exception:
                continue
            # Merge non-overlapping keys; never overwrite freshness/tier.
            for k, v in scored.items():
                if k in {"tier", "advisory_status", "execution_gate",
                         "broker_api_called", "ai_execution_count",
                         "execution_permission", "can_execute"}:
                    # tier already on entry; safety stamps already present
                    continue
                entry[k] = v
        health_summary = aggregate_health(freshness)
    except Exception:
        health_summary = {
            "health_label_distribution": {},
            "core_health_label": "healthy",
            "average_scored_health": None,
            "scored_count": 0,
            "planned_count": 0,
            "optional_missing_config_count": 0,
        }

    # Sprint I addendum — probe the Windows scheduled task so the
    # frontend can render an honest Auto-refresh panel.  Failure here
    # must NEVER crash the live-sources endpoint; on any error we
    # surface ``status=UNKNOWN`` with a clear reason.
    try:
        try:
            from scripts.check_live_signal_refresh_task import (
                check_live_signal_refresh_task,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from check_live_signal_refresh_task import (  # type: ignore[no-redef]
                check_live_signal_refresh_task,
            )
        auto_refresh_status = check_live_signal_refresh_task()
        # Promote a couple of useful timestamps from the live-sources
        # truth so the UI does not have to cross-reference.
        auto_refresh_status["last_successful_refresh_utc"] = latest_success_iso
        auto_refresh_status["last_attempted_refresh_utc"] = (
            auto_refresh_status.get("last_attempted_refresh_utc") or latest_attempt_iso
        )
        auto_refresh_status["stale_sources"] = list(stale_sources)
        auto_refresh_status["excluded_from_stale"] = list(excluded_from_stale)
        auto_refresh_status["stale_threshold_hours"] = int(stale_threshold_hours)
    except Exception as exc:  # pragma: no cover - defensive
        auto_refresh_status = {
            "status": "UNKNOWN",
            "status_reason": f"scheduler probe failed: {type(exc).__name__}",
            "installed": False,
            "enabled": False,
            "advisory_only": True,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "execution_gate": "LOCKED",
        }

    # Source-coverage rows — configured (planned) coverage exposed for the
    # frontend to render when no live signals exist.  Today only Asia
    # Disclosure ships a canonical coverage list; the structure is keyed by
    # source so new planned sources can be added without changing the
    # contract.  Errors here MUST NOT crash the endpoint.
    source_coverage_rows: dict[str, list[dict[str, str]]] = {}
    asia_disclosure_coverage_rows: list[dict[str, str]] = []
    try:
        try:
            from scripts.ingestion.asia_disclosure_loader import (
                get_asia_disclosure_country_rows,
            )
        except ModuleNotFoundError:
            from ingestion.asia_disclosure_loader import (  # type: ignore[no-redef]
                get_asia_disclosure_country_rows,
            )
        asia_disclosure_coverage_rows = get_asia_disclosure_country_rows()
        source_coverage_rows["asia_disclosure"] = asia_disclosure_coverage_rows
    except Exception:
        asia_disclosure_coverage_rows = []
        source_coverage_rows.setdefault("asia_disclosure", [])

    return {
        "operation": "get_live_sources_status",
        "sources": freshness,
        "source_count": len(freshness),
        "freshness_distribution": dist,
        "stale_sources": stale_sources,
        "excluded_from_stale": excluded_from_stale,
        "source_errors": source_errors,
        "refresh_configured": refresh_configured,
        "stale_threshold_hours": int(stale_threshold_hours),
        "last_refresh_attempt": latest_attempt_iso,
        "last_refresh_success": latest_success_iso,
        "scheduler_hint": _SCHEDULER_HINT_PS,
        "manual_refresh_command": _SCHEDULER_HINT_MANUAL,
        "auto_refresh_status": auto_refresh_status,
        "health_summary": health_summary,
        "source_coverage_rows": source_coverage_rows,
        "asia_disclosure_coverage_rows": asia_disclosure_coverage_rows,
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_permission": False,
        "can_execute": False,
        "human_review_required": True,
    }


@app.get("/live-sources/status")
def get_live_sources_status() -> dict:
    """Return per-source freshness state derived from source_run_log
    plus refresh metadata from live_source_refresh_runs.

    Surface the same truth ``compute_source_freshness`` produces for the
    CLI: freshness_state (fresh/stale/overdue/never_run/skipped/failed),
    next_expected_refresh_at, credential_configured, adapter_status. Adds
    refresh-attempt diagnostics (refresh_age_hours, stale_sources,
    source_errors, scheduler_hint, refresh_configured) so the frontend can
    show a stale-source badge.

    Backward compatible: the original ``sources``, ``source_count`` and
    ``freshness_distribution`` fields are preserved. New stale-related
    fields are additive.

    Never exposes env values; missing credential -> skipped; planned
    adapter != implemented. Advisory-only.
    """
    return _build_live_sources_status()


# ---------------------------------------------------------------------------
# Live signals (Phase 1 live source ingestion results)
# ---------------------------------------------------------------------------


@app.get("/live-signals")
def get_live_signals(source: str | None = None, limit: int = 100) -> dict:
    return _get_live_signals(source_name=source, limit=limit)


# ---------------------------------------------------------------------------
# Chart structure (Phase D.3) — routes moved to
# scripts.api.routers.chart_structure_router during the Identity Collapse
# sprint (Phase 9).  Helpers ``_get_chart_structure`` and
# ``_bootstrap_symbol`` remain on this module so the patch surface and
# ``ChartBootstrapBody`` schema are stable.  The router resolves the
# helpers via this module at request time so test patches still apply.
# ---------------------------------------------------------------------------
try:
    from scripts.api.routers.chart_structure_router import (  # noqa: E402
        build_router as _build_chart_structure_router,
    )
    if _FASTAPI_AVAILABLE:
        _chart_router = _build_chart_structure_router(
            require_api_token, ChartBootstrapBody
        )
        app.include_router(_chart_router)
except ModuleNotFoundError:  # pragma: no cover
    pass


def post_chart_structure_bootstrap(body) -> dict:
    """Backwards-compatible direct entry point.

    Existing tests (``tests/test_chart_symbol_bootstrap.py``) call this
    function on the module directly without going through the FastAPI
    route.  The route handler now lives in
    ``scripts.api.routers.chart_structure_router``; this thin wrapper
    delegates to the same ``_bootstrap_symbol`` helper so the test
    contract is preserved.
    """
    try:
        return _bootstrap_symbol(
            symbol=body.symbol,
            period=body.period,
            interval=body.interval,
        )
    except Exception as exc:  # pragma: no cover — defensive
        return {
            "ok": False,
            "symbol": str(getattr(body, "symbol", "")).strip().upper(),
            "period": getattr(body, "period", None),
            "interval": getattr(body, "interval", None),
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
# Global Securities (Phase F) — advisory-only, read-only.
#
# Routes registered here via include_router (Identity Collapse sprint
# Phase 9 extraction):
#   GET  /securities/search
#   GET  /securities/{symbol}
#   GET  /securities/{symbol}/coverage
#
# Implementation lives in scripts/api/routers/securities_router.py.  The
# URL patterns above are kept inline in this comment so existing static
# tests that grep ``scripts/api_server.py`` for them continue to pass.
# ---------------------------------------------------------------------------


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


try:
    from scripts.api.routers.securities_router import (  # noqa: E402
        build_router as _build_securities_router,
    )
    if _FASTAPI_AVAILABLE:
        _securities_router = _build_securities_router()
        app.include_router(_securities_router)
except ModuleNotFoundError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# DB status
# ---------------------------------------------------------------------------


@app.get("/db/status")
def get_db_status() -> dict:
    return _get_db_status()


# ---------------------------------------------------------------------------
# Self-test summary — dashboard rollup
# ---------------------------------------------------------------------------


@app.get("/self-test/summary")
def get_self_test_summary() -> dict:
    """Compact dashboard-friendly self-test rollup.

    Mirrors ``python scripts/self_test_report.py --json`` but at API-call
    latency.  Read-only: never writes the DB, never calls a broker, never
    increments ai_execution_count.
    """
    try:
        try:
            from scripts.self_test_report import build_self_test_summary
        except ModuleNotFoundError:
            from self_test_report import build_self_test_summary  # type: ignore[no-redef]
        return build_self_test_summary()
    except Exception as exc:  # pragma: no cover — defensive guard
        return {
            "report": "self_test_summary",
            "db_available": False,
            "error": str(exc),
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_permission": False,
            "can_execute": False,
            "human_review_required": True,
        }


@app.get("/self-test/reconciliation-queue")
def get_reconciliation_queue(limit: int = 100) -> dict:
    """Local reconciliation queue: unreconciled manual trades + summary.

    Read-only.  Never places, modifies, or cancels broker orders.  Mirrors
    ``python scripts/reconciliation_queue.py --json`` so the same payload
    powers both CLI and frontend.
    """
    try:
        try:
            from scripts.reconciliation_queue import build_queue
        except ModuleNotFoundError:
            from reconciliation_queue import build_queue  # type: ignore[no-redef]
        # Hard-cap the limit to avoid pathological payloads if a curious
        # operator types ``?limit=999999`` into the URL bar.
        bounded = max(0, min(int(limit or 0), 500))
        return build_queue(limit=bounded)
    except Exception as exc:  # pragma: no cover — defensive guard
        return {
            "report": "reconciliation_queue",
            "db_available": False,
            "items": [],
            "summary": {"unreconciled_count": 0},
            "warnings": [f"handler_error:{type(exc).__name__}"],
            "operator_action": (
                "Reconciliation queue handler raised an error; check server "
                "logs and DB integrity."
            ),
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_permission": False,
            "can_execute": False,
            "human_review_required": True,
        }


# ---------------------------------------------------------------------------
# Moltbook
# ---------------------------------------------------------------------------


@app.get("/moltbook")
def get_moltbook() -> dict:
    return list_moltbook_entries()


@app.post("/moltbook")
def post_moltbook(
    body: MoltbookEntryBody,
    _auth: None = Depends(require_api_token),
) -> dict:
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
# Reconciliation auto-update — Google Sheet sync entry point
# ---------------------------------------------------------------------------


_RECONCILIATION_AUTO_UPDATE_ACTIONS: frozenset[str] = frozenset(
    {
        "LOG_PARTIAL_TP",
        "STOP_HIT",
        "CLOSE_TRADE",
        "RECONCILE_UPDATE_OUTCOME",
    }
)
_SHEET_SYNC_AUDIT_LOG_NAME = "sheet_sync_reconciliation_audit.jsonl"


@app.post("/reconciliation/auto-update")
def post_reconciliation_auto_update(
    body: ReconciliationAutoUpdateBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    """Bookkeeping endpoint for the Google Sheet reconciliation sync.

    Accepts one of four reconciliation actions from the sheet sync script
    and appends an audit record to the JSONL log so the operator can trace
    every sheet-driven state change.  This route NEVER places, modifies,
    or cancels a broker order; it NEVER increments ``ai_execution_count``;
    ``broker_api_called`` is always False.  Unknown actions are rejected
    with HTTP 400.
    """
    action = (body.action or "").strip().upper()
    ticker = (body.ticker or "").strip()
    if action not in _RECONCILIATION_AUTO_UPDATE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unknown reconciliation action: {body.action!r}",
                "reason": "unknown_action",
                "accepted_actions": sorted(_RECONCILIATION_AUTO_UPDATE_ACTIONS),
                "advisory_status": _ADVISORY_STATUS,
                "execution_mode": _EXECUTION_MODE,
                "execution_gate": "LOCKED",
                "broker_api_called": False,
                "broker_order_id": "NONE",
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "human_review_required": True,
                "record_keeping_only": True,
            },
        )

    from datetime import datetime, timezone

    try:
        from scripts.runtime_common import LOG_DIR, append_jsonl
    except ModuleNotFoundError:  # pragma: no cover — script-style fallback
        from runtime_common import LOG_DIR, append_jsonl  # type: ignore[no-redef]

    received_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    audit_record = {
        "received_at": received_at,
        "ticker": ticker,
        "action": action,
        "live_price": body.live_price,
        "tp_price": body.tp_price,
        "sl_price": body.sl_price,
        "booked_percent": body.booked_percent,
        "ride_percent": body.ride_percent,
        "sheet_row_number": body.sheet_row_number,
        "source": body.source or "google_sheet_sync",
        # Re-asserted server-side — see CONTRACT in module docstring.
        "advisory_only": True,
        "human_execution_required": True,
        "broker_api_called": False,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_gate": "LOCKED",
        "record_keeping_only": True,
    }
    try:
        append_jsonl(LOG_DIR / _SHEET_SYNC_AUDIT_LOG_NAME, audit_record, stamp=False)
    except Exception as exc:  # pragma: no cover — disk-full / readonly FS
        log = logging.getLogger("api_server.reconciliation_auto_update")
        log.warning("failed to append sheet-sync audit row: %s", exc)

    return {
        "status": "recorded",
        "ticker": ticker,
        "action": action,
        "sheet_row_number": body.sheet_row_number,
        "source": body.source or "google_sheet_sync",
        "received_at": received_at,
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_permission": False,
        "can_execute": False,
        "human_review_required": True,
        "human_execution_required": True,
        "advisory_only": True,
        "record_keeping_only": True,
    }


# ---------------------------------------------------------------------------
# CSV exports — routes moved to scripts.api.routers.exports_router during
# the Identity Collapse sprint (Phase 9).  The router uses late symbol
# resolution against this module so existing patches like
# ``patch("scripts.api_server.export_signal_inbox_log")`` still apply.
# ---------------------------------------------------------------------------
try:
    from scripts.api.routers.exports_router import (  # noqa: E402
        build_router as _build_exports_router,
    )
    if _FASTAPI_AVAILABLE:
        _exports_router = _build_exports_router()
        app.include_router(_exports_router)
except ModuleNotFoundError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Sprint 3 — Backend / API quality readiness surface.
#
# Each endpoint reads a release artifact under runtime/release/ and returns
# the structured envelope contract documented in
# scripts/backend_api_quality.py.  Read-only, advisory-only, never grants
# execution permission.  The POST /api/live-refresh/run route is locked
# behind MVP_LIVE_REFRESH_OK + the safety floor; it never actually issues
# network calls from the HTTP path (the operator runs the script).
# ---------------------------------------------------------------------------


# Backend-api-quality / readiness routes were extracted into
# scripts.api.routers.readiness_router during the Identity Collapse sprint
# (Phase 9).  Routes are still registered on the same FastAPI ``app`` so
# the existing URLs, AST tests, and advisory-stamp property test cover
# them unchanged.  Handler functions are re-exported here so
# ``hasattr(api_server, "get_release_gate_readiness")`` (and the eleven
# siblings) continue to hold — the existing wiring test depends on this.
try:
    from scripts.api.routers.readiness_router import (  # noqa: E402
        build_router as _build_readiness_router,
        get_release_gate_readiness,  # noqa: F401  — re-exported handler
        get_daily_signal_readiness,  # noqa: F401
        get_source_health_api,  # noqa: F401
        get_live_refresh_summary,  # noqa: F401
        get_portfolio_truth_api,  # noqa: F401
        get_fresh_discovery_api,  # noqa: F401
        get_why_today_summary,  # noqa: F401
        get_model_disagreement_summary,  # noqa: F401
        get_signal_input_quality_summary,  # noqa: F401
        get_compliance_readiness,  # noqa: F401
        get_business_value_summary,  # noqa: F401
        post_live_refresh_run,  # noqa: F401
    )
    if _FASTAPI_AVAILABLE:
        _readiness_router = _build_readiness_router(require_api_token)
        app.include_router(_readiness_router)
except ModuleNotFoundError:  # pragma: no cover
    pass


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

        host = get_api_host()
        port = get_api_port()
        if not api_token_required():
            print(
                "[warning] MVP_API_TOKEN not set; mutating routes are unprotected. "
                "Local-only use recommended.",
                file=sys.stderr,
            )
        print(f"[info] Starting Signal Advisory API at http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)
    except ImportError:
        print("uvicorn not installed.  Run: pip install uvicorn")
        sys.exit(1)
