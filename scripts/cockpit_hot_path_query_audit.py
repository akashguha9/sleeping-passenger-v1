"""Cockpit hot-path SQLite query/index audit (Kanté Defensive Sprint — Task 2).

Performance moved when the diagnostics snapshot cache landed, but the *proof*
that the cockpit/diagnostics hot-path reads are indexed and bounded was still
weak.  This module supplies that evidence.  It inspects **only** the cockpit /
diagnostics hot paths (not the whole DB) and, for each SQLite query, runs
``EXPLAIN QUERY PLAN`` to decide whether the read uses an index or degrades to a
full table scan as the audit trail grows.

It is strictly **read-only**: it opens the DB ``mode=ro``, runs introspection
(``PRAGMA``) + ``EXPLAIN QUERY PLAN``, and **never** issues an
``INSERT``/``UPDATE``/``DELETE``/``CREATE``/``DROP``.  Missing indexes are
*recommended*, never created — applying them is the separate, guarded
:mod:`scripts.apply_cockpit_hot_path_indexes` (created only if needed).  No
broker call, no execution.

Per-query report fields: ``query_name, table, columns_used, where_clause,
uses_index, index_name, full_scan_detected, bounded_by_limit, bounded_by_time,
row_count, risk_level, recommendation``.

Score::

    HotPathIndexedCoverage = IndexedHotPathQueries / max(HotPathQueries, 1)
    HotPathBoundedCoverage = BoundedHotPathQueries / max(HotPathQueries, 1)
    HotPathFullScanRisk    = FullScanHotPathQueries / max(HotPathQueries, 1)
    CockpitHotPathScore    = 10 * (0.45*HotPathIndexedCoverage
                                 + 0.35*HotPathBoundedCoverage
                                 + 0.20*(1 - HotPathFullScanRisk))
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import runtime_config as _runtime_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import runtime_config as _runtime_config  # type: ignore[no-redef]

# Plan markers meaning "this step used an index".
_INDEX_MARKERS = ("USING INDEX", "USING COVERING INDEX",
                  "USING INTEGER PRIMARY KEY", "USING PRIMARY KEY")

RISK_LOW, RISK_MEDIUM, RISK_HIGH = "LOW", "MEDIUM", "HIGH"
# Above this row count, an unindexed full scan on a hot path is HIGH risk.
_LARGE_TABLE_ROWS = 1000


@dataclass(frozen=True)
class HotPathQuery:
    """One cockpit/diagnostics hot-path SQLite read to audit."""
    query_name: str
    hot_path: str            # which diagnostic subreport / path it backs
    table: str
    sql: str
    params: tuple
    columns_used: tuple[str, ...]
    filter_column: str | None   # the principal WHERE column (for recommendations)
    bounded_by_time: bool = False


# The curated hot-path read set.  These mirror the shape of the reads the
# cockpit/diagnostics subreports issue (filtered counts + recent-row pulls).
_HOT_PATH_QUERIES: tuple[HotPathQuery, ...] = (
    HotPathQuery(
        "truth_purity_fake_rows", "runtime_truth_purity_audit", "manual_trades",
        "SELECT COUNT(*) FROM manual_trades WHERE created_via = ?",
        ("quarantined_fake_manual_trade",), ("created_via",), "created_via"),
    HotPathQuery(
        "broken_windows_unreconciled", "broken_windows_report", "manual_trades",
        "SELECT * FROM manual_trades WHERE reconciliation_status = ? LIMIT 200",
        ("",), ("reconciliation_status",), "reconciliation_status"),
    HotPathQuery(
        "closed_loop_recon_by_trade", "closed_loop_learning_audit",
        "reconciliation_results",
        "SELECT * FROM reconciliation_results WHERE trade_id = ? LIMIT 50",
        ("MT_x",), ("trade_id",), "trade_id"),
    HotPathQuery(
        "closed_loop_moltbook_by_trade", "closed_loop_learning_audit",
        "moltbook_entries",
        "SELECT * FROM moltbook_entries WHERE manual_trade_log_id = ? LIMIT 50",
        ("MT_x",), ("manual_trade_log_id",), "manual_trade_log_id"),
    HotPathQuery(
        "defensive_alpha_broker_calls", "defensive_alpha_report", "manual_trades",
        "SELECT COUNT(*) FROM manual_trades WHERE broker_api_called = ?",
        (0,), ("broker_api_called",), "broker_api_called"),
    HotPathQuery(
        "defensive_alpha_recent_trades", "defensive_alpha_report", "manual_trades",
        "SELECT * FROM manual_trades WHERE event_id = ? LIMIT 50",
        ("EV_x",), ("event_id",), "event_id"),
    HotPathQuery(
        "source_independence_by_source", "source_independence_audit",
        "signal_events",
        "SELECT * FROM signal_events WHERE source_name = ? "
        "ORDER BY fetched_at DESC LIMIT 50",
        ("rss",), ("source_name", "fetched_at"), "source_name"),
    HotPathQuery(
        "source_independence_recent", "source_independence_audit", "signal_events",
        "SELECT * FROM signal_events ORDER BY fetched_at DESC LIMIT 100",
        (), ("fetched_at",), None, bounded_by_time=False),
)


# Candidate indexes proposed by the sprint brief.  We map each to its
# (table, columns); a recommendation is emitted ONLY when every listed column
# exists on an existing table.  Brief candidates that reference non-existent
# columns (e.g. manual_trades.date, signal_events.timestamp_utc) are therefore
# never recommended — recommendations only use existing columns.
_CANDIDATE_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("idx_manual_trades_created_via", "manual_trades", ("created_via",)),
    ("idx_manual_trades_status_date", "manual_trades", ("status", "date")),
    ("idx_manual_trades_ticker_date", "manual_trades", ("ticker", "date")),
    ("idx_moltbook_trade_id", "moltbook_entries", ("manual_trade_log_id",)),
    ("idx_moltbook_ticker_created", "moltbook_entries", ("ticker", "created_at")),
    ("idx_reconciliation_trade_id", "reconciliation_results",
     ("manual_trade_log_id",)),
    ("idx_signal_events_ticker_timestamp", "signal_events",
     ("ticker", "timestamp_utc")),
    ("idx_signal_events_source_timestamp", "signal_events",
     ("source_name", "timestamp_utc")),
)


# Informational, non-SQLite hot paths (file reads).  Reported for completeness
# but NOT scored — they have no index concept.  Each is a bounded read.
_FILE_HOT_PATHS: tuple[dict[str, Any], ...] = (
    {"query_name": "diagnostics_cache_read", "path": "runtime/diagnostics_cache/"
     "diagnostics_snapshot.json", "bounded_by_limit": True,
     "note": "single derived-cache JSON read (non-canonical)."},
    {"query_name": "operator_audit_log_tail", "path": "runtime/"
     "operator_audit_log.jsonl", "bounded_by_limit": True,
     "note": "JSONL tail read bounded by `limit` (read_recent_audit_events)."},
    {"query_name": "dry_run_receipt_read", "path": "runtime/"
     "operator_dry_run_receipts/*.json", "bounded_by_limit": True,
     "note": "single receipt JSON read keyed by op+db hash."},
    {"query_name": "cockpit_diagnostics_service", "path": "diagnostics_service "
     "-> diagnostics_snapshot_cache", "bounded_by_limit": True,
     "note": "cache-first; recomputes once on miss (warmer keeps it warm)."},
)


def _resolve_db_path(db_path: Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return _runtime_config.get_db_path()


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _indexed_lead_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Leading columns of every index on ``table`` (incl. PK autoindex)."""
    lead: set[str] = set()
    try:
        for idx in conn.execute(f"PRAGMA index_list({table})"):
            idx_name = idx[1]
            try:
                cols = list(conn.execute(f"PRAGMA index_info({idx_name})"))
            except sqlite3.Error:
                continue
            if cols:
                # index_info rows: (seqno, cid, name); seqno 0 == leading column.
                first = sorted(cols, key=lambda r: r[0])[0]
                if first[2]:
                    lead.add(first[2])
    except sqlite3.Error:
        pass
    return lead


