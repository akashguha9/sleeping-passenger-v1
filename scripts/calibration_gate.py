"""Sprint 10F — outcome-calibration readiness gate.

Returns a structured readiness status for both paper and real-manual
trade calibration based on the local DB. The gate is intentionally
conservative — it tells the operator to wait for evidence rather than
to interpret a small sample.

Status thresholds (paper):

    rows_with_snapshot_and_outcome < 5   -> NOT_READY
    rows < 20                            -> VERY_LOW_CONFIDENCE
    rows < 50                            -> LOW_CONFIDENCE
    rows >= 50                           -> REVIEWABLE (still not real-money proof)

Real-manual calibration is reported separately. If real rows = 0 the
status is ``NO_REAL_OUTCOME_EVIDENCE`` and no further claim is made.

Safety
------
* Read-only with respect to the DB (opened ``mode=ro``).
* Never claims alpha, edge, profitability, or production readiness.
* Carries the standard advisory invariant stamps in every payload.
* stdlib only.

Usage
-----
    python scripts/calibration_gate.py
    python scripts/calibration_gate.py --json
    python scripts/calibration_gate.py --db-path /path/to/mvp_local.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "runtime" / "mvp_local.db"

STATUS_NOT_READY = "NOT_READY"
STATUS_VERY_LOW = "VERY_LOW_CONFIDENCE"
STATUS_LOW = "LOW_CONFIDENCE"
STATUS_REVIEWABLE = "REVIEWABLE"
STATUS_NO_REAL_EVIDENCE = "NO_REAL_OUTCOME_EVIDENCE"
STATUS_UNAVAILABLE = "UNAVAILABLE"

PAPER_GATE_MESSAGES = {
    STATUS_NOT_READY: "Do not interpret paper outcomes yet.",
    STATUS_VERY_LOW: "Only inspect process errors, not edge.",
    STATUS_LOW: "Look for repeated operator mistakes, not profitability.",
    STATUS_REVIEWABLE: "Still not real-money proof; review process patterns.",
}

_ADVISORY_STAMPS = {
    "advisory_only": True,
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_order_permission": False,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "paper_trade_only_for_paper_rows": True,
    "real_capital_at_risk_for_paper_rows": False,
}

_NO_CLAIMS = (
    "no_alpha_proven",
    "no_edge_proven",
    "no_real_money_proof",
    "no_profitability_claim",
    "no_production_readiness_claim",
)


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {r[1] for r in rows}


def _paper_gate_status(rows_with_snapshot_and_outcome: int) -> str:
    if rows_with_snapshot_and_outcome < 5:
        return STATUS_NOT_READY
    if rows_with_snapshot_and_outcome < 20:
        return STATUS_VERY_LOW
    if rows_with_snapshot_and_outcome < 50:
        return STATUS_LOW
    return STATUS_REVIEWABLE


def _rows_needed_for_next_band(rows: int) -> int:
    """How many more rows are needed to unlock the next confidence band."""
    if rows < 5:
        return 5 - rows
    if rows < 20:
        return 20 - rows
    if rows < 50:
        return 50 - rows
    return 0


def _count_qualifying_rows(
    conn: sqlite3.Connection,
    *,
    trade_mode: str,
) -> dict[str, int]:
    """Count rows in manual_trades joined to reconciliation_results.

    A row "qualifies" if it has all five inputs that the gate equation
    requires: paper-mode (or real-manual-mode), a reactor snapshot at
    decision time, an outcome status that is not UNKNOWN, a process
    label (outcome_quality or process_error filled), and a lesson.
    """
    mt_cols = _table_columns(conn, "manual_trades")
    rr_cols = _table_columns(conn, "reconciliation_results")
    has_trade_mode = "trade_mode" in mt_cols
    has_reactor_col = "reactor_state_at_decision" in mt_cols

    out = {
        "total": 0,
        "with_trade_mode": 0,
        "with_reactor_snapshot": 0,
        "with_outcome": 0,
        "with_process_label": 0,
        "with_lesson": 0,
        "with_snapshot_and_outcome": 0,
        "fully_qualifying": 0,
    }

    if not has_trade_mode or not mt_cols or not rr_cols:
        # Schema is older than Sprint 7B.2; nothing to count.
        return out

    where_trade_mode = (
        "UPPER(COALESCE(mt.trade_mode, '')) = :mode"
        if has_trade_mode
        else "1=1"
    )
    reactor_expr = (
        "TRIM(COALESCE(mt.reactor_state_at_decision, ''))"
        if has_reactor_col
        else "''"
    )

    sql = f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN {where_trade_mode} THEN 1 ELSE 0 END) AS mode_match,
            SUM(CASE WHEN {where_trade_mode}
                     AND {reactor_expr} != '' THEN 1 ELSE 0 END) AS w_snapshot,
            SUM(CASE WHEN {where_trade_mode}
                     AND rr.reconciliation_id IS NOT NULL
                     AND UPPER(COALESCE(rr.outcome_status, 'UNKNOWN')) != 'UNKNOWN'
                     THEN 1 ELSE 0 END) AS w_outcome,
            SUM(CASE WHEN {where_trade_mode}
                     AND (
                         TRIM(COALESCE(rr.outcome_quality, '')) != ''
                         OR TRIM(COALESCE(rr.process_error, '')) != ''
                     )
                     THEN 1 ELSE 0 END) AS w_label,
            SUM(CASE WHEN {where_trade_mode}
                     AND TRIM(COALESCE(rr.lesson, '')) != ''
                     THEN 1 ELSE 0 END) AS w_lesson,
            SUM(CASE WHEN {where_trade_mode}
                     AND {reactor_expr} != ''
                     AND rr.reconciliation_id IS NOT NULL
                     AND UPPER(COALESCE(rr.outcome_status, 'UNKNOWN')) != 'UNKNOWN'
                     THEN 1 ELSE 0 END) AS w_snap_outcome,
            SUM(CASE WHEN {where_trade_mode}
                     AND {reactor_expr} != ''
                     AND rr.reconciliation_id IS NOT NULL
                     AND UPPER(COALESCE(rr.outcome_status, 'UNKNOWN')) != 'UNKNOWN'
                     AND (
                         TRIM(COALESCE(rr.outcome_quality, '')) != ''
                         OR TRIM(COALESCE(rr.process_error, '')) != ''
                     )
                     AND TRIM(COALESCE(rr.lesson, '')) != ''
                     THEN 1 ELSE 0 END) AS w_full
        FROM manual_trades mt
        LEFT JOIN reconciliation_results rr ON rr.trade_id = mt.trade_id
    """
    try:
        row = conn.execute(sql, {"mode": trade_mode}).fetchone()
    except sqlite3.Error:
        return out

    def _val(idx: int) -> int:
        return int(row[idx]) if row and row[idx] is not None else 0

    out["total"] = _val(0)
    out["with_trade_mode"] = _val(1)
    out["with_reactor_snapshot"] = _val(2)
    out["with_outcome"] = _val(3)
    out["with_process_label"] = _val(4)
    out["with_lesson"] = _val(5)
    out["with_snapshot_and_outcome"] = _val(6)
    out["fully_qualifying"] = _val(7)
    return out


