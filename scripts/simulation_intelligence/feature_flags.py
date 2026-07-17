"""Feature flags + resource limits for the Simulation Intelligence Layer.

Every heavyweight or optional capability sits behind a flag that is OFF by
default.  The base Sleeping Passenger workflow — and the SIL council itself —
runs fully with every optional engine unavailable.

Flags (all read from the environment; all safe defaults):

* ``SIL_ENABLED``            — master switch for the SIL API surface (default ON;
                              set to 0 to fail-closed the whole layer).
* ``SIL_STOCKFISH_ENABLED``  — allow the optional Stockfish EXTERNAL_PROCESS
                              adapter (default OFF).  Never on the default path.
* ``SIL_COPASI_ENABLED``     — allow the optional COPASI/basico NATIVE_LIBRARY
                              adapter (default OFF).
* ``SIL_MAX_RUNS``           — hard cap on Monte-Carlo samples per lens.
* ``SIL_MAX_SCENARIOS``      — hard cap on scenarios per request.
* ``SIL_TIMEOUT_MS``         — soft per-lens wall-clock budget (advisory; the
                              council enforces bounded work regardless).

None of these grants execution permission.  They only gate *simulation*
breadth and optional-engine availability.  This module imports nothing beyond
the standard library.
"""
from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def sil_enabled() -> bool:
    """Master switch. Default ON; setting SIL_ENABLED=0 fails the layer closed."""
    return _bool_env("SIL_ENABLED", True)


def stockfish_enabled() -> bool:
    return _bool_env("SIL_STOCKFISH_ENABLED", False)


def copasi_enabled() -> bool:
    return _bool_env("SIL_COPASI_ENABLED", False)


def max_runs() -> int:
    """Hard cap on Monte-Carlo samples per lens (bounded workload)."""
    return _int_env("SIL_MAX_RUNS", 512, minimum=8, maximum=20_000)


def max_scenarios() -> int:
    return _int_env("SIL_MAX_SCENARIOS", 24, minimum=1, maximum=64)


def timeout_ms() -> int:
    return _int_env("SIL_TIMEOUT_MS", 2_000, minimum=100, maximum=30_000)


def snapshot() -> dict[str, object]:
    """Return the current flag state for the /health surface (no secrets)."""
    return {
        "sil_enabled": sil_enabled(),
        "stockfish_enabled": stockfish_enabled(),
        "copasi_enabled": copasi_enabled(),
        "max_runs": max_runs(),
        "max_scenarios": max_scenarios(),
        "timeout_ms": timeout_ms(),
    }


__all__ = [
    "sil_enabled", "stockfish_enabled", "copasi_enabled",
    "max_runs", "max_scenarios", "timeout_ms", "snapshot",
]
