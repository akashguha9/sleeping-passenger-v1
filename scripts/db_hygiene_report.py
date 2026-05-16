"""Read-only DB hygiene report for the private-operator MVP.

Diagnostic only.  Walks the local SQLite database to surface size,
table-count distribution, important table presence, timestamp coverage,
and SQLite page/freelist accounting so the operator can monitor growth
without running blind into a future hot spot.

Safety
------
* Read-only.  Never deletes, archives, mutates, or vacuums the DB.
* No network calls.  No secret access.  No broker references.
* Carries the standard ADVISORY_ONLY / execution_gate=LOCKED stamps.
* Degrades gracefully: missing DB returns a safe, well-formed payload.

Usage
-----
    python scripts/db_hygiene_report.py
    python scripts/db_hygiene_report.py --json
    python scripts/db_hygiene_report.py --db-path /path/to/mvp_local.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "runtime" / "mvp_local.db"

# Important tables we always look for if present; missing tables are
# simply omitted rather than treated as errors (the report is diagnostic).
_IMPORTANT_TABLES = (
    "signal_events",
    "manual_trades",
    "source_run_log",
    "live_source_refresh_runs",
    "reconciliations",
    "signal_decisions",
)

# Candidate timestamp column names we will probe when present.  We never
# infer a column type from name alone; we read what SQLite reports.
_TIMESTAMP_COLUMN_CANDIDATES = (
    "created_at",
    "inserted_at",
    "occurred_at",
    "event_time",
    "logged_at",
    "started_at",
    "finished_at",
    "marked_at",
    "ts",
    "timestamp",
)

# Size thresholds (bytes / rows).  Used to map raw measurements to
# textual recommendations.  These are advisory only — the report never
# mutates the DB.
_DB_MONITOR_BYTES = 100 * 1024 * 1024     # 100 MB
_DB_ARCHIVE_BYTES = 500 * 1024 * 1024     # 500 MB
_SIGNAL_EVENTS_MONITOR_ROWS = 100_000

_NO_CLAIMS = (
    "DB hygiene report is diagnostic only.",
    "No data was deleted, archived, or vacuumed.",
    "Performance/scalability is not solved by this report.",
)

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


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _user_tables(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in rows]


def _user_indexes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT name, tbl_name FROM sqlite_master "
            "WHERE type='index' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY tbl_name, name"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [{"name": r[0], "table": r[1]} for r in rows]


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return []
    return [str(r[1]) for r in rows]


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return -1


def _pragma_int(conn: sqlite3.Connection, name: str) -> int | None:
    try:
        row = conn.execute(f"PRAGMA {name}").fetchone()
        if row is None:
            return None
        return int(row[0])
    except (sqlite3.Error, ValueError, TypeError):
        return None


def _timestamp_range(
    conn: sqlite3.Connection, table: str, columns: list[str]
) -> dict[str, Any]:
    """Return oldest/newest timestamp for the first matching column.

    We probe candidates in order and stop at the first that returns a
    non-null pair.  String comparison is sufficient for ISO-8601 stored
    as TEXT (the convention everywhere in this repo).
    """
    out: dict[str, Any] = {"column": None, "oldest": None, "newest": None}
    lowered = {c.lower(): c for c in columns}
    for candidate in _TIMESTAMP_COLUMN_CANDIDATES:
        if candidate not in lowered:
            continue
        col = lowered[candidate]
        try:
            row = conn.execute(
                f"SELECT MIN({col}), MAX({col}) FROM {table} "
                f"WHERE {col} IS NOT NULL AND {col} != ''"
            ).fetchone()
        except sqlite3.Error:
            continue
        if row is None:
            continue
        oldest, newest = row
        if oldest is None and newest is None:
            continue
        out["column"] = col
        out["oldest"] = oldest
        out["newest"] = newest
        return out
    return out


def _source_distribution(
    conn: sqlite3.Connection, table: str, columns: list[str], *, limit: int = 10
) -> dict[str, int] | None:
    """Top-N source counts for ``signal_events``-style tables.

    Only runs when the table has a recognisable source column; otherwise
    returns ``None`` so the caller can omit the field.
    """
    candidate_cols = ("source", "source_key", "provider", "feed")
    lowered = {c.lower(): c for c in columns}
    for cand in candidate_cols:
        if cand not in lowered:
            continue
        col = lowered[cand]
        try:
            rows = conn.execute(
                f"SELECT {col}, COUNT(*) FROM {table} "
                f"GROUP BY {col} ORDER BY COUNT(*) DESC LIMIT {limit}"
            ).fetchall()
        except sqlite3.Error:
            return None
        return {str(r[0] if r[0] is not None else "<null>"): int(r[1]) for r in rows}
    return None


def _build_recommendations(
    *,
    db_size: int | None,
    table_counts: dict[str, int],
    freelist_count: int | None,
) -> list[str]:
    recs: list[str] = ["no_action"]
    if isinstance(db_size, int):
        if db_size >= _DB_ARCHIVE_BYTES:
            recs.append("consider_archive_policy_later")
        elif db_size >= _DB_MONITOR_BYTES:
            recs.append("monitor_db_size")
    signal_events = table_counts.get("signal_events")
    if isinstance(signal_events, int) and signal_events >= _SIGNAL_EVENTS_MONITOR_ROWS:
        recs.append("consider_archive_policy_later")
    if isinstance(freelist_count, int) and freelist_count > 0:
        # Surface a backup-before-compaction recommendation but never run
        # the compaction ourselves — that is an explicit operator decision.
        recs.append("consider_vacuum_only_after_backup")
    # Re-run a dedup since the heuristics above can append duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for r in recs:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    # If we ever added a real recommendation, drop the leading "no_action".
    if len(out) > 1 and out[0] == "no_action":
        out = [r for r in out if r != "no_action"]
    return out


def build_report(
    db_path: Path = _DEFAULT_DB, *, top_n: int = 10
) -> dict[str, Any]:
    """Read-only DB hygiene report.  Never mutates the DB."""
    report: dict[str, Any] = {
        "report": "db_hygiene_report",
        "generated_at": _utc_iso(),
        "repo_root": str(_REPO_ROOT),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_size_bytes": None,
        "sqlite_page_count": None,
        "sqlite_page_size": None,
        "sqlite_freelist_count": None,
        "table_count": 0,
        "table_counts": {},
        "largest_tables": [],
        "important_tables": {},
        "timestamp_coverage": {},
        "source_distribution": None,
        "indexes": [],
        "recommendations": ["no_action"],
        "warnings": [],
        "no_claims": list(_NO_CLAIMS),
        **_ADVISORY_STAMPS,
    }
    if not db_path.exists():
        report["warnings"].append("db_missing")
        return report

    try:
        report["db_size_bytes"] = db_path.stat().st_size
    except OSError as exc:
        report["warnings"].append(f"db_stat_failed: {type(exc).__name__}")

    conn = _readonly_connect(db_path)
    if conn is None:
        report["warnings"].append("db_open_failed")
        return report

    try:
        report["sqlite_page_count"] = _pragma_int(conn, "page_count")
        report["sqlite_page_size"] = _pragma_int(conn, "page_size")
        report["sqlite_freelist_count"] = _pragma_int(conn, "freelist_count")

        tables = _user_tables(conn)
        report["table_count"] = len(tables)
        counts: dict[str, int] = {}
        for t in tables:
            counts[t] = _row_count(conn, t)
        report["table_counts"] = counts

        ranked = sorted(
            (
                {"table": t, "row_count": c}
                for t, c in counts.items()
            ),
            key=lambda d: (-d["row_count"] if d["row_count"] >= 0 else 1, d["table"]),
        )
        report["largest_tables"] = ranked[:top_n]

        important: dict[str, Any] = {}
        for name in _IMPORTANT_TABLES:
            if name not in counts:
                important[name] = {"present": False}
                continue
            cols = _column_names(conn, name)
            important[name] = {
                "present": True,
                "row_count": counts.get(name, 0),
                "column_count": len(cols),
            }
        report["important_tables"] = important

        coverage: dict[str, Any] = {}
        for name in _IMPORTANT_TABLES:
            if name not in counts:
                continue
            cols = _column_names(conn, name)
            ts = _timestamp_range(conn, name, cols)
            if ts.get("column"):
                coverage[name] = ts
        report["timestamp_coverage"] = coverage

        if "signal_events" in counts:
            cols = _column_names(conn, "signal_events")
            dist = _source_distribution(conn, "signal_events", cols)
            if dist is not None:
                report["source_distribution"] = dist

        report["indexes"] = _user_indexes(conn)
    except sqlite3.Error as exc:
        report["warnings"].append(f"sqlite_error: {type(exc).__name__}")
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    report["recommendations"] = _build_recommendations(
        db_size=report.get("db_size_bytes"),
        table_counts=report.get("table_counts") or {},
        freelist_count=report.get("sqlite_freelist_count"),
    )
    return report


def _emit_text(report: dict[str, Any]) -> None:
    print("Sleeping Passenger - DB Hygiene Report")
    print("=" * 38)
    print(f"generated_at      : {report.get('generated_at')}")
    print(f"db_path           : {report.get('db_path')}")
    print(f"db_exists         : {report.get('db_exists')}")
    size = report.get("db_size_bytes")
    if size is not None:
        print(f"db_size_bytes     : {size:,}")
    print(f"sqlite_page_count : {report.get('sqlite_page_count')}")
    print(f"sqlite_page_size  : {report.get('sqlite_page_size')}")
    print(f"sqlite_freelist   : {report.get('sqlite_freelist_count')}")
    print(f"table_count       : {report.get('table_count')}")
    largest = report.get("largest_tables") or []
    if largest:
        print("")
        print("largest tables:")
        for entry in largest:
            print(
                f"  - {entry.get('table'):<32} {entry.get('row_count'):>12} rows"
            )
    coverage = report.get("timestamp_coverage") or {}
    if coverage:
        print("")
        print("timestamp coverage:")
        for tbl, ts in coverage.items():
            print(
                f"  - {tbl:<28} col={ts.get('column')}  "
                f"oldest={ts.get('oldest')}  newest={ts.get('newest')}"
            )
    dist = report.get("source_distribution") or {}
    if dist:
        print("")
        print("signal_events source distribution (top):")
        for src, n in dist.items():
            print(f"  - {src:<24} {n:>10}")
    recs = report.get("recommendations") or []
    print("")
    print("recommendations:")
    for r in recs:
        print(f"  - {r}")
    warnings = report.get("warnings") or []
    if warnings:
        print("")
        print("warnings:")
        for w in warnings:
            print(f"  - {w}")
    print("")
    for line in _NO_CLAIMS:
        print(f"NOTE: {line}")
    print(
        "Safety: ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false, "
        "ai_execution_count=0, can_execute=false."
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="db_hygiene_report.py",
        description=(
            "Read-only diagnostic for the local SQLite DB.  Reports size, "
            "table counts, important tables, timestamp coverage, indexes, "
            "and growth-based recommendations.  Never deletes, archives, "
            "or vacuums.  No broker call, no order placement."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--top-n", type=int, default=10)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = (args.db_path or _DEFAULT_DB).expanduser().resolve()
    rep = build_report(db, top_n=max(1, int(args.top_n)))
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True, default=str))
    else:
        _emit_text(rep)
    return 0


__all__ = ["build_report", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
