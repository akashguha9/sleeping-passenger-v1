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
    from pydantic import BaseModel, Field
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

    def Field(default=None, **_kwargs):  # type: ignore[no-redef]
        return default

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
        bootstrap_symbol_denylist,
        bootstrap_symbol_quota,
        clamp_limit,
        extract_client_ip,
        get_environment_tag,
        get_max_request_bytes,
        get_trusted_proxies,
        is_loopback_bind,
        preflight_auth_or_die,
        rate_limit_expensive_max_requests,
        rate_limit_enabled,
        rate_limit_max_requests,
        rate_limit_mutation_max_requests,
        rate_limit_window_seconds,
        safe_db_display_path,
        security_headers,
        unauth_override_active,
    )
except ModuleNotFoundError:  # pragma: no cover
    from runtime_config import (  # type: ignore[no-redef]
        api_token_required,
        db_available,
        get_allowed_origins,
        get_api_host,
        get_api_port,
        get_api_token,
        bootstrap_symbol_denylist,
        bootstrap_symbol_quota,
        clamp_limit,
        extract_client_ip,
        get_environment_tag,
        get_max_request_bytes,
        get_trusted_proxies,
        is_loopback_bind,
        preflight_auth_or_die,
        rate_limit_expensive_max_requests,
        rate_limit_enabled,
        rate_limit_max_requests,
        rate_limit_mutation_max_requests,
        rate_limit_window_seconds,
        safe_db_display_path,
        security_headers,
        unauth_override_active,
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
            "error": _safe_exc_summary(exc),
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
            "error": _safe_exc_summary(exc),
            "advisory_status": _ADVISORY_STATUS,
            "ai_execution_count": _AI_EXECUTION_COUNT,
        }


# R2 fix: count silent write failures so /health/full can flag a
# degraded server.  Module-global; reset by tests via _reset_health_counters.
_WRITE_FAILURE_COUNT = 0


def _reset_health_counters() -> None:
    """Test helper: zero out the R2 degraded-state counter."""
    global _WRITE_FAILURE_COUNT
    _WRITE_FAILURE_COUNT = 0


def _log_source_health(stats: dict, bull_state: str) -> None:
    global _WRITE_FAILURE_COUNT
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
    except Exception as exc:
        # R2: bump the counter and surface a clear ERROR log so the
        # operator can spot a degraded write path on /health/full.
        _WRITE_FAILURE_COUNT += 1
        _logger.error(
            "db write failure in _log_source_health: %s (cumulative=%d)",
            type(exc).__name__,
            _WRITE_FAILURE_COUNT,
        )

# Advisory response-contract constants + pure sanitizer extracted to
# scripts/api_response_contract.py (god-module reduction). Re-imported under
# their original private names so all route references stay byte-identical.
try:
    from scripts.api_response_contract import (
        CSV_MEDIA_TYPE as _CSV_MEDIA_TYPE,
        ADVISORY_STATUS as _ADVISORY_STATUS,
        EXECUTION_MODE as _EXECUTION_MODE,
        AI_EXECUTION_COUNT as _AI_EXECUTION_COUNT,
        API_VERSION as _VERSION,
        safe_exc_summary as _safe_exc_summary,
    )
except ModuleNotFoundError:  # pragma: no cover - script-path fallback
    from api_response_contract import (  # type: ignore[no-redef]
        CSV_MEDIA_TYPE as _CSV_MEDIA_TYPE,
        ADVISORY_STATUS as _ADVISORY_STATUS,
        EXECUTION_MODE as _EXECUTION_MODE,
        AI_EXECUTION_COUNT as _AI_EXECUTION_COUNT,
        API_VERSION as _VERSION,
        safe_exc_summary as _safe_exc_summary,
    )


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

    # I3 fix: which paths are "expensive" and get the stricter bucket.
    # Match prefixes so any added CSV/diagnostic route inherits the policy.
    _EXPENSIVE_PREFIXES = (
        "/exports/",
        "/diagnostics/",
        "/learning-completeness",
        "/self-test/",
        # Simulation Intelligence Layer runs the six-lens Monte-Carlo council;
        # give it the stricter rate-limit bucket so a burst can't hog CPU.
        "/api/simulation/",
    )

    def _scope_for(path: str, is_mutating: bool) -> str:
        if is_mutating:
            return "write"
        if any(path.startswith(p) for p in _EXPENSIVE_PREFIXES):
            return "expensive"
        return "read"

    def _get_rate_limiter(scope: str) -> "RateLimiter":
        """Return (and cache) a limiter for the given scope.

        Three scopes:
          * ``read`` — standard GET endpoints
          * ``write`` — mutating POST/PUT/PATCH/DELETE endpoints
          * ``expensive`` — heavy read endpoints (I3): exports,
            diagnostics, learning-completeness, self-test
        """
        if scope == "write":
            limit = rate_limit_mutation_max_requests()
        elif scope == "expensive":
            limit = rate_limit_expensive_max_requests()
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
        # S3 fix: resolve real client IP via the trusted-proxy allowlist so
        # the limiter cannot be bypassed (or starved) by everyone-looks-the-
        # same when uvicorn sits behind nginx/traefik.
        direct_host = (request.client.host if request.client else "") or ""
        forwarded_for = request.headers.get("x-forwarded-for") or ""
        client_host = extract_client_ip(direct_host, forwarded_for) or "unknown"

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
            scope = _scope_for(request.url.path, is_mutating)
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
        # S1: refuse to start on non-loopback bind without a token unless
        # MVP_ALLOW_UNAUTH=1 is set explicitly.  Raises StartupSecurityError.
        preflight_auth_or_die()
        if not api_token_required():
            if is_loopback_bind():
                _logger.warning(
                    "MVP_API_TOKEN not set; mutating routes are unprotected. "
                    "Loopback bind only (API_HOST=%s).",
                    get_api_host(),
                )
            else:
                _logger.warning(
                    "MVP_API_TOKEN not set AND MVP_ALLOW_UNAUTH=1 explicitly "
                    "overrides S1 preflight. NON-LOOPBACK bind is exposed."
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


    def _check_bearer_token(authorization: str | None) -> None:
        """Constant-time bearer-token verification.

        S2 fix: use ``hmac.compare_digest`` instead of ``!=`` so the
        comparison does not leak length/equality timing.
        """
        import hmac

        expected = get_api_token()
        if not expected:
            return None
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        provided = authorization.split(" ", 1)[1].strip()
        if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
            raise HTTPException(status_code=401, detail="invalid bearer token")
        return None

    def require_api_token(authorization: str | None = Header(default=None)) -> None:
        """Enforce Bearer token on mutating routes when ``MVP_API_TOKEN`` is set."""
        return _check_bearer_token(authorization)

    def require_api_token_for_reads(
        request: "Request",
        authorization: str | None = Header(default=None),
    ) -> None:
        """S5 fix: gate read endpoints that return operator-authored journal data.

        When ``MVP_API_TOKEN`` is unset and the operator has not explicitly
        bypassed S1 via ``MVP_ALLOW_UNAUTH=1``, the server refuses to start
        on a non-loopback bind.  On a loopback bind without a token, reads
        stay open (preserves single-operator localhost UX).

        When a token IS set, every read endpoint protected by this
        dependency requires ``Authorization: Bearer <token>``.
        """
        expected = get_api_token()
        if expected:
            return _check_bearer_token(authorization)
        # No token configured: only allowed for loopback binds (preflight
        # already refused non-loopback boot without override).  We still
        # log to /health that the override is active.
        if not is_loopback_bind():
            if not unauth_override_active():
                # Defense in depth — preflight should have caught this at boot.
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "server_misconfigured",
                        "reason": "non_loopback_bind_without_token",
                        "advisory_status": _ADVISORY_STATUS,
                        "execution_gate": "LOCKED",
                        "broker_api_called": False,
                        "ai_execution_count": _AI_EXECUTION_COUNT,
                    },
                )
        return None
