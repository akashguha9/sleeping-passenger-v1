"""Tests for the manual trade log soft-cancel path.

The Reconciliation tab's "Cancel Log" action removes a duplicate / mis-
logged manual trade from the active reconciliation queue.  These tests
pin:

* Cancelling an unreconciled log succeeds and stamps the row.
* The cancelled row drops out of the reconciliation queue.
* The cancelled row drops out of ``list_manual_trades`` as "active"
  unreconciled work (still present in the listing with status set).
* Cancelling a nonexistent trade returns a structured ``not_found``.
* Already-reconciled trades cannot be silently cancelled — refused.
* Already-cancelled trades are idempotent (no duplicate audit row).
* ``broker_api_called`` and ``ai_execution_count`` stamps are preserved
  on the response, the audit log, and the persisted row.
* Defence-in-depth: a row that claims broker_api_called=True is refused.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import persistence
from scripts import signal_inbox_api
from scripts import reconciliation_queue as rq


def _rebind_defaults(fn, new_db: Path) -> None:
    if fn.__defaults__:
        new_defs = tuple(
            new_db if isinstance(d, Path) else d for d in fn.__defaults__
        )
        fn.__defaults__ = new_defs
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "cancel_log.db"
    persistence.init_schema(db)
    helper_names = [
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_trades_for_event",
        "get_event_id_for_trade",
        "get_all_manual_trades",
        "get_manual_trade",
        "get_manual_trade_raw_broker_flag",
        "cancel_manual_trade",
        "insert_reconciliation",
        "get_reconciliations_for_trade",
        "get_all_reconciliations",
    ]
    originals: dict = {}
    for name in helper_names:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(signal_inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(signal_inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(signal_inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    monkeypatch.setattr(
        signal_inbox_api,
        "MANUAL_TRADE_CANCELLATIONS_LOG",
        log_dir / "mt_cancels.jsonl",
    )
    try:
        yield db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


def _safety_stamps_ok(resp: dict) -> None:
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["ai_execution_count"] == 0
    assert resp["broker_api_called"] is False
    assert resp.get("execution_gate") == "LOCKED"
    assert resp.get("execution_permission") is False
    assert resp.get("can_execute") is False
    assert resp.get("execution_mode") == "HUMAN_ONLY"


def _log_duplicate_pair(symbol: str = "ICICIBANK.NS") -> tuple[str, str]:
    a = signal_inbox_api.log_manual_trade(
        event_id="EV_DUP",
        ticker=symbol,
        side="BUY",
        quantity=10.0,
        price=950.0,
        thesis="duplicate first entry coverage",
    )
    b = signal_inbox_api.log_manual_trade(
        event_id="EV_DUP",
        ticker=symbol,
        side="BUY",
        quantity=10.0,
        price=950.0,
        thesis="duplicate SECOND mis-logged entry coverage",
    )
    return a["trade_id"], b["trade_id"]


def test_cancel_unreconciled_log_succeeds(tmp_db: Path) -> None:
    first_id, dup_id = _log_duplicate_pair()
    resp = signal_inbox_api.cancel_manual_trade_log(
        dup_id, reason="duplicate manual log"
    )
    _safety_stamps_ok(resp)
    assert resp["status"] == "cancelled"
    assert resp["trade_id"] == dup_id
    assert resp["reconciliation_status"] == "CANCELLED_DUPLICATE"
    assert resp["cancel_reason"] == "duplicate manual log"
    assert resp["record_keeping_only"] is True
    assert resp["sqlite_updated"] is True

    # The other log entry stays active.
    listing = signal_inbox_api.list_manual_trades()
    by_id = {t["trade_id"]: t for t in listing["trades"]}
    assert by_id[first_id].get("reconciliation_status", "") == ""
    assert by_id[dup_id]["reconciliation_status"] == "CANCELLED_DUPLICATE"


def test_cancelled_log_drops_off_reconciliation_queue(tmp_db: Path) -> None:
    first_id, dup_id = _log_duplicate_pair()
    queue_before = rq.build_queue(tmp_db)
    ids_before = {it["trade_id"] for it in queue_before["items"]}
    assert ids_before == {first_id, dup_id}
    assert queue_before["summary"]["unreconciled_count"] == 2

    signal_inbox_api.cancel_manual_trade_log(dup_id)

    queue_after = rq.build_queue(tmp_db)
    ids_after = [it["trade_id"] for it in queue_after["items"]]
    assert ids_after == [first_id]
    assert queue_after["summary"]["unreconciled_count"] == 1
    # Safety stamps remain locked on the queue envelope.
    assert queue_after["broker_api_called"] is False
    assert queue_after["ai_execution_count"] == 0


def test_cancel_preserves_audit_trail(tmp_db: Path) -> None:
    _, dup_id = _log_duplicate_pair()
    signal_inbox_api.cancel_manual_trade_log(dup_id, reason="dup_log")
    path = signal_inbox_api.MANUAL_TRADE_CANCELLATIONS_LOG
    assert path.exists()
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    rec = lines[0]
    assert rec["trade_id"] == dup_id
    assert rec["reconciliation_status"] == "CANCELLED_DUPLICATE"
    assert rec["cancel_reason"] == "dup_log"
    assert rec["broker_api_called"] is False
    assert rec["ai_execution_count"] == 0
    assert rec["record_keeping_only"] is True


def test_cancel_nonexistent_trade_returns_not_found(tmp_db: Path) -> None:
    resp = signal_inbox_api.cancel_manual_trade_log("MT_DOES_NOT_EXIST")
    assert resp["status"] == "not_found"
    assert "error" in resp
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["ai_execution_count"] == 0


def test_cancel_empty_trade_id_returns_error(tmp_db: Path) -> None:
    resp = signal_inbox_api.cancel_manual_trade_log("")
    assert "error" in resp
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["ai_execution_count"] == 0


def test_cannot_cancel_reconciled_trade(tmp_db: Path) -> None:
    a = signal_inbox_api.log_manual_trade(
        event_id="EV_R",
        ticker="ICICIBANK.NS",
        side="BUY",
        quantity=5.0,
        price=950.0,
        thesis="reconciled trade",
    )
    signal_inbox_api.reconcile_trade(
        a["trade_id"],
        actual_fill_price=950.0,
        actual_quantity=5.0,
        outcome_notes="closed at +1R",
        pnl_estimate=50.0,
        outcome_status="WIN",
    )
    resp = signal_inbox_api.cancel_manual_trade_log(a["trade_id"])
    assert resp["status"] == "refused"
    assert resp["reconciled"] is True
    assert resp["broker_api_called"] is False


def test_cancel_is_idempotent(tmp_db: Path) -> None:
    _, dup_id = _log_duplicate_pair()
    first = signal_inbox_api.cancel_manual_trade_log(dup_id)
    assert first["status"] == "cancelled"
    second = signal_inbox_api.cancel_manual_trade_log(dup_id)
    assert second["status"] == "already_cancelled"
    assert second["reconciliation_status"] == "CANCELLED_DUPLICATE"
    # Audit log should only have the first cancellation row.
    path = signal_inbox_api.MANUAL_TRADE_CANCELLATIONS_LOG
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    assert len(lines) == 1


def test_cancel_refused_when_broker_api_called_flag_set(tmp_db: Path) -> None:
    # Defence-in-depth: this app never sets broker_api_called=1, but if
    # a corrupted/imported row claims it, the cancel must refuse.
    _log_duplicate_pair()
    conn = sqlite3.connect(str(tmp_db))
    try:
        rows = conn.execute("SELECT trade_id FROM manual_trades").fetchall()
        target_id = rows[0][0]
        conn.execute(
            "UPDATE manual_trades SET broker_api_called=1 WHERE trade_id=?",
            (target_id,),
        )
        conn.commit()
    finally:
        conn.close()

    resp = signal_inbox_api.cancel_manual_trade_log(target_id)
    assert resp["status"] == "refused"
    assert resp["broker_api_called"] is True


def test_cancel_does_not_increment_ai_execution_count(tmp_db: Path) -> None:
    _, dup_id = _log_duplicate_pair()
    resp = signal_inbox_api.cancel_manual_trade_log(dup_id)
    assert resp["ai_execution_count"] == 0
    # After cancel, list_manual_trades must still report 0 AI executions
    # on its envelope, and broker_api_called=False on every row.
    listing = signal_inbox_api.list_manual_trades()
    assert listing["ai_execution_count"] == 0
    assert listing["broker_api_called"] is False
    for t in listing["trades"]:
        assert t.get("broker_api_called") in (False, 0)
        assert t.get("ai_execution_count", 0) == 0


def test_human_manual_log_carries_created_via_provenance(tmp_db: Path) -> None:
    """Every row logged via the Manual Trade Log API stamps created_via."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_PROV",
        ticker="ICICIBANK.NS",
        side="BUY",
        quantity=1.0,
        price=100.0,
        thesis="provenance coverage sentence",
    )
    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT created_via FROM manual_trades WHERE trade_id=?",
            (resp["trade_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "manual_trade_log"


def test_cancel_refused_for_non_manual_log_origin(tmp_db: Path) -> None:
    """Seed/demo/unknown-provenance rows must refuse Cancel Log."""
    # Insert a seed-style row directly via persistence (mimics what
    # smoke seeds / gsheet fixtures / JSONL imports do — they bypass the
    # Manual Trade Log API and leave created_via empty).
    persistence.insert_manual_trade(
        "MT_seed_spy",
        "EV_SEED",
        "SPY",
        "BUY",
        10.0,
        450.0,
        "2026-05-10T06:11:39+00:00",
        "Strong persistence in recent window",
        "",
        "human",
        db_path=tmp_db,
        # NOTE: no created_via -> stays empty -> excluded
    )
    resp = signal_inbox_api.cancel_manual_trade_log("MT_seed_spy")
    assert resp["status"] == "refused"
    assert resp["reason"] == "non_manual_trade_log_origin"
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0


def test_cancel_refused_for_explicit_seed_provenance(tmp_db: Path) -> None:
    """A row stamped with anything other than manual_trade_log refuses."""
    persistence.insert_manual_trade(
        "MT_imported_csv",
        "EV_IMP",
        "AAPL",
        "BUY",
        1.0,
        100.0,
        "2026-05-10T06:11:39+00:00",
        "imported audit row",
        "",
        "import_script",
        db_path=tmp_db,
        created_via="imported_csv",
    )
    resp = signal_inbox_api.cancel_manual_trade_log("MT_imported_csv")
    assert resp["status"] == "refused"
    assert resp["reason"] == "non_manual_trade_log_origin"
    assert resp["created_via"] == "imported_csv"


def test_cancel_does_not_affect_learning_completeness(tmp_db: Path) -> None:
    """A cancelled log must not be counted as a learning-incomplete row.

    learning_completeness_report INNER JOINs reconciliation_results, so
    a cancelled-but-unreconciled row is naturally excluded.  This test
    pins that property: cancelling the duplicate does not add anything
    to the report.
    """
    try:
        from scripts.learning_completeness_report import build_report
    except ImportError:
        pytest.skip("learning_completeness_report not importable")
    _, dup_id = _log_duplicate_pair()
    before = build_report(tmp_db)
    signal_inbox_api.cancel_manual_trade_log(dup_id)
    after = build_report(tmp_db)
    assert after["reconciled_count"] == before["reconciled_count"]
    assert after["learning_incomplete_count"] == before["learning_incomplete_count"]
    assert after["broker_api_called"] is False
    assert after["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Sprint I — structured cancel-error contract.  When refused, the response
# must include a ``reason`` field the frontend renders instead of bare
# "HTTP 400".  This pins the contract so the user-visible error never
# regresses to "Could not cancel log (HTTP 400). The card has been kept."
# ---------------------------------------------------------------------------


def test_cancel_refused_response_carries_reason_field(tmp_db: Path) -> None:
    a = signal_inbox_api.log_manual_trade(
        event_id="EV_REASON",
        ticker="ICICIBANK.NS",
        side="BUY",
        quantity=5.0,
        price=950.0,
        thesis="reason-field reasoning sentence",
    )
    signal_inbox_api.reconcile_trade(
        a["trade_id"],
        actual_fill_price=950.0,
        actual_quantity=5.0,
        outcome_notes="closed",
        pnl_estimate=0.0,
        outcome_status="WIN",
    )
    resp = signal_inbox_api.cancel_manual_trade_log(a["trade_id"])
    assert resp["status"] == "refused"
    assert resp.get("reason") == "already_reconciled"
    assert "reconciled" in resp.get("error", "").lower()
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0


def test_cancel_not_found_response_carries_reason_field(tmp_db: Path) -> None:
    resp = signal_inbox_api.cancel_manual_trade_log("MT_NONEXISTENT")
    assert resp["status"] == "not_found"
    assert resp.get("reason") == "not_found"
    assert resp["ai_execution_count"] == 0


def test_cancel_refused_for_non_manual_log_origin_has_reason(tmp_db: Path) -> None:
    # A row with empty created_via (seed-style) cannot be cancelled from
    # the Reconciliation tab.  The refused response must carry a reason
    # the frontend can render.
    persistence.insert_manual_trade(
        "MT_SEED_REASON",
        "EV_SEED_REASON",
        "ZZZ",
        "BUY",
        1.0,
        1.0,
        "2026-05-01T00:00:00Z",
        "seed row",
        "",
        "human",
        db_path=tmp_db,
        created_via="",
    )
    resp = signal_inbox_api.cancel_manual_trade_log("MT_SEED_REASON")
    assert resp["status"] == "refused"
    assert resp.get("reason") == "non_manual_trade_log_origin"
    assert resp["broker_api_called"] is False
