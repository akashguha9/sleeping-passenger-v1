"""Bridge — canonical SQLite ``signal_events`` -> daily payload rows.

Live ingestion (GDELT / NewsAPI / Event Registry / SEC EDGAR / EDINET /
OpenDART / global_filings / asia_disclosure) persists to the SQLite
``signal_events`` table, but the five-model synthesis only reads the JSON files
under ``data/daily_payload/``. That disconnect is why synthesis only ever saw
the static US-biased fallback. This module is the missing bridge.

It is strictly read-only against SQLite and advisory-only:
    * never mutates ``signal_events`` (only SELECTs through ``persistence``)
    * never creates the DB — a missing DB short-circuits to honest fallback
    * never sets ``is_live=true`` unless genuinely-fresh rows from a live source
      are present
    * invokes entity->ticker mapping and RETAINS unmapped events (never drops)

Freshness (verbatim from the sprint spec)::

    age_hours(e)        = (now_utc - timestamp_utc(e)) / 3600
    timestamp_utc(e)    = published_at | event_timestamp | fetched_at | None
    fresh(e, ttl)       = 1 if ts not None and age_hours <= ttl else 0
    freshness_score(e)  = max(0, 1 - age_hours/ttl) if fresh else 0
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.entity_ticker_mapper import DEFAULT_THETA_MAP, map_event_to_tickers
    from scripts.top30_country_coverage import canonical_country, country_from_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from entity_ticker_mapper import DEFAULT_THETA_MAP, map_event_to_tickers
    from top30_country_coverage import canonical_country, country_from_ticker


# Source categorisation. Operator-extendable via function args.
NEWS_SOURCES: frozenset[str] = frozenset({"gdelt", "newsapi", "event_registry"})
FILINGS_SOURCES: frozenset[str] = frozenset(
    {
        "sec_edgar",
        "edinet",
        "opendart",
        "global_filings",
        "asia_disclosure",
        "india",
        "nse_bse",
        "sebi",
        "rbi",
        "eu_esef",
        "uk_companies_house",
        "china_disclosure",
        "singapore_acra_sgx",
    }
)

NEWS_TTL_HOURS = 24.0
FILINGS_TTL_HOURS = 72.0

# Allowed per-row health states that still count toward a live payload.
_LIVE_OK_STATES = {"LIVE_VERIFIED", "OK_LIVE", "OK", "DEGRADED_WITH_FRESH_ROWS", "PARTIAL"}


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # Try a date-only form.
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def event_timestamp_utc(raw: dict[str, Any], fetched_at: Any) -> str | None:
    """timestamp_utc(e) = published_at | event_timestamp | fetched_at | None."""
    for key in ("published_at", "event_timestamp_utc", "event_timestamp", "timestamp_utc", "timestamp"):
        dt = _parse_dt(raw.get(key))
        if dt is not None:
            return dt.isoformat()
    dt = _parse_dt(fetched_at)
    return dt.isoformat() if dt is not None else None


def freshness(now_utc: datetime, timestamp_iso: str | None, ttl_hours: float) -> tuple[float | None, int, float]:
    """Return ``(age_hours, fresh_flag, freshness_score)``."""
    dt = _parse_dt(timestamp_iso)
    if dt is None:
        return None, 0, 0.0
    age_hours = (now_utc - dt).total_seconds() / 3600.0
    if age_hours < 0:
        age_hours = 0.0
    if ttl_hours <= 0:
        return age_hours, 0, 0.0
    fresh_flag = 1 if age_hours <= ttl_hours else 0
    score = max(0.0, 1.0 - age_hours / ttl_hours) if fresh_flag else 0.0
    return round(age_hours, 4), fresh_flag, round(score, 4)


def _headline(raw: dict[str, Any]) -> str | None:
    for key in ("headline", "title", "summary", "disclosure_type", "event_type"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return None


def _country(raw: dict[str, Any]) -> str | None:
    return (
        canonical_country(raw.get("country"))
        or canonical_country(raw.get("jurisdiction"))
        or country_from_ticker(raw.get("ticker") or raw.get("ticker_or_identifier") or raw.get("symbol"))
    )


def normalize_signal_event_row(
    db_row: dict[str, Any],
    *,
    now_utc: datetime,
    ttl_hours: float,
    event_type: str,
    db_path: Path | None,
    theta_map: float,
    phantom_set: set[str] | None,
    securities_master_path: Path | None = None,
) -> dict[str, Any]:
    """Normalize one ``signal_events`` row into a daily-payload row.

    Entity->ticker mapping is invoked here; unmapped rows are retained with
    ``mapping_status="UNMAPPED"``.
    """
    raw = db_row.get("raw_payload")
    if not isinstance(raw, dict):
        raw = {}
    source_name = str(db_row.get("source_name") or raw.get("source_name") or "").strip()
    fetched_at = db_row.get("fetched_at") or raw.get("fetched_at")
    ts_iso = event_timestamp_utc(raw, fetched_at)
    age_hours, fresh_flag, score = freshness(now_utc, ts_iso, ttl_hours)

    mapped = map_event_to_tickers(
        raw,
        db_path=db_path,
        securities_master_path=securities_master_path,
        theta_map=theta_map,
        phantom_set=phantom_set,
    )
    best = max(mapped, key=lambda m: float(m.get("mapping_confidence") or 0.0))
    mapping_status = best.get("mapping_status", "UNMAPPED")
    mapping_conf = float(best.get("mapping_confidence") or 0.0)
    ticker = best.get("ticker")
    country = best.get("country") or _country(raw)
    exchange = best.get("exchange") or ""

    if mapping_status == "MAPPED" and mapping_conf >= theta_map:
        row_health = "DEGRADED_WITH_FRESH_ROWS" if fresh_flag else "EMPTY_FALLBACK"
    elif fresh_flag:
        row_health = "DEGRADED_LIVE_UNMAPPED"
    else:
        row_health = "STALE_OR_UNMAPPED"

    return {
        "event_id": db_row.get("event_id") or raw.get("event_id"),
        "source_name": source_name,
        "source_type": event_type,
        "provider": raw.get("provider") or source_name or "SIGNAL_EVENTS",
        "provider_status": raw.get("provider_status") or "OK",
        "source_health": row_health,
        "is_live": bool(fresh_flag),
        "fetched_at_utc": _parse_dt(fetched_at).isoformat() if _parse_dt(fetched_at) else None,
        "published_at_utc": ts_iso,
        "event_timestamp_utc": ts_iso,
        "country": country,
        "jurisdiction": raw.get("jurisdiction"),
        "region": raw.get("region"),
        "entity_name": best.get("entity_name") or raw.get("entity_name") or raw.get("issuer_name"),
        "asset_tags": raw.get("asset_tags") or [],
        "ticker": ticker,
        "exchange": exchange,
        "currency": raw.get("currency"),
        "headline": _headline(raw),
        "summary": raw.get("summary"),
        "url": raw.get("url") or raw.get("source_url"),
        "event_type": event_type,
        "freshness": "FRESH_TODAY" if fresh_flag else "STALE",
        "freshness_age_hours": age_hours,
        "freshness_score": score,
        "mapping_status": mapping_status,
        "mapping_confidence": round(mapping_conf, 4),
        "mapping_failure_reason": best.get("mapping_failure_reason"),
        "is_adr": bool(best.get("is_adr")),
        "is_local_listing": bool(best.get("is_local_listing")),
        "phantom": bool(best.get("phantom")),
        "data_quality": round(min(1.0, score * (mapping_conf if mapping_conf > 0 else 0.5)), 4),
        "why_today": (
            f"Fresh live {event_type} event detected today."
            if fresh_flag
            else f"Stale {event_type} event; research/context only."
        ),
        "advisory_only": True,
        "human_review_required": True,
    }


def _read_source_rows(
    source_name: str, limit: int, db_path: Path
) -> tuple[list[dict[str, Any]], str | None]:
    """Read rows for one source via persistence (read-only). Returns (rows, error)."""
    try:
        try:
            from scripts.persistence import get_signal_events
        except ModuleNotFoundError:  # pragma: no cover
            from persistence import get_signal_events  # type: ignore[no-redef]
        rows = get_signal_events(source_name=source_name, limit=limit, db_path=db_path)
        return rows, None
    except sqlite3.OperationalError as exc:
        return [], f"SIGNAL_EVENTS_TABLE_MISSING: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return [], f"SIGNAL_EVENTS_READ_ERROR: {type(exc).__name__}"


def load_fresh_signal_events_for_daily_payload(
    db_path: Path | None,
    now_utc: datetime | None = None,
    lookback_hours: float = FILINGS_TTL_HOURS,
    source_types: Iterable[str] | None = None,
    max_events: int = 200,
    *,
    event_type: str = "news",
    theta_map: float = DEFAULT_THETA_MAP,
    phantom_set: set[str] | None = None,
    securities_master_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read fresh ``signal_events`` and normalize them into daily-payload rows.

    Returns ``(fresh_rows, diagnostics)``. ``fresh_rows`` contains only rows
    within ``lookback_hours``; stale rows are excluded but counted in
    diagnostics. ``diagnostics`` carries the honest bridge status + fallback
    reason so the caller never has to guess.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    sources = list(source_types) if source_types is not None else sorted(NEWS_SOURCES)

    diagnostics: dict[str, Any] = {
        "attempted": True,
        "status": "OK",
        "fallback_reason": None,
        "fresh_count": 0,
        "stale_excluded_count": 0,
        "mapped_count": 0,
        "unmapped_count": 0,
        "sources_scanned": sources,
        "db_path": str(db_path) if db_path else None,
    }

    if db_path is None:
        try:
            try:
                from scripts.persistence import DB_PATH as _DB_PATH
            except ModuleNotFoundError:  # pragma: no cover
                from persistence import DB_PATH as _DB_PATH  # type: ignore
            db_path = _DB_PATH
        except Exception:
            db_path = None
        diagnostics["db_path"] = str(db_path) if db_path else None

    if not db_path or not Path(db_path).exists():
        diagnostics.update(status="FALLBACK", fallback_reason="SIGNAL_EVENTS_DB_MISSING")
        return [], diagnostics

    db_path = Path(db_path)
    fresh_rows: list[dict[str, Any]] = []
    stale_count = 0
    for source_name in sources:
        rows, error = _read_source_rows(source_name, max_events, db_path)
        if error:
            diagnostics.update(status="FALLBACK", fallback_reason=error.split(":")[0])
            continue
        for db_row in rows:
            norm = normalize_signal_event_row(
                db_row,
                now_utc=now_utc,
                ttl_hours=lookback_hours,
                event_type=event_type,
                db_path=db_path,
                theta_map=theta_map,
                phantom_set=phantom_set,
                securities_master_path=securities_master_path,
            )
            if norm["is_live"]:
                fresh_rows.append(norm)
                if norm["mapping_status"] == "MAPPED":
                    diagnostics["mapped_count"] += 1
                else:
                    diagnostics["unmapped_count"] += 1
            else:
                stale_count += 1

    fresh_rows.sort(key=lambda r: (-(r.get("freshness_score") or 0.0), str(r.get("ticker") or "")))
    fresh_rows = fresh_rows[:max_events]
    diagnostics["fresh_count"] = len(fresh_rows)
    diagnostics["stale_excluded_count"] = stale_count
    if not fresh_rows and diagnostics["fallback_reason"] is None:
        diagnostics.update(status="FALLBACK", fallback_reason="NO_ROWS_WITHIN_TTL")
    return fresh_rows, diagnostics


def _payload_health(rows: list[dict[str, Any]], diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Derive the envelope is_live/source_health/provider from normalized rows."""
    if not rows:
        return {
            "is_live": False,
            "source_health": "STATIC_OR_EMPTY_FALLBACK",
            "provider": "STATIC_OR_EMPTY_FALLBACK",
            "executable_allowed": False,
            "fallback_reason": diagnostics.get("fallback_reason") or "NO_FRESH_SIGNAL_EVENTS",
        }
    any_mapped = any(r["mapping_status"] == "MAPPED" and r["mapping_confidence"] >= DEFAULT_THETA_MAP for r in rows)
    max_score = max((r.get("freshness_score") or 0.0) for r in rows)
    all_ok = all(r.get("source_health") in _LIVE_OK_STATES or r.get("source_health") == "DEGRADED_LIVE_UNMAPPED" for r in rows)
    if any_mapped and max_score > 0 and all_ok:
        health = "LIVE_VERIFIED"
        executable_allowed = True
    else:
        health = "DEGRADED_LIVE_UNMAPPED"
        executable_allowed = False
    providers = sorted({str(r.get("provider") or "").strip() for r in rows if r.get("provider")})
    return {
        "is_live": True,
        "source_health": health,
        "provider": "+".join(providers) if providers else "SIGNAL_EVENTS_BRIDGE",
        "executable_allowed": executable_allowed,
        "fallback_reason": None,
    }


