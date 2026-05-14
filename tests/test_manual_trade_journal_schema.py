"""Tests for the additive manual-trade / reconciliation journal-quality schema.

Why this test exists
--------------------
The Operator Discipline UI + Journal Schema Sprint adds nine new columns to
``manual_trades`` and five new columns to ``reconciliation_results``.  The
migration must be:

* additive only (no DROP, no DELETE),
* idempotent (running twice is a no-op),
* survivable for existing rows (no data loss when migrating a populated DB),
* safe on a fresh install (``CREATE TABLE`` inline definitions match),
* tolerant when ``reconciliation_results`` is absent (the helper must skip).

Every assertion runs against a ``tmp_path`` SQLite DB — ``runtime/mvp_local.db``
is never touched.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import persistence


MANUAL_TRADE_NEW_COLUMNS = (
    "invalidation_level",
    "expected_horizon",
    "risk_reason",
    "entry_reason",
    "exit_plan",
    "confidence_before",
    "emotional_state",
    "mistake_tags",
    "lesson",
)


RECONCILIATION_NEW_COLUMNS = (
    "outcome_quality",
    "process_error",
    "process_error_notes",
    "mistake_tags",
    "lesson",
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def test_fresh_db_has_new_manual_trade_fields(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    persistence.init_schema(db)
    with _open(db) as conn:
        cols = _columns(conn, "manual_trades")
    for col in MANUAL_TRADE_NEW_COLUMNS:
        assert col in cols, f"missing {col} from manual_trades fresh schema"


def test_fresh_db_has_new_reconciliation_fields(tmp_path: Path) -> None:
    db = tmp_path / "fresh_recon.db"
    persistence.init_schema(db)
    with _open(db) as conn:
        cols = _columns(conn, "reconciliation_results")
    for col in RECONCILIATION_NEW_COLUMNS:
        assert col in cols, f"missing {col} from reconciliation_results fresh schema"


def test_legacy_manual_trades_db_gets_columns_via_migration(tmp_path: Path) -> None:
    """A DB created with only the pre-sprint columns must gain the new ones
    when ``init_schema`` is re-run."""
    db = tmp_path / "legacy.db"
    legacy_sql = """
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
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(legacy_sql)
        conn.execute(
            "INSERT INTO manual_trades"
            " (trade_id, event_id, ticker, side, quantity, price, executed_at,"
            "  thesis, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("MT_LEGACY", "EV_LEGACY", "BTC", "BUY", 1.0, 100.0,
             "2024-01-01T00:00:00Z", "legacy thesis", "legacy notes"),
        )
        conn.commit()
    finally:
        conn.close()

    persistence.init_schema(db)
    persistence._initialized.discard(str(db.resolve()))
    persistence.init_schema(db)  # twice — must be idempotent

    with _open(db) as conn:
        cols = _columns(conn, "manual_trades")
        row = conn.execute(
            "SELECT * FROM manual_trades WHERE trade_id='MT_LEGACY'"
        ).fetchone()

    for col in MANUAL_TRADE_NEW_COLUMNS:
        assert col in cols, f"migration did not add {col}"
    assert row is not None, "existing manual_trade row was lost by migration"
    assert row["thesis"] == "legacy thesis"
    assert row["notes"] == "legacy notes"
    for col in MANUAL_TRADE_NEW_COLUMNS:
        if col == "confidence_before":
            assert row[col] is None
        else:
            assert row[col] == ""


