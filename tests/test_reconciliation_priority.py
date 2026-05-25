"""
Tests for constrained_first_priority ordering in the reconciliation queue.

Proves:
  - the queue is ordered by constrained_first_priority (fragile/high-risk first)
  - a high-leverage, missing-exit-data trade outranks a low-leverage,
    fully-journaled trade
  - the ordering is advisory-only and introduces no execution language
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import scripts.persistence as persistence
import scripts.reconciliation_queue as rq

_FORBIDDEN = (
    "place_order", "execute_trade", "trade_now", "auto_trade", "place order",
    "execute trade", "buy_now", "sell_now", "order_ready",
)


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "prio.db"
    persistence.init_schema(db)
    return db


def _insert(db: Path, *, trade_id, ticker, leverage, executed_at,
            invalidation_level="", exit_plan=""):
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO manual_trades"
            " (trade_id, event_id, ticker, side, quantity, price, executed_at,"
            "  thesis, leverage, invalidation_level, exit_plan, created_via)"
            " VALUES (?, ?, ?, 'BUY', 1.0, 100.0, ?, 'real thesis', ?, ?, ?,"
            "         'manual_trade_log')",
            (trade_id, f"USER_{trade_id}", ticker, executed_at, leverage,
             invalidation_level, exit_plan),
        )
        conn.commit()
    finally:
        conn.close()


def _flatten(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _flatten(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _flatten(v)
    else:
        yield str(obj)


def test_high_risk_trade_surfaces_first(tmp_path):
    db = _db(tmp_path)
    now = dt.datetime(2026, 5, 20, tzinfo=dt.timezone.utc)
    recent = "2026-05-19T12:00:00+00:00"
    # Low-risk: 1x leverage, full exit data.
    _insert(db, trade_id="LOWRISK", ticker="AAA", leverage=1.0,
            executed_at=recent, invalidation_level="95.0", exit_plan="exit at 110")
    # High-risk: 5x leverage, missing exit data.
    _insert(db, trade_id="HIGHRISK", ticker="BBB", leverage=5.0,
            executed_at=recent)

    payload = rq.build_queue(db, now=now)
    assert payload["ordering"] == "constrained_first_priority"
    assert payload["ordering_advisory_only"] is True
    tickers = [it["ticker"] for it in payload["items"]]
    assert tickers[0] == "BBB", f"high-risk trade should be first, got {tickers}"
    high = next(it for it in payload["items"] if it["ticker"] == "BBB")
    low = next(it for it in payload["items"] if it["ticker"] == "AAA")
    assert high["constrained_first_priority"] > low["constrained_first_priority"]


def test_priority_ordering_is_advisory_only(tmp_path):
    db = _db(tmp_path)
    _insert(db, trade_id="X1", ticker="AAA", leverage=3.0,
            executed_at="2026-05-19T12:00:00+00:00")
    payload = rq.build_queue(db)
    blob = "\n".join(_flatten(payload)).lower()
    for token in _FORBIDDEN:
        assert token not in blob, f"forbidden execution token {token!r} in queue payload"
    for it in payload["items"]:
        assert it["execution_permission"] is False
        assert it["can_execute"] is False
        assert it["broker_api_called"] is False
        assert "priority_bucket" in it
