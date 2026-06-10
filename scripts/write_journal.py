"""S4-A1: journal write-ahead event log — atomic-or-recoverable writes.

Residual being closed: the journal's JSONL append and SQLite mutation
were two unrelated writes.  A crash between them produced split-brain
that was only DETECTED (F10) and manually replayed (H5).  This module
gives every journal write a durable lifecycle in an append-only
``write_journal`` table that lives in the same SQLite file as the
domain rows:

    NEW -> JSONL_APPENDED -> DB_COMMITTED -> APPLIED
    NEW -> JSONL_APPENDED -> (apply failed) -> RECOVERABLE

A write may be reported as a success ONLY when its event row reaches
``APPLIED``.  Crash windows and their recovery:

* crash before the JSONL append  -> row at NEW: startup flags it
  RECOVERABLE (intent recorded, nothing persisted; replay re-applies).
* crash between JSONL and DB     -> row at JSONL_APPENDED: startup flags
  RECOVERABLE; guarded replay applies the SAME canonical apply function
  exactly once (idempotency key = the domain primary key).
* crash between DB commit and the APPLIED marker -> row at DB_COMMITTED:
  startup reconciliation checks the domain row EXISTS and marks APPLIED
  without re-inserting (no duplicates).

Startup never auto-replays NEW/JSONL_APPENDED intents — those go to
/health/full counters and the guarded replay path (operator decision),
because blind auto-apply at boot could resurrect a write the operator
deliberately abandoned.

Honest limit (documented, not hidden): the event row lives in the same
SQLite database.  If the DB is entirely unreachable, the intent exists
only in JSONL — exactly the pre-A1 degraded mode — and F10 divergence
detection still covers it.  A1 closes the crash-window class, not the
dead-database class (which already fails loud).

Advisory invariants: record-keeping only; no broker, no execution.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import persistence as _persistence
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

_logger = logging.getLogger("scripts.write_journal")

JOURNAL_ATOMICITY_MODE = "event_wal"

STATE_NEW = "NEW"
STATE_JSONL_APPENDED = "JSONL_APPENDED"
STATE_DB_COMMITTED = "DB_COMMITTED"
STATE_APPLIED = "APPLIED"
STATE_RECOVERABLE = "RECOVERABLE"

_PENDING_STATES = (STATE_NEW, STATE_JSONL_APPENDED, STATE_DB_COMMITTED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS write_journal (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    db_row_id TEXT,
    error_kind TEXT,
    error_message_redacted TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(event_type, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_wj_state ON write_journal(state);
"""


class WriteJournalError(RuntimeError):
    """The canonical apply failed; the event is RECOVERABLE."""

    def __init__(self, message: str, *, event_row_id: int | None):
        super().__init__(message)
        self.event_row_id = event_row_id


def _conn(db_path: Path | None) -> sqlite3.Connection:
    conn = _persistence._get_conn(db_path or _persistence.DB_PATH)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _redact(message: str) -> str:
    # Defensive: keep only exception class + a short bounded summary; never
    # raw values that could embed tokens.
    return message[:240]


def _set_state(
    conn: sqlite3.Connection,
    event_row_id: int,
    state: str,
    *,
    db_row_id: str | None = None,
    error_kind: str | None = None,
    error_message: str | None = None,
    bump_attempt: bool = False,
) -> None:
    conn.execute(
        "UPDATE write_journal SET state=?, updated_at=?,"
        " db_row_id=COALESCE(?, db_row_id),"
        " error_kind=COALESCE(?, error_kind),"
        " error_message_redacted=COALESCE(?, error_message_redacted),"
        " attempt_count=attempt_count + ?"
        " WHERE event_id=?",
        (
            state,
            utc_timestamp(),
            db_row_id,
            error_kind,
            _redact(error_message) if error_message else None,
            1 if bump_attempt else 0,
            event_row_id,
        ),
    )
    conn.commit()


def append_then_apply_event(
    *,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    jsonl_append: Callable[[], None],
    apply: Callable[[], Any],
    db_path: Path | None = None,
) -> dict[str, Any]:
    """The single canonical journal write function (S4-A1).

    Lifecycle per module docstring.  Returns an applied receipt dict.
    Raises :class:`WriteJournalError` when the apply step fails — the
    event is then RECOVERABLE and the caller must surface a stamped
    failure (never success).

    Duplicate ``(event_type, idempotency_key)`` with an APPLIED row
    returns the prior receipt WITHOUT re-running jsonl/apply.
    """
    conn = _conn(db_path)
    try:
        existing = conn.execute(
            "SELECT event_id, state, db_row_id FROM write_journal"
            " WHERE event_type=? AND idempotency_key=?",
            (event_type, idempotency_key),
        ).fetchone()
        if existing is not None and existing["state"] == STATE_APPLIED:
            return {
                "event_id": int(existing["event_id"]),
                "state": STATE_APPLIED,
                "db_row_id": existing["db_row_id"],
                "replayed_receipt": True,
                "db_committed": True,
                "execution_gate": "LOCKED",
                "broker_api_called": False,
            }
        if existing is not None:
            # In-flight or recoverable row for this key: reuse it (replay).
            event_row_id = int(existing["event_id"])
        else:
            now = utc_timestamp()
            cur = conn.execute(
                "INSERT INTO write_journal"
                " (event_type, idempotency_key, payload_json, payload_hash,"
                "  state, created_at, updated_at, attempt_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    event_type,
                    idempotency_key,
                    json.dumps(payload, sort_keys=True, default=str),
                    _payload_hash(payload),
                    STATE_NEW,
                    now,
                    now,
                ),
            )
            conn.commit()
            event_row_id = int(cur.lastrowid)

        # Step 1 — durable JSONL intent.
        if existing is None or existing["state"] == STATE_NEW:
            jsonl_append()
            _set_state(conn, event_row_id, STATE_JSONL_APPENDED)

        # Step 2 — canonical DB mutation.
        try:
            apply()
        except Exception as exc:
            _set_state(
                conn,
                event_row_id,
                STATE_RECOVERABLE,
                error_kind=type(exc).__name__,
                error_message=str(exc),
                bump_attempt=True,
            )
            _logger.error(
                "write_journal: apply FAILED for %s/%s (event %d) — RECOVERABLE",
                event_type,
                idempotency_key,
                event_row_id,
            )
            raise WriteJournalError(
                f"{event_type} apply failed: {type(exc).__name__}",
                event_row_id=event_row_id,
            ) from exc

        _set_state(conn, event_row_id, STATE_DB_COMMITTED, db_row_id=idempotency_key)
        _set_state(conn, event_row_id, STATE_APPLIED, bump_attempt=True)
        return {
            "event_id": event_row_id,
            "state": STATE_APPLIED,
            "db_row_id": idempotency_key,
            "replayed_receipt": False,
            "db_committed": True,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
        }
    finally:
        conn.close()


