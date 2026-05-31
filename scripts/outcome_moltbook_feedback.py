"""Close the Outcome Loop Sprint — Phase 4: real outcome -> Moltbook learning.

When a real-forward outcome attaches to a decision snapshot, the learning loop
should *close*: a bad outcome becomes a Moltbook failure-pattern entry, a good
outcome can be recorded as good-process evidence.  This module is the bridge —
it reuses the audited :func:`scripts.moltbook_learning_bridge.record_reconciliation_learning`
so all the existing eligibility / safety / outcome-quality logic applies.

Honest, idempotent, advisory-only:

* Bad outcome:  ``Bad_i = I(y==0) ∨ I(realized_return < 0) ∨ I(stop_loss_hit)``.
* Idempotency key ``k = sha1(decision_id | y | outcome_timestamp_utc | scoring_version)``
  is recorded in an additive ``outcome_moltbook_feedback_log`` table; a repeat
  call with the same key is a no-op (``status = "skipped_duplicate"``) so the
  same outcome never creates two learning entries.
* Moltbook learning NEVER unlocks execution: the response carries
  ``execution_gate = LOCKED``, ``broker_api_called = False``,
  ``ai_execution_count = 0``, ``execution_permission = False``.

This module places no orders and calls no broker.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Any

try:  # package layout
    from scripts import persistence
    from scripts.moltbook_learning_bridge import record_reconciliation_learning
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from moltbook_learning_bridge import record_reconciliation_learning  # type: ignore[no-redef]

_FEEDBACK_LOG_TABLE = "outcome_moltbook_feedback_log"

_CREATE_LOG_SQL = f"""
CREATE TABLE IF NOT EXISTS {_FEEDBACK_LOG_TABLE} (
    idempotency_key TEXT PRIMARY KEY,
    decision_id     TEXT NOT NULL,
    outcome_y       INTEGER,
    outcome_timestamp_utc TEXT,
    scoring_version TEXT,
    moltbook_entry_id TEXT,
    learning_direction TEXT,
    created_at_utc  TEXT NOT NULL
)
"""

_SAFETY = {
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_feedback_idempotency_key(
    *,
    decision_id: str,
    outcome_y: Any,
    outcome_timestamp_utc: str | None,
    scoring_version: str | None,
) -> str:
    """Stable key ``sha1(decision_id | y | outcome_ts | scoring_version)``."""
    parts = [
        str(decision_id or "").strip(),
        str(int(outcome_y)) if outcome_y in (0, 1) else "NA",
        str(outcome_timestamp_utc or "").strip(),
        str(scoring_version or "").strip(),
    ]
    raw = "|".join(parts).encode("utf-8")
    digest = hashlib.sha1(raw, usedforsecurity=False).hexdigest()  # advisory hash
    return f"OMB_{digest[:24]}"


def is_bad_outcome(
    *,
    outcome_y: Any,
    realized_return: float | None = None,
    stop_loss_hit: bool = False,
) -> bool:
    """``Bad_i = I(y==0) ∨ I(realized_return < 0) ∨ I(stop_loss_hit)``."""
    if outcome_y == 0:
        return True
    if realized_return is not None and realized_return < 0:
        return True
    if stop_loss_hit:
        return True
    return False


def _ensure_log(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_LOG_SQL)
    conn.commit()


def _seen_key(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        f"SELECT * FROM {_FEEDBACK_LOG_TABLE} WHERE idempotency_key = ?", (key,)
    ).fetchone()
    return dict(row) if row is not None else None


def record_outcome_feedback(
    *,
    decision_id: str,
    ticker: str,
    outcome_y: Any,
    realized_return: float | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    stop_loss_hit: bool = False,
    outcome_timestamp_utc: str | None = None,
    scoring_version: str | None = None,
    signal_class: str = "",
    source_name: str = "",
    country: str = "",
    target_event_definition: str = "",
    record_good_process: bool = True,
    db_path: Any = None,
    jsonl_path: Any = None,
) -> dict[str, Any]:
    """Turn a real-forward outcome into (at most one) Moltbook learning entry.

    Returns a status dict.  ``status`` is one of ``created`` / ``updated`` /
    ``skipped_duplicate`` / ``skipped`` / ``skipped_good_process_disabled``.
    Advisory safety stamps are always present and execution is never unlocked.
    """
    target = db_path if db_path is not None else persistence.DB_PATH

    key = compute_feedback_idempotency_key(
        decision_id=decision_id,
        outcome_y=outcome_y,
        outcome_timestamp_utc=outcome_timestamp_utc,
        scoring_version=scoring_version,
    )

    conn = sqlite3.connect(str(target))
    try:
        _ensure_log(conn)
        prior = _seen_key(conn, key)
    finally:
        conn.close()

    if prior is not None:
        return {
            "status": "skipped_duplicate",
            "idempotency_key": key,
            "decision_id": decision_id,
            "moltbook_entry_id": prior.get("moltbook_entry_id"),
            "message": "Outcome feedback already recorded for this idempotency key.",
            **_SAFETY,
        }

    bad = is_bad_outcome(
        outcome_y=outcome_y, realized_return=realized_return,
        stop_loss_hit=stop_loss_hit,
    )

    if not bad and not record_good_process:
        # A good outcome with good-process recording disabled is a no-op (still
        # logged so the idempotency key is consumed honestly).
        _persist_log(target, key, decision_id, outcome_y, outcome_timestamp_utc,
                     scoring_version, moltbook_entry_id=None, learning_direction="GOOD_SKIPPED")
        return {
            "status": "skipped_good_process_disabled",
            "idempotency_key": key,
            "decision_id": decision_id,
            "bad_outcome": False,
            "message": "Good outcome; good-process recording disabled.",
            **_SAFETY,
        }

    # Derive a realized P/L sign from realized_return or entry/exit so the
    # Moltbook bridge classifies CLOSED_WIN / CLOSED_LOSS correctly.  We never
    # fabricate a price: if neither is available we fall back to the binary y.
    realized_pl = realized_return
    if realized_pl is None and entry_price is not None and exit_price is not None:
        try:
            realized_pl = float(exit_price) - float(entry_price)
        except (TypeError, ValueError):
            realized_pl = None
    if realized_pl is None:
        realized_pl = -1.0 if bad else 1.0

    exit_for_moltbook = exit_price
    if exit_for_moltbook is None:
        # The bridge requires an exit price or realized P/L; realized_pl above
        # satisfies that, but supply a neutral non-zero exit so CLOSED maps.
        exit_for_moltbook = None

    thesis = (
        f"Real-forward outcome on {ticker} "
        f"(signal_class={signal_class or 'NA'}, source={source_name or 'NA'}, "
        f"target={target_event_definition or 'NA'})."
    )
    lesson = (
        "Real-forward outcome was unfavourable; record failure pattern for "
        "review."
        if bad else
        "Real-forward outcome was favourable; record good-process evidence."
    )

    result = record_reconciliation_learning(
        trade_id=f"OUTCOME_{decision_id}",
        event_id=decision_id,
        ticker=ticker,
        post_trade_outcome="CLOSED_LOSS" if bad else "CLOSED_WIN",
        explicit_event_type="CLOSED",
        actual_exit_price=exit_for_moltbook,
        entry_price=entry_price,
        realized_pl=realized_pl,
        stop_loss_hit=bool(stop_loss_hit),
        thesis=thesis,
        lesson=lesson,
        notes=f"decision_id={decision_id}; scoring_version={scoring_version or 'NA'}",
        db_path=target,
        jsonl_path=jsonl_path,
    )

    entry_id = result.get("entry_id")
    direction = result.get("learning_direction")
    status = result.get("status", "skipped")

    _persist_log(target, key, decision_id, outcome_y, outcome_timestamp_utc,
                 scoring_version, moltbook_entry_id=entry_id,
                 learning_direction=direction)

    out = {
        "status": status,
        "idempotency_key": key,
        "decision_id": decision_id,
        "ticker": str(ticker).upper(),
        "bad_outcome": bad,
        "moltbook_entry_id": entry_id,
        "moltbook_status": status,
        "learning_direction": direction,
        "outcome_quality": result.get("outcome_quality"),
        "message": result.get("message"),
    }
    out.update(_SAFETY)
    # Re-assert the bridge's own advisory stamps (defensive) — never loosened.
    out["broker_api_called"] = bool(result.get("broker_api_called", False))
    out["ai_execution_count"] = int(result.get("ai_execution_count", 0))
    return out


def _persist_log(
    db_path: Any,
    key: str,
    decision_id: str,
    outcome_y: Any,
    outcome_timestamp_utc: str | None,
    scoring_version: str | None,
    *,
    moltbook_entry_id: str | None,
    learning_direction: str | None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_log(conn)
        conn.execute(
            f"INSERT OR IGNORE INTO {_FEEDBACK_LOG_TABLE} ("
            " idempotency_key, decision_id, outcome_y, outcome_timestamp_utc,"
            " scoring_version, moltbook_entry_id, learning_direction, created_at_utc"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                key, decision_id,
                int(outcome_y) if outcome_y in (0, 1) else None,
                outcome_timestamp_utc, scoring_version, moltbook_entry_id,
                learning_direction, _utc_now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


__all__ = [
    "compute_feedback_idempotency_key",
    "is_bad_outcome",
    "record_outcome_feedback",
]