else:
    app = _NoopApp()  # type: ignore[assignment]

    def require_api_token(authorization: str | None = None) -> None:  # type: ignore[no-redef]
        """No-op fallback when FastAPI is unavailable (test-only path)."""
        return None

    def require_api_token_for_reads(  # type: ignore[no-redef]
        request: object = None, authorization: str | None = None
    ) -> None:
        """No-op fallback when FastAPI is unavailable (test-only path)."""
        return None


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class ReflectionBody(BaseModel):
    # L2: bound free-text fields to prevent unbounded growth + CSV bloat.
    reflection_text: str = Field(..., min_length=1, max_length=4000)
    author: str = Field("human", max_length=120)
    conviction_level: str = Field("MODERATE", max_length=40)


class AISummaryBody(BaseModel):
    summary_text: str
    model_label: str = "AI_ADVISORY"


class DecisionBody(BaseModel):
    status: str


# L1 fix: money validators wired into the pydantic models below.  Imported
# lazily because pydantic-v1 fallback in the FastAPI-absent path can't see
# field_validator.  The validators raise MoneyError → pydantic surfaces it
# as a 422 with a clean field path.
from decimal import Decimal as _Decimal  # noqa: E402
from typing import Any  # noqa: E402

try:
    from scripts.money import (
        MoneyError as _MoneyError,
        parse_money as _parse_money,
        parse_money_opt as _parse_money_opt,
        money_to_legacy_float as _money_to_float,
    )
except ModuleNotFoundError:  # pragma: no cover
    from money import (  # type: ignore[no-redef]
        MoneyError as _MoneyError,
        parse_money as _parse_money,
        parse_money_opt as _parse_money_opt,
        money_to_legacy_float as _money_to_float,
    )

if _FASTAPI_AVAILABLE:
    from pydantic import field_validator as _field_validator
else:  # pragma: no cover

    def _field_validator(*_args, **_kwargs):  # type: ignore[no-redef]
        def _wrap(fn):
            return fn

        return _wrap


class ManualTradeBody(BaseModel):
    """L1 fix: money fields accept Decimal | int | float | str on the wire.

    The validator (see ``_money_validator`` below) coerces every incoming
    money value to a quantised Decimal at the boundary.  Internal callers
    that still take ``float`` get the value via ``money_to_legacy_float``
    — every such call is a marked TODO for the schema migration that
    will swap SQLite ``REAL`` columns for TEXT-stored Decimals.
    """
    event_id: str
    ticker: str
    side: str
    quantity: Any  # validated to Decimal below
    price: Any  # validated to Decimal below
    thesis: str = Field(..., min_length=1, max_length=4000)
    notes: str = Field("", max_length=4000)
    # S9 fix: ``logged_by`` is now SERVER-STAMPED, not client-controlled.
    # We accept the field on the wire for backwards compatibility but the
    # POST handler overwrites it with a stable server-side identity before
    # persistence.  Forging operator attribution is no longer possible.
    logged_by: str = Field("human", max_length=120)
    leverage: Any = 1.0  # validated to Decimal below
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
    # P0 leverage governance — optional jurisdiction hints so the server can
    # resolve the leverage ceiling (India 4.0x / rest-of-world 1.0x / unknown
    # fails closed to 1.0x).  Legacy clients omit these; the server then
    # resolves jurisdiction from the ticker suffix.  Supplying them NEVER
    # grants execution permission and never reaches a broker.
    exchange: str = Field("", max_length=32)
    country: str = Field("", max_length=32)
    jurisdiction: str = Field("", max_length=32)

    @_field_validator("quantity", "price", "leverage", mode="before")
    @classmethod
    def _coerce_required_money(cls, v: Any) -> _Decimal:
        try:
            return _parse_money(v)
        except _MoneyError as exc:
            raise ValueError(str(exc)) from exc


