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
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_local_dotenv() -> None:
    """Best-effort load of the repo-root ``.env`` into ``os.environ``.

    Owner-only hardening: the startup preflight requires ``MVP_API_TOKEN``
    by default, and the Windows start scripts launch uvicorn without
    exporting env vars — so the server must be able to read the operator's
    gitignored ``.env`` itself.  Rules:

    * ``setdefault`` semantics only — real environment variables always win.
    * Never runs under pytest (a developer's local ``.env`` must not leak
      into test assertions); disable explicitly with ``MVP_SKIP_DOTENV=1``.
    * Parses only simple ``KEY=VALUE`` lines; no interpolation, no export
      keywords, no multi-line values.  Values are never logged.
    """
    if "pytest" in sys.modules or os.environ.get("MVP_SKIP_DOTENV", "").strip() == "1":
        return
    try:
        text = (_REPO_ROOT / ".env").read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError):
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _hydrate_provider_secrets() -> None:
    """Pass-3 secret custody: when ``SECRET_PROVIDER=windows-credential-manager``,
    copy known provider keys from OS custody into os.environ (setdefault —
    real env and .env values win). Never raises: unavailable custody just
    leaves keys unset and the loaders skip cleanly. Inert under pytest for
    the same reason the dotenv loader is."""
    if "pytest" in sys.modules:
        return
    try:
        try:
            from scripts.secret_provider import hydrate_environment
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from secret_provider import hydrate_environment  # type: ignore[no-redef]
        hydrate_environment()
    except Exception:  # pragma: no cover - custody must never block boot
        pass


_load_local_dotenv()
_hydrate_provider_secrets()

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
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
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
    """Returns the legacy PLAINTEXT API token if set, else None.

    Prefer ``MVP_API_TOKEN_HASH`` (see ``get_api_token_hash``): with hash
    mode the raw token never sits on disk.  Plaintext remains supported as
    a fallback but the server logs a warning at startup.
    """
    raw = os.environ.get("MVP_API_TOKEN", "")
    token = raw.strip()
    return token if token else None


# Allowed alphabet for stored token hashes (see get_api_token_hash).
# Deliberately NOT named after the credential it validates: a name like
# "<credential>_HEX64 = ..." reads as a hard-coded secret to scanners
# (gitleaks generic-api-key flagged the previous name of this constant).
_LOWER_HEX_DIGITS = "0123456789abcdef"


def get_api_token_hash() -> str | None:
    """Returns the stored SHA-256 token hash (lowercase hex) if set.

    Format is validated strictly: exactly 64 lowercase hex chars after
    normalisation.  A malformed value returns None here and is rejected at
    startup by ``preflight_auth_or_die`` — never silently ignored at
    request time, because that would fail OPEN.

    SHA-256 without salt/stretching is appropriate ONLY because the token
    is 256 bits of machine-generated randomness (no dictionary/rainbow
    attack is possible).  Never reuse this scheme for human passwords.
    """
    raw = os.environ.get("MVP_API_TOKEN_HASH", "").strip().lower()
    if not raw:
        return None
    if len(raw) != 64 or any(c not in _LOWER_HEX_DIGITS for c in raw):
        return None
    return raw


def api_token_hash_malformed() -> bool:
    """True iff MVP_API_TOKEN_HASH is set but not 64 lowercase hex chars."""
    raw = os.environ.get("MVP_API_TOKEN_HASH", "").strip()
    return bool(raw) and get_api_token_hash() is None


def api_token_required() -> bool:
    """True iff owner auth is configured (hash mode or plaintext fallback)."""
    return get_api_token_hash() is not None or get_api_token() is not None


def plaintext_token_fallback_active() -> bool:
    """True iff only the legacy plaintext MVP_API_TOKEN is configured."""
    return get_api_token_hash() is None and get_api_token() is not None


