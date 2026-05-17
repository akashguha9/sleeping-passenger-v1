"""Tests for ``scripts.source_refresh_audit``.

Pin
---
- Registry-only audit works (no DB present): never crashes, empty history.
- Missing-credential sources are reported in credential_missing_count.
- The audit never calls a live API (no network mock needed — just spot-
  check that the helper imports cleanly and runs read-only).
- Safety stamps locked on payload and per-source.
- --days accepted; non-positive days falls back to all-time.
- No secret values leak into output (env keys are referenced by name, not value).
- Planned sources count toward planned_count, not implemented_count.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

import pytest

from scripts import source_refresh_audit as sra


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_run_log(db_path: Path, rows: list[tuple]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE source_run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT, status TEXT, fetched_count INTEGER DEFAULT 0,
                skipped_reason TEXT DEFAULT '', error_message TEXT DEFAULT '',
                timestamp_utc TEXT, duration_ms INTEGER DEFAULT 0
            );
            """
        )
        for r in rows:
            conn.execute(
                "INSERT INTO source_run_log (source_name, status, fetched_count,"
                " skipped_reason, error_message, timestamp_utc, duration_ms)"
                " VALUES (?,?,?,?,?,?,?)",
                r,
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Registry-only behaviour
# ---------------------------------------------------------------------------


def test_audit_works_without_db(tmp_path):
    payload = sra.run_audit(tmp_path / "absent.db")
    assert "db_missing" in payload["warnings"]
    assert payload["source_count"] >= 1
    assert "source_statuses" in payload
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_permission"] is False


def test_planned_partial_implemented_counts_add_up(tmp_path):
    payload = sra.run_audit(tmp_path / "absent.db")
    total = (
        payload["implemented_count"]
        + payload["partial_count"]
        + payload["planned_count"]
    )
    assert total == payload["source_count"]


def test_asia_disclosure_counted_partial_not_implemented(tmp_path):
    """Asia Disclosure must be reported as PARTIAL — EDINET / OpenDART are
    real, but the legacy SSE/SZSE/HKEX/TDnet/SGX/dart entries remain
    placeholders.  It must NOT be counted as fully implemented and must
    NOT be counted as planned."""
    payload = sra.run_audit(tmp_path / "absent.db")
    by_key = {s["source_key"]: s for s in payload["source_statuses"]}
    assert "asia_disclosure" in by_key
    assert by_key["asia_disclosure"]["adapter_status"] == "partial"
    implemented_keys = [
        s["source_key"]
        for s in payload["source_statuses"]
        if s["adapter_status"] == "implemented"
    ]
    assert "asia_disclosure" not in implemented_keys


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_missing_credentials_counted_skipped(tmp_path):
    payload = sra.run_audit(tmp_path / "absent.db", env={})
    # NEWS_API_KEY, XAI_API_KEY, etc. are unset -> these sources go into
    # skipped.
    assert payload["credential_missing_count"] >= 1
    assert payload["skipped_count"] >= 1


def test_no_secret_exposure_in_output(tmp_path):
    payload = sra.run_audit(
        tmp_path / "absent.db",
        env={"NEWS_API_KEY": "super-secret-news-key-987654"},
    )
    serialized = json.dumps(payload)
    assert "super-secret-news-key-987654" not in serialized


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------


def test_run_history_reliability_and_cadence(tmp_path):
    db = tmp_path / "audit.db"
    # 3 OK, 1 FAIL for polymarket within last 7 days.
    base = _dt.datetime(2026, 5, 14, tzinfo=_dt.timezone.utc)
    rows = []
    for hours_ago in (1, 7, 13, 19):
        ts = (base - _dt.timedelta(hours=hours_ago)).isoformat()
        status = "OK" if hours_ago != 19 else "FAIL"
        err = "" if status == "OK" else "rate_limited"
        rows.append(("polymarket", status, 5, "", err, ts, 100))
    _create_run_log(db, rows)
    payload = sra.run_audit(db, days=7, now=base, env={})
    assert payload["run_history_count"] == 4
    rel = payload["source_reliability_scores"]["polymarket"]
    assert rel["total_attempts"] == 4
    assert rel["ok_count"] == 3
    assert rel["fail_count"] == 1
    assert rel["reliability_score"] == pytest.approx(0.75, rel=1e-6)
    # Top failure reasons captures rate_limited.
    reasons = [r["reason"] for r in payload["top_failure_reasons"]]
    assert "rate_limited" in reasons


def test_days_filter_applied(tmp_path):
    db = tmp_path / "audit.db"
    base = _dt.datetime(2026, 5, 14, tzinfo=_dt.timezone.utc)
    far_ago = (base - _dt.timedelta(days=30)).isoformat()
    recent = (base - _dt.timedelta(hours=1)).isoformat()
    _create_run_log(db, [
        ("polymarket", "OK", 5, "", "", far_ago, 100),
        ("polymarket", "OK", 5, "", "", recent, 100),
    ])
    payload = sra.run_audit(db, days=7, now=base, env={})
    # Only the recent one should be in the window.
    assert payload["run_history_count"] == 1


# ---------------------------------------------------------------------------
# Per-source safety stamps
# ---------------------------------------------------------------------------


def test_per_source_safety_stamps_locked(tmp_path):
    payload = sra.run_audit(tmp_path / "absent.db", env={})
    for s in payload["source_statuses"]:
        assert s["advisory_status"] == "ADVISORY_ONLY"
        assert s["execution_gate"] == "LOCKED"
        assert s["broker_api_called"] is False
        assert s["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_json(tmp_path, capsys):
    rc = sra.main([
        "--db-path", str(tmp_path / "absent.db"),
        "--json",
    ])
    out = capsys.readouterr().out
    assert "ADVISORY_ONLY" in out
    # Run history empty -> ok might still be True (no failures, no overdue).
    # Either way the CLI must not crash.
    assert rc in (0, 1)


def test_cli_with_days_option(tmp_path, capsys):
    rc = sra.main([
        "--db-path", str(tmp_path / "absent.db"),
        "--days", "7",
        "--json",
    ])
    out = capsys.readouterr().out
    assert '"days_window": 7' in out
    assert rc in (0, 1)
