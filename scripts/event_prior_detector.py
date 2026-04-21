"""event_prior_detector — read-only prior-window detector.

Scope (v0):
    * read-only queries over logs/observation.db (opened via sqlite URI
      mode=ro so any accidental write raises)
    * deterministic sliding-window logic — given observations sorted by ts,
      find windows containing at least min_count rows within window_minutes
    * optional filters: source, since, until

What this module intentionally does NOT do:
    * invent chronology from thin air — if the DB is empty, the result is empty
    * predict anything — it counts historical windows, nothing more
    * classify observation content — no NLP, no keyword rules, no inference
    * schedule itself, collect inputs, or submit orders

Public API:
    detect_prior_windows(conn, source=None, window_minutes=60, min_count=3,
                         since=None, until=None) -> list[dict]
    count_observations_by_source(conn) -> dict[str, int]
    open_readonly(db_path) -> sqlite3.Connection

CLI:
    python scripts/event_prior_detector.py --summary
    python scripts/event_prior_detector.py --source snapshot_logger \
        --window-min 60 --min-count 3
    python scripts/event_prior_detector.py --db other.db --json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DB_PATH = REPO_ROOT / "logs" / "observation.db"


def open_readonly(db_path: str | os.PathLike) -> sqlite3.Connection:
    """Open the chronology DB in strict read-only mode.

    Uses sqlite's file: URI with mode=ro. Any INSERT/UPDATE/DELETE executed
    against the returned connection raises sqlite3.OperationalError.

    Missing DB paths raise sqlite3.OperationalError immediately rather than
    silently creating an empty DB — the detector never fabricates chronology.
    """
    path = Path(db_path)
    if not path.exists():
        raise sqlite3.OperationalError(f"chronology DB not found: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _parse_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp with or without a trailing Z."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"invalid timestamp: {raw!r}")
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1]
    return datetime.fromisoformat(text)


def _format_ts(dt: datetime, original: str) -> str:
    """Preserve original Z-suffix convention when echoing timestamps back."""
    iso = dt.isoformat()
    if isinstance(original, str) and original.strip().endswith("Z"):
        return iso + "Z"
    return iso


def count_observations_by_source(conn: sqlite3.Connection) -> dict[str, int]:
    """Return {source: count} for all observation rows in the DB."""
    rows = conn.execute(
        "SELECT source, COUNT(*) FROM observations GROUP BY source"
    ).fetchall()
    return {str(source): int(count) for source, count in rows}


def detect_prior_windows(
    conn: sqlite3.Connection,
    source: str | None = None,
    window_minutes: int = 60,
    min_count: int = 3,
    since: str | None = None,
    until: str | None = None,
) -> list[dict[str, Any]]:
    """Detect windows of clustered observations.

    A window is a contiguous run of observations (within the source filter)
    such that the time between its first and last row is <= window_minutes
    and it contains at least min_count rows. Windows are maximal per start
    index — for a given earliest row, we extend j as far as the window allows.

    Parameters
    ----------
    conn : sqlite3.Connection
        Read-only chronology connection (see open_readonly).
    source : str, optional
        Filter observations by source. None = any source.
    window_minutes : int
        Window size in minutes. Must be > 0.
    min_count : int
        Minimum rows for a window to be reported. Must be >= 1.
    since, until : str, optional
        ISO-8601 inclusive bounds. None = unbounded.

    Returns
    -------
    list of {start_ts, end_ts, count, source} dicts, sorted by start_ts.
    Never invents rows. Never merges overlapping windows beyond maximal
    extension per start index. Empty input → empty result.
    """
    if window_minutes <= 0:
        raise ValueError("window_minutes must be > 0")
    if min_count < 1:
        raise ValueError("min_count must be >= 1")

    clauses = []
    params: list[Any] = []
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if since is not None:
        clauses.append("ts >= ?")
        params.append(since)
    if until is not None:
        clauses.append("ts <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    query = f"SELECT ts, source FROM observations{where} ORDER BY ts ASC"
    raw_rows = conn.execute(query, params).fetchall()

    parsed: list[tuple[datetime, str, str]] = []
    for ts, src in raw_rows:
        try:
            parsed.append((_parse_ts(ts), str(src), str(ts)))
        except ValueError:
            # Row has an unparseable timestamp. Skip it silently; the detector
            # must not invent data, but it also must not crash on garbage.
            continue

    windows: list[dict[str, Any]] = []
    window = timedelta(minutes=window_minutes)
    n = len(parsed)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and parsed[j + 1][0] - parsed[i][0] <= window:
            j += 1
        count = j - i + 1
        if count >= min_count:
            start_dt, _, start_raw = parsed[i]
            end_dt, _, end_raw = parsed[j]
            sources_in_window = {parsed[k][1] for k in range(i, j + 1)}
            window_source = (
                next(iter(sources_in_window))
                if len(sources_in_window) == 1
                else "MIXED"
            )
            windows.append({
                "start_ts": _format_ts(start_dt, start_raw),
                "end_ts": _format_ts(end_dt, end_raw),
                "count": count,
                "source": window_source,
            })
            # advance past this window's first row; a later start can still
            # produce a different maximal window.
            i += 1
        else:
            i += 1
    return windows


def build_summary(
    conn: sqlite3.Connection,
    source: str | None = None,
    window_minutes: int = 60,
    min_count: int = 3,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """CLI-friendly summary payload. Pure read."""
    windows = detect_prior_windows(
        conn,
        source=source,
        window_minutes=window_minutes,
        min_count=min_count,
        since=since,
        until=until,
    )
    by_source = count_observations_by_source(conn)
    total_observations = sum(by_source.values())
    return {
        "db": None,  # filled in by the CLI wrapper
        "filters": {
            "source": source,
            "window_minutes": window_minutes,
            "min_count": min_count,
            "since": since,
            "until": until,
        },
        "total_observations": total_observations,
        "observations_by_source": by_source,
        "window_count": len(windows),
        "windows": windows,
    }


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only detector for clustered prior-event windows over "
            "logs/observation.db. Deterministic counts only — no prediction."
        )
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the chronology SQLite DB (default: logs/observation.db).",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Restrict to observations with this source value.",
    )
    parser.add_argument(
        "--window-min",
        type=int,
        default=60,
        help="Window size in minutes (default 60).",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=3,
        help="Minimum observations required inside a window (default 3).",
    )
    parser.add_argument("--since", default=None, help="ISO-8601 inclusive lower bound.")
    parser.add_argument("--until", default=None, help="ISO-8601 inclusive upper bound.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--summary", action="store_true", help="Compact summary.")
    mode.add_argument("--json", action="store_true", help="Full JSON payload.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    try:
        conn = open_readonly(db_path)
    except sqlite3.OperationalError as exc:
        payload = {
            "db": str(db_path),
            "error": str(exc),
            "total_observations": 0,
            "window_count": 0,
            "windows": [],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1

    try:
        summary = build_summary(
            conn,
            source=args.source,
            window_minutes=args.window_min,
            min_count=args.min_count,
            since=args.since,
            until=args.until,
        )
    finally:
        conn.close()
    summary["db"] = str(db_path)

    if args.summary and not args.json:
        compact = {
            "db": summary["db"],
            "filters": summary["filters"],
            "total_observations": summary["total_observations"],
            "window_count": summary["window_count"],
            "sample": summary["windows"][:5],
        }
        print(json.dumps(compact, indent=2, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
