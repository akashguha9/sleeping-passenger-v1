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
