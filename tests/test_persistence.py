"""
Tests for scripts/persistence.py — SQLite persistence layer.

Covers all 14 requirements from Step 3 (SQLite persistence):
  1.  DB created automatically
  2.  Schema initializes cleanly
  3.  Reflections persist and read back
  4.  AI summaries persist and read back
  5.  Decisions persist and read back
  6.  Manual trades persist with HUMAN_ONLY stamps
  7.  Reconciliations persist
  8.  Moltbook entries persist
  9.  Export functions can read persisted rows
  10. No forbidden execution function exists in persistence.py
  11. ai_execution_count is always 0
  12. advisory_status is always ADVISORY_ONLY
  13. broker_api_called is always False
  14. Runtime DB files are not tracked by Git
"""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_FUNCTIONS = {
    "place_order",
    "submit_order",
    "execute_trade",
    "auto_buy",
    "auto_sell",
    "cancel_order",
    "modify_order",
    "broker_execute",
    "live_execute",
    "connect_broker",
    "broker_login",
}


def _p():
    import scripts.persistence as p
    return p


# ---------------------------------------------------------------------------
# 1. DB created automatically
# ---------------------------------------------------------------------------


def test_db_created_automatically(tmp_path):
    p = _p()
    db = tmp_path / "auto_create.db"
    assert not db.exists()
    p.init_schema(db)
    assert db.exists()


# ---------------------------------------------------------------------------
# 2. Schema initializes cleanly — all required tables present
# ---------------------------------------------------------------------------


def test_schema_initializes_cleanly(tmp_path):
    p = _p()
    db = tmp_path / "schema.db"
    p.init_schema(db)

    conn = sqlite3.connect(str(db))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    required = {
        "signal_decisions",
        "user_reflections",
        "ai_discussion_summaries",
        "manual_trades",
        "reconciliation_results",
        "moltbook_entries",
        "source_health",
        "export_logs",
    }
    assert required.issubset(tables), f"Missing tables: {required - tables}"


# ---------------------------------------------------------------------------
# 3. Reflections persist and can be read back
# ---------------------------------------------------------------------------


def test_reflections_persist_and_read_back(tmp_path):
    p = _p()
    db = tmp_path / "refl.db"
    p.init_schema(db)

    p.insert_reflection(
        "REF_t001", "EVT_A", "human", "HIGH",
        "My detailed reflection text", "2026-01-01T00:00:00Z",
        db_path=db,
    )

    rows = p.get_reflections_for_event("EVT_A", db_path=db)
    assert len(rows) == 1
    r = rows[0]
    assert r["reflection_id"] == "REF_t001"
    assert r["reflection_text"] == "My detailed reflection text"
    assert r["conviction_level"] == "HIGH"
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["ai_execution_count"] == 0
    assert r["human_review_required"] is True

    # has_reflection check
    assert p.has_reflection("EVT_A", db_path=db) is True
    assert p.has_reflection("EVT_NONE", db_path=db) is False


# ---------------------------------------------------------------------------
# 4. AI summaries persist and can be read back
# ---------------------------------------------------------------------------


def test_ai_summaries_persist_and_read_back(tmp_path):
    p = _p()
    db = tmp_path / "ai_sum.db"
    p.init_schema(db)

    p.insert_ai_summary(
        "SUM_t001", "EVT_B", "AI_ADVISORY",
        "Advisory context only — not a trade recommendation",
        "2026-01-01T00:00:00Z",
        db_path=db,
    )

    rows = p.get_ai_summaries_for_event("EVT_B", db_path=db)
    assert len(rows) == 1
    s = rows[0]
    assert s["summary_id"] == "SUM_t001"
    assert s["model_label"] == "AI_ADVISORY"
    assert s["advisory_status"] == "ADVISORY_ONLY"
    assert s["ai_execution_count"] == 0

    assert p.has_ai_summary("EVT_B", db_path=db) is True
    assert p.has_ai_summary("EVT_NONE", db_path=db) is False


# ---------------------------------------------------------------------------
# 5. Decisions persist and can be read back (last-write-wins)
# ---------------------------------------------------------------------------


def test_decisions_persist_and_read_back(tmp_path):
    p = _p()
    db = tmp_path / "dec.db"
    p.init_schema(db)

    p.insert_signal_decision("EVT_C", "watchlist", "2026-01-01T00:00:00Z", db_path=db)
    p.insert_signal_decision("EVT_C", "human_review", "2026-01-02T00:00:00Z", db_path=db)

    latest = p.get_latest_signal_decision("EVT_C", db_path=db)
    assert latest is not None
    assert latest["user_status"] == "human_review"
    assert latest["advisory_status"] == "ADVISORY_ONLY"

    all_decisions = p.get_all_signal_decisions(db_path=db)
    assert all_decisions["EVT_C"] == "human_review"


# ---------------------------------------------------------------------------
# 6. Manual trades persist with HUMAN_ONLY stamps
# ---------------------------------------------------------------------------


