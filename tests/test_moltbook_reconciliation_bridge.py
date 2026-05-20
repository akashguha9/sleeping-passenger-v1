"""
Tests for the reconciliation-loss → Moltbook bridge.

Covers the contract:
  - a closed losing real manual trade creates exactly ONE advisory entry
  - GLD-style manual-exit loss and TSM-style stop-loss breach classify right
  - re-running the sync does not duplicate entries
  - winning / flat / open / probe trades never become mistake entries
  - missing close/P&L data degrades to "insufficient data" (no entry)
  - created entries preserve the advisory invariants
  - everything runs against an isolated temp DB (never runtime/mvp_local.db)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import scripts.persistence as persistence
import scripts.moltbook_reconciliation_bridge as bridge


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "bridge.db"
    persistence.init_schema(db)
    return db


def _insert_trade(
    db: Path,
    *,
    trade_id: str,
    ticker: str,
    event_id: str,
    side: str = "BUY",
    quantity: float = 1.0,
    price: float = 100.0,
    thesis: str = "Real operator thesis for the trade.",
    created_via: str = "manual_trade_log",
    executed_at: str = "2026-05-19T18:00:00+00:00",
) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO manual_trades"
            " (trade_id, event_id, ticker, side, quantity, price, executed_at,"
            "  thesis, created_via) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade_id, event_id, ticker, side, quantity, price, executed_at,
             thesis, created_via),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_reconciliation(
    db: Path,
    *,
    rec_id: str,
    trade_id: str,
    event_id: str,
    outcome_status: str,
    pnl_estimate: float,
    actual_fill_price: float = 0.0,
    extras: dict | None = None,
    lesson: str = "",
    reconciled_at: str = "2026-05-20T09:00:00+00:00",
) -> None:
    notes = "Advisory-only close reconciliation. No broker call by MVP."
    if extras is not None:
        notes += f"\n[reconciliation_extras={json.dumps(extras)}]"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO reconciliation_results"
            " (reconciliation_id, trade_id, event_id, reconciled_at,"
            "  actual_fill_price, actual_quantity, outcome_notes, pnl_estimate,"
            "  outcome_status, lesson) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rec_id, trade_id, event_id, reconciled_at, actual_fill_price, 1.0,
             notes, pnl_estimate, outcome_status, lesson),
        )
        conn.commit()
    finally:
        conn.close()


def _gld_extras() -> dict:
    return {
        "post_trade_outcome": "CLOSED_LOSS",
        "reconciliation_status": "RECONCILED",
        "realized_pnl": -0.7319,
        "entry_price": 418.07,
        "actual_exit_price": 411.5,
        "exit_quantity": 0.1114,
        "stop_loss_hit": False,
        "exit_reason": "Manual exit review: GLD hedge thesis weakened; exited "
                       "before stop-loss breach.",
        "lesson_takeaway": "Gold is not automatic safety under dollar pressure.",
    }


# ---------------------------------------------------------------------------
# GLD / TSM happy paths
# ---------------------------------------------------------------------------


def test_gld_style_loss_creates_exactly_one_entry(tmp_path):
    db = _make_db(tmp_path)
    _insert_trade(db, trade_id="MT_GLD", ticker="GLD",
                  event_id="USER_GLD_LONG", price=418.07,
                  thesis="Gold flight-to-safety long idea.")
    _insert_reconciliation(db, rec_id="REC_GLD", trade_id="MT_GLD",
                           event_id="USER_GLD_LONG", outcome_status="LOSS",
                           pnl_estimate=-0.7319, actual_fill_price=411.5,
                           extras=_gld_extras())
    report = bridge.sync_reconciliation_losses_to_moltbook(
        db, write=True, jsonl_path=tmp_path / "audit.jsonl"
    )
    assert report["created"] == 1
    assert report["skipped_duplicate"] == 0
    rows = persistence.get_moltbook_entries(db_path=db)
    gld = [r for r in rows if r["ticker"] == "GLD"]
    assert len(gld) == 1
    entry = gld[0]
    assert entry["mistake_type"] == "manual_exit_loss"
    assert entry["manual_trade_log_id"] == "MT_GLD"
    assert "-0.7319" in entry["outcome"]
    assert entry["advisory_status"] == "ADVISORY_ONLY"
    assert entry["execution_mode"] == "HUMAN_ONLY"
    assert entry["human_review_required"] in (1, True)
    assert entry["ai_execution_count"] == 0


def test_tsm_style_stop_loss_breach_classifies_as_stop(tmp_path):
    db = _make_db(tmp_path)
    _insert_trade(db, trade_id="MT_TSM", ticker="TSM",
                  event_id="USER_TSM_LONG", price=393.26)
    extras = {
        "post_trade_outcome": "STOP_LOSS",
        "realized_pnl": -2.5,
        "entry_price": 393.26,
        "actual_exit_price": 373.60,
        "stop_loss_hit": True,
        "exit_reason": "Stop-loss breached.",
    }
    _insert_reconciliation(db, rec_id="REC_TSM", trade_id="MT_TSM",
                           event_id="USER_TSM_LONG", outcome_status="LOSS",
                           pnl_estimate=-2.5, actual_fill_price=373.60,
                           extras=extras)
    report = bridge.sync_reconciliation_losses_to_moltbook(db, write=True,
                                                           jsonl_path=tmp_path / "a.jsonl")
    assert report["created"] == 1
    rows = persistence.get_moltbook_entries(db_path=db)
    assert rows[0]["mistake_type"] == "stop_loss_breach"


# ---------------------------------------------------------------------------
# Dedup / idempotency
# ---------------------------------------------------------------------------


def test_rerun_does_not_duplicate(tmp_path):
    db = _make_db(tmp_path)
    _insert_trade(db, trade_id="MT_GLD", ticker="GLD", event_id="USER_GLD_LONG")
    _insert_reconciliation(db, rec_id="REC_GLD", trade_id="MT_GLD",
                           event_id="USER_GLD_LONG", outcome_status="LOSS",
                           pnl_estimate=-0.73, actual_fill_price=411.5,
                           extras=_gld_extras())
    first = bridge.sync_reconciliation_losses_to_moltbook(db, write=True,
                                                          jsonl_path=tmp_path / "a.jsonl")
    second = bridge.sync_reconciliation_losses_to_moltbook(db, write=True,
                                                           jsonl_path=tmp_path / "a.jsonl")
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped_duplicate"] == 1
    assert len(persistence.get_moltbook_entries(db_path=db)) == 1


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["WIN", "FLAT", "BREAKEVEN", "PROFIT"])
def test_non_loss_outcomes_excluded(tmp_path, status):
    db = _make_db(tmp_path)
    _insert_trade(db, trade_id="MT_WIN", ticker="AAA", event_id="USER_AAA")
    _insert_reconciliation(db, rec_id="REC_WIN", trade_id="MT_WIN",
                           event_id="USER_AAA", outcome_status=status,
                           pnl_estimate=5.0, actual_fill_price=110.0,
                           extras={"post_trade_outcome": "CLOSED_WIN",
                                   "entry_price": 100.0, "actual_exit_price": 110.0})
    report = bridge.sync_reconciliation_losses_to_moltbook(db, write=True,
                                                          jsonl_path=tmp_path / "a.jsonl")
    assert report["created"] == 0
    assert persistence.get_moltbook_entries(db_path=db) == []


def test_open_unreconciled_trade_excluded(tmp_path):
    db = _make_db(tmp_path)
    # A trade with NO reconciliation row is open → no entry.
    _insert_trade(db, trade_id="MT_OPEN", ticker="OPN", event_id="USER_OPN")
    report = bridge.sync_reconciliation_losses_to_moltbook(db, write=True,
                                                          jsonl_path=tmp_path / "a.jsonl")
    assert report["created"] == 0


def test_probe_provenance_loss_excluded(tmp_path):
    db = _make_db(tmp_path)
    # created_via='' + probe thesis → excluded by canonical origin classifier.
    _insert_trade(db, trade_id="MT_PROBE", ticker="BTC", event_id="EV_REC",
                  thesis="t", created_via="")
    _insert_reconciliation(db, rec_id="REC_PROBE", trade_id="MT_PROBE",
                           event_id="EV_REC", outcome_status="LOSS",
                           pnl_estimate=-1.0, actual_fill_price=99.0,
                           extras={"post_trade_outcome": "CLOSED_LOSS",
                                   "entry_price": 100.0, "actual_exit_price": 99.0})
    report = bridge.sync_reconciliation_losses_to_moltbook(db, write=True,
                                                          jsonl_path=tmp_path / "a.jsonl")
    assert report["created"] == 0
    assert persistence.get_moltbook_entries(db_path=db) == []


def test_missing_pnl_and_prices_degrades_to_no_entry(tmp_path):
    db = _make_db(tmp_path)
    _insert_trade(db, trade_id="MT_NODATA", ticker="NOD", event_id="USER_NOD",
                  price=0.0)
    # outcome_status LOSS but pnl_estimate 0 and no prices anywhere.
    _insert_reconciliation(db, rec_id="REC_NODATA", trade_id="MT_NODATA",
                           event_id="USER_NOD", outcome_status="LOSS",
                           pnl_estimate=0.0, actual_fill_price=0.0,
                           extras={"post_trade_outcome": "CLOSED_LOSS"})
    report = bridge.sync_reconciliation_losses_to_moltbook(db, write=True,
                                                          jsonl_path=tmp_path / "a.jsonl")
    assert report["created"] == 0
    assert report["skipped_insufficient_data"] == 1
    assert persistence.get_moltbook_entries(db_path=db) == []


def test_dry_run_writes_nothing(tmp_path):
    db = _make_db(tmp_path)
    _insert_trade(db, trade_id="MT_GLD", ticker="GLD", event_id="USER_GLD_LONG")
    _insert_reconciliation(db, rec_id="REC_GLD", trade_id="MT_GLD",
                           event_id="USER_GLD_LONG", outcome_status="LOSS",
                           pnl_estimate=-0.73, actual_fill_price=411.5,
                           extras=_gld_extras())
    report = bridge.sync_reconciliation_losses_to_moltbook(db, write=False)
    assert report["created"] == 1  # would-create count
    assert persistence.get_moltbook_entries(db_path=db) == []  # nothing written
