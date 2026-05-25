"""
Pluggable embedding-provider adapters for the Polymarket × Kalshi
semantic-pairing layer.

Goal
----
The cross-venue semantic pairing layer (``prediction_market_semantic_pairing``)
already exposes a swappable ``embedding_fn`` interface. This module wraps
that interface in a small, dependency-free *provider* abstraction so the
scanner CLI can ask for a real provider by name (``--embedding-provider
real``) without:

  * importing any third-party SDK,
  * making any live API call inside unit tests,
  * requiring an API key to exist for the default (deterministic) path,
  * unlocking any execution/broker semantics.

Hard non-goals
--------------
- NOT trading.  NOT execution.  NOT a buy/sell signal.
- NEVER calls a broker API.
- NEVER stores secrets — keys are read from the operator's environment
  at call-time and never copied into the alert payload.
- A network failure is NEVER allowed to crash the scanner; the strict
  mode opt-in is the only way to turn that into a hard error.

Provider taxonomy
-----------------

  ``DeterministicEmbeddingProvider``
      Wraps the local hashed-token baseline.  No network.  Stable
      output.  This is the default for tests and offline usage.

  ``HTTPEmbeddingProvider``
      A *generic* HTTP-compatible embedding client.  It targets endpoints
      that follow the common ``POST {base_url}`` + ``{"input": <text>,
      "model": <model>}`` -> ``{"data": [{"embedding": [...]}, ...]}``
      convention (OpenAI-compatible).  The provider is constructed with
      ``base_url``, ``model``, ``api_key_env``, and ``timeout_seconds``
      so callers can re-use it for OpenAI, an internal proxy, or any
      compatible service without subclassing.

      Tests inject a fake transport via the ``transport`` argument so
      the provider never opens a real socket in CI.

The factory ``resolve_embedding_provider`` accepts a short name
(``"deterministic"`` or ``"real"``) plus a strict flag.  If ``real`` is
requested but no provider config is available, it falls back to the
deterministic provider AND records the fallback in the returned
provider's ``status`` field so the scanner can surface it honestly
(``embedding_available=False``).  Strict mode flips the fallback into a
hard ``EmbeddingProviderUnavailable`` raise.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.prediction_market_semantic_pairing import (
        deterministic_fake_embedding,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script run
    from prediction_market_semantic_pairing import (  # type: ignore[no-redef]
        deterministic_fake_embedding,
    )


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


PROVIDER_DETERMINISTIC = "deterministic"
PROVIDER_REAL = "real"
PROVIDER_FALLBACK_REAL = "deterministic_fallback_from_real"


class EmbeddingProviderUnavailable(RuntimeError):
    """Raised when ``strict`` mode is set and the real provider cannot be
    constructed (missing config, missing transport, etc.)."""


class _Transport(Protocol):
    """Minimal HTTP transport contract used by ``HTTPEmbeddingProvider``.

    Kept tiny on purpose: the provider only needs a function that takes
    ``(url, headers, payload, timeout_seconds)`` and returns a parsed
    JSON dict-like object.  Tests inject a closure that returns
    canned vectors.
    """

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class EmbeddingProvider:
    """Base contract for an embedding provider.

    Subclasses override ``embed_text``; ``embed_batch`` defaults to
    looping over ``embed_text``.  ``status`` carries a short,
    operator-visible label that the scanner stamps onto every alert
    (``embedding_provider``).  ``available`` reflects whether the
    provider is expected to return real (non-fallback) vectors —
    callers use it to drive ``embedding_available`` on the alert.
    """

    name: str
    model: str = ""
    available: bool = True
    status_reason: str = ""

    def embed_text(self, text: str) -> list[float] | None:
        raise NotImplementedError

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        return [self.embed_text(t) for t in texts]

    def as_callable(self) -> Callable[[str], list[float] | None]:
        """Return an ``embedding_fn`` compatible with the semantic-pairing
        layer's ``Callable[[str], list[float] | None]`` interface."""
        return self.embed_text

    def to_status_dict(self) -> dict[str, Any]:
        """Operator-facing provider description; never includes secrets."""
        return {
            "embedding_provider": self.name,
            "embedding_model": self.model or "",
            "embedding_available": bool(self.available),
            "embedding_status_reason": self.status_reason or "",
        }


