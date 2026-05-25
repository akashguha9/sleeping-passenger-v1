"""Regression tests for ``scripts/quarantine_bad_kalshi_records.py``.

Two layers:

1. **Scanner contract** — the script must appear in
   ``preflight.scan_mutation_script_guarding()["guarded"]`` and must NOT
   appear in ``["unguarded"]``.  This is the contract that the release
   gate's ``mutation_guard_release_impact`` evaluates; before this fix
   the script was an unguarded HIGH-severity mutation (it issues
   ``UPDATE signal_events ...``) and the gate hard-BLOCKed.
2. **CLI behaviour** — dry-run is genuinely read-only, ``--yes`` is
   gated by ``operator_permission_guard.build_apply_decision`` (which
   requires ``MVP_OPERATOR_ROLE=OPERATOR``/``ADMIN`` and a recent
   dry-run receipt), and emitted audit JSONL rows carry the advisory
   safety stamps (``advisory_only``, ``human_review_required``,
   ``execution_gate=LOCKED``, ``broker_api_called=false``,
   ``ai_execution_count=0``).
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from scripts import (
    local_deploy_preflight as preflight,
    operator_permission_guard as guard,
    quarantine_bad_kalshi_records as qbkr,
)


# ---------------------------------------------------------------------------
# Scanner contract
# ---------------------------------------------------------------------------


def test_quarantine_bad_kalshi_records_is_guarded():
    """The new Kalshi cleanup script must be classified as guarded."""
    coverage = preflight.scan_mutation_script_guarding()
    assert "quarantine_bad_kalshi_records.py" in coverage["guarded"]
    assert "quarantine_bad_kalshi_records.py" not in coverage["unguarded"]


def test_quarantine_bad_kalshi_records_does_not_break_known_four():
    """Adding the new script must not regress the existing four."""
    coverage = preflight.scan_mutation_script_guarding()
    for name in (
        "quarantine_fake_manual_trades.py",
        "moltbook_cleanup_fake_seed.py",
        "backfill_manual_trade_log_provenance.py",
        "repair_manual_trade_reconciliation.py",
    ):
        assert name in coverage["guarded"], name
    # No mutation script may be unguarded.  This is the assertion the
    # release gate's mutation_guard_release_impact depends on.
    assert coverage["unguarded"] == []


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------


_KALSHI_SAFETY_STAMP_KEYS = (
    "advisory_only",
    "human_review_required",
    "execution_gate",
    "broker_api_called",
    "ai_execution_count",
)


def _seed_bad_row(db_path) -> tuple[int, str]:
    """Seed a single Kalshi row whose ticker triggers ticker-rejection.

    Returns ``(row_id, event_id)``.  The KXMVESPORTS ticker is on the
    governance ticker-rejection list, so any persisted payload carrying
    it is a quarantine candidate when the script re-applies the rules.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                source_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )"""
        )
        payload = {
            "ticker": "KXMVESPORTS-2026",
            "source_market_id": "KXMVESPORTS-2026",
            "title": "Will an esports event happen?",
            "category": "Sports",
            "visible_in_kalshi_feed": True,
        }
        cur = conn.execute(
            "INSERT INTO signal_events (event_id, source_name, raw_payload, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            ("evt-kxm-1", "kalshi", json.dumps(payload), "2026-05-25T00:00:00Z"),
        )
        conn.commit()
        return int(cur.lastrowid), "evt-kxm-1"
    finally:
        conn.close()


def _read_payload(db_path, row_id: int) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT raw_payload FROM signal_events WHERE id = ?", (row_id,)
        )
        return json.loads(cur.fetchone()[0])
    finally:
        conn.close()


@pytest.fixture
def isolated_guard(tmp_path, monkeypatch):
    """Redirect the guard's receipt + audit paths into ``tmp_path``."""
    monkeypatch.setenv(
        guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "_receipts"),
    )
    monkeypatch.setenv(
        guard.AUDIT_PATH_ENV_VAR, str(tmp_path / "operator_audit.jsonl"),
    )
    return tmp_path


