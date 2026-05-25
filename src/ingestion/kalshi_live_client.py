"""Read-only authenticated Kalshi live client.

Strictly GET-only.  Refuses every trading / portfolio / account / fill /
position / deposit / withdrawal / api_keys endpoint and every non-GET
HTTP method — raises :class:`ReadOnlyKalshiViolation` before any request
is built.

Auth
----
Kalshi signs requests with:

    KALSHI-ACCESS-KEY        = <api_key_id>
    KALSHI-ACCESS-TIMESTAMP  = <unix millis>
    KALSHI-ACCESS-SIGNATURE  = base64( RSA-PSS-SHA256(
                                       timestamp + method + path_without_query
                                     ) )

Query string is *not* part of the signed payload.

Secret handling
---------------
- API Key ID is held only on the underlying ``KalshiLiveConfig`` (which
  redacts it in repr/str) and is never logged.
- Private-key bytes are loaded on construction, parsed once, kept on the
  instance for the signer, and never returned by any public method.
- The ``Authorization``-like headers (``KALSHI-ACCESS-*``) are only ever
  read by the HTTP request itself; no public method exposes them.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import requests

from src.ingestion.kalshi_live_config import KalshiConfigError, KalshiLiveConfig


_LOG = logging.getLogger(__name__)
_USER_AGENT = "sleeping-passenger-mvp/kalshi-readonly (advisory-only)"

# Forbidden endpoint segments — any path that contains one of these
# substrings is rejected before a request is built.  Matched against the
# path (case-insensitive); query strings ignored.
_FORBIDDEN_PATH_SEGMENTS: tuple[str, ...] = (
    "/orders",
    "/order",
    "/portfolio",
    "/fills",
    "/positions",
    "/balance",
    "/trades",
    "/trade-history",
    "/deposits",
    "/withdrawals",
    "/api_keys",
    "/api-keys",
    "/exchange/login",
    "/exchange/logout",
    "/communications",
    "/notifications",
    "/account",
)

# Allowed methods.  Anything else is rejected at the public API.
_ALLOWED_METHODS: frozenset[str] = frozenset({"GET"})

# Read-only endpoints we use.  Note: we still defensively pass every
# request through the forbidden-segment check.
_ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "/exchange/status",
    "/markets",
    "/events",
    "/series",
)


class ReadOnlyKalshiViolation(RuntimeError):
    """Raised whenever the client is asked to perform a non-read-only op."""


def _path_without_query(path: str) -> str:
    """Return the path component used for signing (no query, no fragment)."""
    pure = path.split("?", 1)[0].split("#", 1)[0]
    if not pure.startswith("/"):
        pure = "/" + pure
    return pure


def _check_read_only(method: str, path: str) -> str:
    """Validate ``method``/``path`` against the read-only policy.

    Returns the cleaned (no-query) path on success.  Raises
    :class:`ReadOnlyKalshiViolation` otherwise.
    """
    upper_method = (method or "").upper().strip()
    if upper_method not in _ALLOWED_METHODS:
        raise ReadOnlyKalshiViolation(
            f"HTTP method {upper_method!r} is not permitted by the "
            "read-only Kalshi client."
        )
    pure = _path_without_query(path)
    lowered = pure.lower()
    for needle in _FORBIDDEN_PATH_SEGMENTS:
        if needle in lowered:
            # Do not echo the full path in the message — keeps potentially
            # sensitive identifiers out of logs/exceptions.
            raise ReadOnlyKalshiViolation(
                "Kalshi endpoint is on the read-only blocklist "
                f"(segment={needle!r})."
            )
    return pure


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def build_signing_string(timestamp_ms: int, method: str, path: str) -> str:
    """Return the canonical pre-signature string.

    Format: ``f"{ts}{METHOD}{path_without_query}"`` — matches Kalshi's
    documented signing recipe.  Query string is intentionally excluded.
    """
    return f"{int(timestamp_ms)}{method.upper()}{_path_without_query(path)}"


def load_private_key(pem_bytes: bytes):
    """Parse a PEM private key.  Supports PKCS#1 and PKCS#8."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as exc:  # pragma: no cover - dev env has cryptography
        raise KalshiConfigError(
            f"cryptography library required for live Kalshi auth: {exc}"
        ) from exc
    try:
        return load_pem_private_key(pem_bytes, password=None)
    except Exception as exc:
        # Never echo key contents in the error.
        raise KalshiConfigError(
            f"Kalshi private key parse failed ({type(exc).__name__})."
        ) from exc


