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
    python scripts/self_test_report.py --days 30 --json
    python scripts/self_test_report.py --period monthly --json
    python scripts/self_test_report.py --include-reconciliation-queue --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    return any(r[1] == column for r in rows)


def _journal_quality_average(conn: sqlite3.Connection) -> dict[str, Any]:
    empty = {
        "trade_count_considered": 0,
        "average_completeness": 0.0,
        "average_learning_readiness": 0.0,
        "learning_ready_count": 0,
        "missing_field_distribution": {},
        "emotional_state_distribution": {},
        "confidence_before_count": 0,
        "confidence_before_average": None,
        "mistake_tags_distribution": {},
        "lesson_count": 0,
        "available": False,
    }
    if not _table_exists(conn, "manual_trades"):
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

    # Build a SELECT list that tolerates DBs that haven't had the additive
    # migration applied yet — we only pull a column when it exists.
    cols_present = {
        "invalidation_level": _column_exists(conn, "manual_trades", "invalidation_level"),
        "expected_horizon": _column_exists(conn, "manual_trades", "expected_horizon"),
        "risk_reason": _column_exists(conn, "manual_trades", "risk_reason"),
        "entry_reason": _column_exists(conn, "manual_trades", "entry_reason"),
        "exit_plan": _column_exists(conn, "manual_trades", "exit_plan"),
        "confidence_before": _column_exists(conn, "manual_trades", "confidence_before"),
        "emotional_state": _column_exists(conn, "manual_trades", "emotional_state"),
        "mistake_tags": _column_exists(conn, "manual_trades", "mistake_tags"),
        "lesson": _column_exists(conn, "manual_trades", "lesson"),
    }
    select_cols = ["trade_id", "event_id", "ticker", "side", "quantity", "thesis", "notes"]
    for c, present in cols_present.items():
        if present:
            select_cols.append(c)

    try:
        trade_rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM manual_trades"  # noqa: S608
        ).fetchall()
    except sqlite3.Error:
        return empty

    entries: list[dict[str, Any]] = []
    emotional_state_dist: dict[str, int] = {}
    mistake_tag_dist: dict[str, int] = {}
    confidence_values: list[float] = []
    lesson_count = 0

    for row in trade_rows:
        trade_id = row["trade_id"]
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

        # Per-row journal-quality fields, defaulting to legacy "no value"
        # when the additive migration hasn't been run.
        def _get(name: str, default: Any = "") -> Any:
            if cols_present.get(name):
                try:
                    return row[name]
                except (IndexError, KeyError):
                    return default
            return default

        mistake_tag_raw = str(_get("mistake_tags", "") or "")
        # mistake_tags is stored as comma-separated string; split for the dist.
        mistake_tags_list: list[str] = []
        if mistake_tag_raw:
            for tag in mistake_tag_raw.split(","):
                t = tag.strip()
                if t:
                    mistake_tags_list.append(t)
                    mistake_tag_dist[t] = mistake_tag_dist.get(t, 0) + 1

        emotional_state = str(_get("emotional_state", "") or "")
        if emotional_state:
            emotional_state_dist[emotional_state] = (
                emotional_state_dist.get(emotional_state, 0) + 1
            )

        conf_raw = _get("confidence_before", None)
        if isinstance(conf_raw, (int, float)) and not isinstance(conf_raw, bool):
            try:
                if conf_raw == conf_raw:  # NaN guard
                    confidence_values.append(float(conf_raw))
            except (TypeError, ValueError):
                pass

        lesson_text = str(_get("lesson", "") or "")
        if lesson_text.strip():
            lesson_count += 1

        entries.append(
            {
                "signal_id": str(row["event_id"] or ""),
                "thesis": str(row["thesis"] or ""),
                "invalidation_level": str(_get("invalidation_level", "") or ""),
                "expected_horizon": str(_get("expected_horizon", "") or ""),
                "position_size": float(row["quantity"] or 0.0),
                "risk_reason": str(_get("risk_reason", "") or ""),
                "entry_reason": str(_get("entry_reason", "") or ""),
                "exit_plan": str(_get("exit_plan", "") or ""),
                "confidence_before": conf_raw,
                "emotional_state": emotional_state,
                "post_trade_outcome": outcome,
                "reconciliation_status": reconciliation_status,
                "mistake_tags": mistake_tags_list,
                "lesson": lesson_text,
            }
        )

    # Compute per-row scoring once so we can roll up missing-field distribution.
    missing_dist: dict[str, int] = {}
    for entry in entries:
        per = score_journal_entry(entry)
        for field in per.get("missing_fields", []):
            missing_dist[field] = missing_dist.get(field, 0) + 1

    agg = score_journal_entries(entries)
    confidence_avg: float | None = (
        sum(confidence_values) / len(confidence_values) if confidence_values else None
    )

    return {
        "trade_count_considered": int(agg.get("entry_count", 0)),
        "average_completeness": float(agg.get("average_completeness", 0.0)),
        "average_learning_readiness": float(
            agg.get("average_learning_readiness", 0.0)
        ),
        "learning_ready_count": int(agg.get("learning_ready_count", 0)),
        "factor_pass_rates": dict(agg.get("factor_pass_rates", {})),
        "missing_field_distribution": missing_dist,
        "emotional_state_distribution": emotional_state_dist,
        "mistake_tags_distribution": mistake_tag_dist,
        "confidence_before_count": len(confidence_values),
        "confidence_before_average": (
            round(confidence_avg, 6) if confidence_avg is not None else None
        ),
        "lesson_count": lesson_count,
        "available": True,
    }


