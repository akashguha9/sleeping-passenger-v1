"""Tests: evidence maturity calendar (Open-the-Gate sprint, spec Item 6)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts.evidence_calendar import build_evidence_calendar

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)

DDL = (
    "CREATE TABLE decision_probability_snapshots ("
    "snapshot_id TEXT PRIMARY KEY, timestamp_utc TEXT, ticker TEXT,"
    "model_probability REAL, outcome_label INTEGER, is_real_outcome INTEGER,"
    "forward_outcome_eligible INTEGER, horizon_close_utc TEXT)"
)


def _db(tmp_path: Path, rows: list[tuple]) -> Path:
    db = tmp_path / "cal.db"
    conn = sqlite3.connect(db)
    conn.execute(DDL)
    conn.executemany(
        "INSERT INTO decision_probability_snapshots VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db


def _row(sid, ts, label, real, eligible, close):
    return (sid, ts, "SPY", 0.55, label, real, eligible, close)


def test_calendar_computes_projection_correctly(tmp_path: Path) -> None:
    db = _db(tmp_path, [
        # 2 matured outcomes
        _row("m1", "2026-05-31T15:00:00Z", 1, 1, 1, "2026-06-05T15:00:00Z"),
        _row("m2", "2026-05-31T15:00:00Z", 0, 1, 1, "2026-06-05T15:00:00Z"),
        # 3 pending: 2 mature on 07-09, 1 on 07-11
        _row("p1", "2026-07-04T10:00:00Z", None, None, 1, "2026-07-09T10:00:00Z"),
        _row("p2", "2026-07-04T10:00:00Z", None, None, 1, "2026-07-09T10:00:00Z"),
        _row("p3", "2026-07-06T10:00:00Z", None, None, 1, "2026-07-11T10:00:00Z"),
        # ineligible row must not count anywhere
        _row("x1", "2026-07-04T10:00:00Z", None, None, 0, "2026-07-09T10:00:00Z"),
    ])
    cal = build_evidence_calendar(db_path=db, now_utc=NOW, next_days=14)
    assert cal["status"] == "OK"
    assert cal["matured_outcomes_total"] == 2
    assert cal["pending_horizon"] == 3
    assert cal["due_unmatured"] == 0
    assert cal["next_maturity_date"] == "2026-07-09"
    by_date = {s["date"]: s for s in cal["schedule"]}
    assert by_date["2026-07-09"]["newly_matureable"] == 2
    assert by_date["2026-07-09"]["projected_n"] == 4
    assert by_date["2026-07-11"]["newly_matureable"] == 1
    assert by_date["2026-07-11"]["projected_n"] == 5
    assert cal["projected_n_end_of_window"] == 5


def test_no_future_outcome_is_marked_matured(tmp_path: Path) -> None:
    db = _db(tmp_path, [
        _row("p1", "2026-07-04T10:00:00Z", None, None, 1,
             "2026-07-09T10:00:00Z"),
    ])
    cal = build_evidence_calendar(db_path=db, now_utc=NOW, next_days=14)
    # the projection changes NOTHING in the DB and matured stays 0
    assert cal["matured_outcomes_total"] == 0
    conn = sqlite3.connect(db)
    labels = conn.execute(
        "SELECT outcome_label FROM decision_probability_snapshots"
    ).fetchall()
    conn.close()
    assert labels == [(None,)], "projection must never write an outcome"


def test_duplicate_predictions_not_counted_twice(tmp_path: Path) -> None:
    # same snapshot appears once (PK); a prediction matures once in the plan
    db = _db(tmp_path, [
        _row("p1", "2026-07-04T10:00:00Z", None, None, 1,
             "2026-07-06T10:00:00Z"),
    ])
    cal = build_evidence_calendar(db_path=db, now_utc=NOW, next_days=14)
    total_newly = sum(s["newly_matureable"] for s in cal["schedule"])
    assert total_newly == 1


def test_projection_does_not_alter_real_n(tmp_path: Path) -> None:
    db = _db(tmp_path, [
        _row("m1", "2026-05-31T15:00:00Z", 1, 1, 1, "2026-06-05T15:00:00Z"),
        _row("p1", "2026-07-04T10:00:00Z", None, None, 1,
             "2026-07-09T10:00:00Z"),
    ])
    before = build_evidence_calendar(db_path=db, now_utc=NOW)
    after = build_evidence_calendar(db_path=db, now_utc=NOW)
    assert before["matured_outcomes_total"] == after["matured_outcomes_total"] == 1
    assert after["projected_n_end_of_window"] == 2  # projection, not reality
