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
        """
        payload: dict = {
            "error": str(exc.detail) if exc.detail else "request failed",
            "status_code": exc.status_code,
            "advisory_status": _ADVISORY_STATUS,
            "execution_mode": _EXECUTION_MODE,
            "execution_gate": "LOCKED",
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "broker_api_called": False,
            "broker_order_id": "NONE",
            "human_review_required": True,
        }
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


@app.post("/manual-trades")
def post_manual_trade(
    body: ManualTradeBody,
    _auth: None = Depends(require_api_token),
) -> dict:
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
    )


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
        raise HTTPException(status_code=404, detail=result.get("error", "not found"))
    if isinstance(result, dict) and result.get("status") == "refused":
        raise HTTPException(status_code=400, detail=result.get("error", "refused"))
    return result


# ---------------------------------------------------------------------------
# Manual trades — list all
# ---------------------------------------------------------------------------


@app.get("/manual-trades")
def get_manual_trades() -> dict:
    return list_manual_trades()


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
                    rows = conn.execute(
                        "SELECT COALESCE(NULLIF(TRIM(trade_mode),''),'UNKNOWN') AS tm,"
                        " COUNT(*) AS n FROM manual_trades GROUP BY tm"
                    ).fetchall()
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

    try:
        try:
            from scripts.live_source_registry import compute_source_freshness
            from scripts.persistence import (
                get_latest_source_run_per_source,
                get_latest_refresh_run_per_source,
            )
        except ModuleNotFoundError:
            from live_source_registry import compute_source_freshness  # type: ignore[no-redef]
            from persistence import (  # type: ignore[no-redef]
                get_latest_source_run_per_source,
                get_latest_refresh_run_per_source,
            )
        latest_runs = get_latest_source_run_per_source()
        freshness = compute_source_freshness(latest_runs)
        try:
            refresh_runs = get_latest_refresh_run_per_source()
        except Exception:
            refresh_runs = {}
    except Exception as exc:
        return {
            "operation": "get_live_sources_status",
            "sources": {},
            "source_count": 0,
            "freshness_distribution": {},
            "stale_sources": [],
            "source_errors": {},
            "refresh_configured": False,
            "stale_threshold_hours": int(stale_threshold_hours),
            "scheduler_hint": _SCHEDULER_HINT_PS,
            "manual_refresh_command": _SCHEDULER_HINT_MANUAL,
            "error": str(exc),
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_permission": False,
            "can_execute": False,
            "human_review_required": True,
        }

    now_dt = (
        _dt.datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        if now_iso
        else _dt.datetime.now(_dt.timezone.utc)
    )
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)

    refresh_configured = bool(refresh_runs)
    stale_sources: list[str] = []
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
        is_stale = False
        if freshness_state in {"stale", "overdue", "never_run", "failed"}:
            is_stale = True
        if isinstance(hours_since_success, (int, float)) and hours_since_success > stale_threshold_hours:
            is_stale = True
        if refresh_age_hours is not None and refresh_age_hours > stale_threshold_hours:
            is_stale = True
        if not refresh_configured and freshness_state != "skipped":
            is_stale = True

        if is_stale and freshness_state != "skipped":
            stale_sources.append(source_key)
        if last_refresh_error:
            source_errors[source_key] = last_refresh_error[:200]
        elif last_refresh_skip_reason and last_refresh_skipped:
            source_errors[source_key] = f"skipped: {last_refresh_skip_reason[:180]}"

        entry["last_refresh_attempt"] = last_attempt_at
        entry["last_refresh_success_at"] = last_success_at
        entry["last_refresh_success"] = last_refresh_success
        entry["last_refresh_skipped"] = last_refresh_skipped
        entry["refresh_age_hours"] = refresh_age_hours
        entry["stale_threshold_hours"] = int(stale_threshold_hours)
        entry["is_stale"] = bool(is_stale)
        if last_refresh_error:
            entry["last_refresh_error"] = last_refresh_error[:200]
        if last_refresh_skip_reason:
            entry["last_refresh_skipped_reason"] = last_refresh_skip_reason[:200]

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

    return {
        "operation": "get_live_sources_status",
        "sources": freshness,
        "source_count": len(freshness),
        "freshness_distribution": dist,
        "stale_sources": stale_sources,
        "source_errors": source_errors,
        "refresh_configured": refresh_configured,
        "stale_threshold_hours": int(stale_threshold_hours),
        "last_refresh_attempt": latest_attempt_iso,
        "last_refresh_success": latest_success_iso,
        "scheduler_hint": _SCHEDULER_HINT_PS,
        "manual_refresh_command": _SCHEDULER_HINT_MANUAL,
        "health_summary": health_summary,
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
def post_chart_structure_bootstrap(
    body: ChartBootstrapBody,
    _auth: None = Depends(require_api_token),
) -> dict:
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
