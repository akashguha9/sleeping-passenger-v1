"""
Learning-completeness report — exposes incomplete-learning *after*
reconciliation has happened.

Purpose
-------
``scripts/reconciliation_queue.py`` lists trades that have NOT been
reconciled yet.  Once a trade is reconciled, the row drops off that queue
— but the *learning* loop may still be open: the operator may have
recorded an outcome without labelling outcome quality, without separating
signal from process error, without writing a lesson.  Sprint 7C
("reconciliation completion mode") makes that gap impossible to ignore.

Definition of learning-complete
-------------------------------
A reconciled trade is *learning-complete* iff every one of these holds:

  * The reconciliation row's ``outcome_status`` is one of ``WIN``,
    ``LOSS``, ``BREAKEVEN`` (not ``UNKNOWN``/empty).
  * ``outcome_quality`` is non-empty.
  * ``process_error`` is non-empty *or* the operator has explicitly marked
    ``mistake_tags`` empty AND captured a ``lesson`` (i.e. a "no mistake,
    here's what I noticed" rationale).
  * ``lesson`` is non-empty.
  * The pre-trade journal (invalidation_level, expected_horizon,
    risk_reason, entry_reason, exit_plan) on the originating manual_trade
    row is non-empty — borrowed from ``self_test_journal_quality``.

If any one is missing the trade is *learning-incomplete* and the
operator is told exactly which fields to fill in.  This deliberately
mirrors the equation:

  Can_Mark_Learning_Complete =
    Outcome_Known
      × Outcome_Quality_Present
      × Process_Quality_Present
      × Lesson_Captured
      × Journal_Complete

Safety contract
---------------
Read-only.  No DB writes.  No broker calls.  No execution permission.

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----
    python scripts/learning_completeness_report.py
    python scripts/learning_completeness_report.py --json
    python scripts/learning_completeness_report.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

# Provenance contract — mirrors MANUAL_TRADE_LOG_PROVENANCE in
# scripts/signal_inbox_api.py.  Learning completeness counts only rows
# the operator entered through the Manual Trade Log UI/API.  Smoke seeds,
# demo fixtures, JSONL imports, probe theses, and test event_id prefixes
# are excluded — they are not part of the operator's decision journal.
# The full predicate lives in scripts/manual_trade_origin.
MANUAL_TRADE_LOG_PROVENANCE = "manual_trade_log"

try:
    from scripts.manual_trade_origin import (
        PROBE_THESIS_VALUES,
        PROBE_EVENT_ID_PREFIXES,
        EXCLUDED_LOGGED_BY,
        EXCLUDED_TRADE_MODES,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from manual_trade_origin import (  # type: ignore[no-redef]
        PROBE_THESIS_VALUES,
        PROBE_EVENT_ID_PREFIXES,
        EXCLUDED_LOGGED_BY,
        EXCLUDED_TRADE_MODES,
    )

ADVISORY_DISCLAIMER = (
    "Learning-completeness report is advisory-only.  Marking a trade "
    "learning-complete records that the operator filled in the required "
    "review fields; it never places, modifies, or cancels a broker order."
)

OPERATOR_ACTION = (
    "For each learning-incomplete row, fill the listed missing fields on "
    "the reconciliation form.  Do not rush this — incomplete journals "
    "make calibration unreliable."
)

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

# Pre-trade journal fields that must be non-empty on the originating
# manual_trade row for the learning loop to be considered closed.
_PRE_TRADE_REQUIRED: tuple[str, ...] = (
    "invalidation_level",
    "expected_horizon",
    "risk_reason",
    "entry_reason",
    "exit_plan",
    "lesson",  # post-trade lesson captured on the manual_trade row counts too
)

# Reconciliation fields that must be present.
_OUTCOME_KNOWN_STATUSES: frozenset[str] = frozenset({"WIN", "LOSS", "BREAKEVEN"})


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _columns_present(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {r[1] for r in rows}


def _classify_row(row: dict[str, Any]) -> tuple[bool, list[str], str]:
    """Return ``(learning_complete, missing_fields, blocked_reason)``.

    ``blocked_reason`` is a short human-readable phrase the UI/CLI can
    show without needing to know the rule.
    """
    missing: list[str] = []

    outcome_status = str(row.get("outcome_status") or "").strip().upper()
    if outcome_status not in _OUTCOME_KNOWN_STATUSES:
        missing.append("outcome_status")

    outcome_quality = str(row.get("outcome_quality") or "").strip()
    if not outcome_quality:
        missing.append("outcome_quality")

    process_error = str(row.get("process_error") or "").strip()
    mistake_tags_str = str(row.get("mistake_tags") or "").strip()
    mistake_tags = [t.strip() for t in mistake_tags_str.split(",") if t.strip()]
    rec_lesson = str(row.get("rec_lesson") or "").strip()
    # process_quality is satisfied when EITHER a process_error is named OR
    # mistake_tags are present OR the operator wrote a lesson on the
    # reconciliation row.  Empty everywhere means "we don't know whether
    # this was skill, luck, or process error" — incomplete.
    if not process_error and not mistake_tags and not rec_lesson:
        missing.append("process_quality")

    pre_trade_lesson = str(row.get("lesson") or "").strip()
    if not pre_trade_lesson and not rec_lesson:
        missing.append("lesson")

    for field in _PRE_TRADE_REQUIRED:
        if field == "lesson":
            # Handled above to allow reconciliation-side lesson to satisfy.
            continue
        value = row.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(f"journal:{field}")

    if not missing:
        return True, [], ""

    if "outcome_status" in missing:
        reason = (
            "Outcome status is UNKNOWN or empty. Reconcile the trade with an "
            "outcome label (WIN / LOSS / BREAKEVEN) before learning can close."
        )
    elif any(m.startswith("journal:") for m in missing):
        reason = (
            "Pre-trade journal fields are missing on the originating trade. "
            "Backfill invalidation/horizon/risk/entry/exit reasoning."
        )
    elif "outcome_quality" in missing:
        reason = "Outcome quality is unlabelled. Label win/loss as skill/luck/process."
    elif "process_quality" in missing:
        reason = (
            "Process quality is unlabelled. Either name the process_error, "
            "tag the mistakes, or record a lesson on the reconciliation row."
        )
    elif "lesson" in missing:
        reason = (
            "No lesson captured. Write one sentence on what to repeat or "
            "avoid next time — that is the entire point of reconciliation."
        )
    else:
        reason = "Required learning fields are missing."

    return False, missing, reason


def build_report(
    db_path: Path | None = None,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return the learning-completeness report.

    Read-only.  Never raises; missing DB / tables become entries in
    ``warnings`` and the report is otherwise empty.
    """
    path = Path(db_path) if db_path else _default_db_path()
    warnings: list[str] = []
    out: dict[str, Any] = {
        "report": "learning_completeness_report",
        "db_path": str(path),
        "db_available": False,
        "reconciled_count": 0,
        "learning_complete_count": 0,
        "learning_incomplete_count": 0,
        "missing_field_distribution": {},
        "items": [],
        "warnings": warnings,
        "operator_action": OPERATOR_ACTION,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
    }
    out.update(_SAFETY_STAMPS)

    if not path.exists():
        warnings.append("db_missing")
        return out

    conn = _readonly_connect(path)
    if conn is None:
        warnings.append("db_open_failed")
        return out

    try:
        if not _table_exists(conn, "manual_trades"):
            warnings.append("manual_trades_table_missing")
            return out
        if not _table_exists(conn, "reconciliation_results"):
            warnings.append("reconciliation_results_table_missing")
            return out

        mt_cols = _columns_present(conn, "manual_trades")
        rr_cols = _columns_present(conn, "reconciliation_results")

        if "trade_id" not in mt_cols or "trade_id" not in rr_cols:
            warnings.append("trade_id_column_missing")
            return out

        select_mt = [
            "mt.trade_id", "mt.event_id", "mt.ticker", "mt.side",
            "mt.quantity", "mt.executed_at", "mt.thesis", "mt.lesson",
        ]
        for col in ("invalidation_level", "expected_horizon", "risk_reason",
                    "entry_reason", "exit_plan", "mistake_tags"):
            if col in mt_cols:
                select_mt.append(f"mt.{col}")
        select_rr = ["rr.outcome_status"]
        for col in ("outcome_quality", "process_error", "lesson", "mistake_tags"):
            if col in rr_cols:
                alias = "rec_lesson" if col == "lesson" else (
                    "rec_mistake_tags" if col == "mistake_tags" else col
                )
                select_rr.append(f"rr.{col} AS {alias}")

        # Provenance filter — only count rows the operator entered
        # through the Manual Trade Log UI/API.  Empty / unknown
        # provenance is excluded by design so seed/demo/import rows do
        # not pollute the Learning Completeness counts (missing field
        # distribution, oldest incomplete trades, complete-vs-incomplete
        # split).
        if "created_via" in mt_cols:
            provenance_clause = " AND COALESCE(mt.created_via, '') = ?"
            provenance_params: tuple[Any, ...] = (MANUAL_TRADE_LOG_PROVENANCE,)
        else:
            warnings.append("manual_trades_missing_created_via_column")
            provenance_clause = " AND 1=0"
            provenance_params = ()
        # Defence in depth: never count a row that ever claimed a broker
        # call or AI execution, even though this app never sets either.
        broker_clause = (
            " AND COALESCE(mt.broker_api_called, 0) = 0"
            if "broker_api_called" in mt_cols else ""
        )
        ai_clause = (
            " AND COALESCE(mt.ai_execution_count, 0) = 0"
            if "ai_execution_count" in mt_cols else ""
        )
        # Mirror the queue's content-based exclusions so awaiting and
        # learning-completeness agree about which rows are user-manual.
        if "thesis" in mt_cols and PROBE_THESIS_VALUES:
            thesis_ph = ",".join("?" for _ in PROBE_THESIS_VALUES)
            probe_thesis_clause = (
                f" AND LOWER(TRIM(COALESCE(mt.thesis, ''))) NOT IN ({thesis_ph})"
            )
            probe_thesis_params: tuple[Any, ...] = tuple(PROBE_THESIS_VALUES)
        else:
            probe_thesis_clause = ""
            probe_thesis_params = ()
        if "event_id" in mt_cols and PROBE_EVENT_ID_PREFIXES:
            # Escape '_' so 'EV_' is treated as literal text rather than
            # a single-char SQL wildcard (would otherwise eat 'EV1').
            ev_clauses = " AND ".join(
                "COALESCE(mt.event_id, '') NOT LIKE ? ESCAPE '\\'"
                for _ in PROBE_EVENT_ID_PREFIXES
            )
            probe_event_id_clause = f" AND ({ev_clauses})"
            probe_event_id_params: tuple[Any, ...] = tuple(
                f"{p.replace('_', r'\_')}%" for p in PROBE_EVENT_ID_PREFIXES
            )
        else:
            probe_event_id_clause = ""
            probe_event_id_params = ()
        if "logged_by" in mt_cols and EXCLUDED_LOGGED_BY:
            lb_ph = ",".join("?" for _ in EXCLUDED_LOGGED_BY)
            excluded_logged_by_clause = (
                f" AND LOWER(TRIM(COALESCE(mt.logged_by, ''))) NOT IN ({lb_ph})"
            )
            excluded_logged_by_params: tuple[Any, ...] = tuple(EXCLUDED_LOGGED_BY)
        else:
            excluded_logged_by_clause = ""
            excluded_logged_by_params = ()
        if "trade_mode" in mt_cols and EXCLUDED_TRADE_MODES:
            tm_ph = ",".join("?" for _ in EXCLUDED_TRADE_MODES)
            excluded_trade_mode_clause = (
                f" AND UPPER(TRIM(COALESCE(mt.trade_mode, ''))) NOT IN ({tm_ph})"
            )
            excluded_trade_mode_params: tuple[Any, ...] = tuple(EXCLUDED_TRADE_MODES)
        else:
            excluded_trade_mode_clause = ""
            excluded_trade_mode_params = ()
        select_clause = ", ".join(select_mt + select_rr)
        try:
            rows = conn.execute(
                f"SELECT {select_clause} FROM manual_trades mt"  # noqa: S608
                " INNER JOIN reconciliation_results rr"
                "  ON rr.trade_id = mt.trade_id"
                " WHERE 1=1"
                + provenance_clause
                + broker_clause
                + ai_clause
                + probe_thesis_clause
                + probe_event_id_clause
                + excluded_logged_by_clause
                + excluded_trade_mode_clause
                + " ORDER BY mt.executed_at ASC",
                provenance_params
                + probe_thesis_params
                + probe_event_id_params
                + excluded_logged_by_params
                + excluded_trade_mode_params,
            ).fetchall()
        except sqlite3.Error as exc:
            warnings.append(f"query_failed:{type(exc).__name__}")
            return out
        out["db_available"] = True

        items: list[dict[str, Any]] = []
        complete = 0
        incomplete = 0
        missing_dist: dict[str, int] = {}
        for row in rows:
            row_dict = {k: row[k] for k in row.keys()}
            # Merge mistake_tags from manual_trade if reconciliation side
            # is absent.  Reconciliation-side takes precedence when both.
            if "rec_mistake_tags" in row_dict and row_dict.get("rec_mistake_tags"):
                row_dict["mistake_tags"] = row_dict["rec_mistake_tags"]
            ok, missing, reason = _classify_row(row_dict)
            if ok:
                complete += 1
            else:
                incomplete += 1
                for field in missing:
                    missing_dist[field] = missing_dist.get(field, 0) + 1

            item = {
                "trade_id": str(row_dict.get("trade_id") or ""),
                "event_id": str(row_dict.get("event_id") or ""),
                "ticker": str(row_dict.get("ticker") or ""),
                "side": str(row_dict.get("side") or ""),
                "executed_at": str(row_dict.get("executed_at") or ""),
                "outcome_status": str(row_dict.get("outcome_status") or ""),
                "outcome_quality": str(row_dict.get("outcome_quality") or ""),
                "process_error": str(row_dict.get("process_error") or ""),
                "mistake_tags": str(row_dict.get("mistake_tags") or ""),
                "lesson_pre_trade": str(row_dict.get("lesson") or ""),
                "lesson_reconciliation": str(row_dict.get("rec_lesson") or ""),
                "learning_complete": ok,
                "missing_fields": missing,
                "blocked_reason": reason,
            }
            item.update(_SAFETY_STAMPS)
            items.append(item)

        # Summary
        total = complete + incomplete
        out["reconciled_count"] = total
        out["learning_complete_count"] = complete
        # Alias: "learning_incomplete_count" is the count of reconciled
        # trades whose journal is still missing fields.  The frontend
        # also exposes this as reconciled_but_learning_incomplete_count
        # so the landing page can distinguish "needs reconciliation"
        # from "needs journal fields".
        out["learning_incomplete_count"] = incomplete
        out["reconciled_but_learning_incomplete_count"] = incomplete
        out["missing_field_distribution"] = missing_dist
        # Separate "awaiting reconciliation" count — rows that pass the
        # user-manual predicate but have no reconciliation_results row
        # yet AND are not cancelled.  This is what the live queue badge
        # should show; the historical "incomplete" count above is the
        # learning-loop indicator.  We compute it as a separate query so
        # the two surfaces cannot drift.
        try:
            # Reuse the same provenance + safety + probe filters.
            awaiting_select = (
                f"SELECT COUNT(*) FROM manual_trades mt"  # noqa: S608
                " WHERE NOT EXISTS ("
                "   SELECT 1 FROM reconciliation_results rr"
                "   WHERE rr.trade_id = mt.trade_id"
                " )"
            )
            cancelled_sql_clause = ""
            if "reconciliation_status" in mt_cols:
                cancelled_sql_clause = (
                    " AND COALESCE(mt.reconciliation_status, '') NOT IN "
                    "('CANCELLED_LOG', 'CANCELLED_DUPLICATE')"
                )
            awaiting_row = conn.execute(
                awaiting_select
                + cancelled_sql_clause
                + provenance_clause
                + broker_clause
                + ai_clause
                + probe_thesis_clause
                + probe_event_id_clause
                + excluded_logged_by_clause
                + excluded_trade_mode_clause,
                provenance_params
                + probe_thesis_params
                + probe_event_id_params
                + excluded_logged_by_params
                + excluded_trade_mode_params,
            ).fetchone()
            awaiting_count = int(awaiting_row[0] if awaiting_row else 0)
        except sqlite3.Error:
            awaiting_count = 0
        out["awaiting_reconciliation_count"] = awaiting_count

        # Diagnostic count of rows we excluded from this report on
        # purpose (probe theses, test event_ids, paper-ledger imports,
        # cancelled logs).  The frontend can show this small number so
        # the operator understands why their DB row count is bigger than
        # the queue.
        try:
            total_rows_row = conn.execute(
                "SELECT COUNT(*) FROM manual_trades"
            ).fetchone()
            total_rows = int(total_rows_row[0] if total_rows_row else 0)
        except sqlite3.Error:
            total_rows = 0
        # excluded == everything in manual_trades that is NOT counted
        # above plus reconciled rows already counted.  Best-effort
        # estimate; only used as a diagnostic chip.
        excluded_or_cancelled = max(
            0, total_rows - total - awaiting_count
        )
        out["excluded_or_cancelled_count"] = excluded_or_cancelled
        # Only learning-incomplete items are surfaced; the operator's job
        # is to close them, not to scroll past completed work.
        incomplete_items = [it for it in items if not it["learning_complete"]]
        if isinstance(limit, int) and limit >= 0:
            out["items"] = incomplete_items[:limit]
            if limit < len(incomplete_items):
                out["truncated"] = True
                out["truncated_to"] = limit
        else:
            out["items"] = incomplete_items

        return out
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Learning Completeness Report")
    lines.append("=" * 32)
    lines.append(f"Reconciled trades: {payload['reconciled_count']}")
    lines.append(f"  learning-complete   : {payload['learning_complete_count']}")
    lines.append(f"  learning-incomplete : {payload['learning_incomplete_count']}")
    dist = payload.get("missing_field_distribution") or {}
    if dist:
        lines.append("Missing-field distribution:")
        for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
            lines.append(f"  - {k}: {v}")
    if payload.get("warnings"):
        lines.append("Warnings: " + ", ".join(payload["warnings"]))
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    lines.append("")
    lines.append(payload["advisory_disclaimer"])
    items = payload["items"]
    if items:
        lines.append("")
        lines.append("Incomplete items:")
        for it in items:
            lines.append(
                f"  - {it['trade_id']:>14} {it['ticker']:>6} "
                f"{it['outcome_status'] or '-':<10} "
                f"missing={','.join(it['missing_fields']) or '-'}"
            )
            lines.append(f"      -> {it['blocked_reason']}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="learning_completeness_report.py",
        description=(
            "Read-only report of reconciled trades whose learning loop is "
            "still open. Never places, modifies, or cancels broker orders."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of items listed (summary stays global).")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    payload = build_report(db_path, limit=args.limit)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload.get("db_available", False) else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "ADVISORY_DISCLAIMER",
    "OPERATOR_ACTION",
    "MANUAL_TRADE_LOG_PROVENANCE",
    "build_report",
    "_classify_row",
]


if __name__ == "__main__":
    raise SystemExit(main())