def test_manual_trades_persist_human_only(tmp_path):
    p = _p()
    db = tmp_path / "trades.db"
    p.init_schema(db)

    p.insert_manual_trade(
        "MT_t001", "EVT_D", "AAPL", "BUY",
        10.0, 150.0, "2026-01-01T00:00:00Z",
        "Test thesis", "no notes", "human",
        db_path=db,
    )

    rows = p.get_all_manual_trades(db_path=db)
    assert len(rows) == 1
    t = rows[0]
    assert t["trade_id"] == "MT_t001"
    assert t["ticker"] == "AAPL"
    assert t["side"] == "BUY"
    assert t["execution_mode"] == "HUMAN_ONLY"
    assert t["ai_execution_count"] == 0
    assert t["broker_api_called"] is False
    assert t["broker_order_id"] == "NONE"
    assert t["advisory_status"] == "ADVISORY_ONLY"
    assert t["human_review_required"] is True

    # lookup by event
    by_event = p.get_trades_for_event("EVT_D", db_path=db)
    assert len(by_event) == 1

    # lookup event_id from trade_id
    assert p.get_event_id_for_trade("MT_t001", db_path=db) == "EVT_D"
    assert p.get_event_id_for_trade("MT_MISSING", db_path=db) == ""


# ---------------------------------------------------------------------------
# 7. Reconciliations persist
# ---------------------------------------------------------------------------


def test_reconciliations_persist(tmp_path):
    p = _p()
    db = tmp_path / "recon.db"
    p.init_schema(db)

    p.insert_reconciliation(
        "REC_t001", "MT_t001", "EVT_D",
        "2026-01-02T00:00:00Z",
        151.0, 10.0, "Closed position", 10.0, "WIN",
        db_path=db,
    )

    rows = p.get_reconciliations_for_trade("MT_t001", db_path=db)
    assert len(rows) == 1
    r = rows[0]
    assert r["reconciliation_id"] == "REC_t001"
    assert r["outcome_status"] == "WIN"
    assert r["pnl_estimate"] == 10.0
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["ai_execution_count"] == 0
    assert r["execution_mode"] == "HUMAN_ONLY"

    all_recons = p.get_all_reconciliations(db_path=db)
    assert len(all_recons) == 1


# ---------------------------------------------------------------------------
# 8. Moltbook entries persist
# ---------------------------------------------------------------------------


def test_moltbook_entries_persist(tmp_path):
    p = _p()
    db = tmp_path / "molt.db"
    p.init_schema(db)

    p.insert_moltbook_entry(
        "MB_t001", "EVT_E", "TSLA",
        "Signal said buy on momentum",
        "AI saw volume spike",
        "I thought entry was too late",
        "no_trade",
        "", "",
        "late_entry",
        "Enter earlier — within first 30 min of signal",
        "", "", "",
        "2026-01-01T00:00:00Z",
        db_path=db,
    )

    rows = p.get_moltbook_entries(db_path=db)
    assert len(rows) == 1
    m = rows[0]
    assert m["entry_id"] == "MB_t001"
    assert m["ticker"] == "TSLA"
    assert m["mistake_type"] == "late_entry"
    assert m["advisory_status"] == "ADVISORY_ONLY"
    assert m["ai_execution_count"] == 0
    assert m["execution_mode"] == "HUMAN_ONLY"

    # filtering by ticker
    by_ticker = p.get_moltbook_entries(ticker="TSLA", db_path=db)
    assert len(by_ticker) == 1
    assert p.get_moltbook_entries(ticker="AAPL", db_path=db) == []

    # filtering by mistake_type
    by_type = p.get_moltbook_entries(mistake_type="late_entry", db_path=db)
    assert len(by_type) == 1


# ---------------------------------------------------------------------------
# 9. Export functions can read persisted rows
# ---------------------------------------------------------------------------


def test_export_reads_persisted_rows(tmp_path):
    p = _p()
    db = tmp_path / "export.db"
    p.init_schema(db)

    p.insert_reflection(
        "REF_exp001", "EVT_F", "human", "MODERATE",
        "Export test reflection", "2026-01-01T00:00:00Z",
        db_path=db,
    )
    p.insert_manual_trade(
        "MT_exp001", "EVT_F", "GOOG", "BUY",
        5.0, 100.0, "2026-01-01T00:00:00Z",
        "export thesis", "", "human",
        db_path=db,
    )

    reflections = p.get_all_reflections(db_path=db)
    trades = p.get_all_manual_trades(db_path=db)
    assert any(r["reflection_id"] == "REF_exp001" for r in reflections)
    assert any(t["trade_id"] == "MT_exp001" for t in trades)

    # log an export and confirm it's recorded
    p.log_export("reflection_log", len(reflections), db_path=db)
    p.log_export("manual_trade_log", len(trades), db_path=db)

    status = p.get_db_status(db_path=db)
    assert status["table_row_counts"]["export_logs"] == 2
    assert status["table_row_counts"]["user_reflections"] == 1
    assert status["table_row_counts"]["manual_trades"] == 1


