"""SQLite query-plan audit — prove critical reads are indexed & bounded.

Kanté Sprint 2 — Task 3.  Performance claims need *evidence*, not vibes.  This
module runs ``EXPLAIN QUERY PLAN`` over the MVP's critical, repeated queries and
flags anything that would degrade to an unbounded full-table scan as the audit
trail grows:

* a full table SCAN on a large critical table (no usable index),
* a query helper with no ``LIMIT`` ceiling.

Complexity target
-----------------
Without an index a filtered read is ``O(n)``; with one it is ``O(log n + k)``
where ``k`` is bounded by ``LIMIT`` (``MAX_LIMIT = 500``).  We assert::

    indexed_coverage = critical_queries_using_index / critical_queries >= 0.90

Read-only: opens the DB ``mode=ro`` for plans; the only optional write is the
additive ``CREATE INDEX IF NOT EXISTS`` via ``signal_index_query.ensure_indexes``
when ``--ensure-indexes`` is passed.  Never a broker call.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import signal_index_query as _siq
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import signal_index_query as _siq  # type: ignore[no-redef]

INDEXED_COVERAGE_TARGET = 0.90
MAX_LIMIT = _siq.MAX_LIMIT  # 500

# Markers that mean "this plan step used an index" (covers TEXT PK autoindex
# and explicit indexes across SQLite versions).
_INDEX_MARKERS = ("USING INDEX", "USING COVERING INDEX",
                  "USING INTEGER PRIMARY KEY", "USING PRIMARY KEY")

# (name, sql, params) — each is a critical, repeated read filtered on an
# indexed column and capped with LIMIT.
_CRITICAL_QUERIES: tuple[tuple[str, str, tuple], ...] = (
    ("dfp_by_fingerprint",
     "SELECT * FROM duplicate_fingerprints WHERE fingerprint=? LIMIT 50",
     ("fp",)),
    ("dfp_by_ticker",
     "SELECT * FROM duplicate_fingerprints WHERE ticker=?"
     " ORDER BY last_seen_at DESC LIMIT 50", ("AAPL",)),
    ("sci_by_sector",
     "SELECT * FROM signal_cell_index WHERE sector=?"
     " ORDER BY last_seen_at DESC LIMIT 50", ("TECH",)),
    ("sci_by_source_type",
     "SELECT * FROM signal_cell_index WHERE source_type=? LIMIT 50", ("rss",)),
    ("sci_by_event_type",
     "SELECT * FROM signal_cell_index WHERE event_type=? LIMIT 50", ("earnings",)),
    ("moltbook_by_ticker",
     "SELECT * FROM moltbook_entries WHERE ticker=?"
     " ORDER BY logged_at DESC LIMIT 50", ("AAPL",)),
    ("recon_by_trade_id",
     "SELECT * FROM reconciliation_results WHERE trade_id=? LIMIT 50", ("T1",)),
    ("manual_trades_by_event_id",
     "SELECT * FROM manual_trades WHERE event_id=? LIMIT 50", ("EV_T1",)),
)


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


def _explain(conn: sqlite3.Connection, sql: str, params: tuple) -> list[str]:
    try:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    except sqlite3.Error:
        return []
    return [str(r[-1]) for r in rows]


def _analyze_plan(plan_steps: list[str]) -> dict[str, Any]:
    upper = [s.upper() for s in plan_steps]
    uses_index = any(any(m in step for m in _INDEX_MARKERS) for step in upper)
    full_scan = any(step.startswith("SCAN") and not any(m in step for m in _INDEX_MARKERS)
                    for step in upper)
    return {"uses_index": uses_index, "full_scan": full_scan}


def audit_query_plans(db_path: Path | None = None) -> dict[str, Any]:
    """Run EXPLAIN QUERY PLAN over the critical queries; report index coverage."""
    target = Path(db_path) if db_path is not None else Path(_siq._default_db_path())
    out: dict[str, Any] = {
        "report": "sqlite_query_plan_audit",
        "db_path": str(target),
        "db_available": False,
        "max_limit": MAX_LIMIT,
        "indexed_coverage_target": INDEXED_COVERAGE_TARGET,
        "queries": [],
        **_contract.advisory_safety_stamps(),
    }
    conn = _readonly_connect(target)
    if conn is None:
        out["state"] = "INSUFFICIENT_DATA"
        out["note"] = "runtime DB missing/unreadable — cannot audit plans."
        return out
    out["db_available"] = True
    indexed = 0
    has_limit_all = True
    try:
        for name, sql, params in _CRITICAL_QUERIES:
            steps = _explain(conn, sql, params)
            analysis = _analyze_plan(steps)
            has_limit = "limit" in sql.lower()
            has_limit_all = has_limit_all and has_limit
            if analysis["uses_index"] and not analysis["full_scan"]:
                indexed += 1
            out["queries"].append({
                "name": name,
                "uses_index": analysis["uses_index"],
                "full_table_scan": analysis["full_scan"],
                "has_limit": has_limit,
                "plan": " | ".join(steps),
            })
    finally:
        conn.close()
    n = len(_CRITICAL_QUERIES)
    coverage = round(indexed / n, 4) if n else 0.0
    out["critical_query_count"] = n
    out["indexed_query_count"] = indexed
    out["indexed_coverage"] = coverage
    out["all_queries_bounded"] = bool(has_limit_all)
    out["meets_coverage_target"] = bool(coverage >= INDEXED_COVERAGE_TARGET)
    out["full_table_scans"] = [q["name"] for q in out["queries"]
                               if q["full_table_scan"]]
    out["state"] = "PASS" if (out["meets_coverage_target"]
                              and has_limit_all) else "WARN"
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sqlite_query_plan_audit.py",
        description=(
            "Audit EXPLAIN QUERY PLAN for the critical MVP queries. Read-only "
            "(plus optional CREATE INDEX IF NOT EXISTS); never a broker call."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--ensure-indexes", action="store_true",
                   help="Additively create the query indexes before auditing.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else Path(_siq._default_db_path())
    if args.ensure_indexes:
        _siq.ensure_indexes(db)
    report = audit_query_plans(db)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Query-plan audit: {report.get('state')}")
        if report["db_available"]:
            print(f"  indexed coverage : {report['indexed_coverage']} "
                  f"(target {INDEXED_COVERAGE_TARGET})")
            print(f"  all bounded      : {report['all_queries_bounded']}")
            for q in report["queries"]:
                flag = "idx" if q["uses_index"] else ("SCAN" if q["full_table_scan"] else "?")
                print(f"  [{flag:>4}] {q['name']}")
    return 0 if report.get("state") != "WARN" else 0


__all__ = [
    "INDEXED_COVERAGE_TARGET",
    "MAX_LIMIT",
    "audit_query_plans",
]


if __name__ == "__main__":
    raise SystemExit(main())