def verify_api_token(presented: str | None) -> bool:
    """Constant-time owner-token verification.

    Hash mode wins when both are configured.  Invariant (test-pinned):
    ``Verify(t, H) is True`` iff sha256(t) == H (hash mode) or t == token
    (legacy mode); every other input returns False.  No token configured
    → False (fail closed; the request-level gates decide whether an open
    loopback dev override applies).
    """
    import hashlib
    import hmac

    if not presented:
        return False
    stored_hash = get_api_token_hash()
    if stored_hash is not None:
        presented_hash = hashlib.sha256(presented.encode("utf-8")).hexdigest()
        return hmac.compare_digest(presented_hash, stored_hash)
    expected = get_api_token()
    if expected is not None:
        return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    return False


def is_loopback_bind(host: str | None = None) -> bool:
    """True iff API_HOST resolves to a loopback name."""
    candidate = (host if host is not None else get_api_host()).strip().lower()
    return candidate in _LOOPBACK_HOSTS


class StartupSecurityError(RuntimeError):
    """Raised when the server's startup posture is unsafe and not explicitly overridden."""


_UNSAFE_LAN_ACK = "I_UNDERSTAND_THIS_EXPOSES_MY_TOKEN"


def lockdown_mode_active() -> bool:
    """Emergency read-only mode (Pass 3): ``MVP_LOCKDOWN_MODE=1``.

    When active, every mutating route returns 423 Locked; reads stay
    token-gated as usual. Use during suspected compromise, token leak,
    dependency incident, or shared-machine situations
    (docs/INCIDENT_LOCKDOWN.md)."""
    return _bool_env("MVP_LOCKDOWN_MODE", False)


def public_mode_requested() -> bool:
    """True iff the operator explicitly flagged a public deployment."""
    return _bool_env("MVP_PUBLIC_MODE", False)


def exposure_acknowledgement() -> str | None:
    """How a non-loopback (or public-mode) bind is acknowledged, if at all.

    A bearer token over plain HTTP is readable by anyone on the path, so
    exposing the API beyond loopback requires the operator to state how
    transport security is handled.  Returns one of:

    * ``"tls_terminated"``    — MVP_TLS_TERMINATED=1: TLS terminates in
      front of this server (reverse proxy / tunnel).
    * ``"reverse_proxy"``     — MVP_TRUSTED_PROXIES explicitly set: a
      declared proxy allowlist fronts the server.
    * ``"portmap_loopback"``  — MVP_PUBLISHED_BIND resolves to loopback:
      the process binds 0.0.0.0 inside a container but the published
      host port is mapped to 127.0.0.1 (docker-compose default).
    * ``"unsafe_lan_http"``   — MVP_UNSAFE_LAN_HTTP carries the exact
      acknowledgement string: deliberate, loud, token-exposing escape
      hatch for a trusted private network.
    * ``None``                — no acknowledgement: refuse to boot.
    """
    if _bool_env("MVP_TLS_TERMINATED", False):
        return "tls_terminated"
    if os.environ.get("MVP_TRUSTED_PROXIES", "").strip():
        return "reverse_proxy"
    published = os.environ.get("MVP_PUBLISHED_BIND", "").strip().lower()
    if published and published in _LOOPBACK_HOSTS and not public_mode_requested():
        return "portmap_loopback"
    if os.environ.get("MVP_UNSAFE_LAN_HTTP", "").strip() == _UNSAFE_LAN_ACK:
        return "unsafe_lan_http"
    return None


