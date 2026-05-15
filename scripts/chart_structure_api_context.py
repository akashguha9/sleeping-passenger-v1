"""
Chart structure API context helpers -- dependency-free.

Pure parsing utilities importable without FastAPI installed.
Used by scripts/api_server.py and testable in CI without backend deps.

Safety invariants (always present, never modified):
  advisory_status      = ADVISORY_ONLY
  execution_gate       = LOCKED
  human_review_required = True
  ai_execution_count   = 0
  broker_api_called    = False
  broker_order_id      = NONE

Freshness contract (Sprint H — Stale OHLCV repair):
  - Candles are selected as the *latest* N by their payload timestamp,
    never the oldest N — the SQL helper sorts on
    json_extract(raw_payload, '$.timestamp') DESC, not on the wall-clock
    fetched_at, because a historical backfill writes thousands of rows
    with identical fetched_at and SQLite's tie-break order would
    otherwise return the OLDEST candles first.
  - Every response carries a ``freshness`` block (data_freshness_status,
    freshness_gate, latest_candle_utc, data_age_days, source_kind, …)
    so the frontend can refuse to render a normal verdict over ancient
    fixture / seed data.
  - When the freshness gate is BLOCK the advisory verdict is overridden
    with a stale-data summary and suggested_next_step ∈
    {DATA_REFRESH_REQUIRED, HUMAN_REVIEW_DATA_STALE}.  Existing safety
    stamps are preserved.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from scripts import market_data_freshness as _freshness
except ModuleNotFoundError:
    import market_data_freshness as _freshness  # type: ignore[no-redef]

_ADVISORY_STATUS = "ADVISORY_ONLY"
_AI_EXECUTION_COUNT = 0


def _candles_from_market_events(events: list[dict]) -> list[dict]:
    """Extract OHLCV candle dicts from market_data signal_events raw_payload.

    Each event's raw_payload may already be a dict (parsed by get_signal_events)
    or a JSON string. Missing or non-numeric fields are silently skipped.
    """
    candles: list[dict] = []
    for ev in events:
        payload = ev.get("raw_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(payload, dict):
            continue
        o = payload.get("open")
        h = payload.get("high")
        lo = payload.get("low")
        c = payload.get("close") if payload.get("close") is not None else payload.get("latest_price")
        v = payload.get("volume")
        ts = payload.get("timestamp") or ev.get("fetched_at", "")
        if any(x is None for x in (o, h, lo, c, v)) or not ts:
            continue
        candles.append({
            "timestamp": str(ts),
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v,
        })
    return candles


def _classify_event_source_kind(event_id: str) -> str:
    """Map a signal_events.event_id prefix to a market-data source kind.

    Known prefixes:
      ohlcv_*        — real backfill (yfinance) → CANONICAL_SQLITE
      seed_ohlcv_*   — deterministic offline demo seed → SEED
      everything else — UNKNOWN
    """
    eid = str(event_id or "")
    if eid.startswith("seed_ohlcv_") or eid.startswith("seed_"):
        return _freshness.SEED
    if eid.startswith("ohlcv_") or eid.startswith("global_ohlcv_"):
        return _freshness.CANONICAL_SQLITE
    return _freshness.UNKNOWN


def _resolve_source_kind(events: list[dict], candles: list[dict]) -> str:
    """Pick the most-trusted source_kind across the contributing events."""
    if not events and not candles:
        return _freshness.UNKNOWN
    kinds = {_classify_event_source_kind(ev.get("event_id", "")) for ev in events}
    # Trust hierarchy: CANONICAL_SQLITE wins if any real candle is present,
    # otherwise SEED, otherwise UNKNOWN.
    if _freshness.CANONICAL_SQLITE in kinds:
        return _freshness.CANONICAL_SQLITE
    if _freshness.SEED in kinds:
        return _freshness.SEED
    if kinds:
        # Single bucket — return whatever is there.
        return next(iter(kinds))
    return _freshness.UNKNOWN


def _stale_safe_response(
    *,
    base: dict[str, Any],
    symbol: str,
    candle_count: int,
    freshness: dict[str, Any],
    linked_event_id: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a freshness-blocked response that NEVER leaks a normal verdict.

    Used when ``freshness_gate == BLOCK`` (ancient / stale / mock-or-demo).
    The advisory_summary + suggested_next_step are stale-aware and the
    `report` field is set to None so the frontend cannot render the usual
    OHLCV summary tiles over fixture data.
    """
    advisory = _freshness.stale_advisory_summary(
        symbol=symbol, freshness=freshness,
    )
    payload: dict[str, Any] = {
        **base,
        "ok": False,
        "symbol": symbol,
        "input_symbol": symbol,
        "source_event_id": linked_event_id,
        "candle_count": candle_count,
        "chart_state": "STALE_DATA_BLOCKED",
        "advisory_summary": advisory["advisory_summary"],
        "suggested_next_step": advisory["suggested_next_step"],
        "freshness": freshness,
        "data_freshness_status": freshness.get("data_freshness_status"),
        "freshness_gate": freshness.get("freshness_gate"),
        "latest_candle_utc": freshness.get("latest_candle_utc"),
        "data_age_days": freshness.get("data_age_days"),
        "source_kind": freshness.get("source_kind"),
        "report": None,
    }
    if extra:
        payload.update(extra)
    return payload


