"""Kalshi semantic freshness classifier.

Splits "Kalshi truth" into two orthogonal axes the rest of the system
can read without re-deriving:

  1. API / source-health freshness  -> ``api_health_status``
  2. Canonical signal_events freshness -> ``canonical_signal_status``

Combined into a provider-result enum that ``refresh_live_signals.py``
and the watchdog both consume.  No execution code path; no broker
calls; never logs secrets.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_KALSHI_TTL_HOURS = 6

# api_health_status taxonomy
API_HEALTH_LIVE_VERIFIED = "LIVE_VERIFIED"
API_HEALTH_STALE = "STALE_HEALTH"
API_HEALTH_MISSING = "HEALTH_ARTIFACT_MISSING"
API_HEALTH_AUTH_FAILED = "AUTH_FAILED"
API_HEALTH_API_ERROR = "API_ERROR"
API_HEALTH_UNKNOWN = "UNKNOWN"

# canonical_signal_status taxonomy
CANONICAL_LIVE = "LIVE_CANONICAL"
CANONICAL_DUPLICATE_REFRESHED = "DUPLICATE_REFRESHED"
CANONICAL_ZERO_FRESH_ROWS = "ZERO_FRESH_ROWS"
CANONICAL_FILTERED = "FILTERED"
CANONICAL_HEALTH_ONLY = "HEALTH_ONLY"
CANONICAL_STALE = "STALE_CANONICAL"
CANONICAL_MISSING = "MISSING_CANONICAL"
CANONICAL_UNKNOWN = "UNKNOWN"

# provider_result taxonomy
RESULT_OK_INSERTED = "OK_INSERTED"
RESULT_OK_REFRESHED = "OK_REFRESHED"
RESULT_DEGRADED_ZERO_CANONICAL = "DEGRADED_ZERO_CANONICAL"
RESULT_DEGRADED_FILTERED = "DEGRADED_FILTERED"
RESULT_DEGRADED_HEALTH_ONLY = "DEGRADED_HEALTH_ONLY"
RESULT_ERROR = "ERROR"
RESULT_SKIPPED = "SKIPPED"

_HEALTH_TS_KEYS = ("checked_at_utc", "run_at", "generated_at", "timestamp_utc",
                   "completed_at_utc", "attempted_at_utc")

# Live-verified strings the loader emits (canonical + empty-allowed-scope).
_LIVE_HEALTH_STATUSES = {
    "LIVE_VERIFIED",
    "LIVE_VERIFIED_SOURCE_EMPTY_FOR_ALLOWED_SCOPE",
}
_ERROR_HEALTH_STATUSES = {
    "SOURCE_ERROR",
    "SOURCE_ERROR_TIMEOUT",
    "SOURCE_RATE_LIMITED",
    "SOURCE_ERROR_PRODUCTION_ENV_MISSING",
    "HTTP_ERROR",
}


def _parse_utc(value: Any) -> _dt.datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d


def age_hours(ts: Any, now: _dt.datetime) -> float:
    """Return age in hours; ``+inf`` if unparsable."""
    parsed = _parse_utc(ts)
    if parsed is None:
        return float("inf")
    return max(0.0, (now - parsed).total_seconds() / 3600.0)


def is_fresh(ts: Any, now: _dt.datetime, ttl_hours: float) -> bool:
    return age_hours(ts, now) <= float(ttl_hours)


@dataclass
class HealthArtifact:
    """In-memory view of ``runtime/release/kalshi_source_health.json``."""

    present: bool
    timestamp_utc: str | None
    timestamp_source: str | None  # which field we read, or 'file_mtime_fallback'
    source_freshness_status: str
    records_seen_total: int
    records_allowed: int
    records_quarantined: int
    error_type: str
    auth_used: bool
    raw: dict[str, Any]

    @classmethod
    def empty(cls) -> "HealthArtifact":
        return cls(
            present=False,
            timestamp_utc=None,
            timestamp_source=None,
            source_freshness_status="",
            records_seen_total=0,
            records_allowed=0,
            records_quarantined=0,
            error_type="",
            auth_used=False,
            raw={},
        )


def load_health_artifact(path: Path | str | None) -> HealthArtifact:
    """Load the Kalshi source-health artifact safely.

    Never raises; missing or malformed files return an empty artifact
    so callers can degrade to MISSING / UNKNOWN cleanly.
    """
    if path is None:
        return HealthArtifact.empty()
    p = Path(path)
    if not p.exists():
        return HealthArtifact.empty()
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return HealthArtifact.empty()
    except (OSError, ValueError):
        return HealthArtifact.empty()

    ts_source: str | None = None
    ts_value: str | None = None
    for key in _HEALTH_TS_KEYS:
        v = data.get(key)
        if v:
            ts_value = str(v)
            ts_source = key
            break
    if ts_value is None:
        try:
            mtime = p.stat().st_mtime
            ts_value = _dt.datetime.fromtimestamp(
                mtime, tz=_dt.timezone.utc
            ).isoformat()
            ts_source = "file_mtime_fallback"
        except OSError:
            ts_value = None
            ts_source = None

    return HealthArtifact(
        present=True,
        timestamp_utc=ts_value,
        timestamp_source=ts_source,
        source_freshness_status=str(data.get("source_freshness_status") or ""),
        records_seen_total=int(data.get("records_seen_total") or 0),
        records_allowed=int(data.get("records_allowed") or 0),
        records_quarantined=int(data.get("records_quarantined") or 0),
        error_type=str(data.get("error_type") or ""),
        auth_used=bool(data.get("auth_used")),
        raw=data,
    )


def classify_api_health(
    artifact: HealthArtifact,
    now: _dt.datetime,
    ttl_hours: float,
) -> tuple[str, float | None]:
    """Return ``(api_health_status, api_health_age_hours)``."""
    if not artifact.present:
        return API_HEALTH_MISSING, None
    status_upper = artifact.source_freshness_status.upper()
    age = age_hours(artifact.timestamp_utc, now)
    age_or_none = None if age == float("inf") else round(age, 4)

    if status_upper in _ERROR_HEALTH_STATUSES or "AUTH" in (artifact.error_type or "").upper():
        if "AUTH" in (artifact.error_type or "").upper():
            return API_HEALTH_AUTH_FAILED, age_or_none
        return API_HEALTH_API_ERROR, age_or_none
    if status_upper in _LIVE_HEALTH_STATUSES:
        if age <= ttl_hours:
            return API_HEALTH_LIVE_VERIFIED, age_or_none
        return API_HEALTH_STALE, age_or_none
    if not status_upper:
        return API_HEALTH_UNKNOWN, age_or_none
    if age > ttl_hours:
        return API_HEALTH_STALE, age_or_none
    return API_HEALTH_UNKNOWN, age_or_none


def classify_canonical_signal(
    *,
    canonical_live_count: int,
    latest_canonical_fetched_at: str | None,
    latest_canonical_age_hours: float | None,
    rows_added: int,
    rows_refreshed: int,
    records_seen_total: int,
    records_allowed: int,
    records_quarantined: int,
    source_health_live: bool,
    expected_canonical_write: bool = True,
    ttl_hours: float = DEFAULT_KALSHI_TTL_HOURS,
) -> str:
    """Return the ``canonical_signal_status`` enum value."""
    if int(canonical_live_count or 0) > 0:
        if rows_added == 0 and rows_refreshed > 0:
            return CANONICAL_DUPLICATE_REFRESHED
        return CANONICAL_LIVE
    if not expected_canonical_write and source_health_live:
        return CANONICAL_HEALTH_ONLY
    if (
        records_allowed > 0
        and rows_added == 0
        and rows_refreshed == 0
    ):
        return CANONICAL_ZERO_FRESH_ROWS
    if (
        records_seen_total > 0
        and records_allowed == 0
        and records_quarantined > 0
    ):
        return CANONICAL_FILTERED
    if latest_canonical_fetched_at and (
        latest_canonical_age_hours is None
        or latest_canonical_age_hours > ttl_hours
    ):
        return CANONICAL_STALE
    if not latest_canonical_fetched_at:
        return CANONICAL_MISSING
    return CANONICAL_UNKNOWN


def classify_provider_result(
    *,
    rows_added: int,
    rows_refreshed: int,
    records_seen_total: int,
    records_allowed: int,
    records_quarantined: int,
    canonical_signal_fresh: bool,
    source_health_live: bool,
    expected_canonical_write: bool = True,
    error_present: bool = False,
    skipped: bool = False,
    skipped_reason: str = "",
) -> str:
    if skipped and (skipped_reason or "").strip():
        return RESULT_SKIPPED
    if error_present:
        return RESULT_ERROR
    if rows_added > 0:
        return RESULT_OK_INSERTED
    if rows_added == 0 and rows_refreshed > 0 and canonical_signal_fresh:
        return RESULT_OK_REFRESHED
    if (
        not expected_canonical_write
        and source_health_live
        and not canonical_signal_fresh
    ):
        return RESULT_DEGRADED_HEALTH_ONLY
    if records_seen_total > 0 and records_allowed == 0 and records_quarantined > 0:
        return RESULT_DEGRADED_FILTERED
    if records_allowed > 0 and rows_added + rows_refreshed == 0:
        return RESULT_DEGRADED_ZERO_CANONICAL
    if records_seen_total == 0 and not canonical_signal_fresh:
        return RESULT_DEGRADED_ZERO_CANONICAL
    return RESULT_DEGRADED_ZERO_CANONICAL


def operator_message(
    *,
    api_health_status: str,
    canonical_signal_status: str,
) -> str:
    if api_health_status == API_HEALTH_LIVE_VERIFIED and canonical_signal_status in (
        CANONICAL_LIVE,
        CANONICAL_DUPLICATE_REFRESHED,
    ):
        return (
            "Kalshi API health is LIVE_VERIFIED and canonical live signals "
            "are LIVE_CANONICAL."
        )
    if api_health_status == API_HEALTH_LIVE_VERIFIED and canonical_signal_status == CANONICAL_ZERO_FRESH_ROWS:
        return (
            "Kalshi API health is LIVE_VERIFIED, but canonical live signals "
            "are ZERO_FRESH_ROWS. Accepted markets were seen, but no fresh "
            "signal_events rows were inserted or refreshed."
        )
    if api_health_status == API_HEALTH_LIVE_VERIFIED and canonical_signal_status == CANONICAL_FILTERED:
        return (
            "Kalshi API health is LIVE_VERIFIED, but canonical live signals "
            "are FILTERED because observed markets were quarantined by "
            "allowlist."
        )
    if api_health_status == API_HEALTH_LIVE_VERIFIED and canonical_signal_status == CANONICAL_HEALTH_ONLY:
        return (
            "Kalshi API health is LIVE_VERIFIED; canonical Kalshi signal_events "
            "writes are intentionally not attempted (HEALTH_ONLY)."
        )
    if api_health_status == API_HEALTH_MISSING and canonical_signal_status in (
        CANONICAL_STALE,
        CANONICAL_MISSING,
    ):
        return (
            "Kalshi source-health artifact is missing and canonical live "
            "signals are stale."
        )
    if api_health_status in (API_HEALTH_AUTH_FAILED, API_HEALTH_API_ERROR):
        return (
            f"Kalshi API is {api_health_status}; canonical signal freshness "
            "cannot be guaranteed."
        )
    if api_health_status == API_HEALTH_STALE:
        return (
            "Kalshi source-health artifact is stale; canonical signals "
            f"status={canonical_signal_status}."
        )
    return (
        f"Kalshi api_health={api_health_status} canonical={canonical_signal_status}."
    )


def is_semantic_fresh(api_health_status: str, canonical_signal_status: str) -> bool:
    return (
        api_health_status == API_HEALTH_LIVE_VERIFIED
        or canonical_signal_status in (CANONICAL_LIVE, CANONICAL_DUPLICATE_REFRESHED)
    )


def build_kalshi_truth(
    *,
    health_path: Path | str | None,
    canonical_stats: dict[str, Any] | None,
    rows_added: int = 0,
    rows_refreshed: int = 0,
    records_seen_total: int = 0,
    records_allowed: int = 0,
    records_quarantined: int = 0,
    expected_canonical_write: bool = True,
    error_present: bool = False,
    skipped: bool = False,
    skipped_reason: str = "",
    ttl_hours: float = DEFAULT_KALSHI_TTL_HOURS,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Produce the canonical Kalshi truth block consumed by API + watchdog."""
    now_dt = now or _dt.datetime.now(_dt.timezone.utc)
    artifact = load_health_artifact(health_path)
    api_health_status, api_health_age = classify_api_health(
        artifact, now_dt, ttl_hours
    )
    source_health_live = api_health_status == API_HEALTH_LIVE_VERIFIED

    stats = canonical_stats or {}
    canonical_live_count = int(stats.get("fresh_count") or 0)
    latest_canonical_fetched_at = stats.get("latest_fetched_at")
    latest_canonical_age = stats.get("latest_age_hours")

    canonical_signal_status = classify_canonical_signal(
        canonical_live_count=canonical_live_count,
        latest_canonical_fetched_at=latest_canonical_fetched_at,
        latest_canonical_age_hours=(
            float(latest_canonical_age) if latest_canonical_age is not None else None
        ),
        rows_added=int(rows_added or 0),
        rows_refreshed=int(rows_refreshed or 0),
        records_seen_total=int(records_seen_total or 0),
        records_allowed=int(records_allowed or 0),
        records_quarantined=int(records_quarantined or 0),
        source_health_live=source_health_live,
        expected_canonical_write=bool(expected_canonical_write),
        ttl_hours=float(ttl_hours),
    )
    canonical_signal_fresh = canonical_signal_status in (
        CANONICAL_LIVE,
        CANONICAL_DUPLICATE_REFRESHED,
    )
    provider_result = classify_provider_result(
        rows_added=int(rows_added or 0),
        rows_refreshed=int(rows_refreshed or 0),
        records_seen_total=int(records_seen_total or 0),
        records_allowed=int(records_allowed or 0),
        records_quarantined=int(records_quarantined or 0),
        canonical_signal_fresh=canonical_signal_fresh,
        source_health_live=source_health_live,
        expected_canonical_write=bool(expected_canonical_write),
        error_present=bool(error_present),
        skipped=bool(skipped),
        skipped_reason=str(skipped_reason or ""),
    )

    degraded = provider_result.startswith("DEGRADED_")
    semantic_fresh = is_semantic_fresh(api_health_status, canonical_signal_status)

    return {
        "source_name": "kalshi",
        "ttl_hours": float(ttl_hours),
        "checked_at_utc": now_dt.replace(microsecond=0).isoformat(),
        "api_health_status": api_health_status,
        "api_health_age_hours": api_health_age,
        "api_health_timestamp_utc": artifact.timestamp_utc,
        "api_health_timestamp_source": artifact.timestamp_source,
        "canonical_signal_status": canonical_signal_status,
        "canonical_live_count": canonical_live_count,
        "latest_canonical_fetched_at": latest_canonical_fetched_at,
        "latest_canonical_age_hours": (
            float(latest_canonical_age) if latest_canonical_age is not None else None
        ),
        "source_run_status": provider_result,
        "provider_result": provider_result,
        "rows_added": int(rows_added or 0),
        "rows_refreshed": int(rows_refreshed or 0),
        "records_seen_total": int(records_seen_total or 0),
        "records_allowed": int(records_allowed or 0),
        "records_quarantined": int(records_quarantined or 0),
        "semantic_fresh": bool(semantic_fresh),
        "degraded": bool(degraded),
        "operator_message": operator_message(
            api_health_status=api_health_status,
            canonical_signal_status=canonical_signal_status,
        ),
        "advisory_only": True,
        "human_review_required": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "can_execute": False,
    }