def _reconciliation_extended_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Outcome-quality / process-error distributions from reconciliation_results."""
    empty = {
        "outcome_quality_distribution": {},
        "process_error_distribution": {},
        "available": False,
    }
    if not _table_exists(conn, "reconciliation_results"):
        return empty
    has_oq = _column_exists(conn, "reconciliation_results", "outcome_quality")
    has_pe = _column_exists(conn, "reconciliation_results", "process_error")
    if not (has_oq or has_pe):
        return empty
    out: dict[str, Any] = {
        "outcome_quality_distribution": {},
        "process_error_distribution": {},
        "available": True,
    }
    try:
        if has_oq:
            rows = conn.execute(
                "SELECT outcome_quality AS k, COUNT(*) AS n"
                " FROM reconciliation_results"
                " WHERE outcome_quality IS NOT NULL AND outcome_quality != ''"
                " GROUP BY outcome_quality"
            ).fetchall()
            out["outcome_quality_distribution"] = {
                str(r["k"]): int(r["n"]) for r in rows
            }
        if has_pe:
            rows = conn.execute(
                "SELECT process_error AS k, COUNT(*) AS n"
                " FROM reconciliation_results"
                " WHERE process_error IS NOT NULL AND process_error != ''"
                " GROUP BY process_error"
            ).fetchall()
            out["process_error_distribution"] = {
                str(r["k"]): int(r["n"]) for r in rows
            }
    except sqlite3.Error:
        pass
    return out


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


def _reactor_self_check() -> dict[str, Any]:
    """Deterministic, data-free check that the signal reactor is healthy.

    Runs the reactor on a synthetic empty cluster (which legitimately yields
    COLD_OBSERVE) and confirms the returned payload still carries the
    canonical safety invariants.  Pure: no DB read, no live API.

    Returns
    -------
    dict with
        available : bool                — reactor module importable & callable
        reactor_state : str             — reactor's reported state on synth input
        recommendation : str            — reactor's recommendation
        safety_invariants_ok : bool     — all safety stamps survived intact
        import_error : str | None
    """
    out: dict[str, Any] = {
        "available": False,
        "reactor_state": "INSUFFICIENT_DATA",
        "recommendation": "observe",
        "safety_invariants_ok": False,
        "import_error": None,
    }
    try:
        try:
            from scripts.signal_reactor import evaluate_signal_reactor  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from signal_reactor import evaluate_signal_reactor  # type: ignore[no-redef]
    except Exception as exc:
        out["import_error"] = f"{type(exc).__name__}: {exc}"
        return out

    try:
        payload = evaluate_signal_reactor([])
    except Exception as exc:
        out["import_error"] = f"evaluate_failed:{type(exc).__name__}: {exc}"
        return out
    if not isinstance(payload, dict):
        out["import_error"] = "reactor_returned_non_dict"
        return out

    safety = payload.get("safety") or {}
    invariants_ok = (
        payload.get("advisory_status") == "ADVISORY_ONLY"
        and payload.get("execution_gate") == "LOCKED"
        and safety.get("broker_api_called") is False
        and safety.get("ai_execution_count") == 0
        and safety.get("execution_permission") is False
        and safety.get("can_execute") is False
    )
    out["available"] = True
    out["reactor_state"] = str(payload.get("signal_reactor_state") or "INSUFFICIENT_DATA")
    out["recommendation"] = str(payload.get("recommendation") or "observe")
    out["safety_invariants_ok"] = bool(invariants_ok)
    return out


def _geometry_reflection_self_check() -> dict[str, Any]:
    """Deterministic, data-free check that the geometry-reflection layer
    is importable and that its safety contract still holds.

    Pure: no DB read, no live API.
    """
    out: dict[str, Any] = {
        "available": False,
        "recommendation": "observe",
        "safety_invariants_ok": False,
        "import_error": None,
        "vetoes_on_empty_cluster": [],
    }
    try:
        try:
            from scripts.signal_geometry_reflection import (  # type: ignore[import-not-found]
                build_signal_geometry_diagnostics,
            )
        except ModuleNotFoundError:
            from signal_geometry_reflection import (  # type: ignore[no-redef]
                build_signal_geometry_diagnostics,
            )
    except Exception as exc:
        out["import_error"] = f"{type(exc).__name__}: {exc}"
        return out

    try:
        payload = build_signal_geometry_diagnostics([])
    except Exception as exc:
        out["import_error"] = f"evaluate_failed:{type(exc).__name__}: {exc}"
        return out
    if not isinstance(payload, dict):
        out["import_error"] = "geometry_returned_non_dict"
        return out

    safety = payload.get("safety") or {}
    invariants_ok = (
        payload.get("advisory_status") == "ADVISORY_ONLY"
        and payload.get("execution_gate") == "LOCKED"
        and safety.get("broker_api_called") is False
        and safety.get("ai_execution_count") == 0
        and safety.get("execution_permission") is False
        and safety.get("can_execute") is False
        and safety.get("broker_order_id") == "NONE"
        and safety.get("human_review_required") is True
    )
    out["available"] = True
    out["recommendation"] = str(payload.get("recommendation") or "observe")
    out["safety_invariants_ok"] = bool(invariants_ok)
    out["vetoes_on_empty_cluster"] = list(payload.get("vetoes") or [])
    out["canonical_truth_source"] = payload.get("canonical_truth_source")
    out["jsonl_role"] = payload.get("jsonl_role")
    return out


def _complex_systems_self_check() -> dict[str, Any]:
    """Deterministic, data-free check that the complex-systems doctrine
    layer is importable and that its safety contract still holds.

    Pure: no DB read, no live API.
    """
    out: dict[str, Any] = {
        "available": False,
        "advisory_decision_bias": "insufficient_data",
        "safety_invariants_ok": False,
        "import_error": None,
        "doctrine": None,
    }
    try:
        try:
            from scripts.complex_systems_diagnostics import (  # type: ignore[import-not-found]
                build_complex_systems_diagnostics,
            )
        except ModuleNotFoundError:
            from complex_systems_diagnostics import (  # type: ignore[no-redef]
                build_complex_systems_diagnostics,
            )
    except Exception as exc:
        out["import_error"] = f"{type(exc).__name__}: {exc}"
        return out

    try:
        payload = build_complex_systems_diagnostics([])
    except Exception as exc:
        out["import_error"] = f"evaluate_failed:{type(exc).__name__}: {exc}"
        return out
    if not isinstance(payload, dict):
        out["import_error"] = "complex_systems_returned_non_dict"
        return out

    safety = payload.get("safety") or {}
    invariants_ok = (
        payload.get("advisory_status") == "ADVISORY_ONLY"
        and payload.get("execution_gate") == "LOCKED"
        and safety.get("broker_api_called") is False
        and safety.get("ai_execution_count") == 0
        and safety.get("execution_permission") is False
        and safety.get("can_execute") is False
        and safety.get("broker_order_id") == "NONE"
        and safety.get("human_review_required") is True
    )
    out["available"] = True
    out["advisory_decision_bias"] = str(
        payload.get("advisory_decision_bias") or "insufficient_data"
    )
    out["safety_invariants_ok"] = bool(invariants_ok)
    out["doctrine"] = payload.get("doctrine")
    out["canonical_truth_source"] = payload.get("canonical_truth_source")
    out["jsonl_role"] = payload.get("jsonl_role")
    return out


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


def _period_window(
    days: int | None, period: str | None, now: _dt.datetime | None = None,
) -> tuple[_dt.datetime | None, _dt.datetime | None]:
    """Resolve --days / --period into (start, end) inclusive datetimes.

    Returns ``(None, None)`` when no filter was requested.
    """
    if not days and not period:
        return None, None
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if not days and period:
        days = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}.get(
            period.lower(), 30
        )
    days = max(1, int(days or 30))
    start = now - _dt.timedelta(days=days)
    return start, now


def _period_count(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    start: _dt.datetime,
    end: _dt.datetime,
) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608
            f" WHERE {column} >= ? AND {column} <= ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"]) if row else 0


def _period_unreconciled(
    conn: sqlite3.Connection, start: _dt.datetime, end: _dt.datetime
) -> int:
    if not _table_exists(conn, "manual_trades"):
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM manual_trades mt"
            " WHERE mt.executed_at >= ? AND mt.executed_at <= ?"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM reconciliation_results rr"
            "   WHERE rr.trade_id = mt.trade_id"
            " )",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"]) if row else 0


def _build_process_quality_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Roll up process_quality_classifier across all reconciled trades.

    The classifier is pure; this helper just gathers inputs from the DB
    and feeds them in. Returns ``available=False`` if the classifier or
    required tables are unavailable.
    """
    empty = {"available": False}
    if not _table_exists(conn, "manual_trades") or not _table_exists(
        conn, "reconciliation_results"
    ):
        return empty
    try:
        try:
            from scripts.process_quality_classifier import (  # type: ignore[import-not-found]
                aggregate,
            )
            from scripts.self_test_journal_quality import (  # type: ignore[import-not-found]
                score_journal_entry,
            )
        except ModuleNotFoundError:
            from process_quality_classifier import aggregate  # type: ignore[no-redef]
            from self_test_journal_quality import (  # type: ignore[no-redef]
                score_journal_entry,
            )
    except Exception:
        return empty

    cols_present = {
        c: _column_exists(conn, "manual_trades", c)
        for c in (
            "invalidation_level", "expected_horizon", "risk_reason",
            "entry_reason", "exit_plan", "confidence_before",
            "emotional_state", "mistake_tags", "lesson",
        )
    }
    select_cols = ["mt.trade_id", "mt.event_id", "mt.ticker", "mt.side",
                   "mt.quantity", "mt.thesis"]
    for c, present in cols_present.items():
        if present:
            select_cols.append(f"mt.{c}")
    has_outcome_quality = _column_exists(
        conn, "reconciliation_results", "outcome_quality"
    )
    has_process_error = _column_exists(
        conn, "reconciliation_results", "process_error"
    )
    has_process_error_notes = _column_exists(
        conn, "reconciliation_results", "process_error_notes"
    )
    recon_cols = ["rr.outcome_status", "rr.outcome_notes"]
    if has_outcome_quality:
        recon_cols.append("rr.outcome_quality")
    if has_process_error:
        recon_cols.append("rr.process_error")
    if has_process_error_notes:
        recon_cols.append("rr.process_error_notes")

    select_clause = ", ".join(select_cols + recon_cols)

    try:
        rows = conn.execute(
            f"SELECT {select_clause}"  # noqa: S608
            " FROM manual_trades mt"
            " INNER JOIN reconciliation_results rr ON rr.trade_id = mt.trade_id"
        ).fetchall()
    except sqlite3.Error:
        return empty

    records: list[dict[str, Any]] = []
    for row in rows:
        row_dict = {k: row[k] for k in row.keys()}
        entry = {
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
        quality = score_journal_entry(entry)
        rec = {
            "outcome_status": row_dict.get("outcome_status"),
            "process_error": row_dict.get("process_error"),
            "process_error_notes": row_dict.get("process_error_notes"),
            "journal_completeness_score": quality.get(
                "journal_completeness_score", 0.0
            ),
            "learning_ready": quality.get("learning_ready", False),
            "thesis": entry["thesis"],
            "invalidation_level": entry["invalidation_level"],
            "exit_plan": entry["exit_plan"],
            "risk_reason": entry["risk_reason"],
        }
        records.append(rec)

    agg = aggregate(records)
    agg["available"] = True
    return agg


def build_report(
    db_path: Path | None = None,
    *,
    days: int | None = None,
    period: str | None = None,
    include_reconciliation_queue: bool = False,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Build the report dict. Read-only; never raises.

    Parameters
    ----------
    db_path : Path | None
        DB to inspect.
    days : int | None
        If set, include period_* metrics covering the last ``days`` days.
    period : str | None
        Convenience alias for days: 'daily'(1) / 'weekly'(7) / 'monthly'(30)
        / 'quarterly'(90).  Overridden by an explicit ``days``.
    include_reconciliation_queue : bool
        Embed the full reconciliation queue summary (read-only).
    now : datetime | None
        Override the current time for deterministic tests.
    """
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
        reconciliation_extended = _reconciliation_extended_summary(conn)
        process_quality = _build_process_quality_summary(conn)
        reactor_self_check = _reactor_self_check()
        geometry_reflection_self_check = _geometry_reflection_self_check()
        complex_systems_self_check = _complex_systems_self_check()

        period_start, period_end = _period_window(days, period, now=now)
        period_payload: dict[str, Any] | None = None
        if period_start and period_end:
            period_payload = {
                "period_start": period_start.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "period_end": period_end.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "days": int((period_end - period_start).total_seconds() // 86400),
                "trades_logged_in_period": _period_count(
                    conn, "manual_trades", "executed_at", period_start, period_end
                ),
                "reconciled_in_period": _period_count(
                    conn,
                    "reconciliation_results",
                    "reconciled_at",
                    period_start,
                    period_end,
                ),
                "unreconciled_in_period": _period_unreconciled(
                    conn, period_start, period_end
                ),
            }
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
    if not reactor_self_check.get("available"):
        limitations.append("signal_reactor_unavailable")
    elif not reactor_self_check.get("safety_invariants_ok"):
        limitations.append("signal_reactor_safety_invariant_failed")
    if not geometry_reflection_self_check.get("available"):
        limitations.append("signal_geometry_reflection_unavailable")
    elif not geometry_reflection_self_check.get("safety_invariants_ok"):
        limitations.append("signal_geometry_reflection_safety_invariant_failed")
    if not complex_systems_self_check.get("available"):
        limitations.append("complex_systems_diagnostics_unavailable")
    elif not complex_systems_self_check.get("safety_invariants_ok"):
        limitations.append("complex_systems_diagnostics_safety_invariant_failed")
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
        "reconciliation_extended": reconciliation_extended,
        "signal_decision_distribution": decisions,
        "moltbook": moltbook,
        "source_health": source_health,
        "ai_validation_distribution": ai_validation,
        "journal_quality": journal_quality,
        "process_quality": process_quality,
        "reactor_self_check": reactor_self_check,
        "geometry_reflection_self_check": geometry_reflection_self_check,
        "complex_systems_self_check": complex_systems_self_check,
        "limitations": limitations,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
    }
    if period_payload is not None:
        report["period"] = period_payload
    if include_reconciliation_queue:
        try:
            try:
                from scripts.reconciliation_queue import build_queue  # type: ignore[import-not-found]
            except ModuleNotFoundError:
                from reconciliation_queue import build_queue  # type: ignore[no-redef]
            queue_payload = build_queue(db_path, limit=50, now=now)
            report["reconciliation_queue"] = {
                "summary": queue_payload.get("summary", {}),
                "items": queue_payload.get("items", []),
                "operator_action": queue_payload.get("operator_action", ""),
                "warnings": queue_payload.get("warnings", []),
                "truncated": queue_payload.get("truncated", False),
                "truncated_to": queue_payload.get("truncated_to"),
            }
        except Exception:
            limitations.append("reconciliation_queue_helper_unavailable")
    report.update(_SAFETY_STAMPS)
    return report


def build_self_test_summary(db_path: Path | None = None) -> dict[str, Any]:
    """Compact dashboard-friendly summary derived from build_report().

    The full ``build_report`` payload is rich but verbose.  The dashboard
    panel only needs a handful of headline metrics — this helper computes
    them in one place so the API endpoint and any future frontend share the
    same source of truth.
    """
    report = build_report(db_path)
    journal = report.get("journal_quality", {}) or {}
    reconciliation = report.get("reconciliation", {}) or {}
    extended = report.get("reconciliation_extended", {}) or {}
    ai_validation = report.get("ai_validation_distribution", {}) or {}
    reactor = report.get("reactor_self_check", {}) or {}
    geometry = report.get("geometry_reflection_self_check", {}) or {}

    incomplete_journal_count = (
        int(journal.get("trade_count_considered", 0))
        - int(journal.get("learning_ready_count", 0))
    )
    if incomplete_journal_count < 0:
        incomplete_journal_count = 0

    summary = {
        "report": "self_test_summary",
        "db_path": report.get("db_path"),
        "db_available": report.get("db_available", False),
        "signals_reviewed_count": report.get("signals_reviewed_count", 0),
        "manual_trades_logged_count": report.get("manual_trades_count", 0),
        "reconciled_trades_count": reconciliation.get("reconciled_count", 0),
        "unreconciled_trades_count": report.get("unreconciled_trades_count", 0),
        "average_journal_completeness": float(
            journal.get("average_completeness", 0.0)
        ),
        "average_learning_readiness": float(
            journal.get("average_learning_readiness", 0.0)
        ),
        "learning_ready_count": int(journal.get("learning_ready_count", 0)),
        "incomplete_journal_count": incomplete_journal_count,
        "emotional_state_distribution": dict(
            journal.get("emotional_state_distribution", {})
        ),
        "mistake_tags_distribution": dict(
            journal.get("mistake_tags_distribution", {})
        ),
        "missing_field_distribution": dict(
            journal.get("missing_field_distribution", {})
        ),
        "confidence_before_average": journal.get("confidence_before_average"),
        "lesson_count": int(journal.get("lesson_count", 0)),
        "outcome_quality_distribution": dict(
            extended.get("outcome_quality_distribution", {})
        ),
        "process_error_distribution": dict(
            extended.get("process_error_distribution", {})
        ),
        "ai_validation_distribution": dict(ai_validation.get("counts", {})),
        "reactor_available": bool(reactor.get("available", False)),
        "reactor_state": str(reactor.get("reactor_state", "INSUFFICIENT_DATA")),
        "reactor_safety_invariants_ok": bool(
            reactor.get("safety_invariants_ok", False)
        ),
        "geometry_reflection_available": bool(geometry.get("available", False)),
        "geometry_reflection_recommendation": str(
            geometry.get("recommendation", "observe")
        ),
        "geometry_reflection_safety_invariants_ok": bool(
            geometry.get("safety_invariants_ok", False)
        ),
        "limitations": list(report.get("limitations", [])),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
    }
    summary.update(_SAFETY_STAMPS)
    return summary


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
        lines.append(f"- Lessons recorded: **{jq.get('lesson_count', 0)}**")
        if jq.get("confidence_before_average") is not None:
            lines.append(
                f"- Confidence-before avg: **{jq['confidence_before_average']:.3f}** "
                f"across {jq.get('confidence_before_count', 0)} record(s)"
            )
        if jq.get("factor_pass_rates"):
            lines.append("- Factor pass rates:")
            for k, v in sorted(jq["factor_pass_rates"].items()):
                lines.append(f"  - {k}: {v:.3f}")
        if jq.get("missing_field_distribution"):
            lines.append("- Most-missing fields:")
            for k, v in sorted(
                jq["missing_field_distribution"].items(),
                key=lambda kv: -kv[1],
            )[:8]:
                lines.append(f"  - {k}: {v}")
        if jq.get("emotional_state_distribution"):
            lines.append("- Emotional-state distribution:")
            for k, v in sorted(jq["emotional_state_distribution"].items()):
                lines.append(f"  - {k}: {v}")
        if jq.get("mistake_tags_distribution"):
            lines.append("- Mistake-tag distribution:")
            for k, v in sorted(
                jq["mistake_tags_distribution"].items(),
                key=lambda kv: -kv[1],
            )[:10]:
                lines.append(f"  - {k}: {v}")
        lines.append("")
    rext = report.get("reconciliation_extended", {})
    if rext.get("available"):
        oq = rext.get("outcome_quality_distribution", {})
        pe = rext.get("process_error_distribution", {})
        if oq or pe:
            lines.append("## Reconciliation — Attribution")
            lines.append("")
            if oq:
                lines.append("- Outcome quality distribution:")
                for k, v in sorted(oq.items()):
                    lines.append(f"  - {k}: {v}")
            if pe:
                lines.append("- Process-error distribution:")
                for k, v in sorted(pe.items()):
                    lines.append(f"  - {k}: {v}")
            lines.append("")
    rc = report.get("reactor_self_check", {}) or {}
    if rc:
        lines.append("## Signal Reactor Self-Check")
        lines.append("")
        lines.append(f"- Available: **{rc.get('available', False)}**")
        lines.append(
            f"- Synthetic run reactor_state: **{rc.get('reactor_state', 'INSUFFICIENT_DATA')}**"
        )
        lines.append(f"- Recommendation: **{rc.get('recommendation', 'observe')}**")
        lines.append(
            f"- Safety invariants OK: **{rc.get('safety_invariants_ok', False)}**"
        )
        if rc.get("import_error"):
            lines.append(f"- Import error: `{rc['import_error']}`")
        lines.append("")
    gr = report.get("geometry_reflection_self_check", {}) or {}
    if gr:
        lines.append("## Signal Geometry Reflection Self-Check")
        lines.append("")
        lines.append(f"- Available: **{gr.get('available', False)}**")
        lines.append(
            f"- Recommendation on empty cluster: **{gr.get('recommendation', 'observe')}**"
        )
        lines.append(
            f"- Safety invariants OK: **{gr.get('safety_invariants_ok', False)}**"
        )
        lines.append(
            f"- Canonical truth source: `{gr.get('canonical_truth_source', 'sqlite')}`"
        )
        lines.append(
            f"- JSONL role: `{gr.get('jsonl_role', 'audit_fallback_only')}`"
        )
        if gr.get("import_error"):
            lines.append(f"- Import error: `{gr['import_error']}`")
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
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help="Include period_* metrics covering the last N days.",
    )
    p.add_argument(
        "--period",
        type=str,
        choices=("daily", "weekly", "monthly", "quarterly"),
        default=None,
        help="Convenience for --days (daily=1, weekly=7, monthly=30, quarterly=90).",
    )
    p.add_argument(
        "--include-reconciliation-queue",
        action="store_true",
        help="Embed the reconciliation queue summary into the report.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    report = build_report(
        db_path,
        days=args.days,
        period=args.period,
        include_reconciliation_queue=args.include_reconciliation_queue,
    )

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
    "build_self_test_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
