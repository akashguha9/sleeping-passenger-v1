"""Shared seeding helpers for the Forward Snapshot Contract Sprint tests.

Pure test utilities: seed a temp SQLite DB with a CompleteScore side-table
vector and real ``market_data`` OHLCV bars, so the daily decision batch can be
exercised offline and deterministically.  No network, no execution.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from scripts import persistence
from scripts.real_signal_score_vector import SCORING_VERSION
from scripts.score_real_signal_events import (
    SCORE_VECTOR_TABLE,
    ensure_score_vector_schema,
    score_key,
)

_COMPLETE_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.5, "LS": 0.45, "EFS": 0.6, "APS": 0.5}


def init_db(db_path: Any) -> None:
    persistence.init_schema(db_path)
    ensure_score_vector_schema(db_path)


def seed_score_vector(
    db_path: Any,
    *,
    event_id: str,
    source_name: str = "sec_edgar",
    ticker: str | None = "AAPL",
    scored: bool = True,
    axes: dict[str, float] | None = None,
    scored_at_utc: str = "2026-05-10T00:00:00Z",
) -> None:
    """Insert a side-table score vector (CompleteScore when ``scored``)."""
    ensure_score_vector_schema(db_path)
    a = dict(axes or _COMPLETE_AXES)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO {SCORE_VECTOR_TABLE} ("
            " score_key, event_id, source_name, ticker, timestamp_utc,"
            " EMS, EQS, DS, LS, EFS, APS,"
            " score_status, score_reason, scoring_version, model_version,"
            " scored_at_utc, real_row, mock_flag, backfill_flag,"
            " advisory_status, human_execution_required, execution_gate,"
            " broker_api_called, ai_execution_count"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                score_key(event_id, source_name, SCORING_VERSION), event_id,
                source_name, ticker, scored_at_utc,
                a["EMS"], a["EQS"], a["DS"], a["LS"], a["EFS"], a["APS"],
                "SCORED" if scored else "SCORE_UNAVAILABLE",
                "OK" if scored else "MISSING_FIELDS",
                SCORING_VERSION, "advisory-logistic-v1", scored_at_utc,
                1, 0, 0, "ADVISORY_ONLY", 1, "LOCKED", 0, 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def seed_market_bar(
    db_path: Any,
    *,
    symbol: str,
    timestamp: str,
    close: float,
    event_id: str | None = None,
) -> None:
    """Insert one real ``market_data`` OHLCV bar into ``signal_events``."""
    eid = event_id or f"market_data_{symbol}_{timestamp}".replace(" ", "_").replace(":", "")
    payload = {
        "event_id": eid,
        "source_name": "market_data",
        "signal_type": "market_price",
        "symbol": symbol,
        "provider": "yahoo",
        "timestamp": timestamp,
        "close": close,
    }
    persistence.insert_signal_event(
        event_id=eid, source_name="market_data", raw_payload=payload,
        fetched_at=timestamp, db_path=db_path,
    )


def event_row(event_id: str, *, payload: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build an event row dict to feed ``run_daily_decision_batch(events=...)``."""
    row: dict[str, Any] = {"event_id": event_id, "raw_payload": payload or {}}
    row.update(extra)
    return row


def read_snapshot(db_path: Any, *, signal_id: str | None = None) -> dict[str, Any] | None:
    """Read back the latest decision snapshot (optionally by signal_id)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        if signal_id is not None:
            row = conn.execute(
                "SELECT * FROM decision_probability_snapshots WHERE signal_id=?"
                " ORDER BY timestamp_utc DESC LIMIT 1",
                (signal_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM decision_probability_snapshots"
                " ORDER BY timestamp_utc DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()