class ReconcileBody(BaseModel):
    actual_fill_price: Any  # L1: Decimal
    actual_quantity: Any  # L1: Decimal
    outcome_notes: str = ""
    pnl_estimate: Any = "0"  # L1: Decimal
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
    runner_quantity: Any = None  # L1: Decimal
    runner_status: str = ""
    partial_take_profit_price: Any = None  # L1: Decimal
    partial_take_profit_quantity: Any = None  # L1: Decimal
    take_profit_plan: str = ""
    stop_loss_price: Any = None  # L1: Decimal
    stop_loss_hit: bool = False
    exit_reason: str = ""
    invalidation_level: str = ""
    lesson_takeaway: str = ""
    notes: str = ""

    @_field_validator("actual_fill_price", "actual_quantity", mode="before")
    @classmethod
    def _coerce_required_money(cls, v: Any) -> _Decimal:
        try:
            return _parse_money(v)
        except _MoneyError as exc:
            raise ValueError(str(exc)) from exc

    @_field_validator("pnl_estimate", mode="before")
    @classmethod
    def _coerce_pnl(cls, v: Any) -> _Decimal:
        # PnL can be negative; coerce, default 0.
        try:
            return _parse_money(v if v is not None else "0")
        except _MoneyError as exc:
            raise ValueError(str(exc)) from exc

    @_field_validator(
        "runner_quantity",
        "partial_take_profit_price",
        "partial_take_profit_quantity",
        "stop_loss_price",
        mode="before",
    )
    @classmethod
    def _coerce_optional_money(cls, v: Any) -> _Decimal | None:
        try:
            return _parse_money_opt(v)
        except _MoneyError as exc:
            raise ValueError(str(exc)) from exc


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
    # L2: every free-text field is length-capped.
    event_id: str = Field(..., max_length=200)
    ticker: str = Field(..., max_length=40)
    original_signal_thesis: str = Field(..., min_length=1, max_length=4000)
    ai_interpretation: str = Field(..., max_length=4000)
    user_reflection: str = Field(..., max_length=4000)
    final_human_decision: str = Field(..., max_length=4000)
    manual_trade_log_id: str = Field("", max_length=200)
    outcome: str = Field("", max_length=4000)
    mistake_type: str = Field(..., min_length=1, max_length=200)
    lesson_learned: str = Field(..., max_length=4000)
    bias_detected: str = Field("", max_length=200)
    recalibration_note: str = Field("", max_length=4000)
    future_rule_update: str = Field("", max_length=4000)


class SimulationRunBody(BaseModel):
    # Simulation Intelligence Layer run request. Advisory-only, record-only.
    # Bounded: caps mirror scripts/simulation_intelligence/api_surface.py.
    ticker: str = Field(..., min_length=1, max_length=32)
    market: str = Field("UNKNOWN", max_length=8)
    seed: int = Field(0, ge=0, le=2_000_000_000)
    max_runs: int = Field(256, ge=8, le=20_000)
    parent_signal_id: str = Field("", max_length=64)
    observation: dict = Field(default_factory=dict)
    scenarios: list[str] = Field(default_factory=list, max_length=64)
    requested_lenses: list[str] = Field(default_factory=list, max_length=6)


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
    """D2 fix: minimal unauthenticated liveness probe.

    Discloses ONLY benign operational fields: status, version, advisory
    invariants, a boolean ``db_available`` (does the journal exist?), and
    a ``generated_at`` timestamp.

    Deliberately withholds SENSITIVE security posture — environment tag,
    db_path, api_token_required, allowed_origins_count, rate_limit_enabled,
    max_request_bytes, security_headers_enabled.  Those live on the
    token-gated /health/full (D2: don't leak posture to unauth probes).
    """
    from datetime import datetime, timezone

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
        # Benign operational fields — safe for an unauth uptime probe.
        "db_available": db_available(),
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
    }


