"""Tests for ``scripts.reconciliation_queue``.

Pin
---
- Empty DB returns empty queue, no crash, db_available=True.
- Missing DB returns empty queue + ``db_missing`` warning.
- Unreconciled trade appears; reconciled trade is excluded.
- ``age_days`` is computed when an explicit ``now`` is supplied.
- Journal-quality metadata (completeness, learning_ready, missing fields)
  is attached to every item.
- Safety stamps are locked on the envelope and on each item.
- Missing tables degrade gracefully without raising.
- ``--limit`` truncates the items but the summary is global.
- The script never writes to the DB.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path

import pytest

from scripts import reconciliation_queue as rq


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_schema(
    db_path: Path,
    *,
    with_recon: bool = True,
    with_created_via: bool = True,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        provenance_col = (
            ", created_via TEXT DEFAULT ''" if with_created_via else ""
        )
        conn.executescript(
            f"""
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT,
                ticker TEXT,
                side TEXT,
                quantity REAL,
                price REAL,
                executed_at TEXT,
                thesis TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                invalidation_level TEXT DEFAULT '',
                expected_horizon TEXT DEFAULT '',
                risk_reason TEXT DEFAULT '',
                entry_reason TEXT DEFAULT '',
                exit_plan TEXT DEFAULT '',
                confidence_before REAL,
                emotional_state TEXT DEFAULT '',
                mistake_tags TEXT DEFAULT '',
                lesson TEXT DEFAULT '',
                reconciliation_status TEXT DEFAULT '',
                broker_api_called INTEGER DEFAULT 0,
                ai_execution_count INTEGER DEFAULT 0
                {provenance_col}
            );
            """
        )
        if with_recon:
            conn.executescript(
                """
                CREATE TABLE reconciliation_results (
                    reconciliation_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    event_id TEXT,
                    reconciled_at TEXT,
                    actual_fill_price REAL,
                    actual_quantity REAL,
                    outcome_notes TEXT DEFAULT '',
                    pnl_estimate REAL DEFAULT 0.0,
                    outcome_status TEXT DEFAULT 'UNKNOWN'
                );
                """
            )
        conn.commit()
    finally:
        conn.close()


def _insert_trade(
    db_path: Path,
    *,
    trade_id: str,
    event_id: str = "EV1",
    ticker: str = "QQQ",
    side: str = "BUY",
    quantity: float = 10.0,
    price: float = 100.0,
    executed_at: str = "2026-04-01T00:00:00Z",
    thesis: str = "test thesis",
    invalidation_level: str = "",
    expected_horizon: str = "",
    risk_reason: str = "",
    entry_reason: str = "",
    exit_plan: str = "",
    confidence_before: float | None = None,
    emotional_state: str = "",
    mistake_tags: str = "",
    lesson: str = "",
    reconciliation_status: str = "",
    created_via: str = "manual_trade_log",
    broker_api_called: int = 0,
    ai_execution_count: int = 0,
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        base_cols = [
            "trade_id", "event_id", "ticker", "side", "quantity", "price",
            "executed_at", "thesis", "invalidation_level", "expected_horizon",
            "risk_reason", "entry_reason", "exit_plan", "confidence_before",
            "emotional_state", "mistake_tags", "lesson",
            "reconciliation_status", "broker_api_called", "ai_execution_count",
        ]
        base_vals = [
            trade_id, event_id, ticker, side, quantity, price,
            executed_at, thesis, invalidation_level, expected_horizon,
            risk_reason, entry_reason, exit_plan, confidence_before,
            emotional_state, mistake_tags, lesson,
            reconciliation_status, broker_api_called, ai_execution_count,
        ]
        if "created_via" in cols:
            base_cols.append("created_via")
            base_vals.append(created_via)
        placeholders = ",".join("?" for _ in base_cols)
        conn.execute(
            f"INSERT INTO manual_trades ({', '.join(base_cols)})"
            f" VALUES ({placeholders})",
            tuple(base_vals),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_reconciliation(db_path: Path, *, trade_id: str, recon_id: str = "R1") -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO reconciliation_results (reconciliation_id, trade_id, event_id,"
            " reconciled_at, actual_fill_price, actual_quantity, outcome_notes,"
            " pnl_estimate, outcome_status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (recon_id, trade_id, "EV1", "2026-04-05T00:00:00Z", 100.0, 10, "ok",
             50.0, "WIN"),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Empty / missing DB
# ---------------------------------------------------------------------------


def test_missing_db_returns_empty_queue(tmp_path):
    db_path = tmp_path / "absent.db"
    payload = rq.build_queue(db_path)
    assert payload["db_available"] is False
    assert payload["items"] == []
    assert "db_missing" in payload["warnings"]
    assert payload["summary"]["unreconciled_count"] == 0
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0


def test_empty_db_returns_empty_queue(tmp_path):
    db_path = tmp_path / "empty.db"
    _create_schema(db_path)
    payload = rq.build_queue(db_path)
    assert payload["db_available"] is True
    assert payload["items"] == []
    assert payload["summary"]["unreconciled_count"] == 0
    assert payload["summary"]["oldest_unreconciled_age_days"] is None
    assert payload["operator_action"]
    assert payload["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# Unreconciled / reconciled
# ---------------------------------------------------------------------------


def test_unreconciled_trade_appears(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(db_path, trade_id="T1")
    payload = rq.build_queue(db_path)
    assert payload["summary"]["unreconciled_count"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["trade_id"] == "T1"
    assert payload["items"][0]["needs_reconciliation"] is True
    assert payload["items"][0]["execution_permission"] is False
    assert payload["items"][0]["can_execute"] is False
    assert payload["items"][0]["broker_api_called"] is False


def test_reconciled_trade_excluded(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(db_path, trade_id="T1")
    _insert_trade(db_path, trade_id="T2", ticker="SPY")
    _insert_reconciliation(db_path, trade_id="T1")
    payload = rq.build_queue(db_path)
    ids = [it["trade_id"] for it in payload["items"]]
    assert ids == ["T2"]
    assert payload["summary"]["unreconciled_count"] == 1


# ---------------------------------------------------------------------------
# Age, journal quality
# ---------------------------------------------------------------------------


def test_age_days_computed_with_explicit_now(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path, trade_id="T1", executed_at="2026-04-01T00:00:00Z"
    )
    now = _dt.datetime(2026, 4, 11, 0, 0, 0, tzinfo=_dt.timezone.utc)
    payload = rq.build_queue(db_path, now=now)
    item = payload["items"][0]
    assert item["age_days"] == pytest.approx(10.0, rel=1e-6)
    assert payload["summary"]["oldest_unreconciled_age_days"] == pytest.approx(
        10.0, rel=1e-6
    )


def test_age_days_none_when_timestamp_malformed(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(db_path, trade_id="T1", executed_at="not-a-date")
    payload = rq.build_queue(db_path)
    assert payload["items"][0]["age_days"] is None


def test_journal_quality_metadata_attached(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path,
        trade_id="T_strong",
        thesis="meta tightening",
        invalidation_level="9100",
        expected_horizon="2-4 weeks",
        risk_reason="position 1R",
        entry_reason="breakout retest",
        exit_plan="trail by 2 ATR",
        confidence_before=0.6,
        emotional_state="calm",
        mistake_tags="overconfident",
        lesson="wait for volume",
    )
    _insert_trade(db_path, trade_id="T_weak", thesis="")
    payload = rq.build_queue(db_path)
    by_id = {it["trade_id"]: it for it in payload["items"]}
    strong = by_id["T_strong"]
    weak = by_id["T_weak"]
    assert strong["journal_completeness_score"] > weak["journal_completeness_score"]
    assert "missing_journal_fields" in strong
    assert "missing_journal_fields" in weak
    assert "thesis" in weak["missing_journal_fields"]


# ---------------------------------------------------------------------------
# Summary distributions
# ---------------------------------------------------------------------------


def test_summary_distributions(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(db_path, trade_id="T1", ticker="QQQ", emotional_state="fomo",
                  expected_horizon="2w")
    _insert_trade(db_path, trade_id="T2", ticker="QQQ", emotional_state="calm",
                  expected_horizon="2w")
    _insert_trade(db_path, trade_id="T3", ticker="SPY", emotional_state="fomo",
                  expected_horizon="")
    payload = rq.build_queue(db_path)
    summary = payload["summary"]
    assert summary["by_ticker"] == {"QQQ": 2, "SPY": 1}
    assert summary["by_emotional_state"]["fomo"] == 2
    assert summary["by_emotional_state"]["calm"] == 1
    assert summary["by_expected_horizon"]["2w"] == 2
    assert summary["by_expected_horizon"]["UNRECORDED"] == 1


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


def test_limit_truncates_items_but_summary_is_global(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    for i in range(5):
        _insert_trade(
            db_path,
            trade_id=f"T{i}",
            executed_at=f"2026-04-0{i+1}T00:00:00Z",
        )
    payload = rq.build_queue(db_path, limit=2)
    assert len(payload["items"]) == 2
    assert payload["summary"]["unreconciled_count"] == 5
    assert payload.get("truncated") is True
    assert payload.get("truncated_to") == 2


def test_limit_zero_returns_no_items(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(db_path, trade_id="T1")
    payload = rq.build_queue(db_path, limit=0)
    assert payload["items"] == []
    assert payload["summary"]["unreconciled_count"] == 1


# ---------------------------------------------------------------------------
# Missing tables / graceful degradation
# ---------------------------------------------------------------------------


def test_missing_manual_trades_table(tmp_path):
    db_path = tmp_path / "queue.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            "CREATE TABLE other (id INTEGER PRIMARY KEY);"
        )
        conn.commit()
    finally:
        conn.close()
    payload = rq.build_queue(db_path)
    assert payload["summary"]["unreconciled_count"] == 0
    assert "manual_trades_table_missing" in payload["warnings"]
    assert payload["execution_permission"] is False


def test_missing_recon_table_keeps_trades_unreconciled(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path, with_recon=False)
    _insert_trade(db_path, trade_id="T1")
    payload = rq.build_queue(db_path)
    # The SQL refers to reconciliation_results, so the query errors and the
    # script must degrade cleanly rather than raise.
    assert "reconciliation_results_table_missing" in payload["warnings"]
    assert any(
        w.startswith("query_failed:") for w in payload["warnings"]
    )


# ---------------------------------------------------------------------------
# No DB writes
# ---------------------------------------------------------------------------


def test_no_db_writes(tmp_path):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(db_path, trade_id="T1")
    size_before = db_path.stat().st_size
    mtime_before = db_path.stat().st_mtime
    rq.build_queue(db_path)
    assert db_path.stat().st_size == size_before
    assert db_path.stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_json(tmp_path, capsys):
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(db_path, trade_id="T1")
    rc = rq.main(["--db-path", str(db_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "advisory_status" in out
    assert "T1" in out
    assert "broker_api_called" in out


def test_cli_json_missing_db(tmp_path, capsys):
    db_path = tmp_path / "absent.db"
    rc = rq.main(["--db-path", str(db_path), "--json"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "db_missing" in out


# ---------------------------------------------------------------------------
# Provenance contract — Reconciliation is a human-manual-log queue only
# ---------------------------------------------------------------------------


def test_human_manual_trade_log_row_appears(tmp_path):
    """A row created through the Manual Trade Log path is in the queue."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path,
        trade_id="MT_human1",
        ticker="ICICIBANK.NS",
        created_via="manual_trade_log",
    )
    payload = rq.build_queue(db_path)
    ids = [it["trade_id"] for it in payload["items"]]
    assert ids == ["MT_human1"]
    assert payload["summary"]["unreconciled_count"] == 1


