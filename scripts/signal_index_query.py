"""Indexed, paginated, row-limited query helpers for the signal-geometry tables.

This is the *performance / scalability floor* for the two audit-trail tables
that ``scripts/signal_geometry_persistence.py`` writes:

* ``duplicate_fingerprints`` — keyed by ``fingerprint`` (PK), indexed on
  ``ticker`` and ``event_id``.
* ``signal_cell_index``      — keyed by ``cell_key`` (PK), indexed on
  ``sector`` and ``narrative_cluster``.

Why this module exists
----------------------
As the audit trail grows, naive ``SELECT *`` reads become unbounded full-table
scans.  Every helper here:

* filters on **indexed** columns (or adds the missing index via
  :func:`ensure_indexes`),
* enforces ``LIMIT``/``OFFSET`` pagination with a hard ``MAX_LIMIT`` ceiling so
  a caller can never request an unbounded result set,
* opens the DB **read-only** for queries (no write, no broker, no execution).

The duplicate-fingerprint hint and the signal-cell index are PROBABILISTIC
audit data — never canonical truth about a trade.  Nothing here authorizes
execution.
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

# Default page size and the hard ceiling.  A caller asking for more than
# MAX_LIMIT is clamped down — there is no way to request an unbounded read.
DEFAULT_LIMIT = 50
MAX_LIMIT = 500

# Additive indexes for the columns the cell query filters on.  The schema
# already ships idx_sci_sector / idx_sci_cluster and idx_dfp_ticker /
# idx_dfp_event; these cover the remaining filterable columns.  All are
# CREATE INDEX IF NOT EXISTS — safe to run repeatedly.
_EXTRA_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_sci_source_type ON signal_cell_index(source_type)",
    "CREATE INDEX IF NOT EXISTS idx_sci_jurisdiction ON signal_cell_index(jurisdiction)",
    "CREATE INDEX IF NOT EXISTS idx_sci_event_type ON signal_cell_index(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_sci_time_bucket ON signal_cell_index(time_bucket)",
    "CREATE INDEX IF NOT EXISTS idx_sci_last_seen ON signal_cell_index(last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_dfp_source_type ON duplicate_fingerprints(source_type)",
    "CREATE INDEX IF NOT EXISTS idx_dfp_event_type ON duplicate_fingerprints(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_dfp_last_seen ON duplicate_fingerprints(last_seen_at)",
)


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:  # pragma: no cover - defensive
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _clamp_limit(limit: Any) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if n <= 0:
        return DEFAULT_LIMIT
    return min(n, MAX_LIMIT)


def _clamp_offset(offset: Any) -> int:
    try:
        n = int(offset)
    except (TypeError, ValueError):
        return 0
    return max(n, 0)


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


def ensure_indexes(db_path: Path | None = None) -> dict[str, Any]:
    """Create the additive query indexes if missing.  Idempotent.

    This is the only write path in the module (DDL only — no row writes).  It
    never touches broker / execution state.
    """
    target = Path(db_path) if db_path is not None else _default_db_path()
    created = 0
    if not target.exists():
        return {"db_exists": False, "indexes_ensured": 0,
                **_contract.advisory_safety_stamps()}
    conn = sqlite3.connect(str(target))
    try:
        for ddl in _EXTRA_INDEXES:
            try:
                conn.execute(ddl)
                created += 1
            except sqlite3.Error:
                pass
        conn.commit()
    finally:
        conn.close()
    return {"db_exists": True, "indexes_ensured": created,
            **_contract.advisory_safety_stamps()}


def _explain(conn: sqlite3.Connection, sql: str, params: tuple) -> str:
    try:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    except sqlite3.Error:
        return ""
    return " | ".join(str(r[-1]) for r in rows)


def query_duplicate_fingerprints(
    db_path: Path | None = None,
    *,
    fingerprint: str | None = None,
    ticker: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Query ``duplicate_fingerprints`` by fingerprint / ticker / time window.

    Filters use indexed columns (``fingerprint`` PK, ``ticker``,
    ``last_seen_at``).  Always paginated and row-limited.  Read-only.
    """
    target = Path(db_path) if db_path is not None else _default_db_path()
    lim = _clamp_limit(limit)
    off = _clamp_offset(offset)
    out: dict[str, Any] = {
        "table": "duplicate_fingerprints",
        "limit": lim,
        "offset": off,
        "rows": [],
        "row_count": 0,
        "query_plan": "",
        **_contract.advisory_safety_stamps(),
    }
    conn = _readonly_connect(target)
    if conn is None:
        out["db_available"] = False
        return out
    out["db_available"] = True
    where: list[str] = []
    params: list[Any] = []
    if fingerprint:
        where.append("fingerprint = ?")
        params.append(str(fingerprint))
    if ticker:
        where.append("ticker = ?")
        params.append(str(ticker).upper())
    if since:
        where.append("last_seen_at >= ?")
        params.append(str(since))
    if until:
        where.append("last_seen_at <= ?")
        params.append(str(until))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT fingerprint, source_type, event_type, ticker, event_id,"
        " observed_date, thesis_excerpt, first_seen_at, last_seen_at, seen_count"
        " FROM duplicate_fingerprints" + clause
        + " ORDER BY last_seen_at DESC LIMIT ? OFFSET ?"
    )
    full_params = tuple(params) + (lim, off)
    try:
        out["query_plan"] = _explain(conn, sql, full_params)
        rows = conn.execute(sql, full_params).fetchall()
        out["rows"] = [dict(r) for r in rows]
        out["row_count"] = len(out["rows"])
    except sqlite3.Error as exc:
        out["error"] = type(exc).__name__
    finally:
        conn.close()
    return out


