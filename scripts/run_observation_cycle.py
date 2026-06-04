"""Full chronology observation cycle (T1-T4) — OBSERVATION-ONLY, fail-closed.

Runs the T1-T4 detectors over ``signal_candidates`` in a chronology SQLite
store, writes one ``chronology_events`` row per detector evaluation, and
recomputes ``pattern_hit_rates`` honestly from the events table (observation
frequencies only — never a PnL or edge claim).

HARD SAFETY BOUNDARIES (ast-test enforced):
    * Observation events + observation statistics ONLY.
    * Imports no action_engine / execution / broker / order code.
    * Emits no BUY/SELL/ENTER/EXECUTE/ORDER and authorizes no action.
    * Fails CLOSED on missing db / table / candidates.

NOT on the diagnostics orchestrator path. Manual / batch observation tool.
Readiness stays observation-gated — see docs/CHRONOLOGY_OBSERVATION_READINESS.md.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

try:
    from scripts import chronology_store as cs
    from scripts.chronology_detectors import (
        detect_t1_event_prior,
        detect_t2_asset_attachment,
        detect_t3_commitment,
        detect_t4_market_confirmation,
    )
except ModuleNotFoundError:  # pragma: no cover - script-path fallback
    import chronology_store as cs
    from chronology_detectors import (
        detect_t1_event_prior,
        detect_t2_asset_attachment,
        detect_t3_commitment,
        detect_t4_market_confirmation,
    )

EVENT_CLASSES = {
    "T1": "T1_event_prior",
    "T2": "T2_persistence",
    "T3": "T3_contradiction",
    "T4": "T4_outcome",
}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _prior_t1_history(conn: sqlite3.Connection, candidate_id: str) -> list[bool]:
    rows = conn.execute(
        "SELECT payload_json FROM chronology_events "
        "WHERE candidate_id=? AND event_class=? ORDER BY id ASC",
        (candidate_id, EVENT_CLASSES["T1"]),
    ).fetchall()
    history: list[bool] = []
    for (payload_json,) in rows:
        try:
            history.append(bool(json.loads(payload_json).get("detected")))
        except (json.JSONDecodeError, TypeError, AttributeError):
            history.append(False)
    return history


def _write_event(conn, candidate_id, klass, ts, result) -> None:
    cs.log_chronology_event(
        conn,
        {
            "candidate_id": str(candidate_id),
            "event_class": klass,
            "event_ts": str(ts),
            "payload_json": json.dumps(
                {
                    "detected": result.detected,
                    "status": result.status,
                    "reason": result.reason,
                    "evidence": result.evidence,
                },
                sort_keys=True,
            ),
        },
    )


def _recompute_pattern_hit_rates(conn: sqlite3.Connection) -> None:
    """Honest observation frequencies recomputed from the events table.

    For each detector class, observations = events of that class, hits = events
    whose payload ``detected`` is true. ``hit_rate`` stays NULL at zero (store
    enforces this). This is an observation frequency, NOT a performance claim.
    """
    for klass in EVENT_CLASSES.values():
        rows = conn.execute(
            "SELECT payload_json FROM chronology_events WHERE event_class=?", (klass,)
        ).fetchall()
        observations = len(rows)
        hits = 0
        for (payload_json,) in rows:
            try:
                if json.loads(payload_json).get("detected"):
                    hits += 1
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        cs.upsert_pattern_hit_rate(
            conn,
            {"pattern_id": klass, "observations_count": observations, "hits_count": hits},
        )


def run_full_observation_cycle(conn: sqlite3.Connection) -> dict[str, Any]:
    """Run T1-T4 over all signal_candidates. Observation-only; fail-closed."""
    if not _table_exists(conn, "signal_candidates"):
        return {"status": "NO_TABLE", "evaluated": 0,
                "note": "signal_candidates table absent; nothing observed."}

    rows = conn.execute(
        "SELECT candidate_id, ticker, payload_json FROM signal_candidates ORDER BY id ASC"
    ).fetchall()
    if not rows:
        return {"status": "NO_CANDIDATES", "evaluated": 0,
                "note": "no signal_candidates to observe."}

    counts = {"t1_fired": 0, "t2_fired": 0, "t3_fired": 0, "t4_attributed": 0,
              "t4_pending": 0, "insufficient": 0}
    evaluated = 0
    for candidate_id, _ticker, payload_json in rows:
        try:
            obs = json.loads(payload_json) if payload_json else {}
        except (json.JSONDecodeError, TypeError):
            obs = {}
        if not isinstance(obs, dict):
            obs = {}
        ts = str(obs.get("observed_at") or "")
        evaluated += 1

        t1 = detect_t1_event_prior(obs)
        _write_event(conn, candidate_id, EVENT_CLASSES["T1"], ts, t1)
        if t1.detected:
            counts["t1_fired"] += 1
        if t1.status == "INSUFFICIENT_DATA":
            counts["insufficient"] += 1

        # T2 persistence uses the candidate's full T1 history (incl. the row
        # just written) so repeats accumulate across cycles.
        history = _prior_t1_history(conn, str(candidate_id))
        t2 = detect_t2_asset_attachment(history)
        _write_event(conn, candidate_id, EVENT_CLASSES["T2"], ts, t2)
        if t2.detected:
            counts["t2_fired"] += 1

        t3 = detect_t3_commitment(obs)
        _write_event(conn, candidate_id, EVENT_CLASSES["T3"], ts, t3)
        if t3.detected:
            counts["t3_fired"] += 1

        t4 = detect_t4_market_confirmation(obs)
        _write_event(conn, candidate_id, EVENT_CLASSES["T4"], ts, t4)
        if t4.status == "OUTCOME_ATTRIBUTED":
            counts["t4_attributed"] += 1
        elif t4.status == "OUTCOME_PENDING":
            counts["t4_pending"] += 1

    _recompute_pattern_hit_rates(conn)
    return {"status": "OBSERVED", "evaluated": evaluated, **counts,
            "note": "Observation frequencies only. No action authorized."}


def run_from_db_path(db_path: str) -> dict[str, Any]:
    conn = cs.get_connection(db_path)
    try:
        cs.init_schema(conn)
        return run_full_observation_cycle(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one full chronology observation cycle (T1-T4, observation-only)."
    )
    parser.add_argument("--db", required=True, help="Path to the chronology SQLite db.")
    args = parser.parse_args(argv)
    summary = run_from_db_path(args.db)
    print(json.dumps(summary, indent=2))
    # Exit non-zero only for real errors (none here); empty observation is OK.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