def build_news_payload_from_signal_events(
    db_path: Path | None,
    now_utc: datetime | None = None,
    *,
    lookback_hours: float = NEWS_TTL_HOURS,
    source_types: Iterable[str] | None = None,
    max_events: int = 200,
    theta_map: float = DEFAULT_THETA_MAP,
    phantom_set: set[str] | None = None,
    securities_master_path: Path | None = None,
) -> dict[str, Any]:
    """Bridge result for today_news_events. Always returns a dict (honest)."""
    rows, diagnostics = load_fresh_signal_events_for_daily_payload(
        db_path,
        now_utc=now_utc,
        lookback_hours=lookback_hours,
        source_types=source_types if source_types is not None else sorted(NEWS_SOURCES),
        max_events=max_events,
        event_type="news",
        theta_map=theta_map,
        phantom_set=phantom_set,
        securities_master_path=securities_master_path,
    )
    meta = _payload_health(rows, diagnostics)
    meta["diagnostics"] = diagnostics
    return {"events": rows, "meta": meta}


def build_filings_payload_from_signal_events(
    db_path: Path | None,
    now_utc: datetime | None = None,
    *,
    lookback_hours: float = FILINGS_TTL_HOURS,
    source_types: Iterable[str] | None = None,
    max_events: int = 200,
    theta_map: float = DEFAULT_THETA_MAP,
    phantom_set: set[str] | None = None,
    securities_master_path: Path | None = None,
) -> dict[str, Any]:
    """Bridge result for today_filings_events. Always returns a dict (honest)."""
    rows, diagnostics = load_fresh_signal_events_for_daily_payload(
        db_path,
        now_utc=now_utc,
        lookback_hours=lookback_hours,
        source_types=source_types if source_types is not None else sorted(FILINGS_SOURCES),
        max_events=max_events,
        event_type="filing",
        theta_map=theta_map,
        phantom_set=phantom_set,
        securities_master_path=securities_master_path,
    )
    meta = _payload_health(rows, diagnostics)
    meta["diagnostics"] = diagnostics
    return {"events": rows, "meta": meta}


__all__ = [
    "NEWS_SOURCES",
    "FILINGS_SOURCES",
    "NEWS_TTL_HOURS",
    "FILINGS_TTL_HOURS",
    "event_timestamp_utc",
    "freshness",
    "normalize_signal_event_row",
    "load_fresh_signal_events_for_daily_payload",
    "build_news_payload_from_signal_events",
    "build_filings_payload_from_signal_events",
    "advisory_safety_stamps",
]