def build_report(db_path: Path = _DEFAULT_DB) -> dict[str, Any]:
    report: dict[str, Any] = {
        "report": "calibration_gate",
        "db_path": str(db_path),
        "db_available": False,
        "paper": {
            "status": STATUS_NOT_READY,
            "message": PAPER_GATE_MESSAGES[STATUS_NOT_READY],
            "rows": {
                "total": 0,
                "with_trade_mode": 0,
                "with_reactor_snapshot": 0,
                "with_outcome": 0,
                "with_process_label": 0,
                "with_lesson": 0,
                "with_snapshot_and_outcome": 0,
                "fully_qualifying": 0,
            },
            "rows_needed_next": 5,
            "no_claims": list(_NO_CLAIMS),
        },
        "real": {
            "status": STATUS_NO_REAL_EVIDENCE,
            "message": "No real-manual outcome rows recorded; calibration not applicable.",
            "rows": {
                "total": 0,
                "with_trade_mode": 0,
                "with_reactor_snapshot": 0,
                "with_outcome": 0,
                "with_process_label": 0,
                "with_lesson": 0,
                "with_snapshot_and_outcome": 0,
                "fully_qualifying": 0,
            },
            "rows_needed_next": 5,
            "no_claims": list(_NO_CLAIMS),
        },
        **_ADVISORY_STAMPS,
    }

    conn = _readonly_connect(db_path)
    if conn is None:
        report["paper"]["status"] = STATUS_UNAVAILABLE
        report["paper"]["message"] = "DB missing or unreadable; gate cannot evaluate paper rows."
        report["real"]["status"] = STATUS_UNAVAILABLE
        report["real"]["message"] = "DB missing or unreadable; gate cannot evaluate real rows."
        return report

    try:
        report["db_available"] = True
        paper_rows = _count_qualifying_rows(conn, trade_mode="PAPER")
        real_rows = _count_qualifying_rows(conn, trade_mode="REAL_MANUAL")
    finally:
        conn.close()

    report["paper"]["rows"] = paper_rows
    paper_n = paper_rows["with_snapshot_and_outcome"]
    paper_status = _paper_gate_status(paper_n)
    report["paper"]["status"] = paper_status
    report["paper"]["message"] = PAPER_GATE_MESSAGES[paper_status]
    report["paper"]["rows_needed_next"] = _rows_needed_for_next_band(paper_n)

    report["real"]["rows"] = real_rows
    real_n = real_rows["with_snapshot_and_outcome"]
    if real_n == 0:
        report["real"]["status"] = STATUS_NO_REAL_EVIDENCE
        report["real"]["message"] = (
            "No real-manual outcome rows recorded; calibration not applicable."
        )
        report["real"]["rows_needed_next"] = 5
    else:
        real_status = _paper_gate_status(real_n)
        report["real"]["status"] = real_status
        msg_map = {
            STATUS_NOT_READY: "Real-manual rows present but below 5; do not interpret yet.",
            STATUS_VERY_LOW: "Real-manual rows: only inspect process errors, not edge.",
            STATUS_LOW: "Real-manual rows: look for repeated mistakes, not profitability.",
            STATUS_REVIEWABLE: "Real-manual rows reviewable; still not a profitability claim.",
        }
        report["real"]["message"] = msg_map.get(real_status, "")
        report["real"]["rows_needed_next"] = _rows_needed_for_next_band(real_n)

    return report


