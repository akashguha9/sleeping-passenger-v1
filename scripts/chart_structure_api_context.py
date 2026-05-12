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
"""
from __future__ import annotations

import json

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

        kwargs: dict = {"symbol": symbol_upper, "source_name": "market_data", "limit": max(limit * 6, 600)}
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

        real_evts = [ev for ev in events if str(ev.get("event_id", "")).startswith("ohlcv_")]
        seed_evts = [ev for ev in events if not str(ev.get("event_id", "")).startswith("ohlcv_")]

        if real_evts:
            real_candles = _candles_from_market_events(real_evts)
            real_dates = {c["timestamp"][:10] for c in real_candles}
            extra_seed = [
                c for c in _candles_from_market_events(seed_evts)
                if c["timestamp"][:10] not in real_dates
            ]
            merged = sorted(real_candles + extra_seed, key=lambda c: c["timestamp"])
        else:
            merged = sorted(
                _candles_from_market_events(seed_evts or events),
                key=lambda c: c["timestamp"],
            )

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
                "discovery_command": discovery_cmd,
                "backfill_command": backfill_cmd,
                "security": security_meta,
                "report": None,
            }

        report = analyze_chart_structure(candles, symbol=symbol_upper, source="market_data")
        report_dict = report.to_dict()

        return {
            **_safe_base,
            "symbol": symbol_upper,
            "source_event_id": linked_event_id,
            "candle_count": len(candles),
            "report": report_dict,
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