def _explain(conn: sqlite3.Connection, sql: str, params: tuple) -> list[str]:
    try:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    except sqlite3.Error:
        return []
    return [str(r[-1]) for r in rows]


def _index_name_from_plan(plan_steps: list[str]) -> str | None:
    for step in plan_steps:
        upper = step.upper()
        for marker in ("USING COVERING INDEX", "USING INDEX"):
            if marker in upper:
                # "...USING [COVERING ]INDEX idx_foo (col=?)" → token after marker.
                after = step[upper.index(marker) + len(marker):].strip()
                token = after.split(" ")[0].split("(")[0].strip()
                return token or None
    return None


def _analyze_plan(plan_steps: list[str]) -> dict[str, Any]:
    upper = [s.upper() for s in plan_steps]
    uses_index = any(any(m in step for m in _INDEX_MARKERS) for step in upper)
    full_scan = any(step.startswith("SCAN")
                    and not any(m in step for m in _INDEX_MARKERS)
                    for step in upper)
    return {"uses_index": uses_index, "full_scan": full_scan}


def _row_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row is not None else None
    except sqlite3.Error:
        return None


def _where_clause(sql: str) -> str:
    upper = sql.upper()
    if " WHERE " not in upper:
        return ""
    start = upper.index(" WHERE ") + len(" WHERE ")
    tail = sql[start:]
    # Trim trailing ORDER BY / LIMIT for readability.
    for kw in (" ORDER BY ", " LIMIT ", " GROUP BY "):
        idx = tail.upper().find(kw)
        if idx != -1:
            tail = tail[:idx]
    return tail.strip()


