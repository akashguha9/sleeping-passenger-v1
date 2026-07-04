"""Evidence maturity calendar — when does N grow, honestly.

Open-the-Gate sprint (2026-07-04).  Matured outcomes sit at N=56 because
nothing is due yet — that is a calendar fact, not a failure.  This module
makes the calendar visible WITHOUT touching a single outcome:

    Maturity_Date(p)        = horizon_close_utc(p)   (locked at snapshot time)
    Projected_N(T)          = N_current + count(p: now < Maturity_Date(p) <= T)
    Evidence_Velocity_7d    = locked_forward_predictions_last_7d / 7

Read-only over ``decision_probability_snapshots``.  Nothing here can mature,
re-label, or duplicate a prediction; the projection never alters real N.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

CALIBRATION_GATE_N = 200


def build_evidence_calendar(
    *,
    db_path: Any = None,
    now_utc: datetime | None = None,
    next_days: int = 14,
) -> dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    db = db_path if db_path is not None else persistence.DB_PATH
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    report: dict[str, Any] = {
        "report": "evidence_calendar",
        "generated_at_utc": now_iso,
        "window_days": next_days,
        "locked_predictions_total": 0,
        "forward_eligible_total": 0,
        "matured_outcomes_total": 0,
        "pending_horizon": 0,
        "due_unmatured": 0,
        "evidence_velocity_7d": 0.0,
        "next_maturity_date": None,
        "schedule": [],
        **advisory_safety_stamps(),
    }
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        report["status"] = "DB_UNAVAILABLE"
        return report
    try:
        report["locked_predictions_total"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots"
        ).fetchone()[0])
        report["forward_eligible_total"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE forward_outcome_eligible = 1"
        ).fetchone()[0])
        report["matured_outcomes_total"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE is_real_outcome = 1 AND outcome_label IN (0,1)"
        ).fetchone()[0])
        report["due_unmatured"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE forward_outcome_eligible = 1 AND outcome_label IS NULL "
            "AND horizon_close_utc <= ?", (now_iso,),
        ).fetchone()[0])
        report["pending_horizon"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE forward_outcome_eligible = 1 AND outcome_label IS NULL "
            "AND horizon_close_utc > ?", (now_iso,),
        ).fetchone()[0])
        cutoff7 = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        locked_7d = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE forward_outcome_eligible = 1 AND timestamp_utc >= ?",
            (cutoff7,),
        ).fetchone()[0])
        report["evidence_velocity_7d"] = round(locked_7d / 7.0, 3)

        pending = conn.execute(
            "SELECT DISTINCT snapshot_id, horizon_close_utc FROM "
            "decision_probability_snapshots WHERE forward_outcome_eligible=1 "
            "AND outcome_label IS NULL AND horizon_close_utc > ? "
            "ORDER BY horizon_close_utc", (now_iso,),
        ).fetchall()
    except sqlite3.Error as exc:
        report["status"] = f"QUERY_ERROR:{type(exc).__name__}"
        return report
    finally:
        conn.close()

    n_current = report["matured_outcomes_total"]
    if pending:
        report["next_maturity_date"] = str(pending[0][1])[:10]
    schedule: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for day in range(1, next_days + 1):
        t = now + timedelta(days=day)
        t_iso = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        due_by_t = 0
        for sid, close in pending:
            if sid in seen_ids:
                continue  # a prediction matures exactly once in a projection
            if str(close) <= t_iso:
                seen_ids.add(sid)
                due_by_t += 1
        if due_by_t or day in (1, next_days):
            schedule.append({
                "date": t.strftime("%Y-%m-%d"),
                "newly_matureable": due_by_t,
                "projected_n": n_current + len(seen_ids)
                + report["due_unmatured"],
            })
    report["schedule"] = schedule
    projected_end = (
        n_current + report["due_unmatured"] + len(seen_ids)
    )
    report["projected_n_end_of_window"] = projected_end
    report["n_81_by_2026_07_09"] = bool(
        any(s["date"] >= "2026-07-09" and s["projected_n"] >= 81
            for s in schedule)
        or (n_current + report["due_unmatured"] >= 81)
    )
    velocity = report["evidence_velocity_7d"]
    days_to_200 = (
        round((CALIBRATION_GATE_N - projected_end) / velocity)
        if velocity > 0 and projected_end < CALIBRATION_GATE_N
        else 0 if projected_end >= CALIBRATION_GATE_N else None
    )
    report["days_to_n200_at_current_velocity"] = days_to_200
    report["n200_plausible_at_current_velocity"] = days_to_200 is not None
    report["status"] = "OK"
    return report


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--next", type=int, default=14, metavar="DAYS")
    p.add_argument("--db")
    args = p.parse_args(argv)
    report = build_evidence_calendar(db_path=args.db, next_days=args.next)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("status") == "OK" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