def test_dry_run_default_does_not_mutate_db(tmp_path, isolated_guard, capsys):
    """Default invocation (no --yes) reports candidates but writes no row."""
    db = tmp_path / "mvp_local.db"
    row_id, _ = _seed_bad_row(db)
    audit = tmp_path / "kalshi_quarantine_migration.jsonl"

    rc = qbkr.run([
        "--db-path", str(db),
        "--audit-path", str(audit),
    ])
    assert rc == 0

    # DB row payload is unchanged — visible_in_kalshi_feed stays True.
    payload = _read_payload(db, row_id)
    assert payload["visible_in_kalshi_feed"] is True
    assert "quarantine_reason" not in payload

    # A permission dry-run receipt is written (so a subsequent --yes can
    # satisfy the guard's dry_run_required check).
    receipts = list((isolated_guard / "_receipts").glob("*.json"))
    assert receipts, "expected a dry-run receipt to be written"

    # The audit JSONL exists and carries the advisory safety stamps.
    assert audit.exists()
    lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln]
    assert lines, "expected at least one audit JSONL row"
    row = json.loads(lines[0])
    for key in _KALSHI_SAFETY_STAMP_KEYS:
        assert key in row, key
    assert row["advisory_only"] is True
    assert row["human_review_required"] is True
    assert str(row["execution_gate"]).upper() == "LOCKED"
    assert row["broker_api_called"] is False
    assert row["ai_execution_count"] == 0
    # The emitted row carries no broker/order/execution surface.
    for forbidden in ("broker_api", "place_order", "submit_order",
                      "execute_trade", "unlock_execution"):
        assert forbidden not in row


def test_yes_requires_authorized_role(tmp_path, isolated_guard, monkeypatch, capsys):
    """Without OPERATOR/ADMIN, --yes is denied and the DB is untouched."""
    db = tmp_path / "mvp_local.db"
    row_id, _ = _seed_bad_row(db)
    audit = tmp_path / "kalshi_quarantine_migration.jsonl"

    # Default role (VIEWER) cannot REPAIR_WRITE.
    monkeypatch.delenv("MVP_OPERATOR_ROLE", raising=False)

    rc = qbkr.run([
        "--db-path", str(db),
        "--audit-path", str(audit),
        "--yes",
    ])
    assert rc == 2  # DENY exit
    payload = _read_payload(db, row_id)
    assert payload["visible_in_kalshi_feed"] is True


def test_yes_with_role_and_dry_run_receipt_mutates(
    tmp_path, isolated_guard, monkeypatch
):
    """OPERATOR + recent dry-run receipt → --yes writes only to the intended row."""
    db = tmp_path / "mvp_local.db"
    row_id, _ = _seed_bad_row(db)
    audit = tmp_path / "kalshi_quarantine_migration.jsonl"

    # Step 1: dry-run produces the permission receipt.
    monkeypatch.delenv("MVP_OPERATOR_ROLE", raising=False)
    assert qbkr.run([
        "--db-path", str(db),
        "--audit-path", str(audit),
    ]) == 0
    # Sanity: DB still untouched.
    assert _read_payload(db, row_id)["visible_in_kalshi_feed"] is True

    # Step 2: --yes as OPERATOR consumes the receipt and applies.
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    assert qbkr.run([
        "--db-path", str(db),
        "--audit-path", str(audit),
        "--yes",
    ]) == 0

    # The intended quarantine fields are now set on the row's payload.
    payload = _read_payload(db, row_id)
    assert payload["visible_in_kalshi_feed"] is False
    assert payload["category_allowed"] is False
    assert payload["quarantine_reason"]  # non-empty reason

    # The operator audit-log JSONL carries an allow event for this op.
    op_audit = isolated_guard / "operator_audit.jsonl"
    assert op_audit.exists()
    allowed_events = [
        json.loads(ln)
        for ln in op_audit.read_text(encoding="utf-8").splitlines()
        if ln
    ]
    allows = [e for e in allowed_events
              if e.get("operation_name") == qbkr.OPERATION_NAME
              and e.get("allowed") is True]
    assert allows, "expected an ALLOW audit event for the apply path"
    # Every audit row keeps the locked advisory invariants.
    for e in allowed_events:
        assert e.get("advisory_only") is True
        assert str(e.get("execution_gate", "")).upper() == "LOCKED"
        assert e.get("broker_api_called") is False
        assert e.get("ai_execution_count") in (0, None)


def test_direct_write_helper_refuses_without_decision(tmp_path):
    """The write helper itself rejects callers that bypass the CLI guard."""
    db = tmp_path / "mvp_local.db"
    row_id, _ = _seed_bad_row(db)

    with pytest.raises(PermissionError):
        qbkr._mark_quarantined(db, row_id, {"ticker": "X"}, "reason")

    # And the DB row payload is untouched.
    assert _read_payload(db, row_id)["visible_in_kalshi_feed"] is True


def test_script_declares_repair_write_operation_class():
    """Operation identity is REPAIR_WRITE (not RESTORE / MIGRATION / FORBIDDEN)."""
    assert qbkr.OPERATION_NAME == "quarantine_bad_kalshi_records"
    assert qbkr.OPERATION_CLASS == guard.OperationClass.REPAIR_WRITE
