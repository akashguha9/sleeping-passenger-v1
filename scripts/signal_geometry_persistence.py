"""
Signal-geometry persistence — thin SQLite wiring for the *pure* reflection layer.

``scripts/signal_geometry_reflection.py`` is, by contract (see its docstring
and the FORBIDDEN_TOKENS / no-side-effect tests), a PURE module: no DB writes,
no filesystem, no broker calls.  We must not change that.  This module is the
deliberately separate, impure boundary that:

  1. calls the pure compute helpers (``build_signal_cell`` and the
     fingerprint hash) on a signal, then
  2. persists the result through scripts/persistence.py's idempotent upserts
     (``duplicate_fingerprints`` and ``signal_cell_index`` tables).

Truth model
-----------
SQLite remains canonical for the *audit trail* of what fingerprints / cells
have been seen.  The duplicate-fingerprint hint itself is PROBABILISTIC and is
never treated as canonical truth about a trade — moltbook_entries /
manual_trades stay the canonical record.  Nothing here authorizes execution.

Idempotency
-----------
Re-persisting the same fingerprint or the same signal cell increments
``seen_count`` and refreshes ``last_seen_at`` instead of inserting a duplicate
row (handled in persistence.upsert_*).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import scripts.persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]

try:
    from scripts.signal_geometry_reflection import (
        build_signal_cell,
        _signal_fingerprint,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from signal_geometry_reflection import (  # type: ignore[no-redef]
        build_signal_cell,
        _signal_fingerprint,
    )


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _observed_date(signal: dict[str, Any]) -> str:
    raw = (
        signal.get("timestamp")
        or signal.get("event_time")
        or signal.get("occurred_at")
        or signal.get("observed_at")
        or ""
    )
    return _str(raw)[:32]


def persist_duplicate_fingerprint(
    signal: Any,
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Compute and persist the duplicate fingerprint for one signal.

    Returns ``{"fingerprint": str, "is_new": bool, "seen_count": int}``.
    The hint is advisory; SQLite stores only the audit trail.
    """
    data = signal if isinstance(signal, dict) else {}
    fingerprint = _signal_fingerprint(data)
    cell = build_signal_cell(data)
    ticker = ""
    assets = cell.get("asset_tags") or []
    if isinstance(assets, (list, tuple)) and assets:
        ticker = str(assets[0])
    elif _str(data.get("ticker")):
        ticker = _str(data.get("ticker")).upper()
    thesis = _str(data.get("thesis") or data.get("headline") or data.get("title"))
    result = _persistence.upsert_duplicate_fingerprint(
        fingerprint,
        source_type=str(cell.get("source_type") or ""),
        event_type=str(cell.get("event_type") or ""),
        ticker=ticker,
        event_id=_str(data.get("event_id")),
        observed_date=_observed_date(data),
        thesis_excerpt=thesis,
        db_path=db_path,
    )
    return {"fingerprint": fingerprint, **result}


def persist_signal_cell(
    signal: Any,
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Compute and persist the signal-cell index row for one signal.

    Returns ``{"cell_key": str, "is_new": bool, "seen_count": int}``.
    """
    cell = build_signal_cell(signal)
    assets = cell.get("asset_tags") or []
    asset_tags = ",".join(str(a) for a in assets) if isinstance(assets, (list, tuple)) else _str(assets)
    result = _persistence.upsert_signal_cell(
        str(cell.get("cell_key") or ""),
        source_type=str(cell.get("source_type") or ""),
        jurisdiction=str(cell.get("jurisdiction") or ""),
        geography=str(cell.get("geography") or ""),
        sector=str(cell.get("sector") or ""),
        asset_tags=asset_tags,
        event_type=str(cell.get("event_type") or ""),
        time_bucket=str(cell.get("time_bucket") or ""),
        narrative_cluster=str(cell.get("narrative_cluster") or ""),
        freshness_state=str(cell.get("freshness_state") or "unknown"),
        chaos_score=float(cell.get("chaos_score") or 0.0),
        mvp_state=str(cell.get("mvp_state") or "candidate"),
        db_path=db_path,
    )
    return {"cell_key": cell.get("cell_key"), **result}


def persist_signal_geometry(
    signal: Any,
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Persist both the fingerprint and the signal cell for one signal."""
    return {
        "fingerprint": persist_duplicate_fingerprint(signal, db_path=db_path),
        "signal_cell": persist_signal_cell(signal, db_path=db_path),
        "advisory_only": True,
        "human_review_required": True,
        "canonical_source": "sqlite",
    }


__all__ = [
    "persist_duplicate_fingerprint",
    "persist_signal_cell",
    "persist_signal_geometry",
]
