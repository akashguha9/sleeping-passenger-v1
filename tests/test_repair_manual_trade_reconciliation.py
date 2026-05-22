"""Tests for scripts/repair_manual_trade_reconciliation.py.

Coverage
--------
1.  Dry-run is the default — no mutations, no backup file created.
2.  ``--apply`` writes only when a real change is required; idempotent.
3.  Backup file is created BEFORE any mutation (rollback-safe).
4.  Bogus rows (matching ``fake_manual_trade_reason``) are quarantined
    by re-stamping ``created_via`` — never deleted.
5.  India .NS rows with missing/wrong currency get normalised to INR,
    but already-quarantined India rows are left untouched (audit-only).
6.  Quarantine + India fix combined still leaves quarantined
    ``created_via`` intact and only stamps non-quarantined rows.
7.  Reconciliation-eligible count after repair matches the canonical
    Reconciliation-queue predicate (created_via=manual_trade_log and not
    cancelled and not bogus).
8.  Safety stamps are present and broker_api_called=False,
    ai_execution_count=0 are NEVER touched.
9.  Empty / missing DB does not crash; reports ``db_missing`` warning.
10. ASDC-style row with ``CANCELLED_DUPLICATE`` status is reported as a
    cancelled canonical row — never deleted by the script.

No broker calls.  No execution.  Read-only assertions except where the
test explicitly toggles ``apply=True``.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.repair_manual_trade_reconciliation import (
    OPERATION_CLASS,
    QUARANTINE_PROVENANCE,
    SAFETY_STAMPS,
    _serialise,
    run,
)
from scripts import operator_permission_guard as _guard


def _allowed_decision(db: Path) -> "_guard.PermissionDecision":
    """A clean OPERATOR REPAIR_WRITE allow for the function-level write guard."""
    return _guard.evaluate_permission(_guard.PermissionRequest(
        operation_name="repair_manual_trade_reconciliation",
        operation_class=OPERATION_CLASS,
        operator_role=_guard.OperatorRole.OPERATOR,
        apply_requested=True,
        dry_run_completed=True,
        db_path=str(db),
        safety_stamps=_guard.caller_safety_stamps(),
    ))


# ---------------------------------------------------------------------------
# Schema + seed helpers — minimal, no production code dependency.
# ---------------------------------------------------------------------------

_CREATE_SQL = """
CREATE TABLE manual_trades (
    trade_id TEXT PRIMARY KEY,
    event_id TEXT,
    ticker TEXT,
    side TEXT,
    quantity REAL,
    price REAL,
    leverage REAL DEFAULT 1.0,
    executed_at TEXT,
    thesis TEXT,
    notes TEXT,
    logged_by TEXT,
    execution_mode TEXT DEFAULT 'HUMAN_ONLY',
    ai_execution_count INTEGER DEFAULT 0,
    advisory_status TEXT DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER DEFAULT 1,
    broker_order_id TEXT DEFAULT 'NONE',
    broker_api_called INTEGER DEFAULT 0,
    reconciliation_status TEXT DEFAULT '',
    created_via TEXT DEFAULT '',
    trade_mode TEXT DEFAULT 'REAL_MANUAL',
    currency TEXT DEFAULT '',
    ai_model_used TEXT DEFAULT ''
);
"""


def _seed(db_path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_SQL)
        cols = (
            "trade_id, event_id, ticker, side, quantity, price, leverage, "
            "executed_at, thesis, notes, logged_by, broker_api_called, "
            "ai_execution_count, reconciliation_status, created_via, trade_mode, "
            "currency, ai_model_used"
        )
        placeholders = ", ".join(["?"] * 18)
        for r in rows:
            conn.execute(
                f"INSERT INTO manual_trades ({cols}) VALUES ({placeholders})",
                (
                    r["trade_id"], r.get("event_id", "EV"), r["ticker"],
                    r.get("side", "BUY"), r.get("quantity", 1.0),
                    r.get("price", 1.0), r.get("leverage", 1.0),
                    r.get("executed_at", "2026-05-18T00:00:00+00:00"),
                    r.get("thesis", ""), r.get("notes", ""),
                    r.get("logged_by", "human"),
                    int(r.get("broker_api_called", 0)),
                    int(r.get("ai_execution_count", 0)),
                    r.get("reconciliation_status", ""),
                    r.get("created_via", ""),
                    r.get("trade_mode", "REAL_MANUAL"),
                    r.get("currency", ""),
                    r.get("ai_model_used", ""),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _select(db_path: Path, trade_id: str) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM manual_trades WHERE trade_id=?", (trade_id,)
        ).fetchone()
    finally:
        conn.close()
    return {k: row[k] for k in row.keys()} if row else {}


# ---------------------------------------------------------------------------
# Dry-run behaviour.
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_changes(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    _seed(db, [
        {
            "trade_id": "MT_bogus",
            "event_id": "EV_AAPL",  # fake prefix
            "ticker": "AAPL",
            "thesis": "probe",
            "created_via": "manual_trade_log",
        },
        {
            "trade_id": "MT_india",
            "ticker": "BHARTIARTL.NS",
            "thesis": "real india telecom thesis",
            "created_via": "manual_trade_log",
            "currency": "",
            "price": 1700.0,
        },
    ])
    report = run(db, apply=False)
    # Both flagged, neither applied.
    assert report.applied is False
    assert report.changes_written == 0
    assert report.backup_path == ""
    assert any(f.trade_id == "MT_bogus" for f in report.bogus_to_quarantine)
    assert any(f.trade_id == "MT_india" for f in report.india_currency_fixes)
    # Verify DB untouched.
    assert _select(db, "MT_bogus")["created_via"] == "manual_trade_log"
    assert _select(db, "MT_india")["currency"] == ""


def test_apply_quarantines_bogus_and_fixes_india(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    _seed(db, [
        {
            "trade_id": "MT_bogus_asdc",
            "ticker": "ZZZ",
            "thesis": "test marker row",
            "created_via": "manual_trade_log",
        },
        {
            "trade_id": "MT_india_nse",
            "ticker": "ICICIBANK.NS",
            "thesis": "real india bank reasoning that survives marker rules",
            "created_via": "manual_trade_log",
            "currency": "USD",  # WRONG
            "price": 1100.0,
        },
        # Already-quarantined India row must NOT be touched.
        {
            "trade_id": "MT_old_quarantined",
            "ticker": "HDFCBANK.NS",
            "thesis": "old probe",
            "created_via": QUARANTINE_PROVENANCE,
            "currency": "USD",
        },
    ])
    report = run(db, apply=True, permission_decision=_allowed_decision(db))
    assert report.applied is True
    assert report.backup_path  # backup was made
    assert Path(report.backup_path).exists()

    # Bogus row → quarantined.
    assert _select(db, "MT_bogus_asdc")["created_via"] == QUARANTINE_PROVENANCE
    # India non-quarantined row → currency normalised.
    assert _select(db, "MT_india_nse")["currency"] == "INR"
    # Already-quarantined row left as-is.
    assert _select(db, "MT_old_quarantined")["created_via"] == QUARANTINE_PROVENANCE
    assert _select(db, "MT_old_quarantined")["currency"] == "USD"

    # Idempotent: second apply produces no further changes.
    report2 = run(db, apply=True, permission_decision=_allowed_decision(db))
    assert report2.changes_written == 0


def test_safety_invariants_never_touched(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    _seed(db, [
        {
            "trade_id": "MT_safety",
            "ticker": "ASDC",  # bogus ticker
            "thesis": "test marker",
            "created_via": "manual_trade_log",
            "broker_api_called": 0,
            "ai_execution_count": 0,
        },
    ])
    run(db, apply=True, permission_decision=_allowed_decision(db))
    after = _select(db, "MT_safety")
    assert after["broker_api_called"] == 0
    assert after["ai_execution_count"] == 0
    assert after["broker_order_id"] == "NONE"
    assert after["execution_mode"] == "HUMAN_ONLY"
    assert after["advisory_status"] == "ADVISORY_ONLY"


def test_cancelled_canonical_row_is_reported_not_deleted(tmp_path: Path) -> None:
    """The ASDC user-reported card: created_via=manual_trade_log,
    reconciliation_status=CANCELLED_DUPLICATE.  Reported by the script
    but never deleted — audit history is sacred."""
    db = tmp_path / "x.db"
    _seed(db, [
        {
            "trade_id": "MT_asdc_user",
            "ticker": "ASDC",
            "thesis": "operator gibberish that is not a marker word",
            "created_via": "manual_trade_log",
            "reconciliation_status": "CANCELLED_DUPLICATE",
            "ai_model_used": "GPT-5.5",
        },
    ])
    report = run(db, apply=True, permission_decision=_allowed_decision(db))
    assert any(
        f.trade_id == "MT_asdc_user" for f in report.cancelled_user_rows
    )
    # Row still exists.
    assert _select(db, "MT_asdc_user")["trade_id"] == "MT_asdc_user"


def test_reconciliation_eligible_count_after_repair(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    _seed(db, [
        # Real canonical row — survives the repair.
        {
            "trade_id": "MT_real_user",
            "ticker": "MSFT",
            "thesis": "real operator reasoning about MSFT setup that has substance",
            "created_via": "manual_trade_log",
            "currency": "USD",
            "ai_model_used": "Claude Code",
        },
        # Bogus row — would-be quarantined; not counted as eligible.
        {
            "trade_id": "MT_fake_aapl",
            "ticker": "AAPL",
            "quantity": 10.0,
            "price": 180.0,
            "thesis": "probe",
            "created_via": "manual_trade_log",
        },
        # Cancelled canonical — never counted as eligible.
        {
            "trade_id": "MT_cancelled",
            "ticker": "NVDA",
            "thesis": "real reasoning",
            "created_via": "manual_trade_log",
            "reconciliation_status": "CANCELLED_DUPLICATE",
        },
    ])
    report = run(db, apply=False)
    assert report.reconciliation_eligible_rows == ["MT_real_user"]


def test_serialised_payload_contains_safety_stamps(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    _seed(db, [])
    report = run(db, apply=False)
    payload = _serialise(report)
    for k, v in SAFETY_STAMPS.items():
        assert payload[k] == v
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["record_keeping_only"] is True


def test_missing_db_does_not_crash(tmp_path: Path) -> None:
    db = tmp_path / "does_not_exist.db"
    report = run(db, apply=False)
    assert "db_missing" in report.warnings
    report2 = run(db, apply=True, permission_decision=_allowed_decision(db))
    assert "apply_skipped_db_missing" in report2.warnings or "db_missing" in report2.warnings
    assert report2.applied is False


def test_no_destructive_delete_on_apply(tmp_path: Path) -> None:
    """Even when an India row is below the sane floor, the script never
    deletes; the price stays put and (when --repair-india-scale is set)
    we only annotate the notes column.  Audit history is sacred."""
    db = tmp_path / "x.db"
    _seed(db, [
        {
            "trade_id": "MT_low_scale",
            "ticker": "ICICIBANK.NS",
            "thesis": "real india bank thesis with substance",
            "created_via": "manual_trade_log",
            "currency": "INR",
            "price": 40.72,  # below floor
        },
    ])
    report = run(db, apply=True, repair_india_scale=True, permission_decision=_allowed_decision(db))
    assert _select(db, "MT_low_scale")["price"] == 40.72  # untouched
    notes = _select(db, "MT_low_scale")["notes"] or ""
    assert "india_nse_price_below_floor" in notes
    assert any(
        f.trade_id == "MT_low_scale" for f in report.india_scale_anomalies
    )
