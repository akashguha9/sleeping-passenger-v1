"""chronology_store — SQLite-backed observation log + designed-table scaffold.

Scope (v0 — live):
    * explicit db_path parametrization (no hardcoded logs/observation.db)
    * idempotent schema creation
    * thin insert helpers for observations and snapshot rows

Scope (v1 — SCAFFOLD ONLY, observation-gated):
    The three designed chronology tables (signal_candidates, chronology_events,
    pattern_hit_rates) now exist as empty schema. They are created additively
    (IF NOT EXISTS) alongside the v0 observations/snapshots tables, which are
    preserved unchanged. NO detector populates them yet, and NO inference runs.
    Readiness must be EARNED by forward observation — see
    docs/CHRONOLOGY_OBSERVATION_READINESS.md. The presence of these tables is
    NOT a claim of chronology capability; it is structural scaffolding only.

What this module intentionally does NOT do:
    * invent chronology or backfill from nothing
    * run any inference or implement T1/T2/T3/T4 detection
      (see scripts/chronology_detectors.py — all NOT_IMPLEMENTED / fail-closed)
    * wire itself into any execution path
    * authorize any action

Public API:
    get_connection(db_path) -> sqlite3.Connection
    init_schema(conn) -> None
    log_observation(conn, row) -> int
    log_snapshot(conn, run_id, snapshot) -> int
    log_signal_candidate(conn, row) -> int           # scaffold
    log_chronology_event(conn, row) -> int            # scaffold
    upsert_pattern_hit_rate(conn, row) -> None         # scaffold
    list_tables(conn) -> list[str]
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

-- v1 designed-table SCAFFOLD (observation-gated; populated by nothing yet).
-- These exist so forward observations have a home. Empty until detectors are
-- earned. See docs/CHRONOLOGY_OBSERVATION_READINESS.md.
CREATE TABLE IF NOT EXISTS signal_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id    TEXT    NOT NULL,
    ticker          TEXT    NOT NULL,
    first_seen_ts   TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    coarse_class    TEXT,
    run_id          TEXT,
    payload_json    TEXT    NOT NULL,
    inserted_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_signal_candidates_candidate ON signal_candidates(candidate_id);
CREATE INDEX IF NOT EXISTS idx_signal_candidates_ticker    ON signal_candidates(ticker);

CREATE TABLE IF NOT EXISTS chronology_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id    TEXT    NOT NULL,
    event_class     TEXT    NOT NULL,
    event_ts        TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL,
    run_id          TEXT,
    inserted_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chronology_events_candidate ON chronology_events(candidate_id);
CREATE INDEX IF NOT EXISTS idx_chronology_events_class     ON chronology_events(event_class);

CREATE TABLE IF NOT EXISTS pattern_hit_rates (
    pattern_id          TEXT    PRIMARY KEY,
    observations_count  INTEGER NOT NULL DEFAULT 0,
    hits_count          INTEGER NOT NULL DEFAULT 0,
    hit_rate            REAL,
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
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


def list_tables(conn: sqlite3.Connection) -> list[str]:
    """Return the sorted list of table names (read-only helper)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------
# v1 designed-table scaffold inserts (fail-closed; populated by nothing yet).
# These exist so that, WHEN forward observations are earned, there is a typed,
# validated home for them. They run no inference and authorize no action.
# --------------------------------------------------------------------------


def log_signal_candidate(conn: sqlite3.Connection, row: Mapping[str, Any]) -> int:
    """Insert one signal_candidate. Fail-closed on missing required keys.

    Required: candidate_id, ticker, first_seen_ts, source, payload_json.
    Optional: coarse_class, run_id.
    """
    _require(row, ("candidate_id", "ticker", "first_seen_ts", "source", "payload_json"))
    cur = conn.execute(
        "INSERT INTO signal_candidates"
        "(candidate_id, ticker, first_seen_ts, source, coarse_class, run_id, payload_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            str(row["candidate_id"]),
            str(row["ticker"]),
            str(row["first_seen_ts"]),
            str(row["source"]),
            row.get("coarse_class"),
            row.get("run_id"),
            str(row["payload_json"]),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def log_chronology_event(conn: sqlite3.Connection, row: Mapping[str, Any]) -> int:
    """Insert one chronology_event. Fail-closed on missing required keys.

    Required: candidate_id, event_class, event_ts, payload_json.
    Optional: run_id.
    """
    _require(row, ("candidate_id", "event_class", "event_ts", "payload_json"))
    cur = conn.execute(
        "INSERT INTO chronology_events"
        "(candidate_id, event_class, event_ts, payload_json, run_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            str(row["candidate_id"]),
            str(row["event_class"]),
            str(row["event_ts"]),
            str(row["payload_json"]),
            row.get("run_id"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def upsert_pattern_hit_rate(conn: sqlite3.Connection, row: Mapping[str, Any]) -> None:
    """Upsert one pattern_hit_rate row. Fail-closed on missing required keys.

    Required: pattern_id, observations_count, hits_count. hit_rate is derived
    (hits/observations) and never fabricated when observations_count == 0.
    """
    _require(row, ("pattern_id", "observations_count", "hits_count"))
    observations = int(row["observations_count"])
    hits = int(row["hits_count"])
    hit_rate = (hits / observations) if observations > 0 else None
    conn.execute(
        "INSERT INTO pattern_hit_rates"
        "(pattern_id, observations_count, hits_count, hit_rate, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(pattern_id) DO UPDATE SET "
        "observations_count=excluded.observations_count, "
        "hits_count=excluded.hits_count, hit_rate=excluded.hit_rate, "
        "updated_at=excluded.updated_at",
        (str(row["pattern_id"]), observations, hits, hit_rate),
    )
    conn.commit()
