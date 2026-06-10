"""S4-A1: event-type registry for the write-ahead journal.

Maps each journal event type to:
* ``exists`` — does the domain row already exist for this payload?
  (used by startup reconciliation and idempotent replay), and
* ``apply`` — re-run the CANONICAL persistence mutation from the stored
  payload (used by the guarded replay path; never a parallel insert).

Every applier delegates to the same persistence function the live API
path uses, so Decimal normalisation, NaN refusal, provenance stamps and
audit behaviour all hold on replay.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import persistence as _p
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _p  # type: ignore[no-redef]


def _row_exists(table: str, key_col: str, key: str, db_path: Path | None) -> bool:
    conn = _p._get_conn(db_path or _p.DB_PATH)
    try:
        row = conn.execute(
            f"SELECT 1 FROM {_p._safe_identifier(table)}"
            f" WHERE {_p._safe_identifier(key_col)}=?",
            (key,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def build_registry(db_path: Path | None = None) -> dict[str, dict[str, Callable]]:
    """Exists-checks + canonical appliers for every journal event type."""

    def _exists(table: str, col: str, field: str):
        def check(payload: dict[str, Any]) -> bool:
            return _row_exists(table, col, str(payload.get(field) or ""), db_path)
        return check

    def apply_manual_trade(payload: dict[str, Any]) -> None:
        _p.insert_manual_trade(
            str(payload["trade_id"]), str(payload.get("event_id") or ""),
            str(payload.get("ticker") or ""), str(payload.get("side") or ""),
            payload.get("quantity"), payload.get("price"),
            str(payload.get("executed_at") or ""), str(payload.get("thesis") or ""),
            str(payload.get("notes") or ""), str(payload.get("logged_by") or "human"),
            db_path=db_path or _p.DB_PATH,
            leverage=payload.get("leverage", 1),
            trade_mode=str(payload.get("trade_mode") or "REAL_MANUAL"),
            created_via=str(payload.get("created_via") or ""),
            currency=str(payload.get("currency") or ""),
            ai_model_used=str(payload.get("ai_model_used") or ""),
        )

    def apply_reconciliation(payload: dict[str, Any]) -> None:
        _p.insert_reconciliation(
            str(payload["reconciliation_id"]), str(payload.get("trade_id") or ""),
            str(payload.get("event_id") or ""), str(payload.get("reconciled_at") or ""),
            payload.get("actual_fill_price"), payload.get("actual_quantity"),
            str(payload.get("outcome_notes") or ""), payload.get("pnl_estimate", "0"),
            str(payload.get("outcome_status") or "UNKNOWN"),
            db_path=db_path or _p.DB_PATH,
            outcome_quality=str(payload.get("outcome_quality") or ""),
            process_error=str(payload.get("process_error") or ""),
            process_error_notes=str(payload.get("process_error_notes") or ""),
            mistake_tags=str(payload.get("mistake_tags") or ""),
            lesson=str(payload.get("lesson") or ""),
        )

    def apply_cancel(payload: dict[str, Any]) -> None:
        _p.cancel_manual_trade(
            str(payload["trade_id"]), str(payload.get("cancelled_at") or ""),
            cancel_reason=str(payload.get("cancel_reason") or ""),
            status=str(payload.get("reconciliation_status") or "CANCELLED_DUPLICATE"),
            db_path=db_path or _p.DB_PATH,
        )

    def cancel_exists(payload: dict[str, Any]) -> bool:
        conn = _p._get_conn(db_path or _p.DB_PATH)
        try:
            row = conn.execute(
                "SELECT reconciliation_status FROM manual_trades WHERE trade_id=?",
                (str(payload.get("trade_id") or ""),),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()
        if row is None:
            return False
        return str(row["reconciliation_status"] or "").upper().startswith("CANCELLED")

    def apply_reflection(payload: dict[str, Any]) -> None:
        _p.insert_reflection(
            str(payload["reflection_id"]), str(payload.get("event_id") or ""),
            str(payload.get("author") or "human"),
            str(payload.get("conviction_level") or ""),
            str(payload.get("reflection_text") or ""),
            str(payload.get("reflected_at") or ""),
            db_path=db_path or _p.DB_PATH,
        )

    def apply_ai_summary(payload: dict[str, Any]) -> None:
        _p.insert_ai_summary(
            str(payload["summary_id"]), str(payload.get("event_id") or ""),
            str(payload.get("model_label") or ""),
            str(payload.get("summary_text") or ""),
            str(payload.get("summarized_at") or ""),
            db_path=db_path or _p.DB_PATH,
        )

    def apply_signal_decision(payload: dict[str, Any]) -> None:
        _p.insert_signal_decision(
            str(payload["event_id"]), str(payload.get("user_status") or ""),
            str(payload.get("marked_at") or ""),
            db_path=db_path or _p.DB_PATH,
        )

    def decision_exists(payload: dict[str, Any]) -> bool:
        conn = _p._get_conn(db_path or _p.DB_PATH)
        try:
            row = conn.execute(
                "SELECT 1 FROM signal_decisions WHERE event_id=? AND marked_at=?",
                (str(payload.get("event_id") or ""), str(payload.get("marked_at") or "")),
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()

    def apply_moltbook(payload: dict[str, Any]) -> None:
        _p.insert_moltbook_entry(
            str(payload["entry_id"]), str(payload.get("event_id") or ""),
            str(payload.get("ticker") or ""),
            str(payload.get("original_signal_thesis") or ""),
            str(payload.get("ai_interpretation") or ""),
            str(payload.get("user_reflection") or ""),
            str(payload.get("final_human_decision") or ""),
            str(payload.get("manual_trade_log_id") or ""),
            str(payload.get("outcome") or ""),
            str(payload.get("mistake_type") or ""),
            str(payload.get("lesson_learned") or ""),
            str(payload.get("bias_detected") or ""),
            str(payload.get("recalibration_note") or ""),
            str(payload.get("future_rule_update") or ""),
            str(payload.get("logged_at") or ""),
            db_path=db_path or _p.DB_PATH,
        )

    return {
        "manual_trade": {
            "exists": _exists("manual_trades", "trade_id", "trade_id"),
            "apply": apply_manual_trade,
        },
        "reconciliation": {
            "exists": _exists(
                "reconciliation_results", "reconciliation_id", "reconciliation_id"
            ),
            "apply": apply_reconciliation,
        },
        "manual_trade_cancel": {"exists": cancel_exists, "apply": apply_cancel},
        "reflection": {
            "exists": _exists("user_reflections", "reflection_id", "reflection_id"),
            "apply": apply_reflection,
        },
        "ai_summary": {
            "exists": _exists("ai_discussion_summaries", "summary_id", "summary_id"),
            "apply": apply_ai_summary,
        },
        "signal_decision": {"exists": decision_exists, "apply": apply_signal_decision},
        "moltbook_entry": {
            "exists": _exists("moltbook_entries", "entry_id", "entry_id"),
            "apply": apply_moltbook,
        },
    }


def exists_checks(db_path: Path | None = None) -> dict[str, Callable]:
    return {k: v["exists"] for k, v in build_registry(db_path).items()}


def appliers(db_path: Path | None = None) -> dict[str, Callable]:
    return {k: v["apply"] for k, v in build_registry(db_path).items()}