def preflight_auth_or_die() -> None:
    """Fail closed: refuse to boot unless owner auth is configured.

    Owner-only contract (sole-proprietor hardening):

    * Owner token configured (``MVP_API_TOKEN_HASH`` preferred, plaintext
      ``MVP_API_TOKEN`` legacy fallback) → boot on loopback.  On a
      NON-loopback bind (or ``MVP_PUBLIC_MODE=1``) the token alone is NOT
      enough: bearer-over-plain-HTTP exposes the token, so the operator
      must additionally acknowledge transport security (see
      ``exposure_acknowledgement``).
    * Malformed ``MVP_API_TOKEN_HASH`` → refuse (would otherwise fail open).
    * No token, ``MVP_ALLOW_UNAUTH=1`` → boot ONLY on a loopback bind.
    * No token, non-loopback bind      → always refuse, even with the
      override — an unauthenticated non-loopback server is never a
      supported configuration.
    * No token, no override            → refuse, with first-run setup help.

    Generate a token with ``python scripts/generate_api_token.py --write-env``.

    Advisory invariants are not affected by this preflight — the
    execution_gate stays LOCKED whether the server starts or not.
    """
    if api_token_hash_malformed():
        raise StartupSecurityError(
            "Refusing to start: MVP_API_TOKEN_HASH is set but malformed "
            "(expected 64 lowercase hex chars = SHA-256). Re-generate with "
            "`python scripts/generate_api_token.py --rotate --write-env`."
        )
    if api_token_required():
        if is_loopback_bind() and not public_mode_requested():
            return
        ack = exposure_acknowledgement()
        if ack is not None:
            return
        raise StartupSecurityError(
            "Refusing to start: API_HOST="
            + repr(get_api_host())
            + (" with MVP_PUBLIC_MODE=1" if public_mode_requested() else "")
            + " exposes the API beyond loopback, and a bearer token over "
            "plain HTTP is readable by anyone on the network path. "
            "Acknowledge transport security with ONE of: "
            "MVP_TLS_TERMINATED=1 (TLS reverse proxy/tunnel in front), "
            "MVP_TRUSTED_PROXIES=<proxy-ip-list> (declared reverse proxy), "
            "MVP_PUBLISHED_BIND=127.0.0.1 (container port mapped to host "
            "loopback), or the deliberate escape hatch "
            "MVP_UNSAFE_LAN_HTTP=" + _UNSAFE_LAN_ACK + "."
        )
    if _bool_env("MVP_ALLOW_UNAUTH", False) and is_loopback_bind():
        return
    if not is_loopback_bind():
        raise StartupSecurityError(
            "Refusing to start: API_HOST="
            + repr(get_api_host())
            + " is non-loopback but no owner token is set. "
            "Set MVP_API_TOKEN_HASH and bind API_HOST=127.0.0.1. "
            "Unauthenticated non-loopback operation is not supported."
        )
    raise StartupSecurityError(
        "Refusing to start: no owner token is configured (neither "
        "MVP_API_TOKEN_HASH nor legacy MVP_API_TOKEN). This MVP is "
        "owner-only and fails closed by default. First-run setup: run "
        "`python scripts/generate_api_token.py --write-env` to store a "
        "token hash in your local .env, then restart. To explicitly run an "
        "UNAUTHENTICATED loopback-only dev server instead, set "
        "MVP_ALLOW_UNAUTH=1."
    )


def unauth_override_active() -> bool:
    """True iff the operator explicitly bypassed S1 preflight via MVP_ALLOW_UNAUTH=1."""
    return _bool_env("MVP_ALLOW_UNAUTH", False) and not api_token_required()


# DNS-rebinding defense: a malicious website can rebind its own hostname to
# 127.0.0.1 and issue same-origin requests against a loopback-bound API from
# the owner's browser (CORS does not apply — the browser believes it is
# same-origin).  Validating the Host header kills that class of attack.
_DEFAULT_ALLOWED_HOSTS = (
    "localhost",
    "127.0.0.1",
    "[::1]",
    "::1",
    "sleepingpassenger",
    "sleepingpassenger.local",
    # starlette/httpx TestClient default base URL host.
    "testserver",
)


def get_allowed_hosts() -> frozenset[str]:
    """Host-header allowlist (lowercase, no port).

    ``MVP_ALLOWED_HOSTS`` is a comma-separated override; the configured
    ``API_HOST`` bind address is always included so a deliberate LAN bind
    (with a token) keeps working without extra configuration.
    """
    raw = os.environ.get("MVP_ALLOWED_HOSTS", "").strip()
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()} if raw else set(
        _DEFAULT_ALLOWED_HOSTS
    )
    hosts.add(get_api_host().strip().lower())
    return frozenset(hosts)


def host_header_allowed(host_header: str | None) -> bool:
    """True iff the request's Host header names an allowed host.

    Port suffixes are stripped (``localhost:8000`` → ``localhost``); IPv6
    bracket forms are matched both with and without brackets.  A missing
    Host header fails closed.
    """
    if not host_header or not host_header.strip():
        return False
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8000 → [::1]
        host = host.split("]", 1)[0] + "]"
    elif ":" in host:
        host = host.split(":", 1)[0]
    allowed = get_allowed_hosts()
    return host in allowed or host.strip("[]") in allowed


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