__all__ = [
    "DEFAULT_KALSHI_TTL_HOURS",
    "API_HEALTH_LIVE_VERIFIED",
    "API_HEALTH_STALE",
    "API_HEALTH_MISSING",
    "API_HEALTH_AUTH_FAILED",
    "API_HEALTH_API_ERROR",
    "API_HEALTH_UNKNOWN",
    "CANONICAL_LIVE",
    "CANONICAL_DUPLICATE_REFRESHED",
    "CANONICAL_ZERO_FRESH_ROWS",
    "CANONICAL_FILTERED",
    "CANONICAL_HEALTH_ONLY",
    "CANONICAL_STALE",
    "CANONICAL_MISSING",
    "CANONICAL_UNKNOWN",
    "RESULT_OK_INSERTED",
    "RESULT_OK_REFRESHED",
    "RESULT_DEGRADED_ZERO_CANONICAL",
    "RESULT_DEGRADED_FILTERED",
    "RESULT_DEGRADED_HEALTH_ONLY",
    "RESULT_ERROR",
    "RESULT_SKIPPED",
    "HealthArtifact",
    "load_health_artifact",
    "age_hours",
    "is_fresh",
    "classify_api_health",
    "classify_canonical_signal",
    "classify_provider_result",
    "operator_message",
    "is_semantic_fresh",
    "build_kalshi_truth",
]