def _emit_text(report: dict[str, Any]) -> None:
    print("Sleeping Passenger - Outcome Calibration Gate")
    print(f"db_path        : {report['db_path']}")
    print(f"db_available   : {report['db_available']}")
    print("")
    for label in ("paper", "real"):
        section = report[label]
        rows = section["rows"]
        print(f"{label.upper()}:")
        print(f"  status                       : {section['status']}")
        print(f"  message                      : {section['message']}")
        print(f"  total rows                   : {rows['total']}")
        print(f"  with trade_mode              : {rows['with_trade_mode']}")
        print(f"  with reactor snapshot        : {rows['with_reactor_snapshot']}")
        print(f"  with outcome                 : {rows['with_outcome']}")
        print(f"  with process label           : {rows['with_process_label']}")
        print(f"  with lesson                  : {rows['with_lesson']}")
        print(f"  with snapshot AND outcome    : {rows['with_snapshot_and_outcome']}")
        print(f"  fully qualifying             : {rows['fully_qualifying']}")
        print(f"  rows needed for next band    : {section['rows_needed_next']}")
        print("")
    print(
        "Safety: ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false, "
        "ai_execution_count=0, can_execute=false."
    )
    print(f"No claims: {', '.join(_NO_CLAIMS)}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="calibration_gate.py",
        description=(
            "Report calibration readiness for paper and real-manual rows. "
            "Read-only; no broker call; no profitability claim."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = (args.db_path or _DEFAULT_DB).expanduser().resolve()
    report = build_report(db_path)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _emit_text(report)
    return 0


__all__ = [
    "build_report",
    "STATUS_NOT_READY",
    "STATUS_VERY_LOW",
    "STATUS_LOW",
    "STATUS_REVIEWABLE",
    "STATUS_NO_REAL_EVIDENCE",
    "STATUS_UNAVAILABLE",
]


if __name__ == "__main__":
    raise SystemExit(main())
