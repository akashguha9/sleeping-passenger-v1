"""
Reactor calibration report — honest, evidence-bounded readout.

Purpose
-------
A diagnostic system without outcome calibration becomes theatre.  This
script reads `manual_trades` and `reconciliation_results` from the local
SQLite database and produces a single read-only report whose job is to
tell the operator three things:

1. How much *reconciled* data we actually have.
2. What confidence the operator should place in any reactor-related
   inference given the current sample size.
3. Which fields are missing for proper reactor-vs-outcome calibration.

Crucially this report does NOT claim a reactor hit-rate or false-
positive rate when the sample size is small.  It does NOT unlock
execution, ever.  It surfaces gaps; it does not paper over them.

Confidence bands
----------------

    n < 10   -> "very_low"
    n < 30   -> "low"
    n < 100  -> "medium"
    n >= 100 -> "higher_but_contextual"

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----

    python scripts/reactor_calibration_report.py
    python scripts/reactor_calibration_report.py --json
    python scripts/reactor_calibration_report.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

VERY_LOW_THRESHOLD = 10
LOW_THRESHOLD = 30
MEDIUM_THRESHOLD = 100

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

ADVISORY_DISCLAIMER = (
    "Reactor calibration report is advisory-only.  It cannot grant "
    "execution permission, cannot unlock the pre-real-money preflight, "
    "and cannot override an unreconciled-backlog block.  Sample-size "
    "thresholds are deliberately conservative."
)

# Reactor-related fields the operator would need to compute hit-rate,
# false-positive rate, gallardo-block value, etc.  None of these are
# persisted at decision-time yet — see "limitations" in the output.
REACTOR_DECISION_FIELDS: tuple[str, ...] = (
    "reactor_state_at_decision",
    "decision_grade_energy_at_decision",
    "echo_risk_score_at_decision",
    "meltdown_risk_at_decision",
    "fusion_validity_at_decision",
    "fission_branch_clarity_at_decision",
    "operator_heat_at_decision",
    "gallardo_block_at_decision",
    "preflight_state_at_decision",
)


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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    return any(r[1] == column for r in rows)


def _confidence_band(n: int) -> str:
    if n < VERY_LOW_THRESHOLD:
        return "very_low"
    if n < LOW_THRESHOLD:
        return "low"
    if n < MEDIUM_THRESHOLD:
        return "medium"
    return "higher_but_contextual"


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"]) if row else 0


def _outcome_distribution(conn: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(conn, "reconciliation_results"):
        return {}
    try:
        rows = conn.execute(
            "SELECT outcome_status AS k, COUNT(*) AS n"
            " FROM reconciliation_results GROUP BY outcome_status"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(r["k"] or "UNKNOWN"): int(r["n"]) for r in rows}


def _process_error_distribution(conn: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(conn, "reconciliation_results"):
        return {}
    if not _column_exists(conn, "reconciliation_results", "process_error"):
        return {}
    try:
        rows = conn.execute(
            "SELECT process_error AS k, COUNT(*) AS n"
            " FROM reconciliation_results"
            " WHERE process_error IS NOT NULL AND process_error != ''"
            " GROUP BY process_error"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(r["k"]): int(r["n"]) for r in rows}


def _journal_completeness_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Average journal completeness across reconciled trades, using
    `self_test_journal_quality.score_journal_entry` if available."""
    empty: dict[str, Any] = {
        "available": False,
        "trade_count": 0,
        "average_completeness": 0.0,
        "learning_ready_count": 0,
    }
    if not (
        _table_exists(conn, "manual_trades")
        and _table_exists(conn, "reconciliation_results")
    ):
        return empty
    try:
        try:
            from scripts.self_test_journal_quality import (  # type: ignore[import-not-found]
                score_journal_entries,
                score_journal_entry,
            )
        except ModuleNotFoundError:
            from self_test_journal_quality import (  # type: ignore[no-redef]
                score_journal_entries,
                score_journal_entry,
            )
    except Exception:
        return empty

    cols_present = {
        c: _column_exists(conn, "manual_trades", c)
        for c in (
            "invalidation_level",
            "expected_horizon",
            "risk_reason",
            "entry_reason",
            "exit_plan",
            "confidence_before",
            "emotional_state",
            "mistake_tags",
            "lesson",
        )
    }
    select_cols = ["mt.trade_id", "mt.event_id", "mt.quantity", "mt.thesis"]
    for c, present in cols_present.items():
        if present:
            select_cols.append(f"mt.{c}")
    select_cols += ["rr.outcome_status", "rr.outcome_notes"]
    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)}"  # noqa: S608
            " FROM manual_trades mt"
            " INNER JOIN reconciliation_results rr ON rr.trade_id = mt.trade_id"
        ).fetchall()
    except sqlite3.Error:
        return empty

    entries: list[dict[str, Any]] = []
    for row in rows:
        row_dict = {k: row[k] for k in row.keys()}
        entries.append(
            {
                "signal_id": str(row_dict.get("event_id") or ""),
                "thesis": str(row_dict.get("thesis") or ""),
                "invalidation_level": str(row_dict.get("invalidation_level") or ""),
                "expected_horizon": str(row_dict.get("expected_horizon") or ""),
                "position_size": float(row_dict.get("quantity") or 0.0),
                "risk_reason": str(row_dict.get("risk_reason") or ""),
                "entry_reason": str(row_dict.get("entry_reason") or ""),
                "exit_plan": str(row_dict.get("exit_plan") or ""),
                "confidence_before": row_dict.get("confidence_before"),
                "emotional_state": str(row_dict.get("emotional_state") or ""),
                "post_trade_outcome": str(row_dict.get("outcome_notes") or ""),
                "reconciliation_status": str(row_dict.get("outcome_status") or ""),
                "mistake_tags": [
                    t.strip()
                    for t in str(row_dict.get("mistake_tags") or "").split(",")
                    if t.strip()
                ],
                "lesson": str(row_dict.get("lesson") or ""),
            }
        )

    agg = score_journal_entries(entries)
    # Per-entry only used for completeness — never displayed.
    for entry in entries:
        score_journal_entry(entry)
    return {
        "available": True,
        "trade_count": int(agg.get("entry_count", 0)),
        "average_completeness": float(agg.get("average_completeness", 0.0)),
        "average_learning_readiness": float(
            agg.get("average_learning_readiness", 0.0)
        ),
        "learning_ready_count": int(agg.get("learning_ready_count", 0)),
    }


