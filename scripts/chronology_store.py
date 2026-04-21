"""chronology_store — minimal SQLite-backed observation log.

Scope (v0):
    * explicit db_path parametrization (no hardcoded logs/observation.db)
    * idempotent schema creation
    * thin insert helpers for observations and snapshot rows

What this module intentionally does NOT do:
    * invent chronology or backfill from nothing
    * run any inference
    * wire itself into the active runtime (that is a separate task D)

Public API:
    get_connection(db_path) -> sqlite3.Connection
    init_schema(conn) -> None
    log_observation(conn, row) -> int
    log_snapshot(conn, run_id, snapshot) -> int
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL,
    run_id          TEXT,
    inserted_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_observations_ts     ON observations(ts);
CREATE INDEX IF NOT EXISTS idx_observations_source ON observations(source);
CREATE INDEX IF NOT EXISTS idx_observations_run_id ON observations(run_id);

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    snapshot_ts     TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL,
    inserted_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snapshots_run_id ON snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts     ON snapshots(snapshot_ts);
"""


def get_connection(db_path: str | os.PathLike) -> sqlite3.Connection:
    """Open (or create) a SQLite database at db_path.

    Parent directories are created if absent. Callers are responsible for
    closing the returned connection.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the observations/snapshots tables if they do not exist.

    Idempotent: safe to call repeatedly.
    """
    conn.executescript(_SCHEMA)
    conn.commit()


def _require(row: Mapping[str, Any], keys: tuple[str, ...]) -> None:
    missing = [k for k in keys if k not in row or row[k] is None]
    if missing:
        raise ValueError(f"missing required chronology keys: {missing}")


def log_observation(conn: sqlite3.Connection, row: Mapping[str, Any]) -> int:
    """Insert one observation row.

    Required keys: ts (ISO-8601 string), source (non-empty string),
    payload_json (string — caller pre-serializes). Optional: run_id.
    Returns the inserted row id.
    """
    _require(row, ("ts", "source", "payload_json"))
    cur = conn.execute(
        "INSERT INTO observations(ts, source, payload_json, run_id) "
        "VALUES (?, ?, ?, ?)",
        (
            str(row["ts"]),
            str(row["source"]),
            str(row["payload_json"]),
            row.get("run_id"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def log_snapshot(
    conn: sqlite3.Connection,
    run_id: str,
    snapshot: Mapping[str, Any],
) -> int:
    """Persist a runtime snapshot payload keyed by run_id.

    snapshot_ts is taken from snapshot['timestamp'] if present, else
    snapshot['snapshot_ts'], else an empty string. Returns the inserted row id.
    """
    snapshot_ts = (
        snapshot.get("timestamp")
        or snapshot.get("snapshot_ts")
        or ""
    )
    cur = conn.execute(
        "INSERT INTO snapshots(run_id, snapshot_ts, payload_json) "
        "VALUES (?, ?, ?)",
        (str(run_id), str(snapshot_ts), json.dumps(dict(snapshot), sort_keys=True)),
    )
    conn.commit()
    return int(cur.lastrowid)
