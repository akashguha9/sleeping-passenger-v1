"""Shared scaffolding for read-only loaders.

All concrete loaders inherit from :class:`BaseLoader` and expose only:
    - fetch(...)     — pull raw payloads from the upstream source
    - read(...)      — alias / file-based variant for offline sources
    - normalize(...) — transform raw payloads into SignalEvent objects

Loaders MUST NOT define any of the forbidden execution methods. The
``__init_subclass__`` hook below raises immediately if a subclass tries.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - requests is in repo deps already
    requests = None  # type: ignore[assignment]


FORBIDDEN_METHODS = frozenset(
    {
        "place_order",
        "modify_order",
        "cancel_order",
        "redeem_position",
        "submit_order",
        "execute_trade",
        "buy",
        "sell",
        "long",
        "short",
        "auto_buy",
        "auto_sell",
    }
)

DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 3


@dataclass
class LoaderResult:
    """Uniform return type for a loader run."""

    source_name: str
    status: str  # "ok" | "skipped" | "error"
    events: list[Any] = field(default_factory=list)
    skipped_reason: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "event_count": len(self.events),
            "skipped_reason": self.skipped_reason,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseLoader:
    """Base class for every read-only loader.

    Subclasses set ``source_name`` and ``source_type`` and implement
    ``fetch``, ``read`` (optional), and ``normalize``.
    """

    source_name: str = "base"
    source_type: str = "unknown"
    read_only: bool = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        forbidden = FORBIDDEN_METHODS.intersection(vars(cls).keys())
        if forbidden:
            raise TypeError(
                f"Loader {cls.__name__} declares forbidden execution methods: {sorted(forbidden)}"
            )
        if not getattr(cls, "read_only", True):
            raise TypeError(f"Loader {cls.__name__} must remain read_only=True")

    # ----- HTTP helper -------------------------------------------------------

    def _http_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> Any:
        if requests is None:  # pragma: no cover - defensive
            raise RuntimeError("requests is not installed")
        last_err: str | None = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    if "application/json" in resp.headers.get("Content-Type", ""):
                        return resp.json()
                    try:
                        return resp.json()
                    except Exception:
                        return resp.text
                if resp.status_code == 429:
                    time.sleep(min(2 ** attempt, 10))
                    last_err = "429 rate limited"
                    continue
                last_err = f"HTTP {resp.status_code}"
                break
            except Exception as exc:  # pragma: no cover - network errors
                last_err = str(exc)
                time.sleep(min(2 ** attempt, 10))
        raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_err}")

    # ----- Skip / env helpers -----------------------------------------------

    @staticmethod
    def env(name: str) -> str | None:
        val = os.environ.get(name)
        return val.strip() if val and val.strip() else None

    def skip(self, reason: str, **metadata: Any) -> LoaderResult:
        return LoaderResult(
            source_name=self.source_name, status="skipped", skipped_reason=reason, metadata=metadata
        )

    def fail(self, error: str, **metadata: Any) -> LoaderResult:
        return LoaderResult(
            source_name=self.source_name, status="error", error=error, metadata=metadata
        )

    def ok(self, events: list[Any], **metadata: Any) -> LoaderResult:
        return LoaderResult(
            source_name=self.source_name, status="ok", events=events, metadata=metadata
        )

    # ----- API surface (subclasses override) --------------------------------

    def fetch(self, *args: Any, **kwargs: Any) -> LoaderResult:
        raise NotImplementedError

    def read(self, *args: Any, **kwargs: Any) -> LoaderResult:
        return self.fetch(*args, **kwargs)

    def normalize(self, raw: Any) -> Any:
        raise NotImplementedError