def test_seed_row_excluded_from_queue(tmp_path):
    """Seed/sample rows with empty provenance must not appear."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path,
        trade_id="MT_seed_spy",
        ticker="SPY",
        thesis="Strong persistence in recent window",
        created_via="",  # empty == unknown provenance, excluded
    )
    _insert_trade(
        db_path,
        trade_id="MT_seed_qqq",
        ticker="QQQ",
        side="SELL",
        thesis="Exit on kill rate spike",
        created_via="",
    )
    _insert_trade(
        db_path,
        trade_id="MT_human1",
        ticker="ICICIBANK.NS",
        created_via="manual_trade_log",
    )
    payload = rq.build_queue(db_path)
    ids = [it["trade_id"] for it in payload["items"]]
    assert ids == ["MT_human1"]
    tickers = [it["ticker"] for it in payload["items"]]
    assert "SPY" not in tickers
    assert "QQQ" not in tickers


def test_unknown_provenance_legacy_row_excluded(tmp_path):
    """Rows with an unrecognized provenance string are still excluded."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path, trade_id="MT_legacy", created_via="imported_csv"
    )
    payload = rq.build_queue(db_path)
    assert payload["items"] == []
    assert payload["summary"]["unreconciled_count"] == 0


def test_cancelled_human_log_excluded(tmp_path):
    """A soft-cancelled human manual log no longer awaits reconciliation."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path,
        trade_id="MT_human1",
        ticker="ICICIBANK.NS",
        created_via="manual_trade_log",
        reconciliation_status="CANCELLED_DUPLICATE",
    )
    payload = rq.build_queue(db_path)
    assert payload["items"] == []


def test_reconciled_human_log_excluded(tmp_path):
    """A reconciled human manual log is not in the awaiting queue."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path,
        trade_id="MT_human1",
        ticker="ICICIBANK.NS",
        created_via="manual_trade_log",
    )
    _insert_reconciliation(db_path, trade_id="MT_human1")
    payload = rq.build_queue(db_path)
    assert payload["items"] == []


