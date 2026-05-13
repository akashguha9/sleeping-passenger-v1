"""
Central runtime configuration for the local advisory MVP.

Single source of truth for env-driven knobs so the rest of the codebase does
not scatter `os.environ.get(...)` calls and hardcoded defaults.

Read at module-import time and again on each call to the public helpers so
that test code can monkeypatch env vars without restarting the process.

No secrets are stored here.  No values are logged.  Empty/unset env vars
fall back to local-development defaults.

Advisory invariants (never change):
  advisory_status     = "ADVISORY_ONLY"
  execution_mode      = "HUMAN_ONLY"
  execution_gate      = "LOCKED"
  ai_execution_count  = 0
  broker_api_called   = False
  broker_order_id     = "NONE"
"""
from __future__ import annotations

import os
from pathlib import Path

# Advisory constants — duplicated in api_server.py / persistence.py /
# signal_inbox_api.py for historical reasons.  Importing them from here is
# preferred for new code.
ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_MODE = "HUMAN_ONLY"
EXECUTION_GATE = "LOCKED"
AI_EXECUTION_COUNT = 0
BROKER_API_CALLED = False
BROKER_ORDER_ID = "NONE"

# ---------------------------------------------------------------------------
# Defaults — chosen to match prior hardcoded values so behaviour is preserved
# when no env vars are set.
# ---------------------------------------------------------------------------

_DEFAULT_API_HOST = "127.0.0.1"
_DEFAULT_API_PORT = 8000
_DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://sleepingpassenger",
    "http://sleepingpassenger.local",
    "http://sleepingpassenger:80",
    "http://sleepingpassenger.local:80",
)
_DEFAULT_ENVIRONMENT = "local"

# Day 11-25 hardening defaults
_DEFAULT_MAX_REQUEST_BYTES = 1_000_000  # 1 MB JSON ceiling for mutating routes
_DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
_DEFAULT_RATE_LIMIT_MAX_REQUESTS = 120
_DEFAULT_MUTATION_RATE_LIMIT_MAX_REQUESTS = 30
_DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 5000
_DEFAULT_SQLITE_JOURNAL_MODE = "WAL"


def get_api_host() -> str:
    """uvicorn bind host.  Set to 0.0.0.0 inside containers."""
    return os.environ.get("API_HOST", _DEFAULT_API_HOST).strip() or _DEFAULT_API_HOST


def get_api_port() -> int:
    raw = os.environ.get("API_PORT", "").strip()
    if not raw:
        return _DEFAULT_API_PORT
    try:
        port = int(raw)
    except ValueError:
        return _DEFAULT_API_PORT
    if port < 1 or port > 65535:
        return _DEFAULT_API_PORT
    return port