def query_signal_cells(
    db_path: Path | None = None,
    *,
    source_type: str | None = None,
    jurisdiction: str | None = None,
    sector: str | None = None,
    event_type: str | None = None,
    time_bucket: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Query ``signal_cell_index`` by source_type / jurisdiction / sector /
    event_type / time_bucket and an optional last-seen window.

    Always paginated and row-limited.  Read-only.
    """
    target = Path(db_path) if db_path is not None else _default_db_path()
    lim = _clamp_limit(limit)
    off = _clamp_offset(offset)
    out: dict[str, Any] = {
        "table": "signal_cell_index",
        "limit": lim,
        "offset": off,
        "rows": [],
        "row_count": 0,
        "query_plan": "",
        **_contract.advisory_safety_stamps(),
    }
    conn = _readonly_connect(target)
    if conn is None:
        out["db_available"] = False
        return out
    out["db_available"] = True
    where: list[str] = []
    params: list[Any] = []
    for col, val in (
        ("source_type", source_type),
        ("jurisdiction", jurisdiction),
        ("sector", sector),
        ("event_type", event_type),
        ("time_bucket", time_bucket),
    ):
        if val:
            where.append(f"{col} = ?")
            params.append(str(val))
    if since:
        where.append("last_seen_at >= ?")
        params.append(str(since))
    if until:
        where.append("last_seen_at <= ?")
        params.append(str(until))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT cell_key, source_type, jurisdiction, geography, sector,"
        " asset_tags, event_type, time_bucket, narrative_cluster,"
        " freshness_state, chaos_score, mvp_state, first_seen_at,"
        " last_seen_at, seen_count"
        " FROM signal_cell_index" + clause
        + " ORDER BY last_seen_at DESC LIMIT ? OFFSET ?"
    )
    full_params = tuple(params) + (lim, off)
    try:
        out["query_plan"] = _explain(conn, sql, full_params)
        rows = conn.execute(sql, full_params).fetchall()
        out["rows"] = [dict(r) for r in rows]
        out["row_count"] = len(out["rows"])
    except sqlite3.Error as exc:
        out["error"] = type(exc).__name__
    finally:
        conn.close()
    return out


def incremental_cursor(
    db_path: Path | None = None,
    *,
    table: str = "signal_cell_index",
) -> dict[str, Any]:
    """Return the incremental-refresh cursor (max ``last_seen_at``) for a table.

    A downstream refresh can store this value and later call the matching
    ``query_*`` helper with ``since=cursor`` to read only rows seen *after* the
    last refresh — bounded, indexed, never a full re-scan.  Read-only.
    """
    target = Path(db_path) if db_path is not None else _default_db_path()
    allowed = {"signal_cell_index", "duplicate_fingerprints"}
    out: dict[str, Any] = {
        "table": table,
        "cursor": None,
        "row_count": 0,
        **_contract.advisory_safety_stamps(),
    }
    if table not in allowed:
        out["error"] = "unsupported_table"
        return out
    conn = _readonly_connect(target)
    if conn is None:
        out["db_available"] = False
        return out
    out["db_available"] = True
    try:
        row = conn.execute(
            f"SELECT MAX(last_seen_at) AS cur, COUNT(*) AS n FROM {table}"
        ).fetchone()
        if row is not None:
            out["cursor"] = row["cur"]
            out["row_count"] = int(row["n"] or 0)
    except sqlite3.Error as exc:
        out["error"] = type(exc).__name__
    finally:
        conn.close()
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="signal_index_query.py",
        description=(
            "Indexed, paginated, row-limited reads of the signal-geometry "
            "audit tables.  Read-only; never calls a broker."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--ensure-indexes", action="store_true")
    p.add_argument("--table", choices=["duplicate_fingerprints", "signal_cell_index"],
                   default="signal_cell_index")
    p.add_argument("--ticker", default=None)
    p.add_argument("--sector", default=None)
    p.add_argument("--source-type", default=None)
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else _default_db_path()
    if args.ensure_indexes:
        report = ensure_indexes(db)
    elif args.table == "duplicate_fingerprints":
        report = query_duplicate_fingerprints(
            db, ticker=args.ticker, limit=args.limit, offset=args.offset
        )
    else:
        report = query_signal_cells(
            db, sector=args.sector, source_type=args.source_type,
            limit=args.limit, offset=args.offset
        )
    print(json.dumps(report, indent=2, default=str))
    return 0


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "ensure_indexes",
    "query_duplicate_fingerprints",
    "query_signal_cells",
    "incremental_cursor",
]


if __name__ == "__main__":
    raise SystemExit(main())