def rate_limit_expensive_max_requests() -> int:
    """I3 fix: stricter cap on the expensive read endpoints.

    Defaults to 1/3 of the standard read cap so a single client can't
    DoS the entire server by hammering ``/exports/*.csv`` or
    ``/diagnostics/cockpit``.  Override with
    ``MVP_RATE_LIMIT_EXPENSIVE_MAX_REQUESTS``.
    """
    standard = rate_limit_max_requests()
    return _positive_int_env(
        "MVP_RATE_LIMIT_EXPENSIVE_MAX_REQUESTS", max(1, standard // 3)
    )


def bootstrap_symbol_quota() -> int:
    """I2 fix: hard cap on bootstrap-symbol calls per process.

    Default 50 per process lifetime; override with
    ``MVP_BOOTSTRAP_SYMBOL_QUOTA``.  Setting 0 disables the route.
    """
    raw = os.environ.get("MVP_BOOTSTRAP_SYMBOL_QUOTA", "").strip()
    if not raw:
        return 50
    try:
        return max(0, int(raw))
    except ValueError:
        return 50


def bootstrap_symbol_denylist() -> frozenset[str]:
    """I2 fix: explicit per-symbol denylist for the bootstrap route.

    Set ``MVP_BOOTSTRAP_SYMBOL_DENYLIST`` to a comma-separated list of
    symbols (case-insensitive) that should be refused.  Useful for
    blocking symbols an operator has identified as Yahoo-rate-limit
    triggers or known-bad data.
    """
    raw = os.environ.get("MVP_BOOTSTRAP_SYMBOL_DENYLIST", "").strip()
    if not raw:
        return frozenset()
    return frozenset(
        s.strip().upper() for s in raw.split(",") if s.strip()
    )


def get_trusted_proxies() -> frozenset[str]:
    """Return the explicit allowlist of upstream proxy IPs.

    S3 fix: only IPs in this set are allowed to set ``X-Forwarded-For``
    on behalf of a real client.  Empty by default — the limiter ignores
    proxy headers unless an operator declares the upstream IP.

    Env var ``MVP_TRUSTED_PROXIES`` is comma-separated.  Loopback is
    always trusted (uvicorn + a local reverse proxy is the common case).
    """
    base = {"127.0.0.1", "::1"}
    raw = os.environ.get("MVP_TRUSTED_PROXIES", "").strip()
    if raw:
        for entry in raw.split(","):
            entry = entry.strip()
            if entry:
                base.add(entry)
    return frozenset(base)


def clamp_limit(
    value: int | None, *, default: int, ceiling: int, floor: int = 1
) -> int:
    """L4 fix: bound list-endpoint ``limit`` and ``hours`` params.

    Behaviour:
      * None / non-numeric → default.
      * Negative → floor (default 1).
      * Greater than ceiling → ceiling.
      * Otherwise the value unchanged.

    Pure helper so every route can wrap raw query-string ints with one
    call:  ``limit = clamp_limit(limit, default=100, ceiling=500)``.
    """
    if value is None:
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < floor:
        return floor
    if n > ceiling:
        return ceiling
    return n


def extract_client_ip(direct_host: str | None, forwarded_for: str | None) -> str:
    """Resolve the real client IP for rate-limit keying.

    S3 fix: previously the limiter keyed on ``request.client.host``
    directly, so behind any reverse proxy every client looked identical.

    Rules:
      * If the direct host is in ``get_trusted_proxies``, parse the
        left-most entry of ``X-Forwarded-For`` and use that.  This
        matches the de-facto standard for L7 proxies (nginx/traefik).
      * Otherwise use the direct host verbatim.  Untrusted proxies are
        ignored — a client cannot spoof their own X-Forwarded-For.
      * Returns ``"unknown"`` when everything is missing so the limiter
        still has a string key.
    """
    direct = (direct_host or "").strip()
    if not direct:
        return "unknown"
    if direct in get_trusted_proxies() and forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return direct


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