def journal_counters(db_path: Path | None = None) -> dict[str, Any]:
    """Counters for /health/full.  Never raises (health must not 500)."""
    try:
        conn = _conn(db_path)
        try:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS n FROM write_journal GROUP BY state"
            ).fetchall()
        finally:
            conn.close()
        by_state = {str(r["state"]): int(r["n"]) for r in rows}
        pending = sum(by_state.get(s, 0) for s in _PENDING_STATES)
        recoverable = by_state.get(STATE_RECOVERABLE, 0)
        return {
            "journal_atomicity_mode": JOURNAL_ATOMICITY_MODE,
            "write_journal_pending_total": pending,
            "write_journal_recoverable_total": recoverable,
            "write_journal_failed_total": recoverable,
            "write_journal_degraded": (pending + recoverable) > 0,
        }
    except Exception:
        _logger.exception("write_journal counters unavailable")
        return {
            "journal_atomicity_mode": JOURNAL_ATOMICITY_MODE,
            "write_journal_pending_total": -1,
            "write_journal_recoverable_total": -1,
            "write_journal_failed_total": -1,
            "write_journal_degraded": True,
        }


def startup_reconcile(
    exists_checks: dict[str, Callable[[dict[str, Any]], bool]],
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Boot-time pass over non-APPLIED events (safe operations only).

    * DB_COMMITTED rows whose domain row EXISTS are marked APPLIED — the
      crash hit between commit and marker; nothing is re-inserted.
    * NEW / JSONL_APPENDED rows are flagged RECOVERABLE (counted in
      health; replay is a guarded operator action, never automatic).
    """
    marked_applied: list[int] = []
    flagged_recoverable: list[int] = []
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, event_type, state, payload_json FROM write_journal"
            " WHERE state IN (?, ?, ?)",
            (STATE_NEW, STATE_JSONL_APPENDED, STATE_DB_COMMITTED),
        ).fetchall()
        for r in rows:
            event_id = int(r["event_id"])
            state = str(r["state"])
            payload = json.loads(r["payload_json"])
            if state == STATE_DB_COMMITTED:
                check = exists_checks.get(str(r["event_type"]))
                if check is not None and check(payload):
                    _set_state(conn, event_id, STATE_APPLIED)
                    marked_applied.append(event_id)
                    continue
            _set_state(
                conn,
                event_id,
                STATE_RECOVERABLE,
                error_kind="crash_recovery",
                error_message=f"found at {state} on startup",
            )
            flagged_recoverable.append(event_id)
    finally:
        conn.close()
    if marked_applied or flagged_recoverable:
        _logger.warning(
            "write_journal startup reconcile: %d marked APPLIED, %d RECOVERABLE",
            len(marked_applied),
            len(flagged_recoverable),
        )
    return {
        "marked_applied": marked_applied,
        "flagged_recoverable": flagged_recoverable,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
    }


def replay_recoverable(
    appliers: dict[str, Callable[[dict[str, Any]], None]],
    exists_checks: dict[str, Callable[[dict[str, Any]], bool]],
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Guarded replay of RECOVERABLE events through the canonical appliers.

    Idempotent: events whose domain row already exists are marked APPLIED
    without re-applying.  Callers are responsible for the permission
    boundary (the H5 replay tool wraps this in guarded_mutation).
    """
    replayed: list[int] = []
    already_present: list[int] = []
    still_failed: list[int] = []
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, event_type, payload_json FROM write_journal"
            " WHERE state=?",
            (STATE_RECOVERABLE,),
        ).fetchall()
    finally:
        conn.close()
    for r in rows:
        event_id = int(r["event_id"])
        event_type = str(r["event_type"])
        payload = json.loads(r["payload_json"])
        check = exists_checks.get(event_type)
        applier = appliers.get(event_type)
        conn = _conn(db_path)
        try:
            if check is not None and check(payload):
                _set_state(conn, event_id, STATE_APPLIED)
                already_present.append(event_id)
                continue
            if applier is None:
                still_failed.append(event_id)
                continue
            try:
                applier(payload)
            except Exception as exc:
                _set_state(
                    conn,
                    event_id,
                    STATE_RECOVERABLE,
                    error_kind=type(exc).__name__,
                    error_message=str(exc),
                    bump_attempt=True,
                )
                still_failed.append(event_id)
                continue
            _set_state(conn, event_id, STATE_APPLIED, bump_attempt=True)
            replayed.append(event_id)
        finally:
            conn.close()
    return {
        "replayed": replayed,
        "already_present": already_present,
        "still_failed": still_failed,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
    }
