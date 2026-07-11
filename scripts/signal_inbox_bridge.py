"""
Signal Inbox bridge — promote fresh persisted signal_events into Signal Inbox
candidates with **deterministic deduplication / aggregation**.

Why this exists
---------------
The legacy `global_signal_fabric` builder reads from JSONL snapshot logs that
are not written by the new live source ingestion (Phase 1 / Phase 2). The Live
Signals page reads `signal_events` (populated by live ingestion) and stays
fresh, but the Signal Inbox kept showing the same legacy tickers for days.

This module bridges that gap. It reads the most recent `signal_events` rows
from SQLite, **groups** them by a stable candidate key, and projects each
group into a single InboxItem-shaped dict. Source-specific normalizers map
each event's raw_payload to a meaningful display ticker / topic.

Grouping prevents the inbox from being spammed by:
  - per-candle OHLCV rows (one symbol = one card, not one card per candle)
  - repeated news rows that share the same title / topic
  - repeated regulatory filings for the same issuer + form
  - repeated wallet activity for the same address

Advisory contract
-----------------
- READ-ONLY. No writes to external systems, no broker calls, no order routing.
- Every emitted candidate carries:
    advisory_status      = "ADVISORY_ONLY"
    human_review_required = True
    execution_mode       = "HUMAN_ONLY"
    execution_gate       = "LOCKED"
    ai_execution_count   = 0
    broker_api_called    = False
- No buy/sell/trade language. No price targets. Candidates are observational
  context, never recommendations. The human decides whether they're worth
  reviewing.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_EXECUTION_GATE = "LOCKED"
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


# ---------------------------------------------------------------------------
# Time / helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
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


def _clamp_int(value: int, lo: int, hi: int) -> int:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _hash_short(text: str, n: int = 10) -> str:
    h = hashlib.sha1((text or "").encode("utf-8", errors="replace")).hexdigest()
    return h[:n]


# ---------------------------------------------------------------------------
# Display ticker / topic per source
# ---------------------------------------------------------------------------


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
        title = str(p.get("title") or p.get("question") or "").strip()
        if title:
            return _truncate(title, 48)
        mid = str(p.get("market_id") or "").strip()
        if mid:
            return f"PM_{mid[:20]}"

    if src == "sec_edgar":
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

    title = str(p.get("title") or "").strip()
    if title:
        return _truncate(title, 48)
    return src.upper()


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


def _signal_state_for_age(age_hours: float) -> str:
    """Deterministic placeholder fabric state derived from freshness."""
    if age_hours <= 6:
        return "AVENTADOR"
    if age_hours <= 24:
        return "GALLARDO"
    return "MIURA"


# ---------------------------------------------------------------------------
# Grouping key — what makes two events "the same candidate"
# ---------------------------------------------------------------------------


def _group_key_for_event(
    source_name: str,
    payload: dict[str, Any],
    display_ticker: str,
) -> str:
    """Build a stable per-candidate grouping key.

    Two raw events sharing this key collapse into one inbox candidate. The key
    incorporates entry_type so a future cross-type accidental collision (e.g.
    a market_data symbol that happens to equal a polymarket title) still stays
    in its own group.
    """
    src = (source_name or "unknown").lower().strip()
    p = payload if isinstance(payload, dict) else {}
    entry_type = _entry_type_for_source(src)

    # Source-specific normalization — DOES NOT use individual event_id.
    if src == "market_data":
        sym = str(p.get("symbol") or p.get("ticker") or "").strip().upper()
        anchor = sym or display_ticker.upper()
    elif src == "polymarket":
        mid = str(p.get("market_id") or "").strip()
        if mid:
            anchor = f"MID:{mid}"
        else:
            anchor = "TITLE:" + _hash_short(display_ticker.lower(), 12)
    elif src == "sec_edgar":
        cik = str(p.get("cik") or "").strip()
        form = str(p.get("form_type") or "").strip()
        anchor = f"CIK:{cik}|FORM:{form}" if (cik or form) else display_ticker.upper()
    elif src in {"global_filings", "asia_disclosure"}:
        ticker = str(p.get("ticker_or_identifier") or "").strip().upper()
        issuer = str(p.get("issuer_name") or "").strip().lower()
        dtype = str(p.get("disclosure_type") or p.get("form_type") or "").strip().lower()
        anchor = f"T:{ticker}|I:{_hash_short(issuer, 8)}|D:{dtype}"
    elif src == "etherscan":
        addr = (
            str(p.get("to_address") or p.get("from_address") or "")
            .strip()
            .lower()
        )
        chain = str(p.get("chain") or "ethereum").strip().lower()
        category = str(p.get("category") or p.get("tx_category") or "tx").strip().lower()
        anchor = f"{chain}|{addr or 'unknown'}|{category}"
    elif src == "grok_xai":
        topic = str(p.get("interpreted_topic") or "").strip().lower()
        frame = str(p.get("narrative_frame") or "").strip().lower()
        if topic or frame:
            anchor = f"T:{_hash_short(topic, 8)}|F:{_hash_short(frame, 6)}"
        else:
            anchor = "FALLBACK:" + _hash_short(display_ticker.lower(), 10)
    elif src in {"newsapi", "event_registry", "gdelt", "gdelt_fallback"}:
        # Group by detected asset/ticker if present, else by normalized title.
        detected = str(
            p.get("detected_asset")
            or p.get("ticker")
            or p.get("symbol")
            or ""
        ).strip().upper()
        if detected:
            anchor = f"ASSET:{detected}"
        else:
            title = str(p.get("title") or "").strip().lower()
            anchor = "TITLE:" + _hash_short(title or display_ticker.lower(), 12)
    elif src == "india":
        idx = str(p.get("index_name") or p.get("symbol") or "").strip().upper()
        reg = str(p.get("regulatory_source") or "").strip().lower()
        anchor = f"S:{idx}|R:{reg}" if (idx or reg) else display_ticker.upper()
    else:
        anchor = display_ticker.upper() or "UNKNOWN"

    return f"{src}|{entry_type}|{anchor}"


def _normalized_ticker_for_cross_source(ticker: str) -> str:
    """Case-insensitive ticker form used to detect cross-source support."""
    return (ticker or "").strip().lower()


# ---------------------------------------------------------------------------
# Per-group aggregation + scoring
# ---------------------------------------------------------------------------


def _base_priority_for_source(source_name: str, payload: dict[str, Any]) -> float:
    p = payload if isinstance(payload, dict) else {}
    if source_name == "market_data":
        return _clamp(float(p.get("market_confirmation_score", 0.55) or 0.55), 0.05, 0.95)
    if source_name == "grok_xai":
        cs = p.get("confidence_score")
        return _clamp(float(cs) if isinstance(cs, (int, float)) else 0.5, 0.05, 0.95)
    if source_name in _REGULATORY_SOURCES:
        return 0.6
    if source_name == "polymarket":
        vol = float(p.get("volume", 0) or 0)
        return _clamp(0.4 + min(0.3, vol / 1_000_000.0), 0.05, 0.95)
    if source_name == "gdelt_fallback":
        return 0.45
    return 0.5


def _freshness_factor(age_hours: float) -> float:
    if age_hours <= 6:
        return 1.0
    if age_hours <= 24:
        return 0.85
    if age_hours <= 72:
        return 0.7
    return 0.4


def _persistence_score_for_group(event_count: int, freshness_factor: float) -> float:
    """Persistence rises with repeated observations but caps at 1.0.

    Single event -> mild persistence proportional to freshness. Multiple
    events stack but the curve flattens fast so a 50-candle backfill doesn't
    instantly look like 50x conviction.
    """
    if event_count <= 1:
        return round(_clamp(0.35 * freshness_factor + 0.05, 0.0, 1.0), 4)
    bonus = min(0.6, 0.12 * (event_count - 1))  # caps at +0.60
    base = 0.4 + bonus
    return round(_clamp(base, 0.0, 1.0), 4)


def _priority_score_for_group(
    base_priority: float,
    age_hours: float,
    event_count: int,
    cross_source_support: int,
) -> float:
    freshness = _freshness_factor(age_hours)
    raw = base_priority * freshness + 0.05
    if event_count >= 3:
        raw += 0.05
    if cross_source_support >= 2:
        raw += 0.10
    return round(_clamp(raw, 0.0, 1.0), 4)


def _promotion_reason(
    source_name: str,
    event_count: int,
    cross_source_support: int,
    age_hours: float,
) -> str:
    bits: list[str] = []
    if event_count > 1:
        bits.append(f"{event_count} fresh events aggregated into one candidate")
    else:
        bits.append("single fresh event from this source")
    if cross_source_support >= 2:
        bits.append(f"cross-source support from {cross_source_support} sources")
    if age_hours <= 6:
        bits.append("fresh (≤6h)")
    elif age_hours <= 24:
        bits.append("recent (≤24h)")
    elif age_hours <= 72:
        bits.append("aging (≤72h)")
    else:
        bits.append("stale (>72h)")
    return "; ".join(bits) + f"; source={source_name}"


def _aggregate_group(
    rows: list[dict[str, Any]],
    *,
    cross_source_support: int,
    overlay: dict[str, dict[str, Any]],
    has_reflection_fn,
    has_ai_summary_fn,
    now: datetime,
) -> dict[str, Any]:
    """Collapse one group of raw signal_events into a single inbox item."""
    # Sort newest-first so the representative is the most recent observation.
    sorted_rows = sorted(
        rows,
        key=lambda r: str(r.get("fetched_at", "")),
        reverse=True,
    )
    rep = sorted_rows[0]
    oldest = sorted_rows[-1]

    source_name = str(rep.get("source_name", "") or "")
    payload = rep.get("raw_payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    ts_latest = _parse_iso(str(rep.get("fetched_at", ""))) or now
    ts_first = _parse_iso(str(oldest.get("fetched_at", ""))) or ts_latest
    age_hours = max(0.0, (now - ts_latest).total_seconds() / 3600.0)
    display_ticker = _ticker_for_event(source_name, payload)

    base_priority = _base_priority_for_source(source_name, payload)
    event_count = len(rows)
    priority = _priority_score_for_group(
        base_priority, age_hours, event_count, cross_source_support
    )
    freshness = _freshness_factor(age_hours)
    persistence = _persistence_score_for_group(event_count, freshness)

    # Track every event_id covered by the group (capped to keep payload sane).
    aggregated_event_ids = [str(r.get("event_id", "") or "") for r in sorted_rows]
    aggregated_event_ids = [e for e in aggregated_event_ids if e]
    capped_event_ids = aggregated_event_ids[:50]

    source_names = sorted({str(r.get("source_name", "") or "") for r in rows if r.get("source_name")})

    representative_event_id = str(rep.get("event_id", "") or "")
    user_status = str((overlay.get(representative_event_id) or {}).get("user_status", "pending"))

    has_reflection = False
    has_ai_summary = False
    if has_reflection_fn:
        for eid in capped_event_ids:
            try:
                if has_reflection_fn(eid):
                    has_reflection = True
                    break
            except Exception:
                continue
    if has_ai_summary_fn:
        for eid in capped_event_ids:
            try:
                if has_ai_summary_fn(eid):
                    has_ai_summary = True
                    break
            except Exception:
                continue

    state = _signal_state_for_age(age_hours)

    return {
        "event_id": representative_event_id,
        "representative_event_id": representative_event_id,
        "ticker": display_ticker,
        "signal_state": state,
        "entry_type": _entry_type_for_source(source_name),
        "priority_score": priority,
        "observed_at": str(rep.get("fetched_at", "") or ""),
        "first_observed_at": str(oldest.get("fetched_at", "") or ""),
        "last_observed_at": str(rep.get("fetched_at", "") or ""),
        "source_file": source_name,
        "source_name": source_name,
        "source_names": source_names,
        "rejection_dimensions": [],
        "rejection_reason": "",
        "persistence_score": persistence,
        "blocker_pressure_score": 0.0,
        "kill_rate_score": 0.0,
        "blocker_attribution": "NONE",
        "user_status": user_status,
        "has_reflection": has_reflection,
        "has_ai_summary": has_ai_summary,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "signal_origin": "live_event",
        "age_hours": round(age_hours, 2),
        "event_count": event_count,
        "duplicate_suppressed_count": max(0, event_count - 1),
        "cross_source_support_count": int(cross_source_support),
        "aggregated_event_ids": capped_event_ids,
        # Per-event observation provenance for time-decay engines (Market
        # Titration).  Oldest-first, aligned lists, capped like event_ids so
        # payload size stays bounded.  Advisory metadata only.
        "event_timestamps": [
            str(r.get("fetched_at", "") or "") for r in reversed(sorted_rows)
        ][:50],
        "event_sources": [
            str(r.get("source_name", "") or "") for r in reversed(sorted_rows)
        ][:50],
        "promotion_reason": _promotion_reason(
            source_name, event_count, cross_source_support, age_hours
        ),
    }


# ---------------------------------------------------------------------------
# Next-human-action classifier (backend mirror of frontend deriveNextHumanAction)
# ---------------------------------------------------------------------------


_ACTION_KEYS = (
    "ignore",
    "have_a_look",
    "watchlist",
    "human_review",
    "manual_review_candidate",
)

_PLACEHOLDER_SOURCE_HINTS = ("unknown", "placeholder", "mock", "todo", "fake", "stub")


def _is_known_source(item: dict[str, Any]) -> bool:
    raw = (str(item.get("source_name") or item.get("source_file") or "")).lower().strip()
    if not raw:
        return False
    for hint in _PLACEHOLDER_SOURCE_HINTS:
        if hint in raw:
            return False
    return True


def classify_next_human_action(item: dict[str, Any]) -> str:
    """Return one of IGNORE / HAVE_A_LOOK / WATCHLIST / HUMAN_REVIEW /
    MANUAL_REVIEW_CANDIDATE — kept in lockstep with the frontend rules.

    Advisory-only. No trade language, no execution implications.
    """
    user_status = str(item.get("user_status", "pending"))
    state = str(item.get("signal_state", "") or "").upper()
    priority = float(item.get("priority_score", 0.0) or 0.0)
    persistence = float(item.get("persistence_score", 0.0) or 0.0)
    kill_rate = float(item.get("kill_rate_score", 0.0) or 0.0)
    blocker = float(item.get("blocker_pressure_score", 0.0) or 0.0)
    age_hours = float(item.get("age_hours", 0.0) or 0.0)
    rejection_dims = list(item.get("rejection_dimensions", []) or [])
    event_count = int(item.get("event_count", 1) or 1)
    cross_source = int(item.get("cross_source_support_count", 1) or 1)
    ticker = str(item.get("ticker", "") or "").strip()
    known_source = _is_known_source(item)

    # ----- IGNORE -----
    if user_status == "rejected":
        return "IGNORE"
    if state == "DIABLO":
        return "IGNORE"
    if kill_rate >= 0.85:
        return "IGNORE"
    if blocker >= 0.85:
        return "IGNORE"
    if age_hours > 72:
        return "IGNORE"
    if not known_source:
        return "IGNORE"
    if not ticker:
        return "IGNORE"

    has_context = bool(item.get("has_reflection") or item.get("has_ai_summary"))
    serious_rejection = len(rejection_dims) >= 2

    # ----- MANUAL_REVIEW_CANDIDATE -----
    if (
        priority >= 0.85
        and persistence >= 0.75
        and kill_rate <= 0.20
        and blocker <= 0.20
        and known_source
        and not serious_rejection
        and (cross_source >= 2 or event_count >= 3 or has_context)
    ):
        return "MANUAL_REVIEW_CANDIDATE"

    # ----- HUMAN_REVIEW -----
    if (
        priority >= 0.75
        and persistence >= 0.55
        and kill_rate <= 0.30
        and blocker <= 0.30
        and known_source
        and not serious_rejection
        and age_hours <= 48
    ):
        return "HUMAN_REVIEW"

    # ----- WATCHLIST -----
    if (
        0.55 <= priority < 0.75
        and persistence >= 0.45
        and kill_rate < 0.50
        and blocker < 0.50
        and not serious_rejection
    ):
        return "WATCHLIST"

    # ----- HAVE_A_LOOK -----
    if (
        0.30 <= priority < 0.55
        and persistence >= 0.20
        and kill_rate < 0.80
        and blocker < 0.70
    ):
        return "HAVE_A_LOOK"

    return "IGNORE"


def compute_action_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {k: 0 for k in _ACTION_KEYS}
    for it in items:
        action = classify_next_human_action(it).lower()
        if action in counts:
            counts[action] += 1
    return counts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    """Read recent signal_events and project them into deduplicated inbox candidates.

    50 raw OHLCV candles for the same symbol become ONE InboxItem with
    event_count=50 and duplicate_suppressed_count=49. Parameters are
    dependency-injection friendly so tests can pass fakes.
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

    # Pull a wide window — we need many raw rows to dedup correctly. Hard cap
    # to avoid loading the whole table for huge backfills.
    raw_rows = get_signal_events(source_name=None, limit=5000)
    if not isinstance(raw_rows, list):
        return []

    fresh_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        ts = _parse_iso(str(row.get("fetched_at", "")))
        if ts is None or ts < cutoff:
            continue
        fresh_rows.append(row)

    # Bucket by (source, entry_type, normalized anchor).
    buckets: dict[str, list[dict[str, Any]]] = {}
    bucket_ticker_for_xref: dict[str, str] = {}
    for row in fresh_rows:
        payload = row.get("raw_payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        source = str(row.get("source_name", "") or "")
        display_ticker = _ticker_for_event(source, payload)
        key = _group_key_for_event(source, payload, display_ticker)
        buckets.setdefault(key, []).append(row)
        bucket_ticker_for_xref.setdefault(key, display_ticker)

    # Cross-source support: for each normalized ticker (case-insensitive)
    # count how many distinct source_names produced a group.
    ticker_to_sources: dict[str, set[str]] = {}
    for key, rows in buckets.items():
        norm = _normalized_ticker_for_cross_source(bucket_ticker_for_xref.get(key, ""))
        if not norm:
            continue
        src = str(rows[0].get("source_name", "") or "")
        ticker_to_sources.setdefault(norm, set()).add(src)

    aggregated: list[dict[str, Any]] = []
    for key, rows in buckets.items():
        norm = _normalized_ticker_for_cross_source(bucket_ticker_for_xref.get(key, ""))
        xref = max(1, len(ticker_to_sources.get(norm, {""})))
        aggregated.append(
            _aggregate_group(
                rows,
                cross_source_support=xref,
                overlay=overlay,
                has_reflection_fn=has_reflection_fn,
                has_ai_summary_fn=has_ai_summary_fn,
                now=now,
            )
        )

    aggregated.sort(key=lambda it: (it.get("last_observed_at", "") or ""), reverse=True)
    return aggregated[:safe_limit]


def build_inbox_diagnostics(
    *,
    hours: int = DEFAULT_HOURS,
    get_signal_events=None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Diagnostic snapshot for the /signals/diagnostics endpoint.

    Returns counts per source, latest signal_event timestamp, the count of
    candidates that *would* be promoted (post-dedup) plus the raw fresh count,
    and an explicit `mock_fallback=False` flag so the frontend can detect
    honest "no fresh signals" states.
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
                "fresh_event_count": 0,
                "duplicate_suppressed_count": 0,
                "mock_fallback": False,
                "advisory_status": _ADVISORY_STATUS,
                "execution_mode": _EXECUTION_MODE,
                "ai_execution_count": _AI_EXECUTION_COUNT,
                "human_review_required": True,
                "generated_at": utc_timestamp(),
            }

    try:
        all_rows = get_signal_events(source_name=None, limit=5000)
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
            "fresh_event_count": 0,
            "duplicate_suppressed_count": 0,
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
    fresh_rows: list[dict[str, Any]] = []

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
            fresh_rows.append(row)
            if newest_fresh_ts is None or ts_str > newest_fresh_ts:
                newest_fresh_ts = ts_str

    # Re-bucket the fresh rows to compute deduped candidate count.
    buckets: dict[str, int] = {}
    for row in fresh_rows:
        payload = row.get("raw_payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        source = str(row.get("source_name", "") or "")
        display_ticker = _ticker_for_event(source, payload)
        key = _group_key_for_event(source, payload, display_ticker)
        buckets[key] = buckets.get(key, 0) + 1
    promoted_candidate_count = len(buckets)
    duplicate_suppressed = max(0, fresh_count - promoted_candidate_count)

    return {
        "signal_events_total": len(all_rows),
        "fresh_window_hours": safe_hours,
        "latest_signal_event_at": latest_ts,
        "newest_fresh_event_at": newest_fresh_ts,
        "source_counts": dict(sorted(source_counts.items())),
        "fresh_source_counts": dict(sorted(fresh_source_counts.items())),
        "promoted_candidate_count": promoted_candidate_count,
        "fresh_event_count": fresh_count,
        "duplicate_suppressed_count": duplicate_suppressed,
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
    "classify_next_human_action",
    "compute_action_counts",
]
