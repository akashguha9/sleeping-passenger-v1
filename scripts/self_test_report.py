"""
Local self-test evidence report.

Purpose
-------
Read SQLite from ``runtime/mvp_local.db`` and produce a single rollup
report summarizing what the operator's self-test looks like to date.

This script is **read-only**, refuses to call any broker API, never
executes anything, and labels manually-entered PnL as such.

It answers four questions the operator should be able to ask any day:

1. How many signals have I reviewed? How many did I mark for review,
   reject, or watch-list?
2. How many manual trades have I logged? How many have been reconciled?
3. What does my AI validation distribution look like? Are most payloads
   valid, partial, or invalid?
4. What does my Moltbook learning loop look like? How many lessons have
   I logged? What are the dominant mistake types?

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False
    pnl_source             = "operator_entered_manual_only"  (when applicable)

Usage
-----
    python scripts/self_test_report.py
    python scripts/self_test_report.py --json
    python scripts/self_test_report.py --db-path runtime/mvp_local.db
    python scripts/self_test_report.py --markdown docs/SELF_TEST_REPORT.md
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

ADVISORY_DISCLAIMER = (
    "This report is advisory-only. The MVP did not place any trades. All "
    "PnL values, if present, are operator-entered manual records — they "
    "have not been verified against a broker."
)

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


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
    """Open a read-only connection. Returns None on failure."""
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


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"]) if row else 0


def _group_count(
    conn: sqlite3.Connection, table: str, column: str
) -> dict[str, int]:
    if not _table_exists(conn, table):
        return {}
    try:
        rows = conn.execute(
            f"SELECT {column} AS k, COUNT(*) AS n FROM {table} GROUP BY {column}"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(r["k"] or "UNKNOWN"): int(r["n"]) for r in rows}


def _signal_decision_distribution(conn: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(conn, "signal_decisions"):
        return {}
    try:
        rows = conn.execute(
            "SELECT user_status AS k, COUNT(*) AS n FROM signal_decisions"
            " WHERE id IN (SELECT MAX(id) FROM signal_decisions GROUP BY event_id)"
            " GROUP BY user_status"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(r["k"] or "UNKNOWN"): int(r["n"]) for r in rows}


def _reconciliation_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "reconciled_count": _safe_count(conn, "reconciliation_results"),
        "outcome_distribution": _group_count(
            conn, "reconciliation_results", "outcome_status"
        ),
        "operator_entered_pnl_sum": None,
        "operator_entered_pnl_count": 0,
        "pnl_source": "operator_entered_manual_only",
    }
    if _table_exists(conn, "reconciliation_results"):
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_estimate), 0) AS s,"
                " COUNT(pnl_estimate) AS n"
                " FROM reconciliation_results"
            ).fetchone()
            if row:
                summary["operator_entered_pnl_sum"] = float(row["s"] or 0.0)
                summary["operator_entered_pnl_count"] = int(row["n"] or 0)
        except sqlite3.Error:
            pass
    return summary


def _unreconciled_count(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "manual_trades"):
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM manual_trades mt"
            " WHERE NOT EXISTS ("
            "   SELECT 1 FROM reconciliation_results rr"
            "   WHERE rr.trade_id = mt.trade_id"
            " )"
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"]) if row else 0


def _journal_quality_average(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "manual_trades"):
        return {
            "trade_count_considered": 0,
            "average_completeness": 0.0,
            "average_learning_readiness": 0.0,
            "learning_ready_count": 0,
            "available": False,
        }
    try:
        try:
            from scripts.self_test_journal_quality import (  # type: ignore[import-not-found]
                score_journal_entries,
            )
        except ModuleNotFoundError:
            from self_test_journal_quality import (  # type: ignore[no-redef]
                score_journal_entries,
            )
    except Exception:
        return {
            "trade_count_considered": 0,
            "average_completeness": 0.0,
            "average_learning_readiness": 0.0,
            "learning_ready_count": 0,
            "available": False,
        }

    try:
        trade_rows = conn.execute(
            "SELECT trade_id, event_id, ticker, side, quantity, thesis, notes"
            " FROM manual_trades"
        ).fetchall()
    except sqlite3.Error:
        return {
            "trade_count_considered": 0,
            "average_completeness": 0.0,
            "average_learning_readiness": 0.0,
            "learning_ready_count": 0,
            "available": False,
        }

    entries: list[dict[str, Any]] = []
    for row in trade_rows:
        trade_id = row["trade_id"]
        # Pull a reconciliation (most recent) and a moltbook entry for this trade
        outcome = ""
        reconciliation_status = ""
        try:
            rec = conn.execute(
                "SELECT outcome_status, outcome_notes FROM reconciliation_results"
                " WHERE trade_id=? ORDER BY reconciled_at DESC LIMIT 1",
                (trade_id,),
            ).fetchone()
            if rec:
                outcome = str(rec["outcome_notes"] or "")
                reconciliation_status = str(rec["outcome_status"] or "")
        except sqlite3.Error:
            pass
        lesson = ""
        mistake_tags: list[str] = []
        try:
            molt = conn.execute(
                "SELECT lesson_learned, mistake_type FROM moltbook_entries"
                " WHERE manual_trade_log_id=? ORDER BY logged_at DESC LIMIT 1",
                (trade_id,),
            ).fetchone()
            if molt:
                lesson = str(molt["lesson_learned"] or "")
                mistake_type = str(molt["mistake_type"] or "")
                if mistake_type:
                    mistake_tags = [mistake_type]
        except sqlite3.Error:
            pass

        entries.append(
            {
                "signal_id": str(row["event_id"] or ""),
                "thesis": str(row["thesis"] or ""),
                "invalidation_level": "",  # not tracked in current schema
                "expected_horizon": "",
                "position_size": float(row["quantity"] or 0.0),
                "risk_reason": "",
                "entry_reason": "",
                "exit_plan": "",
                "post_trade_outcome": outcome,
                "reconciliation_status": reconciliation_status,
                "mistake_tags": mistake_tags,
                "lesson": lesson,
            }
        )

    agg = score_journal_entries(entries)
    return {
        "trade_count_considered": int(agg.get("entry_count", 0)),
        "average_completeness": float(agg.get("average_completeness", 0.0)),
        "average_learning_readiness": float(
            agg.get("average_learning_readiness", 0.0)
        ),
        "learning_ready_count": int(agg.get("learning_ready_count", 0)),
        "factor_pass_rates": dict(agg.get("factor_pass_rates", {})),
        "available": True,
    }


def _source_health_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "source_run_log"):
        return {"available": False}
    try:
        rows = conn.execute(
            "SELECT srl.source_name, srl.status, srl.fetched_count,"
            "       srl.skipped_reason, srl.error_message,"
            "       srl.timestamp_utc, srl.duration_ms"
            " FROM source_run_log srl"
            " INNER JOIN ("
            "    SELECT source_name, MAX(id) AS max_id"
            "    FROM source_run_log GROUP BY source_name"
            " ) latest ON latest.source_name = srl.source_name"
            "          AND latest.max_id = srl.id"
            " ORDER BY srl.timestamp_utc DESC"
        ).fetchall()
    except sqlite3.Error:
        return {"available": False}
    return {
        "available": True,
        "per_source": [
            {
                "source_name": str(r["source_name"]),
                "status": str(r["status"]),
                "fetched_count": int(r["fetched_count"] or 0),
                "skipped_reason": str(r["skipped_reason"] or ""),
                "error_message": str(r["error_message"] or ""),
                "timestamp_utc": str(r["timestamp_utc"] or ""),
                "duration_ms": int(r["duration_ms"] or 0),
            }
            for r in rows
        ],
    }


def _ai_validation_distribution(conn: sqlite3.Connection) -> dict[str, Any]:
    """Try to estimate AI validation distribution from JSONL backup logs.

    The current SQLite schema does not store validation_status, so this is
    best-effort: it returns ``available=False`` if the JSONL log is absent.
    """
    log_path = Path(__file__).resolve().parents[1] / "logs" / "ai_discussion_summaries.jsonl"
    if not log_path.exists():
        return {"available": False, "counts": {}, "total": 0}
    counts: dict[str, int] = {}
    total = 0
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            total += 1
            status = str(obj.get("validation_status") or "unspecified")
            counts[status] = counts.get(status, 0) + 1
    except OSError:
        return {"available": False, "counts": {}, "total": 0}
    return {"available": True, "counts": counts, "total": total}


def _moltbook_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "moltbook_entries"):
        return {"available": False}
    counts = _group_count(conn, "moltbook_entries", "mistake_type")
    total = sum(counts.values())
    return {
        "available": True,
        "total_entries": total,
        "mistake_type_distribution": counts,
    }


def build_report(db_path: Path | None = None) -> dict[str, Any]:
    """Build the report dict. Read-only; never raises."""
    db_path = Path(db_path) if db_path else _default_db_path()
    limitations: list[str] = []

    if not db_path.exists():
        report: dict[str, Any] = {
            "report": "self_test_evidence",
            "db_path": str(db_path),
            "db_available": False,
            "limitations": [
                "db_missing",
                "no_signals_logged_yet",
                "no_trades_logged_yet",
                "no_reflections_logged_yet",
            ],
            "advisory_disclaimer": ADVISORY_DISCLAIMER,
        }
        report.update(_SAFETY_STAMPS)
        return report

    conn = _readonly_connect(db_path)
    if conn is None:
        report = {
            "report": "self_test_evidence",
            "db_path": str(db_path),
            "db_available": False,
            "limitations": ["db_open_failed"],
            "advisory_disclaimer": ADVISORY_DISCLAIMER,
        }
        report.update(_SAFETY_STAMPS)
        return report

    try:
        signals_reviewed = _safe_count(conn, "signal_events")
        decisions = _signal_decision_distribution(conn)
        manual_trades = _safe_count(conn, "manual_trades")
        reconciliation = _reconciliation_summary(conn)
        unreconciled = _unreconciled_count(conn)
        reflections = _safe_count(conn, "user_reflections")
        ai_summaries = _safe_count(conn, "ai_discussion_summaries")
        moltbook = _moltbook_summary(conn)
        source_health = _source_health_summary(conn)
        ai_validation = _ai_validation_distribution(conn)
        journal_quality = _journal_quality_average(conn)
    finally:
        conn.close()

    if manual_trades == 0:
        limitations.append("no_manual_trades_logged_yet")
    if reflections == 0:
        limitations.append("no_reflections_logged_yet")
    if reconciliation["reconciled_count"] == 0 and manual_trades > 0:
        limitations.append("no_trades_reconciled_yet")
    if not source_health.get("available"):
        limitations.append("source_health_unavailable")
    if not ai_validation.get("available"):
        limitations.append("ai_validation_jsonl_log_absent")
    if not journal_quality.get("available"):
        limitations.append("journal_quality_helper_unavailable")
    limitations.append("pnl_unverified_by_broker")

    report = {
        "report": "self_test_evidence",
        "db_path": str(db_path),
        "db_available": True,
        "signals_reviewed_count": signals_reviewed,
        "ai_summaries_count": ai_summaries,
        "reflections_count": reflections,
        "manual_trades_count": manual_trades,
        "unreconciled_trades_count": unreconciled,
        "reconciliation": reconciliation,
        "signal_decision_distribution": decisions,
        "moltbook": moltbook,
        "source_health": source_health,
        "ai_validation_distribution": ai_validation,
        "journal_quality": journal_quality,
        "limitations": limitations,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
    }
    report.update(_SAFETY_STAMPS)
    return report


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def _render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Local Self-Test Evidence Report")
    lines.append("")
    lines.append(f"> {ADVISORY_DISCLAIMER}")
    lines.append("")
    lines.append("`advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` · ")
    lines.append("`broker_api_called = false` · `ai_execution_count = 0`")
    lines.append("")
    if not report.get("db_available", False):
        lines.append("## Database")
        lines.append("")
        lines.append(f"- **DB path:** `{report['db_path']}`")
        lines.append("- **Status:** missing or unopenable; no data to summarize.")
        lines.append("")
        lines.append("## Limitations")
        for lim in report.get("limitations", []):
            lines.append(f"- {lim}")
        return "\n".join(lines) + "\n"

    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Signals reviewed: **{report['signals_reviewed_count']}**")
    lines.append(f"- AI summaries logged: **{report['ai_summaries_count']}**")
    lines.append(f"- Reflections logged: **{report['reflections_count']}**")
    lines.append(f"- Manual trades logged: **{report['manual_trades_count']}**")
    lines.append(f"- Unreconciled manual trades: **{report['unreconciled_trades_count']}**")
    lines.append("")
    rec = report["reconciliation"]
    lines.append("## Reconciliation")
    lines.append("")
    lines.append(f"- Reconciled count: **{rec['reconciled_count']}**")
    if rec["outcome_distribution"]:
        lines.append("- Outcome distribution:")
        for key, value in sorted(rec["outcome_distribution"].items()):
            lines.append(f"  - {key}: {value}")
    if rec["operator_entered_pnl_count"]:
        lines.append(
            f"- Operator-entered PnL sum (manual, not broker-verified): "
            f"`{rec['operator_entered_pnl_sum']}` across "
            f"{rec['operator_entered_pnl_count']} records"
        )
    lines.append("")
    if report["signal_decision_distribution"]:
        lines.append("## Signal Decision Distribution")
        lines.append("")
        for k, v in sorted(report["signal_decision_distribution"].items()):
            lines.append(f"- {k}: {v}")
        lines.append("")
    molt = report["moltbook"]
    if molt.get("available"):
        lines.append("## Moltbook")
        lines.append("")
        lines.append(f"- Total entries: **{molt['total_entries']}**")
        if molt["mistake_type_distribution"]:
            lines.append("- Mistake-type distribution:")
            for k, v in sorted(molt["mistake_type_distribution"].items()):
                lines.append(f"  - {k}: {v}")
        lines.append("")
    sh = report["source_health"]
    if sh.get("available"):
        lines.append("## Source Health (latest per source)")
        lines.append("")
        for entry in sh["per_source"]:
            lines.append(
                f"- `{entry['source_name']}`: status={entry['status']}, "
                f"fetched={entry['fetched_count']}, "
                f"reason={entry['skipped_reason'] or '-'}, "
                f"ts={entry['timestamp_utc']}"
            )
        lines.append("")
    av = report["ai_validation_distribution"]
    if av.get("available"):
        lines.append("## AI Validation Distribution (from JSONL log)")
        lines.append("")
        lines.append(f"- Total payloads: **{av['total']}**")
        for k, v in sorted(av["counts"].items()):
            lines.append(f"  - {k}: {v}")
        lines.append("")
    jq = report["journal_quality"]
    if jq.get("available"):
        lines.append("## Journal Quality (manual trades)")
        lines.append("")
        lines.append(f"- Trades considered: **{jq['trade_count_considered']}**")
        lines.append(
            f"- Average completeness: **{jq['average_completeness']:.3f}**"
        )
        lines.append(
            f"- Average learning readiness: **{jq['average_learning_readiness']:.3f}**"
        )
        lines.append(f"- Learning-ready trades: **{jq['learning_ready_count']}**")
        if jq.get("factor_pass_rates"):
            lines.append("- Factor pass rates:")
            for k, v in sorted(jq["factor_pass_rates"].items()):
                lines.append(f"  - {k}: {v:.3f}")
        lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for lim in report.get("limitations", []):
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="self_test_report.py",
        description=(
            "Read-only local self-test evidence report. Never executes; "
            "never calls a broker; never writes the DB."
        ),
    )
    p.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to runtime/mvp_local.db. Defaults to the persistence module value.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    p.add_argument(
        "--markdown",
        type=str,
        default=None,
        help="Also write a Markdown rendering to this path.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    report = build_report(db_path)

    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2, default=str))
    else:
        print(_render_markdown(report))

    if args.markdown:
        try:
            Path(args.markdown).write_text(_render_markdown(report), encoding="utf-8")
        except OSError as exc:
            # Reporting tool must never crash the operator's terminal — log and continue
            print(f"[warn] could not write markdown to {args.markdown}: {exc}")

    return 0 if report.get("db_available", False) else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "ADVISORY_DISCLAIMER",
    "build_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
