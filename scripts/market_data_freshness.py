"""
Market-data freshness gate for Chart Structure / OHLCV consumers.

This module is intentionally pure-Python (no FastAPI, no SQLite).  It takes
a list of candles already shaped as ``[{"timestamp": ISO, ...}, ...]`` and
classifies how fresh / trustworthy the dataset is, so the Chart Structure
API and frontend can refuse to render an advisory verdict over ancient
fixture / seed data.

The rules are intentionally generic — they do **not** assume any particular
market or asset class:

* MISSING                — no candles at all
* MOCK_OR_DEMO_BLOCKED   — dataset came from a fixture / seed / demo source
* ANCIENT                — newest candle is more than 90 days old (or year < 2010)
* STALE                  — newest candle is more than 30 days old
* DELAYED                — newest candle is between 10 and 30 days old
* FRESH                  — newest candle is within 10 days

freshness_gate is one of ``PASS`` / ``WARN`` / ``BLOCK``.

Source kinds (no enum so we don't import anything):

* CANONICAL_SQLITE       — local canonical SQLite OHLCV
* READ_ONLY_PROVIDER     — live read-only provider (e.g. yfinance)
* JSONL_AUDIT_ONLY       — JSONL audit / append-only log (NOT canonical)
* MOCK / DEMO / SEED     — deterministic synthetic data (must never look real)
* UNKNOWN                — could not determine

Safety contract: this module never executes trades, never calls a broker,
never increments ai_execution_count.  It is read-only classification.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

# Public freshness statuses
FRESH = "FRESH"
DELAYED = "DELAYED"
STALE = "STALE"
ANCIENT = "ANCIENT"
MISSING = "MISSING"
MOCK_OR_DEMO_BLOCKED = "MOCK_OR_DEMO_BLOCKED"

# Public gate values
PASS = "PASS"
WARN = "WARN"
BLOCK = "BLOCK"

# Public source kinds
CANONICAL_SQLITE = "CANONICAL_SQLITE"
READ_ONLY_PROVIDER = "READ_ONLY_PROVIDER"
JSONL_AUDIT_ONLY = "JSONL_AUDIT_ONLY"
MOCK = "MOCK"
DEMO = "DEMO"
SEED = "SEED"
UNKNOWN = "UNKNOWN"

_DEMO_SOURCE_KINDS = {MOCK, DEMO, SEED}

# Thresholds (in days). Tunable, but BLOCK_THRESHOLD must be the hardest.
DELAYED_THRESHOLD_DAYS: float = 10.0
STALE_THRESHOLD_DAYS: float = 30.0
ANCIENT_THRESHOLD_DAYS: float = 90.0
ANCIENT_YEAR_FLOOR: int = 2010   # year < 2010 → ANCIENT regardless of clock skew


def _parse_ts(value: Any) -> _dt.datetime | None:
    """Best-effort parse of an ISO-8601 timestamp.  Returns None on failure."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        # Tolerate plain dates like "2026-05-15"
        try:
            dt = _dt.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def classify_source_kind(raw: str | None) -> str:
    """Normalize an arbitrary source label to the public source-kind enum."""
    if not raw:
        return UNKNOWN
    text = str(raw).strip().upper()
    if not text:
        return UNKNOWN
    if "MOCK" in text:
        return MOCK
    if "DEMO" in text:
        return DEMO
    if "SEED" in text or "FIXTURE" in text or "SAMPLE" in text:
        return SEED
    if "JSONL" in text or "AUDIT" in text:
        return JSONL_AUDIT_ONLY
    if text in {"YFINANCE", "YAHOO", "READ_ONLY_PROVIDER", "PROVIDER"}:
        return READ_ONLY_PROVIDER
    if text in {"MARKET_DATA", "CANONICAL_SQLITE", "SQLITE", "LOCAL_SQLITE"}:
        return CANONICAL_SQLITE
    return UNKNOWN