def test_broker_api_called_row_excluded_even_with_provenance(tmp_path):
    """Defence in depth: a row that ever claimed a broker call is excluded."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path,
        trade_id="MT_corrupt",
        created_via="manual_trade_log",
        broker_api_called=1,
    )
    payload = rq.build_queue(db_path)
    assert payload["items"] == []


def test_ai_execution_count_nonzero_row_excluded(tmp_path):
    """Defence in depth: ai_execution_count!=0 is excluded."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path,
        trade_id="MT_corrupt",
        created_via="manual_trade_log",
        ai_execution_count=1,
    )
    payload = rq.build_queue(db_path)
    assert payload["items"] == []


def test_missing_created_via_column_emits_warning_and_excludes_all(tmp_path):
    """Very old DBs lacking the provenance column must not leak seeds."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path, with_created_via=False)
    _insert_trade(db_path, trade_id="T1")
    payload = rq.build_queue(db_path)
    assert payload["items"] == []
    assert "manual_trades_missing_created_via_column" in payload["warnings"]


def test_safety_stamps_locked_on_queue_envelope(tmp_path):
    """No code path may flip broker_api_called or ai_execution_count."""
    db_path = tmp_path / "queue.db"
    _create_schema(db_path)
    _insert_trade(
        db_path, trade_id="MT_human1", created_via="manual_trade_log"
    )
    payload = rq.build_queue(db_path)
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False
    for item in payload["items"]:
        assert item["broker_api_called"] is False
        assert item["ai_execution_count"] == 0