def _recommendation(
    conn: sqlite3.Connection,
    q: HotPathQuery,
    *,
    table_exists: bool,
    full_scan: bool,
    columns: set[str],
    indexed_lead: set[str],
) -> str | None:
    """Recommend an additive index ONLY for an existing, unindexed filter column.

    Never emits SQL for a missing table/column, never DROP/DELETE — purely a
    ``CREATE INDEX IF NOT EXISTS`` suggestion string (not executed here).
    """
    if not table_exists or not full_scan or not q.filter_column:
        return None
    col = q.filter_column
    if col not in columns:
        return None  # existing-columns-only guarantee
    if col in indexed_lead:
        return None  # already covered by a leading-column index
    idx_name = f"idx_{q.table}_{col}"
    return f"CREATE INDEX IF NOT EXISTS {idx_name} ON {q.table}({col});"


def audit_hot_paths(db_path: Path | None = None) -> dict[str, Any]:
    """Audit the cockpit/diagnostics hot-path reads; return the scored report."""
    target = _resolve_db_path(db_path)
    out: dict[str, Any] = {
        "report": "cockpit_hot_path_query_audit",
        "db_path": str(target),
        "db_available": False,
        "hot_paths": [],
        "file_hot_paths": [dict(f) for f in _FILE_HOT_PATHS],
        "index_recommendations": [],
        "indexes_applied": False,   # this script never applies — audit-only
        **_contract.advisory_safety_stamps(),
    }
    conn = _readonly_connect(target)
    if conn is None:
        out["state"] = "INSUFFICIENT_DATA"
        out["note"] = "runtime DB missing/unreadable — cannot audit plans."
        out.update(_score([]))
        return out
    out["db_available"] = True
    results: list[dict[str, Any]] = []
    recommendations: list[str] = []
    try:
        for q in _HOT_PATH_QUERIES:
            columns = _table_columns(conn, q.table)
            table_exists = bool(columns)
            if not table_exists:
                results.append({
                    "query_name": q.query_name,
                    "hot_path": q.hot_path,
                    "table": q.table,
                    "columns_used": list(q.columns_used),
                    "where_clause": _where_clause(q.sql),
                    "uses_index": False,
                    "index_name": None,
                    "full_scan_detected": False,
                    "bounded_by_limit": "limit" in q.sql.lower(),
                    "bounded_by_time": q.bounded_by_time,
                    "row_count": None,
                    "risk_level": RISK_LOW,
                    "table_missing": True,
                    "recommendation": None,
                })
                continue
            indexed_lead = _indexed_lead_columns(conn, q.table)
            plan = _explain(conn, q.sql, q.params)
            analysis = _analyze_plan(plan)
            rows = _row_count(conn, q.table)
            bounded_limit = "limit" in q.sql.lower()
            full_scan = analysis["full_scan"] and not analysis["uses_index"]
            recommendation = _recommendation(
                conn, q, table_exists=table_exists, full_scan=full_scan,
                columns=columns, indexed_lead=indexed_lead)
            if recommendation and recommendation not in recommendations:
                recommendations.append(recommendation)
            # Risk: full scan on a large table is HIGH; small table MEDIUM;
            # otherwise (indexed or bounded) LOW.
            if full_scan and isinstance(rows, int) and rows >= _LARGE_TABLE_ROWS:
                risk = RISK_HIGH
            elif full_scan:
                risk = RISK_MEDIUM
            else:
                risk = RISK_LOW
            results.append({
                "query_name": q.query_name,
                "hot_path": q.hot_path,
                "table": q.table,
                "columns_used": list(q.columns_used),
                "where_clause": _where_clause(q.sql),
                "uses_index": analysis["uses_index"],
                "index_name": _index_name_from_plan(plan),
                "full_scan_detected": full_scan,
                "bounded_by_limit": bounded_limit,
                "bounded_by_time": q.bounded_by_time,
                "row_count": rows,
                "risk_level": risk,
                "plan": " | ".join(plan),
                "recommendation": recommendation,
            })
    finally:
        conn.close()
    out["hot_paths"] = results
    out["index_recommendations"] = recommendations
    out.update(_score(results))
    out["state"] = "PASS" if out["cockpit_hot_path_score"] >= 8.0 else "WARN"
    return out


