"""
Tests for the Manual Trade Log leverage field.

Covers:
  1. log_manual_trade accepts and persists leverage.
  2. log_manual_trade defaults missing/None leverage to 1.0.
  3. log_manual_trade validates leverage bounds (>= 1.0, <= 25.0).
  4. log_manual_trade safety invariants unchanged:
       advisory_status = ADVISORY_ONLY
       execution_mode  = HUMAN_ONLY
       broker_api_called = False
       broker_order_id = "NONE"
       ai_execution_count = 0
  5. Persistence layer stores and reads back leverage.
  6. Existing rows without a leverage column are auto-migrated and read as 1.0.
  7. CSV export contains a leverage column.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _api():
    import scripts.signal_inbox_api as api
    return api


def _p():
    import scripts.persistence as p
    return p


# ---------------------------------------------------------------------------
# 1. log_manual_trade accepts and returns leverage
# ---------------------------------------------------------------------------


def test_log_manual_trade_accepts_leverage(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY",
        ticker="SPY",
        side="BUY",
        quantity=10.0,
        price=450.0,
        thesis="leveraged thesis",
        leverage=3.5,
    )
    assert result["status"] == "logged"
    assert result["leverage"] == 3.5
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == "NONE"
    assert result["ai_execution_count"] == 0

    rows = [json.loads(line) for line in (tmp_path / "trades.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["leverage"] == 3.5


# ---------------------------------------------------------------------------
# 2. log_manual_trade defaults missing/None leverage to 1.0
# ---------------------------------------------------------------------------


def test_log_manual_trade_default_leverage(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    # Default kwarg
    result = api.log_manual_trade(
        event_id="EVT_LOG_AAPL",
        ticker="AAPL",
        side="BUY",
        quantity=1.0,
        price=200.0,
        thesis="no explicit leverage",
    )
    assert result["leverage"] == 1.0

    # Explicit None coerces to 1.0
    result = api.log_manual_trade(
        event_id="EVT_LOG_AAPL",
        ticker="AAPL",
        side="BUY",
        quantity=1.0,
        price=200.0,
        thesis="None leverage",
        leverage=None,  # type: ignore[arg-type]
    )
    assert result["leverage"] == 1.0


# ---------------------------------------------------------------------------
# 3. Leverage bounds validation
# ---------------------------------------------------------------------------


def test_log_manual_trade_rejects_leverage_below_1(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY", ticker="SPY", side="BUY",
        quantity=1, price=100, thesis="x", leverage=0.5,
    )
    assert "error" in result
    assert result["ai_execution_count"] == 0


def test_log_manual_trade_rejects_leverage_above_max(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY", ticker="SPY", side="BUY",
        quantity=1, price=100, thesis="x", leverage=100.0,
    )
    assert "error" in result


def test_log_manual_trade_rejects_non_numeric_leverage(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY", ticker="SPY", side="BUY",
        quantity=1, price=100, thesis="x", leverage="five",  # type: ignore[arg-type]
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# 4. Persistence round-trip stores and reads leverage
# ---------------------------------------------------------------------------


def test_persistence_stores_and_reads_leverage(tmp_path):
    p = _p()
    db = tmp_path / "lev.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "MT_lev1", "EVT_X", "AAPL", "BUY",
        2.0, 150.0, "2026-05-12T00:00:00Z",
        "test", "no notes", "human",
        db_path=db, leverage=4.0,
    )
    rows = p.get_all_manual_trades(db_path=db)
    assert len(rows) == 1
    t = rows[0]
    assert t["leverage"] == 4.0
    assert t["advisory_status"] == "ADVISORY_ONLY"
    assert t["execution_mode"] == "HUMAN_ONLY"
    assert t["broker_api_called"] is False
    assert t["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 5. Additive migration: old DB without leverage column gets one and reads 1.0
# ---------------------------------------------------------------------------


def test_persistence_additive_migration_for_legacy_db(tmp_path):
    p = _p()
    db = tmp_path / "legacy.db"

    # Build a *legacy* manual_trades table missing the leverage column.
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                executed_at TEXT NOT NULL,
                thesis TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                logged_by TEXT NOT NULL DEFAULT 'human',
                execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
                ai_execution_count INTEGER NOT NULL DEFAULT 0,
                advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
                human_review_required INTEGER NOT NULL DEFAULT 1,
                broker_order_id TEXT NOT NULL DEFAULT 'NONE',
                broker_api_called INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        conn.execute(
            "INSERT INTO manual_trades"
            " (trade_id, event_id, ticker, side, quantity, price, executed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("MT_legacy", "EVT_LEG", "MSFT", "BUY", 1.0, 300.0, "2026-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    # init_schema must apply the additive migration without dropping data
    p._initialized.discard(str(db.resolve()))
    p.init_schema(db)

    conn = sqlite3.connect(str(db))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(manual_trades)").fetchall()}
    finally:
        conn.close()
    assert "leverage" in cols, "additive migration should add the leverage column"

    rows = p.get_all_manual_trades(db_path=db)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "MT_legacy"
    # legacy row had no leverage value — read-back must coerce to 1.0
    assert rows[0]["leverage"] == 1.0


# ---------------------------------------------------------------------------
# 6. Export includes leverage column
# ---------------------------------------------------------------------------


def test_export_manual_trade_log_contains_leverage_column():
    from scripts import gsheet_export as ex
    assert "leverage" in ex.MANUAL_TRADE_HEADERS


def test_export_manual_trade_log_defaults_missing_leverage_to_1():
    from scripts import gsheet_export as ex
    row = {
        "trade_id": "MT_x",
        "event_id": "EVT_y",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1.0,
        "price": 100.0,
        "executed_at": "2026-05-12T00:00:00Z",
        "thesis": "",
        "notes": "",
        "logged_by": "human",
        "execution_mode": "HUMAN_ONLY",
        "ai_execution_count": 0,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        # leverage intentionally omitted
    }
    projected = ex._enforce_advisory(row, ex.MANUAL_TRADE_HEADERS)
    assert projected["leverage"] == 1.0


# ---------------------------------------------------------------------------
# 7. Safety invariants on every leverage-bearing path
# ---------------------------------------------------------------------------


def test_safety_invariants_preserved_with_leverage(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    result = api.log_manual_trade(
        event_id="EVT_LOG_TSLA",
        ticker="TSLA",
        side="SELL",
        quantity=1.0,
        price=250.0,
        thesis="safety check",
        leverage=5.0,
    )
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["human_review_required"] is True
    assert result["ai_execution_count"] == 0
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == "NONE"
