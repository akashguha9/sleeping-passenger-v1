"""F13 regression: UPDATE/DELETE on journal rows leaves an audit trail.

Audit finding F13: reflection hard-DELETEs (GDPR erasure) and manual-trade
cancellations (status UPDATE) left no record of the prior state — a bad
cancellation or malicious deletion was undetectable after the fact.

Contract: persistence writes an ``audit_log`` row (table, row_id, operation,
old_state_json, changed_at) in the SAME transaction as the mutation.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import persistence


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "audit.db"
    persistence.init_schema(p)
    return p


def _audit_rows(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log ORDER BY id")]
    finally:
        conn.close()


def test_audit_log_table_exists(db):
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_log'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_reflection_delete_is_audited(db):
    persistence.insert_reflection(
        "REF_A1", "EVT_A", "human", "MODERATE",
        "the market taught me humility", "2026-01-01T00:00:00Z", db_path=db,
    )
    result = persistence.soft_delete_reflection("REF_A1", db_path=db)
    assert result["deleted"] is True

    rows = _audit_rows(db)
    assert len(rows) == 1
    a = rows[0]
    assert a["table_name"] == "user_reflections"
    assert a["row_id"] == "REF_A1"
    assert a["operation"] == "DELETE"
    old = json.loads(a["old_state_json"])
    assert old["reflection_id"] == "REF_A1"
    assert "humility" in old["reflection_text"]
    assert a["changed_at"]


def test_trade_cancel_is_audited(db):
    persistence.insert_manual_trade(
        "MT_C1", "EVT_C", "AAPL", "BUY", 1, 100,
        "2026-01-01T00:00:00Z", "t", "", "human", db_path=db,
        created_via="manual_trade_log",
    )
    ok = persistence.cancel_manual_trade(
        "MT_C1", "2026-01-02T00:00:00Z",
        cancel_reason="duplicate", status="CANCELLED_DUPLICATE", db_path=db,
    )
    assert ok is True

    rows = _audit_rows(db)
    assert len(rows) == 1
    a = rows[0]
    assert a["table_name"] == "manual_trades"
    assert a["row_id"] == "MT_C1"
    assert a["operation"] == "UPDATE"
    old = json.loads(a["old_state_json"])
    # The pre-mutation state is captured, not the post-cancel state.
    assert old.get("reconciliation_status") in (None, "", "AWAITING_RECONCILIATION")
    assert old.get("cancel_reason") in (None, "")


def test_cancel_of_missing_trade_writes_no_audit_row(db):
    ok = persistence.cancel_manual_trade(
        "MT_NOPE", "2026-01-02T00:00:00Z", cancel_reason="x", db_path=db,
    )
    assert ok is False
    assert _audit_rows(db) == []