def evaluate(
    *,
    candles: list[dict[str, Any]] | None,
    source_kind: str | None = None,
    now: _dt.datetime | None = None,
    allow_demo: bool = False,
) -> dict[str, Any]:
    """Classify a candle list's freshness.

    Returns a dict with these keys (always present):

        data_freshness_status   — one of FRESH / DELAYED / STALE / ANCIENT
                                   / MISSING / MOCK_OR_DEMO_BLOCKED
        freshness_gate          — PASS / WARN / BLOCK
        latest_candle_utc       — ISO-8601 string or None
        first_candle_utc        — ISO-8601 string or None
        data_age_hours          — float or None
        data_age_days           — float or None
        freshness_reason        — short human-readable string
        source_kind             — normalized source-kind string
        candle_count            — int (len of valid candles)

    The function never raises on bad input; malformed timestamps are
    treated as missing.  ``allow_demo=True`` lets demo-mode pages opt
    into displaying fixture data with a WARN gate; the default refuses.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    src_kind = classify_source_kind(source_kind)
    candles = candles or []

    parsed_ts: list[_dt.datetime] = []
    for c in candles:
        ts = _parse_ts(c.get("timestamp"))
        if ts is not None:
            parsed_ts.append(ts)

    base: dict[str, Any] = {
        "data_freshness_status": MISSING,
        "freshness_gate": BLOCK,
        "latest_candle_utc": None,
        "first_candle_utc": None,
        "data_age_hours": None,
        "data_age_days": None,
        "freshness_reason": "no candles available",
        "source_kind": src_kind,
        "candle_count": len(candles),
    }

    if not parsed_ts:
        # No usable timestamps → MISSING/BLOCK regardless of source.
        if src_kind in _DEMO_SOURCE_KINDS:
            base["data_freshness_status"] = MOCK_OR_DEMO_BLOCKED
            base["freshness_reason"] = (
                f"market data source is {src_kind.lower()}; refusing to render"
            )
        return base

    parsed_ts.sort()
    latest = parsed_ts[-1]
    first = parsed_ts[0]
    age_seconds = (now - latest).total_seconds()
    age_days = age_seconds / 86400.0
    age_hours = age_seconds / 3600.0

    base["latest_candle_utc"] = latest.isoformat().replace("+00:00", "Z")
    base["first_candle_utc"] = first.isoformat().replace("+00:00", "Z")
    base["data_age_hours"] = round(age_hours, 4)
    base["data_age_days"] = round(age_days, 4)

    # Source-level block: demo/mock/seed datasets must never silently
    # masquerade as real current OHLCV.  ``allow_demo`` downgrades to WARN
    # for explicit demo-mode pages.
    if src_kind in _DEMO_SOURCE_KINDS:
        if allow_demo:
            base["data_freshness_status"] = MOCK_OR_DEMO_BLOCKED
            base["freshness_gate"] = WARN
            base["freshness_reason"] = (
                f"demo/seed source ({src_kind.lower()}); advisory analysis "
                f"downgraded — not real market data"
            )
        else:
            base["data_freshness_status"] = MOCK_OR_DEMO_BLOCKED
            base["freshness_gate"] = BLOCK
            base["freshness_reason"] = (
                f"market data source is {src_kind.lower()}; refusing to render "
                f"normal advisory verdict over fixture data"
            )
        return base

    # Hard anti-ancient guard: a year-floor + a calendar-age floor.
    if latest.year < ANCIENT_YEAR_FLOOR or age_days > ANCIENT_THRESHOLD_DAYS:
        base["data_freshness_status"] = ANCIENT
        base["freshness_gate"] = BLOCK
        base["freshness_reason"] = (
            f"latest candle {latest.date().isoformat()} is "
            f"{int(age_days)} days old — refusing to treat as current data"
        )
        return base

    if age_days > STALE_THRESHOLD_DAYS:
        base["data_freshness_status"] = STALE
        base["freshness_gate"] = BLOCK
        base["freshness_reason"] = (
            f"latest candle is {age_days:.1f} days old "
            f"(stale > {STALE_THRESHOLD_DAYS:.0f}d)"
        )
        return base

    if age_days > DELAYED_THRESHOLD_DAYS:
        base["data_freshness_status"] = DELAYED
        base["freshness_gate"] = WARN
        base["freshness_reason"] = (
            f"latest candle is {age_days:.1f} days old "
            f"(delayed > {DELAYED_THRESHOLD_DAYS:.0f}d)"
        )
        return base

    base["data_freshness_status"] = FRESH
    base["freshness_gate"] = PASS
    base["freshness_reason"] = (
        f"latest candle is {age_days:.1f} days old"
    )
    return base


def stale_advisory_summary(
    *,
    symbol: str,
    freshness: dict[str, Any],
) -> dict[str, str]:
    """Return a (advisory_summary, suggested_next_step) pair appropriate
    for a stale/ancient/missing dataset.  The Chart Structure API uses
    this to override the default chart-structure verdict whenever the
    freshness gate is BLOCK so the operator never sees a normal
    "TRENDING_UP" verdict over 2004 candles.
    """
    status = freshness.get("data_freshness_status", "")
    latest = freshness.get("latest_candle_utc") or "unknown"
    age_days = freshness.get("data_age_days")
    src = freshness.get("source_kind", UNKNOWN)
    age_str = f"{age_days:.1f} days old" if isinstance(age_days, (int, float)) else "unknown age"
    if status == MISSING:
        summary = (
            f"No OHLCV candle data is available for {symbol}. "
            "Chart Structure analysis is blocked until fresh data is loaded."
        )
        step = "DATA_REFRESH_REQUIRED"
    elif status == MOCK_OR_DEMO_BLOCKED:
        summary = (
            f"Market data for {symbol} is sourced from {src.lower()} "
            "(mock/demo/seed). Chart Structure analysis is blocked — "
            "this is not real current market data."
        )
        step = "DATA_REFRESH_REQUIRED"
    elif status == ANCIENT:
        summary = (
            f"Market data for {symbol} is ancient — latest candle "
            f"{latest} ({age_str}). Chart Structure analysis is blocked "
            "until fresh data is loaded."
        )
        step = "HUMAN_REVIEW_DATA_STALE"
    else:  # STALE / DELAYED-as-block
        summary = (
            f"Market data for {symbol} is stale — latest candle "
            f"{latest} ({age_str}). Chart Structure analysis is blocked "
            "until fresh data is loaded."
        )
        step = "HUMAN_REVIEW_DATA_STALE"
    return {"advisory_summary": summary, "suggested_next_step": step}


__all__ = [
    "FRESH", "DELAYED", "STALE", "ANCIENT", "MISSING", "MOCK_OR_DEMO_BLOCKED",
    "PASS", "WARN", "BLOCK",
    "CANONICAL_SQLITE", "READ_ONLY_PROVIDER", "JSONL_AUDIT_ONLY",
    "MOCK", "DEMO", "SEED", "UNKNOWN",
    "DELAYED_THRESHOLD_DAYS", "STALE_THRESHOLD_DAYS", "ANCIENT_THRESHOLD_DAYS",
    "evaluate", "classify_source_kind", "stale_advisory_summary",
]