def sign_request(private_key: Any, timestamp_ms: int, method: str, path: str) -> str:
    """Produce the base64 RSA-PSS-SHA256 signature for one request."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover
        raise KalshiConfigError(
            f"cryptography library required for live Kalshi auth: {exc}"
        ) from exc
    payload = build_signing_string(timestamp_ms, method, path).encode("utf-8")
    signature = private_key.sign(
        payload,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class KalshiLiveClient:
    """Authenticated, read-only Kalshi live API client.

    Construct with a validated :class:`KalshiLiveConfig`.  Use only the
    public ``get_*`` helpers below — direct ``request()`` access is also
    routed through ``_check_read_only``.
    """

    def __init__(
        self,
        config: KalshiLiveConfig,
        *,
        session: requests.Session | None = None,
        timeout: int = 12,
        private_key_loader: Any = load_private_key,
    ) -> None:
        config.assert_read_only_safe()
        self._cfg = config
        self._session = session or requests.Session()
        self._timeout = int(timeout)
        if config.enable_auth and not config.use_mock_fixtures:
            if not config.api_key_id:
                raise KalshiConfigError(
                    "KALSHI_API_KEY_ID is required when KALSHI_ENABLE_AUTH=true."
                )
            pem_bytes = config.load_private_key_bytes()
            self._private_key = private_key_loader(pem_bytes)
            # Best-effort overwrite of the local PEM reference.  Python
            # cannot zero memory deterministically, but we can at least
            # drop the reference immediately.
            del pem_bytes
            self._auth_used = True
        else:
            self._private_key = None
            self._auth_used = False

    # ------------------------------------------------------------------
    # Identity / status surface
    # ------------------------------------------------------------------

    @property
    def auth_used(self) -> bool:
        return self._auth_used

    @property
    def base_url(self) -> str:
        return self._cfg.api_base_url

    def sanitized_status(self) -> dict[str, Any]:
        """Public-safe status (used by source-health).  No secrets."""
        status = self._cfg.sanitized_dict()
        status["auth_used"] = self._auth_used
        return status

    # ------------------------------------------------------------------
    # Low-level request — enforces method + path policy
    # ------------------------------------------------------------------

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        if not self._auth_used or self._private_key is None:
            return {}
        timestamp_ms = int(time.time() * 1000)
        signature = sign_request(self._private_key, timestamp_ms, method, path)
        return {
            "KALSHI-ACCESS-KEY": self._cfg.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        """Execute a GET against an allowed read-only endpoint.

        Any non-GET method or any path containing a forbidden segment
        raises :class:`ReadOnlyKalshiViolation` *before* a request is
        built.
        """
        clean_path = _check_read_only(method, path)
        url = f"{self._cfg.api_base_url}{clean_path}"
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }
        headers.update(self._auth_headers(method, clean_path))
        # Never log headers — auth material would leak.
        _LOG.debug("kalshi_live_request method=%s path=%s", method, clean_path)
        response = self._session.get(
            url,
            params=params,
            headers=headers,
            timeout=self._timeout,
        )
        return response

    def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self.request("GET", path, params=params)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Read-only helpers — these are the only endpoints we use
    # ------------------------------------------------------------------

    def get_exchange_status(self) -> dict[str, Any]:
        return self.get_json("/exchange/status")

    def get_markets(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        status: str = "open",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": int(limit), "status": status}
        if cursor:
            params["cursor"] = cursor
        return self.get_json("/markets", params=params)

    def get_events(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": int(limit)}
        if cursor:
            params["cursor"] = cursor
        return self.get_json("/events", params=params)

    def get_event(self, event_ticker: str) -> dict[str, Any]:
        if not event_ticker:
            raise ValueError("event_ticker is required")
        return self.get_json(f"/events/{event_ticker}")

    def get_series(self, series_ticker: str) -> dict[str, Any]:
        if not series_ticker:
            raise ValueError("series_ticker is required")
        return self.get_json(f"/series/{series_ticker}")


__all__ = [
    "ReadOnlyKalshiViolation",
    "KalshiLiveClient",
    "build_signing_string",
    "sign_request",
    "load_private_key",
]