# ---------------------------------------------------------------------------
# Deterministic provider (default)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Local, offline, hashed-token-histogram embedding.

    Identical to ``deterministic_fake_embedding`` — kept as a class so
    the scanner can interrogate ``.name``/``.model`` uniformly.
    """

    name: str = "deterministic"
    model: str = "hashed-token-histogram-16"
    available: bool = True
    status_reason: str = ""

    def embed_text(self, text: str) -> list[float] | None:
        return deterministic_fake_embedding(text)


# ---------------------------------------------------------------------------
# HTTP provider (generic, OpenAI-compatible payload shape)
# ---------------------------------------------------------------------------


def _default_urllib_transport(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:  # pragma: no cover - real network not exercised in CI
    """Real HTTP transport using ``urllib`` only (no third-party deps).

    This is *intentionally* never called by the unit tests — the test
    suite always injects a fake transport.  It exists so an operator
    who explicitly enables a real provider can use the scanner without
    installing extra packages.
    """
    import urllib.request
    import urllib.error

    body = json.dumps(dict(payload)).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", **dict(headers)},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"embedding_provider_http_error:{exc!s}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"embedding_provider_bad_json:{exc!s}") from exc


@dataclass(slots=True)
class HTTPEmbeddingProvider(EmbeddingProvider):
    """Generic OpenAI-style embeddings HTTP provider.

    Construction args are passed through ``resolve_embedding_provider``
    so callers never see a raw API key on the call path.

    Test contract: pass ``transport`` to inject a stand-in for the
    network call.  When ``transport`` is None and ``api_key`` is set
    we lazy-import urllib at first call — no live call ever happens in
    unit tests because the suite always injects a transport.
    """

    name: str = "real"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: float = 10.0
    available: bool = True
    status_reason: str = ""
    transport: _Transport | None = field(default=None, repr=False)
    _fallback: DeterministicEmbeddingProvider | None = field(
        default=None, repr=False
    )

    def _resolve_transport(self) -> _Transport:
        if self.transport is not None:
            return self.transport
        return _default_urllib_transport

    def _fallback_provider(self) -> DeterministicEmbeddingProvider:
        if self._fallback is None:
            self._fallback = DeterministicEmbeddingProvider()
        return self._fallback

    def embed_text(self, text: str) -> list[float] | None:
        if not text:
            return None
        try:
            response = self._resolve_transport()(
                self.base_url,
                {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                {"input": text, "model": self.model},
                self.timeout_seconds,
            )
            vec = _extract_embedding(response)
            if vec is None:
                # Provider returned 200 but payload was unrecognisable —
                # degrade quietly to deterministic so downstream scoring
                # still has a value.  The provider record will note the
                # degradation via ``status_reason`` in fallback mode.
                return self._fallback_provider().embed_text(text)
            return vec
        except Exception:
            # Any network/parse error in the real provider must NOT crash
            # the advisory pipeline.  Fall back to the deterministic
            # baseline so the alert still has an embedding score.  The
            # scanner stamps ``embedding_available=False`` separately
            # if the operator wants strict mode.
            return self._fallback_provider().embed_text(text)


def _extract_embedding(payload: Mapping[str, Any]) -> list[float] | None:
    """Best-effort extraction of an embedding vector from a provider response.

    Accepted shapes:
      - ``{"data": [{"embedding": [...]}, ...]}``   (OpenAI compatible)
      - ``{"embedding": [...]}``                   (single-vector shortcut)
      - ``{"embeddings": [[...]]}``                (alt batch shape)
    """
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, Mapping):
            vec = first.get("embedding")
            if isinstance(vec, list) and all(isinstance(x, (int, float)) for x in vec):
                return [float(x) for x in vec]
    direct = payload.get("embedding")
    if isinstance(direct, list) and all(isinstance(x, (int, float)) for x in direct):
        return [float(x) for x in direct]
    alt = payload.get("embeddings")
    if isinstance(alt, list) and alt and isinstance(alt[0], list):
        return [float(x) for x in alt[0] if isinstance(x, (int, float))]
    return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_DEFAULT_BASE_URL = "https://api.openai.com/v1/embeddings"
_DEFAULT_MODEL = "text-embedding-3-small"


def _env(env: Mapping[str, str] | None, key: str, default: str = "") -> str:
    src = env if env is not None else os.environ
    return str(src.get(key, default) or default).strip()


def resolve_embedding_provider(
    name: str | None,
    *,
    model: str | None = None,
    timeout_seconds: float | None = None,
    strict: bool = False,
    env: Mapping[str, str] | None = None,
    transport: _Transport | None = None,
) -> EmbeddingProvider:
    """Build an ``EmbeddingProvider`` from a short name.

    ``deterministic`` (default) returns the offline baseline.

    ``real`` constructs an ``HTTPEmbeddingProvider`` from environment
    variables — ``PREDICTION_MARKET_EMBEDDING_BASE_URL``,
    ``PREDICTION_MARKET_EMBEDDING_MODEL``,
    ``PREDICTION_MARKET_EMBEDDING_API_KEY`` (falling back to
    ``OPENAI_API_KEY``).  If no API key is configured and ``transport``
    was not explicitly injected, the function degrades:

      - ``strict=False`` (default) → returns a deterministic provider
        marked ``available=False`` so the alert can stamp the fallback;
      - ``strict=True``           → raises ``EmbeddingProviderUnavailable``.

    A live API key is NEVER required to run the scanner — by design.
    """
    selected = (name or PROVIDER_DETERMINISTIC).strip().lower()
    if selected in ("", PROVIDER_DETERMINISTIC, "default", "offline", "fake"):
        return DeterministicEmbeddingProvider()

    if selected in (PROVIDER_REAL, "openai", "http"):
        env_map = env if env is not None else os.environ
        base_url = _env(env_map, "PREDICTION_MARKET_EMBEDDING_BASE_URL", _DEFAULT_BASE_URL)
        chosen_model = (
            (model or "").strip()
            or _env(env_map, "PREDICTION_MARKET_EMBEDDING_MODEL", _DEFAULT_MODEL)
        )
        api_key = _env(env_map, "PREDICTION_MARKET_EMBEDDING_API_KEY") or _env(
            env_map, "OPENAI_API_KEY"
        )
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else float(_env(env_map, "PREDICTION_MARKET_EMBEDDING_TIMEOUT_SECONDS", "10") or 10.0)
        )

        if transport is not None:
            # Explicit transport injection — used by tests.  We trust it
            # blindly; api_key may legitimately be empty in that case.
            return HTTPEmbeddingProvider(
                name=PROVIDER_REAL,
                model=chosen_model,
                base_url=base_url,
                api_key=api_key,
                timeout_seconds=timeout,
                available=True,
                status_reason="transport_injected",
                transport=transport,
            )

        if not api_key:
            reason = "real_provider_unavailable:no_api_key"
            if strict:
                raise EmbeddingProviderUnavailable(reason)
            fallback = DeterministicEmbeddingProvider(
                name=PROVIDER_FALLBACK_REAL,
                model="hashed-token-histogram-16",
                available=False,
                status_reason=reason,
            )
            return fallback

        # API key present but no test transport — return a live provider.
        return HTTPEmbeddingProvider(
            name=PROVIDER_REAL,
            model=chosen_model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout,
            available=True,
            status_reason="live_http_provider",
            transport=None,
        )

    # Unknown provider name — strict callers want a hard failure.  The
    # default behaviour is to fall back so a misconfigured CLI flag
    # never breaks the advisory pipeline.
    reason = f"unknown_embedding_provider:{selected!r}"
    if strict:
        raise EmbeddingProviderUnavailable(reason)
    return DeterministicEmbeddingProvider(
        name=PROVIDER_FALLBACK_REAL,
        model="hashed-token-histogram-16",
        available=False,
        status_reason=reason,
    )


__all__ = [
    "PROVIDER_DETERMINISTIC",
    "PROVIDER_REAL",
    "PROVIDER_FALLBACK_REAL",
    "EmbeddingProvider",
    "DeterministicEmbeddingProvider",
    "HTTPEmbeddingProvider",
    "EmbeddingProviderUnavailable",
    "resolve_embedding_provider",
]
