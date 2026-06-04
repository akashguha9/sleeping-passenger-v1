"""Chronology replay / backfill lab — deterministic, honestly-labelled.

Replays observation events over chronology data and classifies every row's
provenance into exactly one of:

    FORWARD_REAL        — a genuine forward observation captured live over time
    HISTORICAL_BACKFILL — reconstructed from historical/persisted data
    SYNTHETIC_TEST      — fabricated/seeded fixture data

HARD HONESTY RULES (test-enforced):
    * Historical or synthetic data is NEVER relabelled FORWARD_REAL.
    * The conservative default for an unlabelled row is SYNTHETIC_TEST — the
      lab never *assumes* a row is forward-real.
    * Replay summary (structural) is kept SEPARATE from forward-observation
      confidence. Replaying backfill/synthetic data raises structural coverage
      only; it does not earn confidence.

Imports no action_engine / execution / broker code. Authorizes nothing.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

try:
    from scripts import chronology_store as cs
    from scripts import run_observation_cycle as roc
except ModuleNotFoundError:  # pragma: no cover - script-path fallback
    import chronology_store as cs
    import run_observation_cycle as roc

FORWARD_REAL = "FORWARD_REAL"
HISTORICAL_BACKFILL = "HISTORICAL_BACKFILL"
SYNTHETIC_TEST = "SYNTHETIC_TEST"
VALID_LABELS = (FORWARD_REAL, HISTORICAL_BACKFILL, SYNTHETIC_TEST)


def classify_data_origin(row_payload: dict[str, Any]) -> str:
    """Classify one candidate's provenance. Conservative: defaults SYNTHETIC_TEST.

    A row may declare its origin via ``data_origin`` (validated against
    VALID_LABELS). An unknown/absent value is treated as SYNTHETIC_TEST — the
    lab refuses to upgrade unlabelled data to FORWARD_REAL.
    """
    declared = str((row_payload or {}).get("data_origin") or "").strip().upper()
    if declared in VALID_LABELS:
        return declared
    return SYNTHETIC_TEST


def origin_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Count signal_candidates by provenance label."""
    counts = {label: 0 for label in VALID_LABELS}
    if not roc._table_exists(conn, "signal_candidates"):
        return counts
    rows = conn.execute("SELECT payload_json FROM signal_candidates").fetchall()
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        counts[classify_data_origin(payload if isinstance(payload, dict) else {})] += 1
    return counts


def build_replay_report(conn: sqlite3.Connection) -> dict[str, Any]:
    """Replay the observation cycle deterministically + honest readiness.

    Structural coverage (did the cycle run end-to-end) is reported SEPARATELY
    from forward-observation confidence (only FORWARD_REAL rows count toward
    earned confidence).
    """
    counts = origin_counts(conn)
    cycle = roc.run_full_observation_cycle(conn)

    forward_real = counts[FORWARD_REAL]
    structural_ran = cycle.get("status") == "OBSERVED"

    # Observation-mode state is honest about what is and is not earned.
    if forward_real > 0:
        observation_state = "FORWARD_OBSERVATIONS_PRESENT"
        confidence_note = (
            f"{forward_real} forward-real observations present; confidence may "
            "begin to accrue (still requires accumulation over time)."
        )
    elif structural_ran:
        observation_state = "STRUCTURAL_REPLAY_ONLY"
        confidence_note = (
            "Cycle ran end-to-end on backfill/synthetic data only. Structural "
            "readiness demonstrated; NO forward-observation confidence earned."
        )
    else:
        observation_state = "NO_OBSERVATIONS"
        confidence_note = "No candidates to observe."

    return {
        "origin_counts": counts,
        "total_candidates": sum(counts.values()),
        "forward_real_count": forward_real,
        "structural_cycle": cycle,
        "observation_state": observation_state,
        "confidence_note": confidence_note,
        "earned_forward_confidence": forward_real > 0,
        "note": (
            "Replaying HISTORICAL_BACKFILL / SYNTHETIC_TEST data is structural "
            "only and is never counted as forward-real observation."
        ),
    }


def run_from_db_path(db_path: str) -> dict[str, Any]:
    conn = cs.get_connection(db_path)
    try:
        cs.init_schema(conn)
        return build_replay_report(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic chronology replay lab with honest provenance labels."
    )
    parser.add_argument("--db", required=True, help="Path to the chronology SQLite db.")
    args = parser.parse_args(argv)
    print(json.dumps(run_from_db_path(args.db), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
