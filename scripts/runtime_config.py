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
]
