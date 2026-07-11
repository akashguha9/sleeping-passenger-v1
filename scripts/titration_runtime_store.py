"""Runtime store for measured titration inputs — cached, defensive, shadow-mode.

Bridges the offline response pipeline (persisted, sample-gated estimates)
into the live inbox decoration path WITHOUT slowing it down:

* susceptibility estimates: loaded once per process every ``CACHE_TTL_S``
  from ``titration_susceptibility_estimates`` and resolved through the
  TICKER → SECTOR → MARKET → GLOBAL → HEURISTIC_PROXY hierarchy;
* recognition inputs: price/volume recognition computed from locally
  imported OHLCV bars, per-ticker cached; a process-wide short-circuit
  skips all bar lookups when the ohlcv_bars table is empty (the common
  case in fresh environments), so the enrichment costs ~nothing when
  there is no data.

Shadow-mode contract: this layer only *injects inputs*.  The engine keeps
its heuristic proxy alongside any measured estimate, and the measured
layer can never grant execution permission.  Every failure degrades to
None (the engine then reports HEURISTIC_PROXY / missing inputs honestly).
"""

from __future__ import annotations

import time
from typing import Any

try:
    from scripts import persistence
    from scripts.titration_recognition import compute_recognition_inputs
    from scripts.titration_susceptibility import (
        market_for_ticker,
        resolve_susceptibility,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence  # type: ignore[no-redef]
    from titration_recognition import compute_recognition_inputs  # type: ignore[no-redef]
    from titration_susceptibility import (  # type: ignore[no-redef]
        market_for_ticker,
        resolve_susceptibility,
    )

CACHE_TTL_S = 300.0
# Operational horizon (trading days) used for live susceptibility lookups.
OPERATIONAL_HORIZON = 5

_estimates_cache: dict[str, Any] = {"at": 0.0, "rows": None}
_ohlcv_empty_cache: dict[str, Any] = {"at": 0.0, "empty": None}
_bars_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_security_cache: dict[str, tuple[float, tuple[str, str | None]]] = {}


def clear_caches() -> None:
    """Explicit cache invalidation (used by tests and the pipeline CLI)."""
    _estimates_cache.update({"at": 0.0, "rows": None})
    _ohlcv_empty_cache.update({"at": 0.0, "empty": None})
    _bars_cache.clear()
    _security_cache.clear()


def _load_estimates() -> list[dict[str, Any]]:
    now = time.monotonic()
    if (
        _estimates_cache["rows"] is not None
        and now - _estimates_cache["at"] < CACHE_TTL_S
    ):
        return _estimates_cache["rows"]
    try:
        # Resolve DB_PATH lazily via the module attribute so test fixtures
        # that monkeypatch persistence.DB_PATH are honored (several
        # persistence functions bind their default eagerly).
        rows = persistence.get_titration_susceptibility_estimates(
            db_path=persistence.DB_PATH
        )
    except Exception:
        rows = []
    _estimates_cache.update({"at": now, "rows": rows})
    return rows


def _security_context(ticker: str) -> tuple[str, str | None]:
    now = time.monotonic()
    cached = _security_cache.get(ticker)
    if cached and now - cached[0] < CACHE_TTL_S:
        return cached[1]
    country = None
    sector = None
    try:
        sec = persistence.get_global_security(ticker, db_path=persistence.DB_PATH)
        if isinstance(sec, dict):
            country = sec.get("country") or None
            sector = (sec.get("sector") or "").strip() or None
    except Exception:
        pass
    result = (market_for_ticker(ticker, country), sector)
    _security_cache[ticker] = (now, result)
    return result


def measured_susceptibility_for(
    ticker: str, *, horizon: int = OPERATIONAL_HORIZON
) -> dict[str, Any] | None:
    """Resolved measured-susceptibility block for the engine, or None.

    Returns the resolve_susceptibility() result flattened with its chosen
    estimate so the engine sees chi_norm / source / fallback_level /
    sample_size / acceleration_class / fallback_path directly.  None when
    the estimate table is empty (fresh environment) — the engine then
    keeps its labelled heuristic proxy.
    """
    t = str(ticker or "").strip().upper()
    if not t:
        return None
    estimates = _load_estimates()
    if not estimates:
        return None
    market, sector = _security_context(t)
    resolved = resolve_susceptibility(
        ticker=t, market=market, sector=sector,
        horizon=horizon, estimates=estimates,
    )
    est = resolved.get("estimate") or {}
    return {
        "source": resolved["source"],
        "fallback_level": resolved["fallback_level"],
        "fallback_path": resolved["fallback_path"],
        "chi_norm": est.get("chi_norm"),
        "slope": est.get("slope"),
        "slope_lo": est.get("slope_lo"),
        "slope_hi": est.get("slope_hi"),
        "n": est.get("n"),
        "was_shrunk": est.get("was_shrunk"),
        "estimator": est.get("estimator"),
        "acceleration_class": est.get("acceleration_class"),
        "horizon": est.get("horizon", horizon),
    }


def _ohlcv_is_empty() -> bool:
    now = time.monotonic()
    if (
        _ohlcv_empty_cache["empty"] is not None
        and now - _ohlcv_empty_cache["at"] < CACHE_TTL_S
    ):
        return bool(_ohlcv_empty_cache["empty"])
    try:
        empty = persistence.count_ohlcv_bars(db_path=persistence.DB_PATH) == 0
    except Exception:
        empty = True
    _ohlcv_empty_cache.update({"at": now, "empty": empty})
    return empty


def recognition_inputs_for(ticker: str) -> dict[str, Any] | None:
    """Price/volume recognition inputs from local OHLCV, or None.

    None means "no independent recognition data" — the engine's VMR then
    reports the overlap warning and PAG confidence is discounted, which is
    exactly the honest degradation."""
    t = str(ticker or "").strip().upper()
    if not t or _ohlcv_is_empty():
        return None
    now = time.monotonic()
    cached = _bars_cache.get(t)
    if cached and now - cached[0] < CACHE_TTL_S:
        bars = cached[1]
    else:
        try:
            bars = persistence.get_ohlcv_bars(t, db_path=persistence.DB_PATH)
        except Exception:
            bars = []
        _bars_cache[t] = (now, bars)
    if not bars:
        return None
    result = compute_recognition_inputs(bars)
    if not result.get("available"):
        return None
    return {
        "price_recognition": result.get("price_recognition"),
        "volume_recognition": result.get("volume_recognition"),
        "estimator": result.get("estimator"),
        "bars_used": result.get("bars_used"),
    }


__all__ = [
    "OPERATIONAL_HORIZON",
    "CACHE_TTL_S",
    "clear_caches",
    "measured_susceptibility_for",
    "recognition_inputs_for",
]