def get_allowed_origins() -> list[str]:
    """CORS allowlist.

    Comma-separated env var ``ALLOWED_ORIGINS`` overrides the default tuple.
    Empty/whitespace entries are discarded.  Order is preserved.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_ALLOWED_ORIGINS)
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    return parsed or list(_DEFAULT_ALLOWED_ORIGINS)


def get_api_token() -> str | None:
    """Returns the API token if set, else None.

    When None, mutating routes are unprotected — appropriate for local-only
    use, but a warning is emitted at server startup.
    """
    raw = os.environ.get("MVP_API_TOKEN", "")
    token = raw.strip()
    return token if token else None


def api_token_required() -> bool:
    """True iff ``MVP_API_TOKEN`` is set and non-empty."""
    return get_api_token() is not None


def get_environment_tag() -> str:
    """Free-form environment label surfaced on /health (e.g. ``local``, ``ci``)."""
    return os.environ.get("MVP_ENVIRONMENT", _DEFAULT_ENVIRONMENT).strip() or _DEFAULT_ENVIRONMENT


def get_db_path() -> Path:
    """Override the SQLite DB path via ``MVP_DB_PATH``.

    Defaults to ``runtime/mvp_local.db`` relative to the repo root (matches
    ``scripts.persistence.DB_PATH``).
    """
    raw = os.environ.get("MVP_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "runtime" / "mvp_local.db"


def db_available(db_path: Path | None = None) -> bool:
    """Lightweight check: does the DB file exist on disk?"""
    target = db_path if db_path is not None else get_db_path()
    try:
        return target.exists() and target.is_file()
    except OSError:
        return False


def safe_db_display_path() -> str:
    """Return a repo-relative DB path string suitable for /health.

    Never leaks the user's home directory or absolute filesystem layout
    unless the DB lives outside the repo, in which case we surface only the
    file name.
    """
    db_path = get_db_path()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        return db_path.relative_to(repo_root).as_posix()
    except ValueError:
        return db_path.name


def get_max_request_bytes() -> int:
    """Maximum allowed request body size in bytes.

    Enforced by ``scripts.api_server`` via a Content-Length-based middleware
    on mutating routes.  Requests larger than this return 413.

    Override with env var ``MVP_MAX_REQUEST_BYTES``; defaults to 1_000_000.
    Invalid values fall back to the default.  A floor of 1024 is enforced so
    normal JSON payloads never get clipped.
    """
    raw = os.environ.get("MVP_MAX_REQUEST_BYTES", "").strip()
    if not raw:
        return _DEFAULT_MAX_REQUEST_BYTES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_REQUEST_BYTES
    if value < 1024:
        return _DEFAULT_MAX_REQUEST_BYTES
    return value


def security_headers() -> dict[str, str]:
    """Conservative HTTP security headers for the local API surface.

    Tuned for a localhost JSON API consumed by the Next.js frontend.  We
    deliberately avoid CSP here because this service does not serve HTML;
    the frontend renders its own CSP via Next.

    Override the whole map via ``MVP_SECURITY_HEADERS_DISABLED=1`` (returns
    an empty dict) for niche local debugging.  No granular env tuning yet --
    add it only when a real consumer asks for it.
    """
    if os.environ.get("MVP_SECURITY_HEADERS_DISABLED", "").strip() == "1":
        return {}
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        ),
        "Cross-Origin-Resource-Policy": "same-site",
        "X-Robots-Tag": "noindex, nofollow",
    }


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def rate_limit_enabled() -> bool:
    """Whether the in-memory rate limiter is active.

    Default behaviour:
      * Auto-disabled under pytest (``PYTEST_CURRENT_TEST`` is set) so the
        large existing suite of API tests can fire bursts from one client
        without tripping the limiter.  Tests that *want* to exercise the
        limiter set ``MVP_RATE_LIMIT_ENABLED=1`` explicitly via monkeypatch.
      * Enabled everywhere else, so an out-of-the-box ``python
        scripts/api_server.py`` has a safety floor against accidental loops.

    Override with ``MVP_RATE_LIMIT_ENABLED=1`` / ``=0``.
    """
    raw = os.environ.get("MVP_RATE_LIMIT_ENABLED", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _positive_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def rate_limit_window_seconds() -> int:
    """Sliding window length, in seconds, for the in-memory rate limiter."""
    return _positive_int_env(
        "MVP_RATE_LIMIT_WINDOW_SECONDS", _DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    )


def rate_limit_max_requests() -> int:
    """Per-client request ceiling per window for all routes."""
    return _positive_int_env(
        "MVP_RATE_LIMIT_MAX_REQUESTS", _DEFAULT_RATE_LIMIT_MAX_REQUESTS
    )


def rate_limit_mutation_max_requests() -> int:
    """Stricter per-client ceiling per window for mutating (POST) routes."""
    return _positive_int_env(
        "MVP_MUTATION_RATE_LIMIT_MAX_REQUESTS",
        _DEFAULT_MUTATION_RATE_LIMIT_MAX_REQUESTS,
    )


def sqlite_busy_timeout_ms() -> int:
    """PRAGMA busy_timeout value applied to every SQLite connection.

    A non-zero busy timeout lets concurrent writers wait briefly instead of
    failing immediately with ``database is locked``.  This is the single
    most useful pragma for a single-machine multi-process MVP.
    """
    return _positive_int_env(
        "MVP_SQLITE_BUSY_TIMEOUT_MS",
        _DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
        minimum=0,
    )


def sqlite_journal_mode() -> str:
    """PRAGMA journal_mode applied to every SQLite connection.

    WAL is strongly recommended for the local MVP because it lets readers
    and writers operate concurrently and is what the backup script's
    ``connection.backup()`` API copes with best.  Override with
    ``MVP_SQLITE_JOURNAL_MODE=DELETE`` if you need to inspect a DB on a
    filesystem that doesn't support WAL (rare).
    """
    raw = os.environ.get("MVP_SQLITE_JOURNAL_MODE", "").strip().upper()
    if not raw:
        return _DEFAULT_SQLITE_JOURNAL_MODE
    if raw not in {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"}:
        return _DEFAULT_SQLITE_JOURNAL_MODE
    return raw


def runtime_safety_stamps() -> dict[str, object]:
    """Common advisory stamp block used by handlers and responses."""
    return {
        "advisory_status": ADVISORY_STATUS,
        "execution_mode": EXECUTION_MODE,
        "execution_gate": EXECUTION_GATE,
        "ai_execution_count": AI_EXECUTION_COUNT,
        "broker_api_called": BROKER_API_CALLED,
        "broker_order_id": BROKER_ORDER_ID,
        "human_review_required": True,
    }


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_MODE",
    "EXECUTION_GATE",
    "AI_EXECUTION_COUNT",
    "BROKER_API_CALLED",
    "BROKER_ORDER_ID",
    "get_api_host",
    "get_api_port",
    "get_allowed_origins",
    "get_api_token",
    "api_token_required",
    "get_environment_tag",
    "get_db_path",
    "db_available",
    "safe_db_display_path",
    "runtime_safety_stamps",
    "get_max_request_bytes",
    "security_headers",
    "rate_limit_enabled",
    "rate_limit_window_seconds",
    "rate_limit_max_requests",
    "rate_limit_mutation_max_requests",
    "sqlite_busy_timeout_ms",
    "sqlite_journal_mode",
]
