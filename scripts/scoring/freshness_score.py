"""Freshness score: 1.0 right now, decays linearly to 0 over a horizon."""
from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_HORIZON_HOURS = 72.0


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # Accept "...Z" by stripping trailing Z (Python 3.11+ accepts it natively).
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def freshness_score(timestamp_utc: str, horizon_hours: float = DEFAULT_HORIZON_HOURS,
                    now: datetime | None = None) -> float:
    ref = now or datetime.now(timezone.utc)
    parsed = _parse_ts(timestamp_utc)
    if parsed is None:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_h = (ref - parsed).total_seconds() / 3600.0
    if age_h <= 0:
        return 1.0
    return max(0.0, 1.0 - (age_h / max(horizon_hours, 1e-9)))