def _score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the cockpit hot-path coverage/risk score over SQLite queries.

    Queries against a *missing* table are excluded from the denominator (we
    cannot judge index use on a table that does not exist).
    """
    scored = [r for r in results if not r.get("table_missing")]
    n = max(len(scored), 1)
    indexed = sum(1 for r in scored if r["uses_index"] and not r["full_scan_detected"])
    bounded = sum(1 for r in scored
                  if r["bounded_by_limit"] or r["bounded_by_time"])
    full_scans = sum(1 for r in scored if r["full_scan_detected"])
    indexed_cov = indexed / n
    bounded_cov = bounded / n
    full_scan_risk = full_scans / n
    score = 10.0 * (
        0.45 * indexed_cov + 0.35 * bounded_cov + 0.20 * (1 - full_scan_risk)
    )
    return {
        "hot_path_query_count": len(scored),
        "indexed_hot_path_queries": indexed,
        "bounded_hot_path_queries": bounded,
        "full_scan_hot_path_queries": full_scans,
        "hot_path_indexed_coverage": round(indexed_cov, 4),
        "hot_path_bounded_coverage": round(bounded_cov, 4),
        "hot_path_full_scan_risk": round(full_scan_risk, 4),
        "cockpit_hot_path_score": round(score, 3),
        "full_scan_query_names": [r["query_name"] for r in scored
                                  if r["full_scan_detected"]],
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cockpit_hot_path_query_audit.py",
        description=(
            "Audit cockpit/diagnostics hot-path SQLite reads with EXPLAIN QUERY "
            "PLAN. Read-only; recommends (never creates) indexes; no broker call."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else None
    report = audit_hot_paths(db)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("Cockpit Hot-Path Query/Index Audit")
        print("==================================")
        print(f"  db available           : {report['db_available']}")
        print(f"  hot path query count   : {report.get('hot_path_query_count')}")
        print(f"  indexed coverage       : {report.get('hot_path_indexed_coverage')}")
        print(f"  bounded coverage       : {report.get('hot_path_bounded_coverage')}")
        print(f"  full scan risk         : {report.get('hot_path_full_scan_risk')}")
        print(f"  cockpit_hot_path_score : {report.get('cockpit_hot_path_score')}")
        print(f"  state                  : {report.get('state')}")
        for r in report["hot_paths"]:
            flag = ("idx" if r["uses_index"]
                    else ("SCAN" if r["full_scan_detected"] else "?"))
            print(f"  [{flag:>4}] {r['query_name']:<32} risk={r['risk_level']} "
                  f"rows={r['row_count']}")
        if report["index_recommendations"]:
            print("  index recommendations:")
            for rec in report["index_recommendations"]:
                print(f"    - {rec}")
        else:
            print("  index recommendations: (none — hot paths covered)")
    return 0


__all__ = [
    "HotPathQuery",
    "RISK_LOW", "RISK_MEDIUM", "RISK_HIGH",
    "audit_hot_paths",
]


if __name__ == "__main__":
    raise SystemExit(main())