def test_legacy_reconciliation_db_gets_columns_via_migration(tmp_path: Path) -> None:
    db = tmp_path / "legacy_recon.db"
    legacy_sql = """
    CREATE TABLE reconciliation_results (
        reconciliation_id TEXT PRIMARY KEY,
        trade_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        reconciled_at TEXT NOT NULL,
        actual_fill_price REAL NOT NULL,
        actual_quantity REAL NOT NULL,
        outcome_notes TEXT NOT NULL DEFAULT '',
        pnl_estimate REAL NOT NULL DEFAULT 0.0,
        outcome_status TEXT NOT NULL DEFAULT 'UNKNOWN',
        execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
        ai_execution_count INTEGER NOT NULL DEFAULT 0,
        advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
        human_review_required INTEGER NOT NULL DEFAULT 1
    );
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(legacy_sql)
        conn.execute(
            "INSERT INTO reconciliation_results"
            " (reconciliation_id, trade_id, event_id, reconciled_at,"
            "  actual_fill_price, actual_quantity, outcome_notes,"
            "  pnl_estimate, outcome_status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("REC_LEGACY", "MT_LEGACY", "EV_LEGACY",
             "2024-01-02T00:00:00Z", 101.0, 1.0, "legacy notes", 1.0, "WIN"),
        )
        conn.commit()
    finally:
        conn.close()

    persistence.init_schema(db)
    persistence._initialized.discard(str(db.resolve()))
    persistence.init_schema(db)

    with _open(db) as conn:
        cols = _columns(conn, "reconciliation_results")
        row = conn.execute(
            "SELECT * FROM reconciliation_results WHERE reconciliation_id='REC_LEGACY'"
        ).fetchone()

    for col in RECONCILIATION_NEW_COLUMNS:
        assert col in cols
    assert row is not None
    assert row["outcome_status"] == "WIN"
    for col in RECONCILIATION_NEW_COLUMNS:
        assert row[col] == ""


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "idempotent.db"
    persistence.init_schema(db)
    # Capture column ordering after first init
    with _open(db) as conn:
        cols_a = list(conn.execute("PRAGMA table_info(manual_trades)").fetchall())
    persistence._initialized.discard(str(db.resolve()))
    persistence.init_schema(db)
    persistence._initialized.discard(str(db.resolve()))
    persistence.init_schema(db)
    with _open(db) as conn:
        cols_b = list(conn.execute("PRAGMA table_info(manual_trades)").fetchall())
    assert [c[1] for c in cols_a] == [c[1] for c in cols_b]


def test_migration_tolerates_missing_reconciliation_table(tmp_path: Path) -> None:
    """If reconciliation_results is missing, the additive helper must skip."""
    db = tmp_path / "no_recon.db"
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
        conn.commit()
    finally:
        conn.close()
    # Should not raise — reconciliation_results doesn't exist yet.
    persistence.init_schema(db)
    with _open(db) as conn:
        # Now both tables exist (init_schema creates them via _SCHEMA_SQL)
        assert "manual_trades" in {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


def test_confidence_before_accepts_null_and_numeric(tmp_path: Path) -> None:
    db = tmp_path / "confidence.db"
    persistence.init_schema(db)
    # NULL via insert_manual_trade with no confidence
    persistence.insert_manual_trade(
        trade_id="MT_NULL",
        event_id="EV1",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=100.0,
        executed_at="2024-01-01T00:00:00Z",
        thesis="t1",
        notes="",
        logged_by="human",
        db_path=db,
    )
    # Fractional [0,1]
    persistence.insert_manual_trade(
        trade_id="MT_FRAC",
        event_id="EV2",
        ticker="ETH",
        side="BUY",
        quantity=1.0,
        price=100.0,
        executed_at="2024-01-01T00:00:00Z",
        thesis="t2",
        notes="",
        logged_by="human",
        db_path=db,
        confidence_before=0.65,
    )
    # Percentage [0,100]
    persistence.insert_manual_trade(
        trade_id="MT_PCT",
        event_id="EV3",
        ticker="SOL",
        side="BUY",
        quantity=1.0,
        price=100.0,
        executed_at="2024-01-01T00:00:00Z",
        thesis="t3",
        notes="",
        logged_by="human",
        db_path=db,
        confidence_before=72,
    )
    # Bad inputs all coerce to NULL — never raise.
    for bad in ("not a number", -1, 999.0, float("nan"), True):
        persistence.insert_manual_trade(
            trade_id=f"MT_BAD_{bad!r}",
            event_id="EV_BAD",
            ticker="BAD",
            side="BUY",
            quantity=1.0,
            price=100.0,
            executed_at="2024-01-01T00:00:00Z",
            thesis="x",
            notes="",
            logged_by="human",
            db_path=db,
            confidence_before=bad,
        )

    with _open(db) as conn:
        rows = {r["trade_id"]: r for r in conn.execute(
            "SELECT trade_id, confidence_before FROM manual_trades"
        ).fetchall()}

    assert rows["MT_NULL"]["confidence_before"] is None
    assert rows["MT_FRAC"]["confidence_before"] == pytest.approx(0.65)
    assert rows["MT_PCT"]["confidence_before"] == pytest.approx(72.0)
    for tid in [k for k in rows if k.startswith("MT_BAD_")]:
        assert rows[tid]["confidence_before"] is None


def test_default_text_fields_are_empty_string_not_null(tmp_path: Path) -> None:
    db = tmp_path / "defaults.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        trade_id="MT_DEFAULT",
        event_id="EV_DEFAULT",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=100.0,
        executed_at="2024-01-01T00:00:00Z",
        thesis="t",
        notes="",
        logged_by="human",
        db_path=db,
    )
    with _open(db) as conn:
        row = conn.execute(
            "SELECT * FROM manual_trades WHERE trade_id='MT_DEFAULT'"
        ).fetchone()
    text_cols = [c for c in MANUAL_TRADE_NEW_COLUMNS if c != "confidence_before"]
    for col in text_cols:
        assert row[col] == "", f"column {col} should default to '' not {row[col]!r}"


def test_insert_manual_trade_persists_journal_fields(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        trade_id="MT_JRN",
        event_id="EV_JRN",
        ticker="ETH",
        side="BUY",
        quantity=2.0,
        price=2000.0,
        executed_at="2024-02-01T00:00:00Z",
        thesis="thesis text",
        notes="notes text",
        logged_by="human",
        db_path=db,
        invalidation_level="1950",
        expected_horizon="2-5d",
        risk_reason="size <=1R",
        entry_reason="break of structure",
        exit_plan="trim 50% at 2100, exit at 1950",
        confidence_before=0.55,
        emotional_state="calm",
        mistake_tags="late_entry,oversized",
        lesson="wait for retest next time",
    )
    with _open(db) as conn:
        row = conn.execute(
            "SELECT * FROM manual_trades WHERE trade_id='MT_JRN'"
        ).fetchone()
    assert row["invalidation_level"] == "1950"
    assert row["expected_horizon"] == "2-5d"
    assert row["risk_reason"] == "size <=1R"
    assert row["entry_reason"] == "break of structure"
    assert row["exit_plan"] == "trim 50% at 2100, exit at 1950"
    assert row["confidence_before"] == pytest.approx(0.55)
    assert row["emotional_state"] == "calm"
    assert row["mistake_tags"] == "late_entry,oversized"
    assert row["lesson"] == "wait for retest next time"


def test_insert_reconciliation_persists_outcome_quality(tmp_path: Path) -> None:
    db = tmp_path / "recon_outcome.db"
    persistence.init_schema(db)
    persistence.insert_reconciliation(
        reconciliation_id="REC_NEW",
        trade_id="MT_X",
        event_id="EV_X",
        reconciled_at="2024-03-01T00:00:00Z",
        actual_fill_price=100.0,
        actual_quantity=1.0,
        outcome_notes="stopped out late",
        pnl_estimate=-50.0,
        outcome_status="LOSS",
        db_path=db,
        outcome_quality="process_error",
        process_error="no_invalidation_set",
        process_error_notes="forgot to set stop",
        mistake_tags="no_stop",
        lesson="never enter without a stop level",
    )
    with _open(db) as conn:
        row = conn.execute(
            "SELECT * FROM reconciliation_results WHERE reconciliation_id='REC_NEW'"
        ).fetchone()
    assert row["outcome_quality"] == "process_error"
    assert row["process_error"] == "no_invalidation_set"
    assert row["process_error_notes"] == "forgot to set stop"
    assert row["mistake_tags"] == "no_stop"
    assert row["lesson"] == "never enter without a stop level"


def test_no_destructive_columns_dropped(tmp_path: Path) -> None:
    """Belt-and-braces: no pre-sprint column is lost from either table."""
    db = tmp_path / "drop_check.db"
    persistence.init_schema(db)
    with _open(db) as conn:
        mt_cols = _columns(conn, "manual_trades")
        rec_cols = _columns(conn, "reconciliation_results")
    required_mt = {
        "trade_id", "event_id", "ticker", "side", "quantity", "price",
        "executed_at", "thesis", "notes", "logged_by", "leverage",
        "execution_mode", "ai_execution_count", "advisory_status",
        "human_review_required", "broker_order_id", "broker_api_called",
    }
    required_rec = {
        "reconciliation_id", "trade_id", "event_id", "reconciled_at",
        "actual_fill_price", "actual_quantity", "outcome_notes",
        "pnl_estimate", "outcome_status", "execution_mode",
        "ai_execution_count", "advisory_status", "human_review_required",
    }
    assert required_mt.issubset(mt_cols)
    assert required_rec.issubset(rec_cols)