@app.get("/health/full")
def health_full(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """D2 fix: detailed posture, token-gated.

    Carries every field the old /health used to leak: environment tag, DB
    path, allowed-origin count, rate-limit + body-size config, and the
    new ``unauth_override_active`` flag so the operator can spot an
    S1-bypassed deployment from a single curl.
    """
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
        "loopback_bind": is_loopback_bind(),
        "unauth_override_active": unauth_override_active(),
        "allowed_origins_count": len(_allowed),
        "rate_limit_enabled": _rate_limit_active,
        "max_request_bytes": _max_bytes,
        "security_headers_enabled": bool(security_headers()),
        # R2: write-failure counter — non-zero means the server has been
        # silently dropping writes; operator should check the logs.
        "db_write_failures_total": _WRITE_FAILURE_COUNT,
        "degraded": _WRITE_FAILURE_COUNT > 0,
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
def get_signals(limit: int = 100, hours: int = 72, _auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Return Signal Inbox candidates derived from fresh signal_events.

    L4: ``limit`` clamped to [1, 500]; ``hours`` clamped to [1, 24*30].
    """
    limit = clamp_limit(limit, default=100, ceiling=500)
    hours = clamp_limit(hours, default=72, ceiling=24 * 30)
    result = list_inbox_items(limit=limit, hours=hours)
    # Attach the honest calibration status so the precise-looking priority
    # scores in every item can never be rendered as if they were validated.
    # Advisory-only; never authorises sizing or execution.
    try:
        from scripts.score_calibration import build_score_calibration_report
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        try:
            from score_calibration import build_score_calibration_report  # type: ignore[no-redef]
        except Exception:
            build_score_calibration_report = None  # type: ignore[assignment]
    if isinstance(result, dict) and build_score_calibration_report is not None:
        try:
            summary = build_score_calibration_report()
            result["score_calibration"] = summary
            # Attach the uniform score contract for the priority scores in
            # this response. should_drive_sizing stays False (no human sizing
            # approval is granted via a read endpoint). Advisory-only.
            try:
                from scripts.score_output_contract import build_score_contract
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                from score_output_contract import build_score_contract  # type: ignore[no-redef]
            top = None
            items = result.get("items") if isinstance(result.get("items"), list) else []
            if items:
                try:
                    top = max(
                        (float(it.get("priority_score", 0.0)) for it in items),
                        default=None,
                    )
                except (TypeError, ValueError):
                    top = None
            result["score_contract"] = build_score_contract(
                top, summary, label="priority_score"
            )
        except Exception:  # pragma: no cover - defensive
            pass
    return result


@app.get("/signals/diagnostics")
def get_signals_diagnostics(hours: int = 72, _auth: None = Depends(require_api_token_for_reads)) -> dict:
    hours = clamp_limit(hours, default=72, ceiling=24 * 30)
    """Freshness + source-count diagnostic for the Signal Inbox bridge.

    Advisory-only — does not authorize any execution.
    """
    return get_inbox_diagnostics(hours=hours)


@app.get("/signals/{event_id}")
def get_signal(event_id: str, _auth: None = Depends(require_api_token_for_reads)) -> dict:
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _auth: None = Depends(require_api_token),
) -> dict:
    # L3 fix: replay the cached response when the operator retries with
    # the same Idempotency-Key.  Single source of truth for "have we
    # processed this request?" — protects against double-logged trades
    # from sheet sync, browser reload, network retries.
    try:
        from scripts.idempotency import lookup as _idemp_lookup, store as _idemp_store, validate_key as _idemp_key
    except ModuleNotFoundError:  # pragma: no cover
        from idempotency import (  # type: ignore[no-redef]
            lookup as _idemp_lookup,
            store as _idemp_store,
            validate_key as _idemp_key,
        )

    _key = _idemp_key(idempotency_key)
    if _key:
        cached = _idemp_lookup("POST /manual-trades", _key)
        if cached is not None:
            cached.setdefault("idempotent_replay", True)
            return cached

    # S9 ordering: reject an EXPLICIT synthetic-identity claim (smoke_test,
    # seed, fixture, …) at the boundary BEFORE we stamp the server identity.
    # Rationale: such a request is test/automation traffic hitting a
    # production endpoint — we refuse it loudly with a clear logged_by
    # message rather than silently relabelling it as a real operator action.
    # Only legitimate submissions proceed to the server-identity stamp.
    try:
        from scripts.signal_inbox_api import SYNTHETIC_LOGGED_BY_MARKERS as _SYNTH_MARKERS
    except ModuleNotFoundError:  # pragma: no cover
        from signal_inbox_api import SYNTHETIC_LOGGED_BY_MARKERS as _SYNTH_MARKERS  # type: ignore
    if str(body.logged_by or "").strip().lower() in _SYNTH_MARKERS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "logged_by names a test/fixture source; not an explicit user action",
                "reason": "synthetic_logged_by_rejected",
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "execution_gate": "LOCKED",
                "execution_permission": False,
                "can_execute": False,
                "record_keeping_only": True,
            },
        )

    # S9 fix: derive ``logged_by`` from the server's view of the caller,
    # never trust the client.  Single shared token means we cannot identify
    # the human operator individually, so we stamp the token-mode (or
    # loopback-mode) along with the auth method used.  When you migrate
    # to per-user tokens this is the single line that needs to change.
    if api_token_required():
        body.logged_by = "operator@token-auth"
    elif is_loopback_bind():
        body.logged_by = "operator@loopback"
    else:
        body.logged_by = "operator@unauth-override"
    # L1 bridge: persistence layer still types money as float.  Convert at
    # the boundary so the wire-validated Decimal does not become a float
    # until the very last possible moment, preserving the operator's exact
    # input through pydantic and through this handler.  Each _money_to_float
    # call is a TODO marker for the schema migration.
    result = log_manual_trade(
        event_id=body.event_id,
        ticker=body.ticker,
        side=body.side,
        quantity=_money_to_float(body.quantity),
        price=_money_to_float(body.price),
        thesis=body.thesis,
        notes=body.notes,
        logged_by=body.logged_by,
        leverage=_money_to_float(body.leverage),
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
        exchange=body.exchange,
        country=body.country,
        jurisdiction=body.jurisdiction,
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
        # L3: do NOT cache validation-refusal responses — operator may
        # resubmit a corrected payload under the same key.
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
    # L3: cache the successful response so retries replay identically.
    if _key and isinstance(result, dict):
        try:
            _idemp_store("POST /manual-trades", _key, result)
        except Exception:  # pragma: no cover — non-critical
            _logger.warning("idempotency store failed for /manual-trades")
    return result


@app.delete("/reflections/{reflection_id}")
def delete_reflection(
    reflection_id: str, _auth: None = Depends(require_api_token)
) -> dict:
    """D1 fix: GDPR-style erasure of an individual reflection row.

    Hard-deletes the row from ``user_reflections``.  This is record-keeping
    only — it does NOT touch any broker, never increments
    ``ai_execution_count``, and never modifies ``execution_gate``.
    """
    try:
        try:
            from scripts.persistence import soft_delete_reflection
        except ModuleNotFoundError:
            from persistence import soft_delete_reflection  # type: ignore
        result = soft_delete_reflection(reflection_id)
    except Exception as exc:
        _logger.exception("delete_reflection failed for %s", reflection_id)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "delete_reflection_failed",
                "reason": _safe_exc_summary(exc),
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "execution_gate": "LOCKED",
                "record_keeping_only": True,
            },
        )
    if not result.get("deleted"):
        raise HTTPException(
            status_code=404,
            detail={
                "message": "reflection not found",
                "reason": result.get("reason", "not_found"),
                "reflection_id": reflection_id,
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "execution_gate": "LOCKED",
                "record_keeping_only": True,
            },
        )
    return {
        **result,
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
        "record_keeping_only": True,
    }


@app.post("/manual-trades/{trade_id}/reconcile")
def post_reconcile(
    trade_id: str,
    body: ReconcileBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    # L1 bridge: Decimal → float at the persistence boundary (see comment in
    # post_manual_trade above).
    return reconcile_trade(
        trade_id,
        actual_fill_price=_money_to_float(body.actual_fill_price),
        actual_quantity=_money_to_float(body.actual_quantity),
        outcome_notes=body.outcome_notes,
        pnl_estimate=_money_to_float(body.pnl_estimate),
        outcome_status=body.outcome_status,
        outcome_quality=body.outcome_quality,
        process_error=body.process_error,
        process_error_notes=body.process_error_notes,
        mistake_tags=body.mistake_tags,
        lesson=body.lesson,
        post_trade_outcome=body.post_trade_outcome,
        reconciliation_status=body.reconciliation_status,
        runner_quantity=_money_to_float(body.runner_quantity),
        runner_status=body.runner_status,
        partial_take_profit_price=_money_to_float(body.partial_take_profit_price),
        partial_take_profit_quantity=_money_to_float(body.partial_take_profit_quantity),
        take_profit_plan=body.take_profit_plan,
        stop_loss_price=_money_to_float(body.stop_loss_price),
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
def get_manual_trades(origin: str | None = "manual_trade_log", _auth: None = Depends(require_api_token_for_reads)) -> dict:
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
def get_learning_completeness(limit: int | None = 50, _auth: None = Depends(require_api_token_for_reads)) -> dict:
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
def get_diagnostics_cockpit(_auth: None = Depends(require_api_token_for_reads)) -> dict:
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
def get_source_health(_auth: None = Depends(require_api_token_for_reads)) -> dict:
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
def get_source_health_summary(_auth: None = Depends(require_api_token_for_reads)) -> dict:
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
            "error": _safe_exc_summary(exc),
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
def get_live_sources_status(_auth: None = Depends(require_api_token_for_reads)) -> dict:
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
def get_live_signals(source: str | None = None, limit: int = 100, _auth: None = Depends(require_api_token_for_reads)) -> dict:
    limit = clamp_limit(limit, default=100, ceiling=500)
    return _get_live_signals(source_name=source, limit=limit)


# ---------------------------------------------------------------------------
# Chart structure (Phase D.3) — advisory-only, read-only, no execution
# ---------------------------------------------------------------------------


@app.get("/chart-structure")
def get_chart_structure(
    symbol: str,
    source_event_id: str | None = None,
    limit: int = 100,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    limit = clamp_limit(limit, default=100, ceiling=2000)
    return _get_chart_structure(symbol=symbol, source_event_id=source_event_id, limit=limit)


_BOOTSTRAP_SYMBOL_CALLS = 0


def _reset_bootstrap_quota() -> None:
    """Test helper: zero out the I2 bootstrap counter."""
    global _BOOTSTRAP_SYMBOL_CALLS
    _BOOTSTRAP_SYMBOL_CALLS = 0


@app.post("/chart-structure/bootstrap-symbol")
def post_chart_structure_bootstrap(
    body: ChartBootstrapBody,
    _auth: None = Depends(require_api_token),
) -> dict:
    """Discover + backfill OHLCV for a missing symbol on demand.

    Read-only market-data ingestion. Never places orders, never connects to
    a broker, never increments ai_execution_count.

    I2 fix: enforce per-process quota + denylist before invoking the
    discovery/backfill pipeline so this route cannot be used as a free
    egress + Yahoo rate-limit burn channel.
    """
    global _BOOTSTRAP_SYMBOL_CALLS

    symbol_upper = str(body.symbol or "").strip().upper()
    if symbol_upper in bootstrap_symbol_denylist():
        raise HTTPException(
            status_code=403,
            detail={
                "message": "symbol_denylisted",
                "reason": "bootstrap_denylist",
                "symbol": symbol_upper,
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "execution_gate": "LOCKED",
            },
        )

    quota = bootstrap_symbol_quota()
    if quota == 0 or _BOOTSTRAP_SYMBOL_CALLS >= quota:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "bootstrap_quota_exhausted",
                "reason": "bootstrap_quota",
                "calls_so_far": _BOOTSTRAP_SYMBOL_CALLS,
                "quota": quota,
                "broker_api_called": False,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "execution_gate": "LOCKED",
            },
        )
    _BOOTSTRAP_SYMBOL_CALLS += 1

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
            "message": f"Unexpected error: {_safe_exc_summary(exc)}",
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
def search_securities(q: str = "", limit: int = 20, _auth: None = Depends(require_api_token_for_reads)) -> dict:
    limit = clamp_limit(limit, default=20, ceiling=200)
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
        return {**_SEC_SAFE_BASE, "query": q, "count": 0, "results": [], "error": _safe_exc_summary(exc)}


@app.get("/securities/{symbol}")
def get_security(symbol: str, _auth: None = Depends(require_api_token_for_reads)) -> dict:
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
        return {**_SEC_SAFE_BASE, "symbol": symbol, "found": False, "error": _safe_exc_summary(exc)}


@app.get("/securities/{symbol}/coverage")
def get_security_coverage_endpoint(symbol: str, _auth: None = Depends(require_api_token_for_reads)) -> dict:
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
            "error": _safe_exc_summary(exc),
        }


# ---------------------------------------------------------------------------
# DB status
# ---------------------------------------------------------------------------


@app.get("/db/status")
def get_db_status(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _get_db_status()


# ---------------------------------------------------------------------------
# Self-test summary — dashboard rollup
# ---------------------------------------------------------------------------


@app.get("/self-test/summary")
def get_self_test_summary(_auth: None = Depends(require_api_token_for_reads)) -> dict:
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
            "error": _safe_exc_summary(exc),
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_permission": False,
            "can_execute": False,
            "human_review_required": True,
        }


@app.get("/self-test/reconciliation-queue")
def get_reconciliation_queue(limit: int = 100, _auth: None = Depends(require_api_token_for_reads)) -> dict:
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
def get_moltbook(_auth: None = Depends(require_api_token_for_reads)) -> dict:
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
# CSV exports
# ---------------------------------------------------------------------------


@app.get("/exports/signal-inbox.csv")
def export_signal_inbox(_auth: None = Depends(require_api_token_for_reads)) -> Response:
    return Response(content=export_signal_inbox_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/reflections.csv")
def export_reflections(_auth: None = Depends(require_api_token_for_reads)) -> Response:
    return Response(content=export_reflection_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/manual-trades.csv")
def export_manual_trades(_auth: None = Depends(require_api_token_for_reads)) -> Response:
    return Response(content=export_manual_trade_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/reconciliation.csv")
def export_reconciliation(_auth: None = Depends(require_api_token_for_reads)) -> Response:
    return Response(content=export_reconciliation_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/moltbook.csv")
def export_moltbook(_auth: None = Depends(require_api_token_for_reads)) -> Response:
    return Response(content=export_moltbook_mistake_log(), media_type=_CSV_MEDIA_TYPE)


@app.get("/exports/source-health.csv")
def export_source_health(_auth: None = Depends(require_api_token_for_reads)) -> Response:
    return Response(content=export_source_health_log(), media_type=_CSV_MEDIA_TYPE)


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


try:
    from scripts.backend_api_quality import (
        read_artifact_envelope as _read_artifact_envelope,
        live_refresh_run_locked_response as _live_refresh_run_locked_response,
    )
except ModuleNotFoundError:  # pragma: no cover
    from backend_api_quality import (  # type: ignore[no-redef]
        read_artifact_envelope as _read_artifact_envelope,
        live_refresh_run_locked_response as _live_refresh_run_locked_response,
    )


@app.get("/api/readiness/release-gate")
def get_release_gate_readiness(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("release_gate")


@app.get("/api/readiness/daily-signal")
def get_daily_signal_readiness(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("daily_signal")


@app.get("/api/source-health")
def get_source_health_api(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("source_health")


@app.get("/api/live-refresh/summary")
def get_live_refresh_summary(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("live_refresh")


@app.get("/api/portfolio-truth")
def get_portfolio_truth_api(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("portfolio_truth")


@app.get("/api/fresh-discovery")
def get_fresh_discovery_api(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("fresh_discovery")


@app.get("/api/why-today/summary")
def get_why_today_summary(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("why_today")


@app.get("/api/model-disagreement/summary")
def get_model_disagreement_summary(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("model_disagreement")


@app.get("/api/signal-input-quality/summary")
def get_signal_input_quality_summary(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("signal_input_quality")


@app.get("/api/compliance/readiness")
def get_compliance_readiness(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("compliance_readiness")


@app.get("/api/business-value/summary")
def get_business_value_summary(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    return _read_artifact_envelope("business_value")


@app.get("/api/score-calibration")
def get_score_calibration(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Honest calibration status for the signal scores.

    Computed from reconciled outcomes in the local DB. Tells the operator
    whether the precise-looking scores are actually backed by evidence yet —
    advisory-only, never authorises sizing or execution.
    """
    try:
        from scripts.score_calibration import build_score_calibration_report
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from score_calibration import build_score_calibration_report  # type: ignore[no-redef]
    return build_score_calibration_report()


@app.get("/api/readiness/real-money")
def get_real_money_readiness(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Honest manual real-money readiness gate.

    Scores readiness (capped at 7.0 — never scaling-ready) and returns an
    allowed_mode: SCALE_BLOCKED / PAPER_ONLY / TINY_MANUAL_PROBE_ONLY /
    MANUAL_REAL_MONEY_READY. Read-only; never authorises execution.
    """
    try:
        from scripts.pre_real_money_preflight import assess_real_money_readiness
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from pre_real_money_preflight import assess_real_money_readiness  # type: ignore[no-redef]
    return assess_real_money_readiness()


@app.get("/api/calibration-map")
def get_calibration_map(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """OOS-validated recalibration status (isotonic/Platt) from local outcomes.

    Reports whether the raw scores can be recalibrated into honest
    probabilities and by how much ECE/Brier improve out of sample. Advisory —
    a recalibrated probability never enables sizing on its own.
    """
    try:
        from scripts.outcome_evidence_extractor import extract_from_db
        from scripts.calibration_map import fit_from_outcomes
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from outcome_evidence_extractor import extract_from_db  # type: ignore[no-redef]
        from calibration_map import fit_from_outcomes  # type: ignore[no-redef]
    outcomes = extract_from_db(None)
    result = fit_from_outcomes(outcomes).to_dict() if outcomes else {
        "method": "identity", "improved_out_of_sample": False, "train_n": 0, "test_n": 0,
        "advisory_only": True, "human_review_required": True, "broker_api_called": False,
    }
    return result


@app.get("/api/signal-quality")
def get_signal_quality(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Outcome-backed signal quality score (advisory-only).

    Combines calibration metrics, securities coverage, the feedback loop, and
    import-hygiene into a single honest score with hard caps. Read-only.
    """
    try:
        from scripts.signal_quality_report import build_signal_quality_report_from_db
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from signal_quality_report import build_signal_quality_report_from_db  # type: ignore[no-redef]
    return build_signal_quality_report_from_db()


@app.get("/api/calibration-recommendations")
def get_calibration_recommendations(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Guarded calibration recommendations from reconciled outcomes.

    The Moltbook/reconciliation feedback loop, made safe: recommends whether a
    score threshold should move but NEVER auto-applies (applied always False,
    human_review_required always True). Advisory-only.
    """
    try:
        from scripts.calibration_recommendations import build_recommendation_report
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from calibration_recommendations import build_recommendation_report  # type: ignore[no-redef]
    return build_recommendation_report()


@app.post("/api/live-refresh/run")
def post_live_refresh_run(
    _auth: None = Depends(require_api_token),
) -> dict:
    """Locked operator endpoint — refuses unless every safety gate holds.

    Does NOT actually run the live refresh from the HTTP path: live calls
    are operator-run via ``scripts/operator_live_provider_refresh.py``.  The
    endpoint exists to give the cockpit a deterministic, structured
    "is live refresh permitted right now?" answer.
    """
    import os as _os
    mvp_ok = _os.environ.get("MVP_LIVE_REFRESH_OK", "").lower() in {
        "1", "true", "yes", "on",
    }
    return _live_refresh_run_locked_response(
        mvp_live_refresh_ok=mvp_ok,
        advisory_only=True,
        human_execution_required=True,
        execution_gate="LOCKED",
    )


# ---------------------------------------------------------------------------
# Simulation Intelligence Layer (SIL) — advisory-only six-lens simulation council
#
# All routes are advisory-only and record-only.  The POST route runs a bounded,
# deterministic Monte-Carlo council and persists a SIMULATED_ONLY run to SQLite;
# it NEVER feeds calibration, NEVER calls a broker, and NEVER grants execution.
# Heavy work is bounded by SIL feature-flag caps; the layer degrades gracefully
# when optional engines are unavailable (the council always runs).
# ---------------------------------------------------------------------------


def _sil_import():
    """Lazy dual-path import of the SIL API surface + replay + persistence."""
    try:
        from scripts.simulation_intelligence import api_surface as _api
        from scripts.simulation_intelligence import replay as _replay
        from scripts.simulation_intelligence import engine_manifest as _em
        from scripts import persistence as _persist
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from simulation_intelligence import api_surface as _api  # type: ignore[no-redef]
        from simulation_intelligence import replay as _replay  # type: ignore[no-redef]
        from simulation_intelligence import engine_manifest as _em  # type: ignore[no-redef]
        import persistence as _persist  # type: ignore[no-redef]
    return _api, _replay, _em, _persist


@app.get("/api/simulation/health")
def get_simulation_health(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """SIL availability + feature flags (advisory-only). Never blocks."""
    try:
        api, _replay, _em, _persist = _sil_import()
        return api.health_report()
    except Exception as exc:  # fail soft
        return {"report": "simulation_health", "ok": False,
                "error": _safe_exc_summary(exc), "advisory_status": _ADVISORY_STATUS,
                "execution_gate": "LOCKED", "ai_execution_count": 0,
                "broker_api_called": False, "human_review_required": True}


@app.get("/api/simulation/engines")
def get_simulation_engines(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Verified 18-engine manifest + honest live adapter availability."""
    api, _replay, _em, _persist = _sil_import()
    return api.engines_report()


@app.get("/api/simulation/scenarios")
def get_simulation_scenarios(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Reusable India/US stress + operational scenario catalog."""
    api, _replay, _em, _persist = _sil_import()
    return api.scenarios_report()


@app.post("/api/simulation/run")
def post_simulation_run(
    body: "SimulationRunBody",
    _auth: None = Depends(require_api_token),
) -> dict:
    """Run the six-lens council for a candidate; persist a SIMULATED_ONLY run.

    Advisory-only and record-only: the result never feeds calibration and never
    grants execution.  Deterministic given (seed, data cutoff, observation).
    """
    api, _replay, _em, _persist = _sil_import()
    payload = {
        "ticker": body.ticker, "market": body.market, "seed": body.seed,
        "max_runs": body.max_runs, "parent_signal_id": body.parent_signal_id,
        "observation": body.observation or {}, "scenarios": body.scenarios,
        "requested_lenses": body.requested_lenses,
    }
    result = api.run_simulation(payload)
    if result.get("ok"):
        try:
            _persist.insert_simulation_run(
                result, request_payload=payload,
                engine_manifest_version=_em.MANIFEST_VERSION,
            )
        except Exception:  # persistence is best-effort; the run itself is returned
            result["persisted"] = False
        else:
            result["persisted"] = True
    return result


@app.get("/api/simulation/runs")
def get_simulation_runs(
    limit: int = 50,
    ticker: str | None = None,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """List recent simulation runs (newest first), optionally by ticker."""
    api, _replay, _em, _persist = _sil_import()
    limit = clamp_limit(limit, default=50, ceiling=200)
    runs = _persist.get_recent_simulation_runs(limit=limit, ticker=ticker)
    # Return compact rows (drop the heavy result_json blob from the list view).
    compact = []
    for r in runs:
        compact.append({k: r.get(k) for k in (
            "run_id", "ticker", "market", "seed", "aggregate_vote",
            "disagreement_class", "aggregate_confidence", "evidence_label",
            "risk_block_engaged", "simulation_only", "usefulness_score", "created_at",
        )})
    return {
        "report": "simulation_runs", "count": len(compact), "runs": compact,
        "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
        "ai_execution_count": 0, "broker_api_called": False,
        "human_review_required": True,
    }


@app.get("/api/simulation/runs/{run_id}")
def get_simulation_run_by_id(
    run_id: str,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Return one stored simulation run (full council result)."""
    api, _replay, _em, _persist = _sil_import()
    run = _persist.get_simulation_run(run_id[:64])
    if run is None:
        raise HTTPException(status_code=404, detail={
            "message": "simulation run not found", "reason": "unknown_run_id",
            "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
            "ai_execution_count": 0, "broker_api_called": False,
            "human_review_required": True, "record_keeping_only": True,
        })
    return {"report": "simulation_run_detail", **run}


@app.get("/api/simulation/runs/{run_id}/replay")
def get_simulation_replay(
    run_id: str,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Re-run the council from the stored request and confirm determinism."""
    api, _replay, _em, _persist = _sil_import()
    run = _persist.get_simulation_run(run_id[:64])
    if run is None:
        raise HTTPException(status_code=404, detail={
            "message": "simulation run not found", "reason": "unknown_run_id",
            "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
            "ai_execution_count": 0, "broker_api_called": False,
            "human_review_required": True, "record_keeping_only": True,
        })
    return _replay.replay_run(run)


@app.get("/api/simulation/council/{ticker}")
def get_simulation_council(
    ticker: str,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Return the latest stored council result for a ticker (advisory-only)."""
    api, _replay, _em, _persist = _sil_import()
    run = _persist.get_latest_simulation_run_for_ticker(ticker[:32])
    if run is None:
        return {
            "report": "simulation_council", "ticker": ticker, "found": False,
            "message": "no stored simulation run for this ticker; POST /api/simulation/run first",
            "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
            "ai_execution_count": 0, "broker_api_called": False,
            "human_review_required": True,
        }
    return {"report": "simulation_council", "ticker": ticker, "found": True, **run}


@app.get("/api/simulation/stress-summary")
def get_simulation_stress_summary(
    ticker: str | None = None,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Roll up stress-test survival across recent runs (advisory-only)."""
    api, _replay, _em, _persist = _sil_import()
    runs = _persist.get_recent_simulation_runs(limit=50, ticker=ticker)
    total = 0
    survived = 0
    worst_tail = 0.0
    per_scenario: dict = {}
    for r in runs:
        for st in (r.get("result", {}) or {}).get("stress_results", []):
            total += 1
            if st.get("survived"):
                survived += 1
            band = st.get("band", {}) or {}
            worst_tail = min(worst_tail, float(band.get("tail_low", 0.0) or 0.0))
            sid = st.get("scenario_id", "unknown")
            slot = per_scenario.setdefault(sid, {"n": 0, "survived": 0})
            slot["n"] += 1
            slot["survived"] += 1 if st.get("survived") else 0
    return {
        "report": "simulation_stress_summary", "runs_considered": len(runs),
        "stress_cells": total, "survived": survived,
        "survival_rate": round(survived / total, 4) if total else None,
        "worst_tail": round(worst_tail, 6), "per_scenario": per_scenario,
        "evidence_note": "SIMULATED_ONLY — stress outcomes are simulated, not measured.",
        "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
        "ai_execution_count": 0, "broker_api_called": False,
        "human_review_required": True,
    }


# ---------------------------------------------------------------------------
# Role-Adjusted Contribution Rating (RACR / "Kanté Index") — advisory-only
# role-aware scoring surface. Every route is record-only and never grants
# execution. Heavy work (ablation, reliability batch) is bounded.
# ---------------------------------------------------------------------------


def _racr_import():
    """Lazy dual-path import of the RACR service + supporting modules."""
    try:
        from scripts.simulation_intelligence import role_contracts as _rc
        from scripts.simulation_intelligence import role_rating_service as _svc
        from scripts.simulation_intelligence import reliability as _rel
        from scripts.simulation_intelligence import engine_validation as _ev
        from scripts.simulation_intelligence import signal_bridge as _bridge
        from scripts.simulation_intelligence import api_surface as _api
        from scripts import persistence as _persist
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from simulation_intelligence import role_contracts as _rc  # type: ignore[no-redef]
        from simulation_intelligence import role_rating_service as _svc  # type: ignore[no-redef]
        from simulation_intelligence import reliability as _rel  # type: ignore[no-redef]
        from simulation_intelligence import engine_validation as _ev  # type: ignore[no-redef]
        from simulation_intelligence import signal_bridge as _bridge  # type: ignore[no-redef]
        from simulation_intelligence import api_surface as _api  # type: ignore[no-redef]
        import persistence as _persist  # type: ignore[no-redef]
    return _rc, _svc, _rel, _ev, _bridge, _api, _persist


@app.get("/api/simulation/role-contracts")
def get_role_contracts(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Versioned, immutable component role contracts (the RACR taxonomy)."""
    rc, _svc, _rel, _ev, _bridge, _api, _persist = _racr_import()
    return rc.registry_report()


@app.get("/api/simulation/observation/{ticker}")
def get_simulation_observation(
    ticker: str,
    session_date: str | None = None,
    parent_signal_id: str = "",
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Priority-1 bridge: build a validated MarketObservation from live DB state.

    Advisory-only; never a trade action. Fails closed (missing_fields) when the
    canonical OHLCV/live data is incomplete.
    """
    rc, _svc, _rel, _ev, _bridge, _api, _persist = _racr_import()
    result = _bridge.build_observation_for_ticker(
        ticker[:32], session_date=session_date, parent_signal_id=parent_signal_id[:64])
    out = result.to_dict()
    out["report"] = "simulation_observation"
    out.update({"advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
                "ai_execution_count": 0, "broker_api_called": False,
                "human_review_required": True})
    return out


@app.post("/api/simulation/ratings")
def post_simulation_ratings(
    body: "SimulationRunBody",
    _auth: None = Depends(require_api_token),
) -> dict:
    """Build the five role-aware scores for a candidate and persist events +
    ratings. Advisory-only, record-only, bounded."""
    rc, svc, _rel, _ev, _bridge, api, _persist = _racr_import()
    if not api.flags.sil_enabled():
        return {"report": "role_adjusted_ratings", "ok": False, "error": "sil_disabled",
                "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
                "ai_execution_count": 0, "broker_api_called": False,
                "human_review_required": True}
    payload = {
        "ticker": body.ticker, "market": body.market, "seed": body.seed,
        "max_runs": body.max_runs, "parent_signal_id": body.parent_signal_id,
        "observation": body.observation or {}, "scenarios": body.scenarios,
        "requested_lenses": body.requested_lenses,
    }
    request = api.build_request(payload)
    result = svc.build_ratings(request)
    result["ok"] = True
    # Persist events + per-component ratings (best-effort).
    try:
        _persist.insert_contribution_events(result.get("contribution_events", []))
        for rating in result.get("ratings", []):
            rating2 = dict(rating)
            rating2.setdefault("rating_id",
                               f"RR_{rating.get('component_id','')}_{result.get('run_id','')}")
            _persist.insert_role_rating(rating2, run_id=str(result.get("run_id", "")))
        result["persisted"] = True
    except Exception:
        result["persisted"] = False
    return result


@app.get("/api/simulation/ratings")
def get_simulation_ratings(
    limit: int = 50,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Recent persisted role-adjusted rating snapshots (newest first)."""
    rc, _svc, _rel, _ev, _bridge, _api, _persist = _racr_import()
    limit = clamp_limit(limit, default=50, ceiling=200)
    ratings = _persist.get_role_ratings(limit=limit)
    return {"report": "role_ratings", "count": len(ratings), "ratings": ratings,
            "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
            "ai_execution_count": 0, "broker_api_called": False,
            "human_review_required": True}


@app.get("/api/simulation/contribution-events")
def get_simulation_contribution_events(
    component_id: str | None = None,
    run_id: str | None = None,
    limit: int = 200,
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Recent contribution events (the audit trail behind role ratings)."""
    rc, _svc, _rel, _ev, _bridge, _api, _persist = _racr_import()
    limit = clamp_limit(limit, default=200, ceiling=1000)
    events = _persist.get_contribution_events(
        component_id=component_id[:64] if component_id else None,
        run_id=run_id[:64] if run_id else None, limit=limit)
    return {"report": "contribution_events", "count": len(events), "events": events,
            "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
            "ai_execution_count": 0, "broker_api_called": False,
            "human_review_required": True}


@app.get("/api/simulation/reliability")
def get_simulation_reliability(_auth: None = Depends(require_api_token_for_reads)) -> dict:
    """Fault-injection + scenario-mutation reliability report (advisory-only)."""
    rc, _svc, rel, _ev, _bridge, _api, _persist = _racr_import()
    faults = [f.to_dict() for f in rel.run_fault_injection()]
    all_safe = all(f["survived"] and f["safe"] for f in faults)
    return {
        "report": "simulation_reliability",
        "fault_injection": faults,
        "all_faults_survived_safely": all_safe,
        "advisory_status": _ADVISORY_STATUS, "execution_gate": "LOCKED",
        "ai_execution_count": 0, "broker_api_called": False,
        "human_review_required": True,
    }


@app.get("/api/simulation/engine-validation")
def get_simulation_engine_validation(
    _auth: None = Depends(require_api_token_for_reads),
) -> dict:
    """Optional-engine (Stockfish/COPASI) verification profiles."""
    rc, _svc, _rel, ev, _bridge, _api, _persist = _racr_import()
    return ev.validate_optional_engines()


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
        # S1: preflight refuses to boot in unsafe configurations.  Run it
        # here too (before uvicorn starts) so the operator sees the
        # refusal in their shell, not in a Docker restart loop.
        try:
            preflight_auth_or_die()
        except Exception as exc:
            print(f"[FATAL] {exc}", file=sys.stderr)
            sys.exit(2)
        if not api_token_required():
            print(
                "[warning] MVP_API_TOKEN not set; mutating routes are unprotected. "
                "Loopback-only use recommended.",
                file=sys.stderr,
            )
        # A4: pin uvicorn to ONE worker.  The in-memory rate-limit and
        # idempotency caches are per-process; multi-worker would split
        # them and break both invariants.  See A4 in the audit.
        print(f"[info] Starting Signal Advisory API at http://{host}:{port} (workers=1)")
        uvicorn.run(app, host=host, port=port, workers=1)
    except ImportError:
        print("uvicorn not installed.  Run: pip install uvicorn")
        sys.exit(1)