def _reactor_self_check_via_self_test() -> dict[str, Any]:
    """Inherit the existing reactor self-check from self_test_report so the
    calibration report and the self-test report agree on reactor health."""
    try:
        try:
            from scripts.self_test_report import _reactor_self_check  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from self_test_report import _reactor_self_check  # type: ignore[no-redef]
        return _reactor_self_check()
    except Exception:
        return {
            "available": False,
            "reactor_state": "INSUFFICIENT_DATA",
            "recommendation": "observe",
            "safety_invariants_ok": False,
            "import_error": "self_test_report._reactor_self_check unavailable",
        }


def build_report(db_path: Path | None = None) -> dict[str, Any]:
    """Build the calibration report.  Read-only; never raises."""
    db_path = Path(db_path) if db_path else _default_db_path()
    limitations: list[str] = []

    if not db_path.exists():
        out: dict[str, Any] = {
            "report": "reactor_calibration_report",
            "db_path": str(db_path),
            "db_available": False,
            "limitations": ["db_missing"],
            "advisory_disclaimer": ADVISORY_DISCLAIMER,
        }
        out.update(_SAFETY_STAMPS)
        return out

    conn = _readonly_connect(db_path)
    if conn is None:
        out = {
            "report": "reactor_calibration_report",
            "db_path": str(db_path),
            "db_available": False,
            "limitations": ["db_open_failed"],
            "advisory_disclaimer": ADVISORY_DISCLAIMER,
        }
        out.update(_SAFETY_STAMPS)
        return out

    try:
        manual_trade_count = _safe_count(conn, "manual_trades")
        reconciled_count = _safe_count(conn, "reconciliation_results")
        outcome_dist = _outcome_distribution(conn)
        process_error_dist = _process_error_distribution(conn)
        journal = _journal_completeness_summary(conn)

        # Confidence band derives from the reconciled-trade count — that
        # is the only number where signal-vs-outcome attribution exists.
        confidence = _confidence_band(reconciled_count)

        # Inventory missing reactor-at-decision fields.  None of these
        # are persisted yet; this is intentionally surfaced as a gap so
        # the operator knows reactor hit-rate cannot be computed.
        missing_decision_fields: list[str] = []
        for col in REACTOR_DECISION_FIELDS:
            # manual_trades is the natural place to attach them.
            if not _column_exists(conn, "manual_trades", col):
                missing_decision_fields.append(col)

        if not _table_exists(conn, "manual_trades"):
            limitations.append("manual_trades_table_missing")
        if not _table_exists(conn, "reconciliation_results"):
            limitations.append("reconciliation_results_table_missing")
        if manual_trade_count == 0:
            limitations.append("no_manual_trades_logged_yet")
        if reconciled_count == 0:
            limitations.append("no_reconciled_trades_yet")
        if missing_decision_fields:
            limitations.append("reactor_at_decision_fields_not_persisted")
        if not journal.get("available"):
            limitations.append("journal_quality_helper_unavailable")
        if confidence in ("very_low", "low"):
            limitations.append("sample_size_too_small_for_calibration_claims")
    finally:
        conn.close()

    reactor_self_check = _reactor_self_check_via_self_test()

    out = {
        "report": "reactor_calibration_report",
        "db_path": str(db_path),
        "db_available": True,
        "manual_trade_count": manual_trade_count,
        "reconciled_count": reconciled_count,
        "outcome_distribution": outcome_dist,
        "process_error_distribution": process_error_dist,
        "journal": journal,
        "reactor_self_check": reactor_self_check,
        "confidence_band": confidence,
        "confidence_thresholds": {
            "very_low_lt": VERY_LOW_THRESHOLD,
            "low_lt": LOW_THRESHOLD,
            "medium_lt": MEDIUM_THRESHOLD,
        },
        "missing_decision_fields": missing_decision_fields,
        "limitations": limitations,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        # Explicit non-claims — what this report CANNOT honestly say yet.
        "non_claims": [
            "reactor_hit_rate is NOT computed; reactor_state at decision "
            "time is not yet persisted.",
            "gallardo_block value-vs-cost is NOT computed; obeyed/ignored "
            "history is not yet tracked.",
            "Echo-risk utility is NOT computed; echo_risk_score at "
            "decision time is not yet persisted.",
            "Calibration confidence is bounded by reconciled-trade "
            "sample size; do not infer skill from small n.",
        ],
    }
    out.update(_SAFETY_STAMPS)
    return out


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Reactor Calibration Report")
    lines.append("=" * 28)
    if not payload.get("db_available", False):
        lines.append(f"DB: {payload['db_path']} (unavailable)")
        for lim in payload.get("limitations", []):
            lines.append(f"  - {lim}")
        return "\n".join(lines) + "\n"
    lines.append(f"DB: {payload['db_path']}")
    lines.append(f"Manual trades logged   : {payload['manual_trade_count']}")
    lines.append(f"Reconciled trades      : {payload['reconciled_count']}")
    lines.append(f"Confidence band        : {payload['confidence_band']}")
    journal = payload.get("journal", {}) or {}
    if journal.get("available"):
        lines.append(
            f"Avg journal completeness: {journal['average_completeness']:.3f}"
            f" (learning-ready {journal['learning_ready_count']})"
        )
    rsc = payload.get("reactor_self_check", {}) or {}
    lines.append(
        f"Reactor self-check     : available={rsc.get('available', False)},"
        f" state={rsc.get('reactor_state', 'INSUFFICIENT_DATA')},"
        f" invariants_ok={rsc.get('safety_invariants_ok', False)}"
    )
    if payload.get("outcome_distribution"):
        lines.append("Outcome distribution:")
        for k, v in sorted(payload["outcome_distribution"].items()):
            lines.append(f"  - {k}: {v}")
    if payload.get("missing_decision_fields"):
        lines.append("Reactor-at-decision fields NOT persisted yet:")
        for f in payload["missing_decision_fields"]:
            lines.append(f"  - {f}")
    if payload.get("limitations"):
        lines.append("Limitations:")
        for lim in payload["limitations"]:
            lines.append(f"  - {lim}")
    lines.append("Non-claims (what this report CANNOT honestly say):")
    for nc in payload.get("non_claims", []):
        lines.append(f"  - {nc}")
    lines.append("")
    lines.append(payload["advisory_disclaimer"])
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reactor_calibration_report.py",
        description=(
            "Read-only honest readout of reactor-vs-outcome calibration "
            "evidence.  Never grants execution permission."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    payload = build_report(db_path)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload.get("db_available", False) else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "ADVISORY_DISCLAIMER",
    "VERY_LOW_THRESHOLD",
    "LOW_THRESHOLD",
    "MEDIUM_THRESHOLD",
    "REACTOR_DECISION_FIELDS",
    "build_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