def _get_chart_structure(
    symbol: str,
    source_event_id: str | None = None,
    limit: int = 100,
    db_path=None,
) -> dict:
    """Fetch market_data signal events for *symbol*, adapt to candles, run engine.

    Returns an advisory-only chart structure report. Never places orders.
    Safety invariants are always present in the returned dict.
    Importable without FastAPI — no web framework dependency.
    """
    _safe_base = {
        "advisory_status": _ADVISORY_STATUS,
        "execution_gate": "LOCKED",
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }
    try:
        try:
            from scripts.persistence import get_signal_events, get_signal_events_for_symbol
        except ModuleNotFoundError:
            from persistence import get_signal_events, get_signal_events_for_symbol  # type: ignore

        try:
            from scripts.chart_structure_engine import analyze_chart_structure
        except ModuleNotFoundError:
            from chart_structure_engine import analyze_chart_structure  # type: ignore

        symbol_upper = symbol.strip().upper()

        # Pull a generous window of events ordered by candle timestamp DESC
        # (see persistence.get_signal_events_for_symbol — the sort key is
        # the embedded raw_payload.timestamp, NOT fetched_at).  We grab
        # ``limit * 6`` (min 600) so we can dedupe seed-vs-real candles by
        # date and still have at least ``limit`` real ones left.
        kwargs: dict = {
            "symbol": symbol_upper,
            "source_name": "market_data",
            "limit": max(limit * 6, 600),
        }
        if db_path is not None:
            kwargs["db_path"] = db_path

        events = get_signal_events_for_symbol(**kwargs)

        linked_event_id: str | None = None
        if source_event_id:
            matched = [ev for ev in events if ev.get("event_id") == source_event_id]
            if not matched:
                ge_kwargs: dict = {"limit": limit * 5}
                if db_path is not None:
                    ge_kwargs["db_path"] = db_path
                broader = get_signal_events(**ge_kwargs)
                matched = [ev for ev in broader if ev.get("event_id") == source_event_id]
            if matched:
                linked_event_id = matched[0].get("event_id")

        # Split real-backfill events from seed/demo events by event_id prefix.
        # Real backfill uses ``ohlcv_*`` (and ``global_ohlcv_*``); the demo
        # seeder uses ``seed_ohlcv_*``.
        real_evts = [
            ev for ev in events
            if str(ev.get("event_id", "")).startswith(("ohlcv_", "global_ohlcv_"))
        ]
        seed_evts = [
            ev for ev in events
            if str(ev.get("event_id", "")).startswith(("seed_ohlcv_", "seed_"))
        ]

        if real_evts:
            real_candles = _candles_from_market_events(real_evts)
            real_dates = {c["timestamp"][:10] for c in real_candles}
            extra_seed = [
                c for c in _candles_from_market_events(seed_evts)
                if c["timestamp"][:10] not in real_dates
            ]
            merged = sorted(real_candles + extra_seed, key=lambda c: c["timestamp"])
            # Source-kind reflects that we've got at least one real backfill row.
            source_kind = _freshness.CANONICAL_SQLITE
        else:
            merged = sorted(
                _candles_from_market_events(seed_evts or events),
                key=lambda c: c["timestamp"],
            )
            # No real backfill rows → either pure seed/demo or an unknown
            # provenance bucket.  classify accordingly so the freshness gate
            # can refuse to render a normal verdict over fixture data.
            source_kind = _resolve_source_kind(seed_evts or events, merged)

        # Select the LATEST `limit` candles (not the oldest).  Already sorted
        # ascending above, so tail-slice is safe.
        candles = merged[-limit:] if len(merged) > limit else merged

        if not candles:
            # Try symbol normalization to provide canonical info and exact commands
            canonical_symbol = symbol_upper
            security_meta: dict | None = None
            try:
                try:
                    from scripts.symbol_normalizer import normalize_symbol
                except ModuleNotFoundError:
                    from symbol_normalizer import normalize_symbol  # type: ignore[no-redef]
                norm = normalize_symbol(symbol_upper, db_path=db_path)
                canonical_symbol = norm.get("canonical_symbol", symbol_upper)
                security_meta = norm.get("security")
            except Exception:
                norm = {}

            discovery_cmd = (
                f"python scripts/global_security_master_discovery.py --symbols {canonical_symbol} --write"
            )
            backfill_cmd = (
                f"python scripts/backfill_global_ohlcv.py --symbols {canonical_symbol} --period max --interval 1d --write"
            )

            freshness = _freshness.evaluate(candles=[], source_kind=source_kind)
            return {
                **_safe_base,
                "ok": False,
                "reason": "NO_LOCAL_OHLCV",
                "can_bootstrap": True,
                "message": (
                    f"No local OHLCV candles found for {canonical_symbol}."
                ),
                "execution_mode": "HUMAN_ONLY",
                "symbol": canonical_symbol,
                "input_symbol": symbol_upper,
                "source_event_id": linked_event_id,
                "candle_count": 0,
                "chart_state": "INSUFFICIENT_DATA",
                "advisory_summary": (
                    f"No OHLCV candle data available for {canonical_symbol}. "
                    f"Click 'Yes, download data' to discover + backfill from the UI, "
                    f"or run manually: {discovery_cmd}  &&  {backfill_cmd}"
                ),
                "suggested_next_step": "DATA_REFRESH_REQUIRED",
                "freshness": freshness,
                "data_freshness_status": freshness.get("data_freshness_status"),
                "freshness_gate": freshness.get("freshness_gate"),
                "latest_candle_utc": freshness.get("latest_candle_utc"),
                "data_age_days": freshness.get("data_age_days"),
                "source_kind": freshness.get("source_kind"),
                "discovery_command": discovery_cmd,
                "backfill_command": backfill_cmd,
                "security": security_meta,
                "report": None,
            }

        # Freshness gate — block ancient / stale / mock-or-demo datasets
        # BEFORE running the chart structure engine.  This prevents the
        # frontend from ever seeing a normal "TRENDING_UP" verdict over
        # 2004 candles.
        freshness = _freshness.evaluate(
            candles=candles, source_kind=source_kind,
        )
        if freshness.get("freshness_gate") == _freshness.BLOCK:
            return _stale_safe_response(
                base=_safe_base,
                symbol=symbol_upper,
                candle_count=len(candles),
                freshness=freshness,
                linked_event_id=linked_event_id,
            )

        report = analyze_chart_structure(candles, symbol=symbol_upper, source="market_data")
        report_dict = report.to_dict()

        return {
            **_safe_base,
            "symbol": symbol_upper,
            "source_event_id": linked_event_id,
            "candle_count": len(candles),
            "report": report_dict,
            "freshness": freshness,
            "data_freshness_status": freshness.get("data_freshness_status"),
            "freshness_gate": freshness.get("freshness_gate"),
            "latest_candle_utc": freshness.get("latest_candle_utc"),
            "data_age_days": freshness.get("data_age_days"),
            "source_kind": freshness.get("source_kind"),
        }

    except Exception as exc:
        return {
            **_safe_base,
            "symbol": symbol,
            "source_event_id": source_event_id,
            "candle_count": 0,
            "chart_state": "ERROR",
            "error": str(exc),
            "report": None,
        }
