"""Chronology observation-cycle runner — OBSERVATION-ONLY, fail-closed.

Reads ``signal_candidates`` from a chronology SQLite store, evaluates the T1
event-prior detector over each candidate's payload, records the outcome as a
``chronology_events`` row, and updates the ``T1_event_prior`` observation
statistics in ``pattern_hit_rates``.

HARD SAFETY BOUNDARIES (enforced by tests):
    * Produces observation events + observation statistics ONLY.
    * Never imports or calls action_engine / execution / broker code.
    * Never emits BUY/ENTER or any order.
    * Never authorizes action or touches governance flags.
    * Fails CLOSED: missing db / table / candidates -> structured no-op, never
      a fabricated detection.

This runner is NOT on the diagnostics orchestrator path. It is a manual /
batch observation tool. Readiness remains observation-gated — see
docs/CHRONOLOGY_OBSERVATION_READINESS.md.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

try:
    from scripts import chronology_store as cs
    from scripts.chronology_detectors import detect_t1_event_prior
except ModuleNotFoundError:  # pragma: no cover - script-path fallback
    import chronology_store as cs
    from chronology_detectors import detect_t1_event_prior

T1_PATTERN_ID = "T1_event_prior"
T1_EVENT_CLASS = "T1_event_prior"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def run_observation_cycle(conn: sqlite3.Connection) -> dict[str, Any]:
    """Evaluate T1 over all signal_candidates. Observation-only; fail-closed.

    Returns a structured summary. Writes one chronology_event per evaluated
    candidate and upserts the T1 observation statistics. Writes nothing and
    reports ``status=NO_CANDIDATES`` / ``NO_TABLE`` when there is nothing to do.
    """
    if not _table_exists(conn, "signal_candidates"):
        return {
            "status": "NO_TABLE",
            "evaluated": 0,
            "fired": 0,
            "insufficient": 0,
            "note": "signal_candidates table absent; nothing observed.",
        }

    rows = conn.execute(
        "SELECT candidate_id, ticker, payload_json FROM signal_candidates "
        "ORDER BY id ASC"
    ).fetchall()

    if not rows:
        return {
            "status": "NO_CANDIDATES",
            "evaluated": 0,
            "fired": 0,
            "insufficient": 0,
            "note": "no signal_candidates to observe.",
        }

    evaluated = 0
    fired = 0
    insufficient = 0
    for candidate_id, ticker, payload_json in rows:
        try:
            observation = json.loads(payload_json) if payload_json else {}
        except (json.JSONDecodeError, TypeError):
            observation = {}
        if not isinstance(observation, dict):
            observation = {}

        result = detect_t1_event_prior(observation)
        evaluated += 1
        if result.detected:
            fired += 1
        if result.status == "INSUFFICIENT_DATA":
            insufficient += 1

        cs.log_chronology_event(
            conn,
            {
                "candidate_id": str(candidate_id),
                "event_class": T1_EVENT_CLASS,
                "event_ts": str(observation.get("observed_at") or ""),
                "payload_json": json.dumps(
                    {
                        "ticker": ticker,
                        "detected": result.detected,
                        "status": result.status,
                        "reason": result.reason,
                        "evidence": result.evidence,
                    },
                    sort_keys=True,
                ),
            },
        )

    # Observation statistics only — never a performance/edge claim. hit_rate is
    # the fraction of evaluated candidates for which T1 FIRED (an observation
    # frequency), and stays NULL at zero observations (enforced in the store).
    cs.upsert_pattern_hit_rate(
        conn,
        {
            "pattern_id": T1_PATTERN_ID,
            "observations_count": evaluated,
            "hits_count": fired,
        },
    )

    return {
        "status": "OBSERVED",
        "evaluated": evaluated,
        "fired": fired,
        "insufficient": insufficient,
        "note": "Observation frequencies only. No action authorized.",
    }


def run_from_db_path(db_path: str) -> dict[str, Any]:
    """Open ``db_path`` read/write, ensure schema, run one observation cycle."""
    conn = cs.get_connection(db_path)
    try:
        cs.init_schema(conn)
        return run_observation_cycle(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one chronology T1 observation cycle (observation-only)."
    )
    parser.add_argument("--db", required=True, help="Path to the chronology SQLite db.")
    args = parser.parse_args(argv)
    print(json.dumps(run_from_db_path(args.db), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
