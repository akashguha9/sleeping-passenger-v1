"""Objective 9 — source freshness / canonical-truth contract (pure).

Makes "is this source actually LIVE?" impossible to fake by separating provider
API health from *canonical fresh rows*:

    LIVE_CANONICAL_s = I(api_health in {OK, LIVE_VERIFIED})
                     · I(rows_added > 0)
                     · I(age_hours <= TTL)
                     · I(mock_flag == false)
                     · I(not backfill_only)

    If api_health == OK but rows_added == 0:
        canonical_signal_status = ZERO_FRESH_ROWS  (DEGRADED, never LIVE)

    freshness_s = exp(-age_hours / TTL)
    row_score_s = min(1, rows_added / rows_min)
    C_s         = freshness_s · row_score_s · quality_s

Backfill rows (historical OHLCV reloads) and mock rows NEVER count as fresh
canonical rows.  Filtered-but-healthy fetches are OK_FILTERED/DEGRADED, not
LIVE_CANONICAL.

This is a pure contract.  Wiring it as the single source of truth inside
``live_source_registry`` is a follow-up — see ``TODO(freshness-contract wiring)``.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

# Canonical status labels.
LIVE_CANONICAL = "LIVE_CANONICAL"
ZERO_FRESH_ROWS = "ZERO_FRESH_ROWS"
OK_FILTERED = "OK_FILTERED"
STALE = "STALE"
MOCK_NON_CANONICAL = "MOCK_NON_CANONICAL"
BACKFILL_NON_FRESH = "BACKFILL_NON_FRESH"
DEGRADED = "DEGRADED"
UNHEALTHY = "UNHEALTHY"

_HEALTHY_API = {"OK", "LIVE_VERIFIED"}
# Statuses that are NEVER live regardless of row count.
_NON_LIVE_CANONICAL = {
    ZERO_FRESH_ROWS, OK_FILTERED, STALE, MOCK_NON_CANONICAL,
    BACKFILL_NON_FRESH, DEGRADED, UNHEALTHY,
}

DEFAULT_TTL_HOURS: float = 24.0
DEFAULT_ROWS_MIN: int = 1


def freshness_score(age_hours: float | None, ttl_hours: float = DEFAULT_TTL_HOURS) -> float:
    """exp(-age/ttl); 0 when age is unknown."""
    if age_hours is None or ttl_hours <= 0:
        return 0.0
    return math.exp(-max(0.0, age_hours) / ttl_hours)


def row_score(rows_added: int, rows_min: int = DEFAULT_ROWS_MIN) -> float:
    if rows_min <= 0:
        rows_min = 1
    return min(1.0, max(0, rows_added) / rows_min)


def classify_canonical_status(
    *,
    api_health_status: str,
    rows_added: int,
    age_hours: float | None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    mock_flag: bool = False,
    backfill_only: bool = False,
    filtered: bool = False,
) -> dict[str, Any]:
    """Return the canonical signal status, separated from API health.

    A source is ``LIVE_CANONICAL`` only when EVERY condition holds; otherwise
    the most specific non-live label is returned.
    """
    api = str(api_health_status or "").strip().upper()
    api_ok = api in _HEALTHY_API
    fresh = age_hours is not None and age_hours <= ttl_hours

    # Resolve the most specific NON-live reason first.
    if not api_ok:
        status = UNHEALTHY
    elif mock_flag:
        status = MOCK_NON_CANONICAL
    elif rows_added <= 0:
        # Healthy API but zero canonical rows -> degraded, never live.
        status = ZERO_FRESH_ROWS
    elif backfill_only:
        status = BACKFILL_NON_FRESH
    elif filtered:
        status = OK_FILTERED
    elif not fresh:
        status = STALE
    else:
        status = LIVE_CANONICAL

    is_live = status == LIVE_CANONICAL
    quality = 0.0 if (mock_flag or backfill_only) else 1.0
    c_s = freshness_score(age_hours, ttl_hours) * row_score(rows_added) * quality if is_live else 0.0

    return {
        "api_health_status": api,
        "api_health_ok": api_ok,
        "canonical_signal_status": status,
        "live_canonical": is_live,
        "rows_added": rows_added,
        "age_hours": age_hours,
        "ttl_hours": ttl_hours,
        "fresh": bool(fresh),
        "mock_flag": bool(mock_flag),
        "backfill_only": bool(backfill_only),
        "filtered": bool(filtered),
        "freshness_score": round(freshness_score(age_hours, ttl_hours), 6),
        "row_score": round(row_score(rows_added), 6),
        "C_s": round(c_s, 6),
    }


def is_live_canonical(**kwargs: Any) -> bool:
    return classify_canonical_status(**kwargs)["live_canonical"]


# TODO(freshness-contract wiring): adopt classify_canonical_status() as the
# single canonical-status reducer inside live_source_registry so the registry,
# watchdog, and UI can never disagree on LIVE vs DEGRADED.


__all__ = [
    "LIVE_CANONICAL",
    "ZERO_FRESH_ROWS",
    "OK_FILTERED",
    "STALE",
    "MOCK_NON_CANONICAL",
    "BACKFILL_NON_FRESH",
    "DEGRADED",
    "UNHEALTHY",
    "DEFAULT_TTL_HOURS",
    "freshness_score",
    "row_score",
    "classify_canonical_status",
    "is_live_canonical",
]