# ---------------------------------------------------------------------------
# 10. No forbidden execution functions in persistence.py
# ---------------------------------------------------------------------------


def test_no_forbidden_functions_in_persistence():
    src = (REPO_ROOT / "scripts" / "persistence.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    found = FORBIDDEN_FUNCTIONS & defined
    assert not found, f"Forbidden execution functions found in persistence.py: {found}"


# ---------------------------------------------------------------------------
# 11. ai_execution_count is always 0
# ---------------------------------------------------------------------------


def test_ai_execution_count_always_zero(tmp_path):
    p = _p()
    db = tmp_path / "ai_zero.db"
    p.init_schema(db)

    p.insert_manual_trade(
        "MT_z001", "EVT_Z", "MSFT", "SELL",
        5.0, 200.0, "2026-01-01T00:00:00Z",
        "thesis", "", "human", db_path=db,
    )
    p.insert_reflection(
        "REF_z001", "EVT_Z", "human", "LOW", "text",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    p.insert_ai_summary(
        "SUM_z001", "EVT_Z", "AI_ADVISORY", "summary",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    p.insert_moltbook_entry(
        "MB_z001", "EVT_Z", "MSFT", "", "", "", "no_trade", "", "",
        "missed_signal", "lesson text", "", "", "",
        "2026-01-01T00:00:00Z", db_path=db,
    )

    for t in p.get_all_manual_trades(db_path=db):
        assert t["ai_execution_count"] == 0, f"Non-zero ai_execution_count in trade: {t}"
    for r in p.get_all_reflections(db_path=db):
        assert r["ai_execution_count"] == 0, f"Non-zero ai_execution_count in reflection: {r}"
    for s in p.get_all_ai_summaries(db_path=db):
        assert s["ai_execution_count"] == 0, f"Non-zero ai_execution_count in summary: {s}"
    for m in p.get_moltbook_entries(db_path=db):
        assert m["ai_execution_count"] == 0, f"Non-zero ai_execution_count in moltbook: {m}"

    status = p.get_db_status(db_path=db)
    assert status["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 12. advisory_status is always ADVISORY_ONLY
# ---------------------------------------------------------------------------


def test_advisory_status_always_advisory_only(tmp_path):
    p = _p()
    db = tmp_path / "adv.db"
    p.init_schema(db)

    p.insert_signal_decision("EVT_ADV", "pending", "2026-01-01T00:00:00Z", db_path=db)
    p.insert_reflection(
        "REF_adv001", "EVT_ADV", "human", "MODERATE", "text",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    p.insert_moltbook_entry(
        "MB_adv001", "EVT_ADV", "NFLX", "", "", "", "no_trade", "", "",
        "no_trade_correct", "lesson", "", "", "",
        "2026-01-01T00:00:00Z", db_path=db,
    )

    for r in p.get_all_reflections(db_path=db):
        assert r["advisory_status"] == "ADVISORY_ONLY"
    for m in p.get_moltbook_entries(db_path=db):
        assert m["advisory_status"] == "ADVISORY_ONLY"

    decision = p.get_latest_signal_decision("EVT_ADV", db_path=db)
    assert decision["advisory_status"] == "ADVISORY_ONLY"

    status = p.get_db_status(db_path=db)
    assert status["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# 13. broker_api_called is always False; broker_order_id is always NONE
# ---------------------------------------------------------------------------


def test_broker_api_called_always_false(tmp_path):
    p = _p()
    db = tmp_path / "broker.db"
    p.init_schema(db)

    p.insert_manual_trade(
        "MT_br001", "EVT_BR", "AMZN", "BUY",
        1.0, 100.0, "2026-01-01T00:00:00Z",
        "thesis", "", "human", db_path=db,
    )
    p.insert_manual_trade(
        "MT_br002", "EVT_BR", "AMZN", "SELL",
        1.0, 110.0, "2026-01-02T00:00:00Z",
        "exit thesis", "", "human", db_path=db,
    )

    for t in p.get_all_manual_trades(db_path=db):
        assert t["broker_api_called"] is False, f"broker_api_called is True in: {t}"
        assert t["broker_order_id"] == "NONE", f"broker_order_id not NONE in: {t}"

    status = p.get_db_status(db_path=db)
    assert status["broker_api_called"] is False


# ---------------------------------------------------------------------------
# 14. Runtime DB files are not tracked by Git
# ---------------------------------------------------------------------------


def test_db_path_in_gitignored_runtime_dir():
    p = _p()
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    # Both coverage paths: runtime/ directory and *.db extension are gitignored
    assert "runtime/" in gitignore, "runtime/ must appear in .gitignore"
    assert "*.db" in gitignore, "*.db must appear in .gitignore"

    # DB_PATH must live inside runtime/
    db_path = p.DB_PATH
    assert "runtime" in str(db_path), (
        f"DB_PATH ({db_path}) must be inside runtime/ so it is gitignored"
    )
    assert db_path.suffix == ".db", f"DB_PATH suffix must be .db, got {db_path.suffix}"
