"""H5 regression: guarded JSONL→DB divergence replay.

F10 detects split-brain; this tool repairs the replayable class
(missing-in-db) through the canonical insert path, under the full
guarded-mutation doctrine, idempotently, with audit-log rows.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import operator_permission_guard as guard
from scripts import persistence
from scripts.replay_jsonl_divergence import (
    OPERATION_CLASS,
    OPERATION_NAME,
    apply_replay,
    collect_divergence,
)


def _jsonl_row(trade_id: str, **over) -> dict:
    base = {
        "trade_id": trade_id,
        "event_id": f"EVT_{trade_id}",
        "ticker": "BTC",
        "side": "BUY",
        "quantity": "0.1",
        "price": "42000.5",
        "executed_at": "2026-06-01T00:00:00Z",
        "thesis": "replay drill",
        "notes": "",
        "logged_by": "operator@loopback",
        "leverage": "1",
        "trade_mode": "REAL_MANUAL",
        "created_via": "manual_trade_log",
        "currency": "USD",
    }
    base.update(over)
    return base


@pytest.fixture()
def env(tmp_path):
    db = tmp_path / "replay.db"
    persistence.init_schema(db)
    jsonl = tmp_path / "mt.jsonl"
    return db, jsonl


def _write_jsonl(jsonl: Path, rows: list[dict]) -> None:
    jsonl.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _insert_db(db: Path, row: dict) -> None:
    persistence.insert_manual_trade(
        row["trade_id"], row["event_id"], row["ticker"], row["side"],
        row["quantity"], row["price"], row["executed_at"], row["thesis"],
        row["notes"], row["logged_by"], db_path=db,
        created_via=row["created_via"],
    )


def _decision(tmp_path, db, monkeypatch):
    monkeypatch.setenv(guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    guard.write_dry_run_receipt(OPERATION_NAME, 1, str(db))
    return guard.build_apply_decision(
        OPERATION_NAME, OPERATION_CLASS, str(db), operator_role="OPERATOR"
    )


# ---------------------------------------------------------------------------
# Report mode
# ---------------------------------------------------------------------------


def test_report_classifies_all_three_divergence_kinds(env):
    db, jsonl = env
    lost = _jsonl_row("MT_LOST")            # in JSONL only → missing_in_db
    matched = _jsonl_row("MT_OK")           # in both, identical
    skewed = _jsonl_row("MT_SKEW")          # in both, price differs
    _write_jsonl(jsonl, [lost, matched, skewed])
    _insert_db(db, matched)
    _insert_db(db, {**skewed, "price": "999"})
    _insert_db(db, _jsonl_row("MT_DBONLY"))  # in DB only

    report = collect_divergence(db, jsonl)
    assert [r["trade_id"] for r in report["missing_in_db"]] == ["MT_LOST"]
    assert [m["trade_id"] for m in report["mismatched"]] == ["MT_SKEW"]
    assert report["db_only"] == ["MT_DBONLY"]
    assert report["divergent"] is True
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False


def test_report_clean_when_in_sync(env):
    db, jsonl = env
    row = _jsonl_row("MT_SYNC")
    _write_jsonl(jsonl, [row])
    _insert_db(db, row)
    report = collect_divergence(db, jsonl)
    assert report["divergent"] is False


# ---------------------------------------------------------------------------
# Apply mode
# ---------------------------------------------------------------------------


def test_apply_replays_missing_rows_via_canonical_path(env, tmp_path, monkeypatch):
    db, jsonl = env
    lost = _jsonl_row("MT_LOST2", quantity="0.1", price="42000.5")
    _write_jsonl(jsonl, [lost])

    report = collect_divergence(db, jsonl)
    assert len(report["missing_in_db"]) == 1

    decision = _decision(tmp_path, db, monkeypatch)
    result = apply_replay(db, report["missing_in_db"], permission_decision=decision)
    assert result["applied"] == 1
    assert result["replayed_trade_ids"] == ["MT_LOST2"]
    assert Path(result["backup_path"]).exists()

    # Canonical-path proof: money landed as TEXT canonical Decimal strings.
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            "SELECT quantity, price, typeof(price) tp, created_via"
            " FROM manual_trades WHERE trade_id='MT_LOST2'"
        ).fetchone()
        audit = conn.execute(
            "SELECT * FROM audit_log WHERE row_id='MT_LOST2'"
        ).fetchall()
    finally:
        conn.close()
    assert r["tp"] == "text"
    assert r["quantity"] == "0.1"
    assert r["price"] == "42000.5"
    assert r["created_via"] == "manual_trade_log"
    assert len(audit) == 1
    assert audit[0]["operation"] == "REPLAY_INSERT"

    # Divergence resolved.
    assert collect_divergence(db, jsonl)["divergent"] is False


def test_apply_is_idempotent(env, tmp_path, monkeypatch):
    db, jsonl = env
    _write_jsonl(jsonl, [_jsonl_row("MT_IDEM")])
    report = collect_divergence(db, jsonl)
    decision = _decision(tmp_path, db, monkeypatch)
    first = apply_replay(db, report["missing_in_db"], permission_decision=decision)
    assert first["applied"] == 1

    # Second pass: nothing left to replay.
    report2 = collect_divergence(db, jsonl)
    assert report2["missing_in_db"] == []
    second = apply_replay(db, report2["missing_in_db"], permission_decision=decision)
    assert second["applied"] == 0

    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM manual_trades WHERE trade_id='MT_IDEM'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_apply_never_touches_mismatched_rows(env, tmp_path, monkeypatch):
    db, jsonl = env
    skew = _jsonl_row("MT_SKEW2")
    _write_jsonl(jsonl, [skew])
    _insert_db(db, {**skew, "price": "1"})  # DB disagrees

    report = collect_divergence(db, jsonl)
    assert report["missing_in_db"] == []
    assert len(report["mismatched"]) == 1
    decision = _decision(tmp_path, db, monkeypatch)
    result = apply_replay(db, report["missing_in_db"], permission_decision=decision)
    assert result["applied"] == 0
    conn = sqlite3.connect(str(db))
    try:
        price = conn.execute(
            "SELECT price FROM manual_trades WHERE trade_id='MT_SKEW2'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert price == "1"  # untouched — human review required


# ---------------------------------------------------------------------------
# Guard doctrine
# ---------------------------------------------------------------------------


def test_apply_requires_permission_decision(env):
    db, jsonl = env
    with pytest.raises(PermissionError):
        apply_replay(db, [], permission_decision=None)


def test_apply_rejects_sub_floor_role(env, tmp_path, monkeypatch):
    db, jsonl = env
    monkeypatch.setenv(guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    guard.write_dry_run_receipt(OPERATION_NAME, 1, str(db))
    with pytest.raises(PermissionError):
        decision = guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(db), operator_role="VIEWER"
        )
        apply_replay(db, [], permission_decision=decision)


def test_health_flag_clears_after_replay(env, tmp_path, monkeypatch):
    """End-to-end with the F10 detector: lost write → flag → replay → clear."""
    import scripts.signal_inbox_api as api

    db, jsonl = env
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", jsonl)
    originals = {}
    for name in ("count_manual_trades_by_provenance",):
        fn = getattr(persistence, name)
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        if fn.__defaults__:
            fn.__defaults__ = tuple(
                db if isinstance(d, Path) else d for d in fn.__defaults__
            )
    try:
        _write_jsonl(jsonl, [_jsonl_row("MT_FLAG")])
        before = api.journal_divergence()
        assert before["journal_divergence_detected"] is True

        decision = _decision(tmp_path, db, monkeypatch)
        report = collect_divergence(db, jsonl)
        apply_replay(db, report["missing_in_db"], permission_decision=decision)

        after = api.journal_divergence()
        assert after["journal_divergence_detected"] is False
        assert after["manual_trades_jsonl_lines"] == after["manual_trades_db_rows"] == 1
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None
