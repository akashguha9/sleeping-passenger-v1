"""Kalshi live read-only config.

Loads credentials & runtime knobs from ``.env.local`` (and the process
environment) WITHOUT printing or persisting the secret values.  Used by
the read-only live client and the demo smoke script.

Safety contract
---------------
- Read-only operation: ``read_only=True`` is enforced.
- Trading must be explicitly disabled:
  ``enable_trading=False`` AND ``order_placement_enabled=False`` AND
  ``broker_api_called=False``.
- The dataclass ``repr``/``str`` deliberately redact every secret
  (API Key ID, private-key path, file bytes).
- ``logging`` never receives secret values: callers should log via
  :func:`KalshiLiveConfig.sanitized_dict`.
- The private key bytes are loaded lazily and never stored on the dataclass.

This module *must not*:
- print or log the API Key ID
- print or log the private-key file path
- print or log auth headers or signatures
- read or write to ``.env`` (only ``.env.local`` and ``os.environ``)
- modify ``.env.local``
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_LOCAL = REPO_ROOT / ".env.local"

# Endpoint defaults — demo by default.  Production base URLs are only
# returned when ``KALSHI_ENV=prod`` is explicitly set; the smoke script
# never asks for prod.
_DEMO_API_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
_PROD_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Allowed display slugs (mirrors scripts.kalshi_category_governance).  Kept
# duplicated here so the config module has no import-time dependency on the
# governance module (avoids a cycle if the loader is imported early).
_DEFAULT_ALLOWED_CATEGORIES: tuple[str, ...] = (
    "elections",
    "politics",
    "crypto",
    "commodities",
    "economics",
    "finance",
    "tech_science",
)

_TRUE_VALUES = {"1", "true", "yes", "on", "TRUE", "YES", "ON", "True", "Yes", "On"}


class KalshiConfigError(RuntimeError):
    """Raised when live mode is requested but config is incomplete/unsafe."""


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return default
    return text in _TRUE_VALUES


def load_env_local(
    path: Path | str | None = None,
    *,
    override: bool = False,
) -> dict[str, str]:
    """Parse ``.env.local`` into a dict.  Never prints values.

    The parser accepts simple ``KEY=VALUE`` lines.  Comments (``#``),
    blank lines, and quoted values are tolerated.  When ``override`` is
    False (the default), values already present in ``os.environ`` win.
    Returns the *parsed file* mapping (the in-memory dict), regardless of
    whether each key was promoted into ``os.environ``.
    """
    src = Path(path) if path else DEFAULT_ENV_LOCAL
    parsed: dict[str, str] = {}
    if not src.exists():
        return parsed
    try:
        raw = src.read_text(encoding="utf-8")
    except OSError:
        return parsed
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Strip a single set of matching quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        parsed[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return parsed


@dataclass(frozen=True)
class KalshiLiveConfig:
    """Read-only Kalshi live config.

    Frozen dataclass — instances cannot be mutated to weaken a flag.

    Secrets stored on the dataclass:
    - ``api_key_id``: present only because it is required to sign
      requests.  ``__repr__`` and ``sanitized_dict`` redact it.
    - ``private_key_path``: filesystem location only; bytes are never
      kept here.
    """

    env: str
    api_base_url: str
    ws_base_url: str
    api_key_id: str
    private_key_path: str
    enable_auth: bool
    read_only: bool
    enable_trading: bool
    order_placement_enabled: bool
    broker_api_called: bool
    use_mock_fixtures: bool
    live_verify: bool
    freshness_ttl_seconds: int
    allowed_categories: tuple[str, ...]

    # ------------------------------------------------------------------
    # Redacted representations
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover - exercised by tests
        return (
            "KalshiLiveConfig("
            f"env={self.env!r}, "
            f"api_base_url={self.api_base_url!r}, "
            f"ws_base_url={self.ws_base_url!r}, "
            "api_key_id='<redacted>', "
            "private_key_path='<redacted>', "
            f"enable_auth={self.enable_auth}, "
            f"read_only={self.read_only}, "
            f"enable_trading={self.enable_trading}, "
            f"order_placement_enabled={self.order_placement_enabled}, "
            f"broker_api_called={self.broker_api_called}, "
            f"use_mock_fixtures={self.use_mock_fixtures}, "
            f"live_verify={self.live_verify}, "
            f"freshness_ttl_seconds={self.freshness_ttl_seconds}, "
            f"allowed_categories={self.allowed_categories!r}"
            ")"
        )

    def __str__(self) -> str:  # pragma: no cover - exercised by tests
        return self.__repr__()

    def sanitized_dict(self) -> dict[str, Any]:
        """Public-safe summary suitable for source-health/frontend.

        Excludes the API Key ID, the private-key filesystem path, and
        any auth-derived material.  Exposes only the mode, env, base
        URL, and the safety/policy flags.
        """
        return {
            "env": self.env,
            "api_base_url": self.api_base_url,
            "ws_base_url": self.ws_base_url,
            "auth_used": bool(self.enable_auth and not self.use_mock_fixtures),
            "read_only": self.read_only,
            "enable_trading": self.enable_trading,
            "order_placement_enabled": self.order_placement_enabled,
            "broker_api_called": self.broker_api_called,
            "use_mock_fixtures": self.use_mock_fixtures,
            "live_verify": self.live_verify,
            "freshness_ttl_seconds": self.freshness_ttl_seconds,
            "allowed_categories": list(self.allowed_categories),
        }

    # ------------------------------------------------------------------
    # Safety validation
    # ------------------------------------------------------------------

    def assert_read_only_safe(self) -> None:
        """Raise if any flag would permit a non-read-only operation."""
        violations: list[str] = []
        if not self.read_only:
            violations.append("KALSHI_READ_ONLY must be true")
        if self.enable_trading:
            violations.append("KALSHI_ENABLE_TRADING must be false")
        if self.order_placement_enabled:
            violations.append("KALSHI_ORDER_PLACEMENT_ENABLED must be false")
        if self.broker_api_called:
            violations.append("KALSHI_BROKER_API_CALLED must be false")
        if violations:
            raise KalshiConfigError(
                "Kalshi live config rejected unsafe flags: "
                + "; ".join(violations)
            )

    # ------------------------------------------------------------------
    # Private-key access — bytes returned, never stored on the instance
    # ------------------------------------------------------------------

    def load_private_key_bytes(self) -> bytes:
        """Return the private key file contents as bytes.

        Raises :class:`KalshiConfigError` if the path is missing or
        unreadable.  The bytes are returned to the caller and never
        cached on the dataclass.
        """
        if not self.private_key_path:
            raise KalshiConfigError(
                "KALSHI_PRIVATE_KEY_PATH is not set — cannot load private key."
            )
        key_path = Path(self.private_key_path)
        if not key_path.is_absolute():
            key_path = REPO_ROOT / key_path
        if not key_path.exists():
            raise KalshiConfigError(
                "Kalshi private key file is missing "
                "(path redacted; verify KALSHI_PRIVATE_KEY_PATH)."
            )
        try:
            return key_path.read_bytes()
        except OSError as exc:
            raise KalshiConfigError(
                "Kalshi private key could not be read "
                f"(io error: {type(exc).__name__})."
            ) from exc


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _resolve_base_url(env: str, explicit: str) -> str:
    if explicit:
        return explicit.rstrip("/")
    return (_PROD_API_BASE if env == "prod" else _DEMO_API_BASE).rstrip("/")


def _resolve_ws_url(env: str, explicit: str) -> str:
    if explicit:
        return explicit.rstrip("/")
    if env == "prod":
        return "wss://api.elections.kalshi.com/trade-api/ws/v2"
    return "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"


def _resolve_allowed_categories(value: str | None) -> tuple[str, ...]:
    if not value:
        return _DEFAULT_ALLOWED_CATEGORIES
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return _DEFAULT_ALLOWED_CATEGORIES
    return tuple(parts)


def load_kalshi_live_config(
    *,
    env_local_path: Path | str | None = None,
    environ: dict[str, str] | None = None,
    override_env: bool = False,
) -> KalshiLiveConfig:
    """Load and validate Kalshi live config.

    Reads ``.env.local`` into ``os.environ`` (without overriding existing
    values, unless ``override_env=True``), then constructs the frozen
    :class:`KalshiLiveConfig`.

    ``environ`` lets tests inject a fully isolated mapping without
    touching the real ``os.environ`` — when provided, the loader reads
    values exclusively from it and skips the ``.env.local`` parse.
    """
    if environ is None:
        load_env_local(env_local_path, override=override_env)
        env_source = os.environ
    else:
        env_source = environ

    env = (env_source.get("KALSHI_ENV", "demo") or "demo").strip().lower()
    api_base = _resolve_base_url(env, env_source.get("KALSHI_API_BASE_URL", "").strip())
    ws_base = _resolve_ws_url(env, env_source.get("KALSHI_WS_BASE_URL", "").strip())
    api_key_id = (env_source.get("KALSHI_API_KEY_ID", "") or "").strip()
    private_key_path = (env_source.get("KALSHI_PRIVATE_KEY_PATH", "") or "").strip()
    enable_auth = _coerce_bool(env_source.get("KALSHI_ENABLE_AUTH"), default=False)
    read_only = _coerce_bool(env_source.get("KALSHI_READ_ONLY"), default=True)
    enable_trading = _coerce_bool(env_source.get("KALSHI_ENABLE_TRADING"), default=False)
    order_placement_enabled = _coerce_bool(
        env_source.get("KALSHI_ORDER_PLACEMENT_ENABLED"), default=False
    )
    broker_api_called = _coerce_bool(
        env_source.get("KALSHI_BROKER_API_CALLED"), default=False
    )
    use_mock_fixtures = _coerce_bool(
        env_source.get("KALSHI_USE_MOCK_FIXTURES"), default=False
    )
    live_verify = _coerce_bool(env_source.get("KALSHI_LIVE_VERIFY"), default=False)
    try:
        freshness_ttl_seconds = int(
            env_source.get("KALSHI_FRESHNESS_TTL_SECONDS", "21600") or "21600"
        )
    except ValueError:
        freshness_ttl_seconds = 21600
    allowed_categories = _resolve_allowed_categories(
        env_source.get("KALSHI_ALLOWED_CATEGORIES", "")
    )

    cfg = KalshiLiveConfig(
        env=env,
        api_base_url=api_base,
        ws_base_url=ws_base,
        api_key_id=api_key_id,
        private_key_path=private_key_path,
        enable_auth=enable_auth,
        read_only=read_only,
        enable_trading=enable_trading,
        order_placement_enabled=order_placement_enabled,
        broker_api_called=broker_api_called,
        use_mock_fixtures=use_mock_fixtures,
        live_verify=live_verify,
        freshness_ttl_seconds=freshness_ttl_seconds,
        allowed_categories=allowed_categories,
    )
    cfg.assert_read_only_safe()
    return cfg


__all__ = [
    "KalshiConfigError",
    "KalshiLiveConfig",
    "load_env_local",
    "load_kalshi_live_config",
]
