"""
Signal Inbox bridge — promote fresh persisted signal_events into Signal Inbox
candidates.

Why this exists
---------------
The legacy `global_signal_fabric` builder reads from JSONL snapshot logs that
are not written by the new live source ingestion (Phase 1 / Phase 2). The Live
Signals page reads `signal_events` (populated by live ingestion) and stays
fresh, but the Signal Inbox kept showing the same legacy tickers for days.

This module bridges that gap. It reads the most recent `signal_events` rows
from SQLite and projects them into the InboxItem-shaped dicts the frontend
already understands. Source-specific normalizers map each event's raw_payload
to a meaningful display ticker/topic.

Advisory contract
-----------------
- READ-ONLY. No writes to external systems, no broker calls, no order routing.
- Every emitted candidate carries:
    advisory_status      = "ADVISORY_ONLY"
    human_review_required = True
    execution_mode       = "HUMAN_ONLY"
    execution_gate       = "LOCKED"
    ai_execution_count   = 0
- No buy/sell/trade language. No price targets. Candidates are observational
  context, never recommendations. The human decides whether they're worth
  reviewing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0

# Default freshness window — bridge will reach this far back when promoting.
DEFAULT_HOURS = 72
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_HOURS = 720  # 30 days

# Sources whose payload represents a regulatory/disclosure signal — slightly
# higher base priority because each row is its own discrete event.
_REGULATORY_SOURCES = {
    "sec_edgar",
    "global_filings",
    "asia_disclosure",
}


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # Accept both "...Z" and "...+00:00"
        cleaned = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _ticker_for_event(source_name: str, payload: dict[str, Any]) -> str:
    """Map source-specific payload fields to a single display label.

    Never returns an empty string. Falls back to the upper-cased source name.
    """
    src = source_name or "unknown"
    p = payload if isinstance(payload, dict) else {}

    if src == "market_data":
        sym = str(p.get("symbol") or p.get("ticker") or "").strip().upper()
        if sym:
            return sym

    if src == "polymarket":
        # Topic-shaped — title or market_id, NOT a fake stock ticker.
        title = str(p.get("title") or p.get("question") or "").strip()
        if title:
            return _truncate(title, 48)
        mid = str(p.get("market_id") or "").strip()
        if mid:
            return f"PM_{mid[:20]}"

    if src == "sec_edgar":
        # Prefer issuer ticker if available; fall back to CIK or form
        cik = str(p.get("cik") or "").strip()
        form = str(p.get("form_type") or "").strip()
        if cik and form:
            return f"CIK{cik}/{form}"
        if cik:
            return f"CIK{cik}"
        if form:
            return f"SEC/{form}"

    if src in {"global_filings", "asia_disclosure"}:
        ticker = str(p.get("ticker_or_identifier") or "").strip()
        if ticker:
            return ticker.upper()
        issuer = str(p.get("issuer_name") or "").strip()
        if issuer:
            return _truncate(issuer, 40)
        exch = str(p.get("exchange_or_regulator") or "").strip()
        if exch:
            return exch.upper()

    if src == "etherscan":
        addr = str(p.get("to_address") or p.get("from_address") or "").strip()
        if addr:
            return f"ETH/{addr[:6]}…{addr[-4:]}" if len(addr) > 14 else f"ETH/{addr}"
        chain = str(p.get("chain") or "ethereum").upper()
        return f"{chain}/TX"

    if src == "grok_xai":
        topic = str(p.get("interpreted_topic") or "").strip()
        if topic:
            return _truncate(topic, 48)
        prompt = str(p.get("source_prompt") or "").strip()
        if prompt:
            return _truncate(prompt, 48)
        return "Grok Interpretation"

    if src in {"newsapi", "event_registry"}:
        title = str(p.get("title") or "").strip()
        if title:
            return _truncate(title, 60)
        publisher = str(p.get("publisher") or "").strip()
        if publisher:
            return f"NEWS/{publisher}"

    if src == "gdelt":
        title = str(p.get("title") or "").strip()
        if title:
            return _truncate(title, 60)
        domain = str(p.get("domain") or "").strip()
        if domain:
            return f"GDELT/{domain}"

    if src == "gdelt_fallback":
        title = str(p.get("title") or "").strip()
        if title:
            return _truncate(title, 60)
        provider = str(p.get("provider_fallback") or "fallback").strip()
        return f"GDELT_FALLBACK/{provider}"

    if src == "india":
        idx = str(p.get("index_name") or p.get("symbol") or "").strip()
        if idx:
            return idx.upper()
        regsrc = str(p.get("regulatory_source") or "").strip()
        if regsrc:
            return f"IN/{regsrc.upper()}"

    # Fallback: try generic title, then source name
    title = str(p.get("title") or "").strip()
    if title:
        return _truncate(title, 48)
    return src.upper()


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _entry_type_for_source(source_name: str) -> str:
    return {
        "polymarket": "PREDICTION_MARKET",
        "gdelt": "NEWS_EVENT",
        "gdelt_fallback": "NEWS_EVENT_FALLBACK",
        "sec_edgar": "SEC_FILING",
        "newsapi": "NEWS_ARTICLE",
        "event_registry": "NEWS_ARTICLE",
        "etherscan": "ONCHAIN_TX",
        "grok_xai": "AI_INTERPRETATION",
        "market_data": "MARKET_PRICE",
        "india": "INDIA_MARKET",
        "global_filings": "REGULATORY_DISCLOSURE",
        "asia_disclosure": "ASIA_DISCLOSURE",
    }.get(source_name, "LIVE_SIGNAL")


def _signal_state_for_event(age_hours: float, source_name: str) -> str:
    """Deterministic placeholder fabric state derived from freshness.

    The legacy fabric assigns Lamborghini-flavored states. New live events
    don't have a kill/blocker history yet, so we keep classification minimal
    and honest: fresh = AVENTADOR (steady), aging = GALLARDO, stale = MIURA.
    DIABLO is reserved for the legacy chaos path.
    """
    if age_hours <= 6:
        return "AVENTADOR"
    if age_hours <= 24:
        return "GALLARDO"
    if age_hours <= 72:
        return "MIURA"
    return "MIURA"


def _scores_for_event(
    source_name: str,
    payload: dict[str, Any],
    age_hours: float,
    same_ticker_count: int,
) -> dict[str, float]:
    """Compute deterministic advisory scores from event metadata.

    These are not predictions. They reflect:
      - priority: source confidence + recency
      - persistence: how many fresh events share the same display ticker
      - kill_rate: 0 (no rejection history attached to a raw live event)
      - blocker_pressure: 0 (no blocker engine output on live events)

    The downstream `deriveNextHumanAction()` then classifies these scores into
    IGNORE / HAVE_A_LOOK / WATCHLIST / HUMAN_REVIEW / MANUAL_CANDIDATE.
    """
    p = payload if isinstance(payload, dict) else {}

    if source_name == "market_data":
        base = float(p.get("market_confirmation_score", 0.55) or 0.55)
    elif source_name == "grok_xai":
        cs = p.get("confidence_score")
        base = float(cs) if isinstance(cs, (int, float)) else 0.5
    elif source_name in _REGULATORY_SOURCES:
        base = 0.6
    elif source_name == "polymarket":
        # Bigger market = more attention; clamp to 0.4–0.7 band
        vol = float(p.get("volume", 0) or 0)
        base = 0.4 + min(0.3, vol / 1_000_000.0)
    elif source_name == "gdelt_fallback":
        base = 0.45
    else:
        base = 0.5

    base = _clamp(base, 0.05, 0.95)

    # Freshness factor — fresher = higher priority within the bridge window.
    if age_hours <= 6:
        freshness_factor = 1.0
    elif age_hours <= 24:
        freshness_factor = 0.85
    elif age_hours <= 72:
        freshness_factor = 0.7
    else:
        freshness_factor = 0.4
    priority = _clamp(base * freshness_factor + 0.05, 0.0, 1.0)

    # Persistence — multiple fresh events for the same ticker boost confidence.
    if same_ticker_count >= 3:
        persistence = _clamp(0.7 + 0.05 * min(6, same_ticker_count - 3), 0.0, 1.0)
    elif same_ticker_count == 2:
        persistence = 0.55
    else:
        persistence = _clamp(base * freshness_factor, 0.0, 1.0)

    return {
        "priority_score": round(priority, 4),
        "persistence_score": round(persistence, 4),
        "kill_rate_score": 0.0,
        "blocker_pressure_score": 0.0,
    }


def _signal_event_to_inbox_item(
    row: dict[str, Any],
    *,
    overlay: dict[str, dict[str, Any]],
    same_ticker_count: int,
    has_reflection_fn,
    has_ai_summary_fn,
    now: datetime,
) -> dict[str, Any]:
    event_id = str(row.get("event_id", "") or "")
    source_name = str(row.get("source_name", "") or "")
    fetched_at = str(row.get("fetched_at", "") or "")
    payload = row.get("raw_payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    ts = _parse_iso(fetched_at) or now
    age_hours = max(0.0, (now - ts).total_seconds() / 3600.0)

    ticker = _ticker_for_event(source_name, payload)
    scores = _scores_for_event(source_name, payload, age_hours, same_ticker_count)
    state = _signal_state_for_event(age_hours, source_name)

    user_status = str((overlay.get(event_id) or {}).get("user_status", "pending"))

    return {
        "event_id": event_id,
        "ticker": ticker,
        "signal_state": state,
        "entry_type": _entry_type_for_source(source_name),
        "priority_score": scores["priority_score"],
        "observed_at": fetched_at,
        "source_file": source_name,
        "rejection_dimensions": [],
        "rejection_reason": "",
        "persistence_score": scores["persistence_score"],
        "blocker_pressure_score": scores["blocker_pressure_score"],
        "kill_rate_score": scores["kill_rate_score"],
        "blocker_attribution": "NONE",
        "user_status": user_status,
        "has_reflection": bool(has_reflection_fn(event_id)) if has_reflection_fn else False,
        "has_ai_summary": bool(has_ai_summary_fn(event_id)) if has_ai_summary_fn else False,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "signal_origin": "live_event",
        "source_name": source_name,
        "age_hours": round(age_hours, 2),
    }


def _clamp_int(value: int, lo: int, hi: int) -> int:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def promote_signal_events_to_inbox(
    *,
    hours: int = DEFAULT_HOURS,
    limit: int = DEFAULT_LIMIT,
    overlay: dict[str, dict[str, Any]] | None = None,
    has_reflection_fn=None,
    has_ai_summary_fn=None,
    get_signal_events=None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Read recent signal_events and project them into InboxItem-shaped dicts.

    Parameters are dependency-injection friendly so tests can pass fakes.
    """
    safe_hours = _clamp_int(int(hours or DEFAULT_HOURS), 1, MAX_HOURS)
    safe_limit = _clamp_int(int(limit or DEFAULT_LIMIT), 1, MAX_LIMIT)
    overlay = overlay or {}
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=safe_hours)

    if get_signal_events is None:
        try:
            try:
                from scripts.persistence import get_signal_events as _gse
            except ModuleNotFoundError:
                from persistence import get_signal_events as _gse  # type: ignore[no-redef]
            get_signal_events = _gse
        except Exception:
            return []

    # Pull more than `limit` so we can filter by freshness then slice.
    raw_rows = get_signal_events(source_name=None, limit=max(safe_limit * 3, safe_limit + 50))
    if not isinstance(raw_rows, list):
        return []

    fresh_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        ts = _parse_iso(str(row.get("fetched_at", "")))
        if ts is None:
            continue
        if ts < cutoff:
            continue
        fresh_rows.append(row)

    # Count occurrences per (source_name, derived ticker) to feed persistence.
    counts: dict[tuple[str, str], int] = {}
    derived_tickers: list[str] = []
    for row in fresh_rows:
        payload = row.get("raw_payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        source = str(row.get("source_name", ""))
        ticker = _ticker_for_event(source, payload)
        derived_tickers.append(ticker)
        key = (source, ticker)
        counts[key] = counts.get(key, 0) + 1

    items: list[dict[str, Any]] = []
    for row, ticker in zip(fresh_rows, derived_tickers):
        source = str(row.get("source_name", ""))
        ct = counts.get((source, ticker), 1)
        items.append(
            _signal_event_to_inbox_item(
                row,
                overlay=overlay,
                same_ticker_count=ct,
                has_reflection_fn=has_reflection_fn,
                has_ai_summary_fn=has_ai_summary_fn,
                now=now,
            )
        )

    items.sort(key=lambda it: it.get("observed_at", ""), reverse=True)
    return items[:safe_limit]


def build_inbox_diagnostics(
    *,
    hours: int = DEFAULT_HOURS,
    get_signal_events=None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Diagnostic snapshot for the /signals/diagnostics endpoint.

    Returns counts per source, latest signal_event timestamp, the count of
    candidates that *would* be promoted, and an explicit `mock_fallback=False`
    flag so the frontend can detect honest "no fresh signals" states.
    """
    safe_hours = _clamp_int(int(hours or DEFAULT_HOURS), 1, MAX_HOURS)
    now = now or datetime.now(timezone.utc)

    if get_signal_events is None:
        try:
            try:
                from scripts.persistence import get_signal_events as _gse
            except ModuleNotFoundError:
                from persistence import get_signal_events as _gse  # type: ignore[no-redef]
            get_signal_events = _gse
        except Exception:
            return {
                "error": "persistence_unavailable",
                "signal_events_total": 0,
                "fresh_window_hours": safe_hours,
                "promoted_candidate_count": 0,
                "mock_fallback": False,
                "advisory_status": _ADVISORY_STATUS,
                "execution_mode": _EXECUTION_MODE,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "human_review_required": True,
                "generated_at": utc_timestamp(),
            }

    try:
        all_rows = get_signal_events(source_name=None, limit=2000)
    except Exception as exc:
        return {
            "error": f"persistence_call_failed:{type(exc).__name__}",
            "signal_events_total": 0,
            "fresh_window_hours": safe_hours,
            "latest_signal_event_at": None,
            "newest_fresh_event_at": None,
            "source_counts": {},
            "fresh_source_counts": {},
            "promoted_candidate_count": 0,
            "mock_fallback": False,
            "advisory_status": _ADVISORY_STATUS,
            "execution_mode": _EXECUTION_MODE,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "human_review_required": True,
            "generated_at": utc_timestamp(),
        }
    if not isinstance(all_rows, list):
        all_rows = []

    cutoff = now - timedelta(hours=safe_hours)
    source_counts: dict[str, int] = {}
    fresh_source_counts: dict[str, int] = {}
    latest_ts: str | None = None
    newest_fresh_ts: str | None = None
    fresh_count = 0

    for row in all_rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source_name", "") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        ts_str = str(row.get("fetched_at", "") or "")
        if ts_str and (latest_ts is None or ts_str > latest_ts):
            latest_ts = ts_str
        ts = _parse_iso(ts_str)
        if ts is not None and ts >= cutoff:
            fresh_count += 1
            fresh_source_counts[source] = fresh_source_counts.get(source, 0) + 1
            if newest_fresh_ts is None or ts_str > newest_fresh_ts:
                newest_fresh_ts = ts_str

    return {
        "signal_events_total": len(all_rows),
        "fresh_window_hours": safe_hours,
        "latest_signal_event_at": latest_ts,
        "newest_fresh_event_at": newest_fresh_ts,
        "source_counts": dict(sorted(source_counts.items())),
        "fresh_source_counts": dict(sorted(fresh_source_counts.items())),
        "promoted_candidate_count": fresh_count,
        "mock_fallback": False,
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
        "generated_at": utc_timestamp(),
    }


__all__ = [
    "DEFAULT_HOURS",
    "DEFAULT_LIMIT",
    "MAX_HOURS",
    "MAX_LIMIT",
    "promote_signal_events_to_inbox",
    "build_inbox_diagnostics",
]
