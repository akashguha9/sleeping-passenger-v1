"""Objective 3 — Moltbook idempotent upsert is race-safe.

The upsert does SELECT-by-idempotency-key then INSERT.  Under a concurrent
duplicate, a second writer can insert the same key between our SELECT and
INSERT; the partial UNIQUE index then fires ``sqlite3.IntegrityError``.  The
fix recovers idempotently (returns the existing row) instead of 500-ing, while
still re-raising genuinely unrelated integrity violations.

Invariant: ``count(moltbook_entries where idempotency_key=k) <= 1`` for every
non-empty key, and a raced duplicate never crashes nor double-writes.
"""
from __future__ import annotations

import sqlite3

import pytest


def _p():
    import scripts.persistence as p
    return p


def _bridge():
    import scripts.moltbook_learning_bridge as b
    return b


def _entry(**overrides):
    """Full kwarg set for upsert_moltbook_learning_entry with sane defaults."""
    base = dict(
        entry_id="MBK_ENTRY_1",
        idempotency_key="MBK_KEY_1",
        trade_id="T1",
        event_id="E1",
        ticker="AAA",
        source_trade_state="CLOSED",
        event_type="CLOSED_LOSS",
        outcome_quality="LOSS",
        learning_direction="LOSS",
        entry_price=100.0,
        exit_price=90.0,
        exit_quantity=10.0,
        stop_loss_price=95.0,
        take_profit_price=120.0,
        realized_pl=-100.0,
        booked_percent=1.0,
        ride_percent=0.0,
        mistake_tags="late_exit",
        success_tags="",
        lesson="cut losses sooner",
        notes="",
        original_signal_thesis="thesis",
        ai_interpretation="",
        user_reflection="",
        final_human_decision="EXIT",
        outcome="LOSS",
        mistake_type="late_exit",
        lesson_learned="cut losses sooner",
        bias_detected="",
        recalibration_note="",
        future_rule_update="",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return base


def _count_key(db, key):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM moltbook_entries WHERE idempotency_key=?",
            (key,),
        ).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Sequential duplicate -> UPDATE branch returns the existing row.
# ---------------------------------------------------------------------------

def test_moltbook_duplicate_idempotency_returns_existing(tmp_path):
    p = _p()
    db = tmp_path / "m.db"
    p.init_schema(db)

    first = p.upsert_moltbook_learning_entry(**_entry(entry_id="A", idempotency_key="K1"), db_path=db)
    assert first["created"] is True

    second = p.upsert_moltbook_learning_entry(**_entry(entry_id="B", idempotency_key="K1"), db_path=db)
    assert second["created"] is False
    assert second["entry_id"] == "A"  # original row, not the new entry_id
    assert _count_key(db, "K1") == 1


# ---------------------------------------------------------------------------
# 2. Concurrent duplicate (row appears AFTER our SELECT) -> IntegrityError
#    recovery returns the existing row, no 500.
# ---------------------------------------------------------------------------

class _RaceConn:
    """Proxy that blinds ONLY the first idempotency-key SELECT, simulating a
    racing writer whose row is not yet visible to this transaction."""

    def __init__(self, real):
        self._real = real
        self._select_seen = 0

    def execute(self, sql, params=()):
        if sql.strip().upper().startswith("SELECT") and "WHERE IDEMPOTENCY_KEY" in sql.upper():
            self._select_seen += 1
            if self._select_seen == 1:
                class _Empty:
                    def fetchone(self_inner):
                        return None
                return _Empty()
        return self._real.execute(sql, params)

    def commit(self):
        return self._real.commit()

    def rollback(self):
        return self._real.rollback()

    def close(self):
        # Leave the underlying connection to the test to close.
        pass

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_moltbook_concurrent_duplicate_does_not_500(tmp_path, monkeypatch):
    p = _p()
    db = tmp_path / "m.db"
    p.init_schema(db)

    # The racing writer already committed a row carrying key K2.
    p.upsert_moltbook_learning_entry(**_entry(entry_id="RACER", idempotency_key="K2"), db_path=db)

    real = sqlite3.connect(str(db))
    real.row_factory = sqlite3.Row
    proxy = _RaceConn(real)
    monkeypatch.setattr(p, "_get_conn", lambda *a, **k: proxy)
    try:
        # Our SELECT is blinded -> INSERT collides on the UNIQUE key index ->
        # recovery returns the existing row instead of raising.
        res = p.upsert_moltbook_learning_entry(
            **_entry(entry_id="NEWCOMER", idempotency_key="K2"), db_path=db
        )
    finally:
        real.close()

    assert res["created"] is False
    assert res.get("raced_duplicate") is True
    assert res["entry_id"] == "RACER"
    assert _count_key(db, "K2") == 1


# ---------------------------------------------------------------------------
# 3. An IntegrityError with NO matching key row is unrelated -> still raises.
# ---------------------------------------------------------------------------

def test_moltbook_integrity_error_without_existing_record_still_raises(tmp_path):
    p = _p()
    db = tmp_path / "m.db"
    p.init_schema(db)

    # Seed a row with an EMPTY idempotency_key (no unique-key index) and a
    # known entry_id "DUP".
    p.upsert_moltbook_learning_entry(**_entry(entry_id="DUP", idempotency_key=""), db_path=db)

    # Re-use entry_id "DUP" with a never-seen key: pre-SELECT finds nothing ->
    # INSERT collides on the entry_id PRIMARY KEY -> recovery SELECT for the
    # unseen key finds nothing -> the unrelated IntegrityError must propagate.
    with pytest.raises(sqlite3.IntegrityError):
        p.upsert_moltbook_learning_entry(
            **_entry(entry_id="DUP", idempotency_key="UNSEEN_KEY"), db_path=db
        )


# ---------------------------------------------------------------------------
# 4 & 5. Idempotency key stability.
# ---------------------------------------------------------------------------

def test_moltbook_idempotency_key_stable_for_same_event():
    b = _bridge()
    k1 = b.compute_idempotency_key(trade_id="T1", event_type="CLOSED_LOSS", exit_price=90.0, exit_quantity=10.0)
    k2 = b.compute_idempotency_key(trade_id="T1", event_type="CLOSED_LOSS", exit_price=90.0, exit_quantity=10.0)
    assert k1 == k2
    assert k1.startswith("MBK_")


def test_moltbook_idempotency_key_changes_when_exit_price_changes():
    b = _bridge()
    k1 = b.compute_idempotency_key(trade_id="T1", event_type="CLOSED_LOSS", exit_price=90.0, exit_quantity=10.0)
    k2 = b.compute_idempotency_key(trade_id="T1", event_type="CLOSED_LOSS", exit_price=91.0, exit_quantity=10.0)
    assert k1 != k2
