"""Tests: rows_persisted health axis (Close-the-Loop sprint, audit SP-016).

Kalshi/Polymarket persisted ZERO rows for 11 days while every run reported
"Source healthy (filtered)".  With the last-persisted axis supplied, that
silence must classify as ZERO_PERSISTED_DEGRADED (severity warning) — never
"ok".  Without the axis (legacy callers), behavior is unchanged.
"""
from __future__ import annotations

from scripts.source_health_summary import build_source_health_summary


def _run_row(source: str, status: str = "OK_FILTERED") -> dict:
    return {
        "source_name": source,
        "status": status,
        "skipped_reason": "",
        "error_message": "",
        "fetched_count": 75,
        "duration_ms": 900,
        "timestamp_utc": "2026-07-04T10:00:00Z",
    }


def test_ok_filtered_with_recent_persist_stays_ok() -> None:
    summary = build_source_health_summary(
        [_run_row("kalshi")],
        {"kalshi": 100},
        last_persisted_at={"kalshi": "2026-07-03T10:00:00Z"},
        now_utc="2026-07-04T10:00:00Z",
    )
    row = next(s for s in summary["sources"] if s["source_name"] == "kalshi")
    assert row["severity"] == "ok"
    assert row["category"] == "OK_FILTERED"
    assert row["persist_age_days"] == 1.0


def test_ok_filtered_with_11_day_silence_is_degraded() -> None:
    summary = build_source_health_summary(
        [_run_row("kalshi")],
        {"kalshi": 100},
        last_persisted_at={"kalshi": "2026-06-22T07:37:00Z"},
        now_utc="2026-07-03T16:00:00Z",
    )
    row = next(s for s in summary["sources"] if s["source_name"] == "kalshi")
    assert row["severity"] == "warning"
    assert row["category"] == "ZERO_PERSISTED_DEGRADED"
    assert "DEGRADED" in row["human_message"]


def test_never_persisted_source_is_degraded() -> None:
    summary = build_source_health_summary(
        [_run_row("polymarket", status="OK")],
        {"polymarket": 0},
        last_persisted_at={},  # no entry: never persisted anything
        now_utc="2026-07-04T10:00:00Z",
    )
    row = next(s for s in summary["sources"] if s["source_name"] == "polymarket")
    assert row["severity"] == "warning"
    assert row["category"] == "ZERO_PERSISTED_DEGRADED"
    assert "ever" in row["human_message"]


def test_error_statuses_not_masked_by_axis() -> None:
    summary = build_source_health_summary(
        [_run_row("gdelt", status="TIMEOUT")],
        {"gdelt": 5},
        last_persisted_at={"gdelt": "2026-07-04T09:00:00Z"},
        now_utc="2026-07-04T10:00:00Z",
    )
    row = next(s for s in summary["sources"] if s["source_name"] == "gdelt")
    assert row["severity"] != "ok"


def test_legacy_callers_without_axis_unchanged() -> None:
    summary = build_source_health_summary([_run_row("kalshi")], {"kalshi": 100})
    row = next(s for s in summary["sources"] if s["source_name"] == "kalshi")
    assert row["severity"] == "ok"
    assert row["category"] == "OK_FILTERED"
    assert row["last_persisted_at"] is None
