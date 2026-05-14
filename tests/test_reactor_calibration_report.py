"""Tests for ``scripts.reactor_calibration_report``.

Pins
----
- Missing DB returns a graceful payload with db_available=False.
- Confidence band thresholds map correctly: 0/9/29/99/100/200.
- The report NEVER unlocks execution.
- The report lists ``reactor_at_decision_fields_not_persisted`` as a
  limitation today, because no migration has added those columns.
- Honest non-claims appear in the payload.
- CLI runs both json and text modes; no DB writes.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import reactor_calibration_report as rcr


def _make_db(db: Path, *, reconciled_n: int = 0, manual_n: int | None = None) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    if manual_n is None:
        manual_n = max(reconciled_n, 0)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT, ticker TEXT, side TEXT, quantity REAL, price REAL,
                executed_at TEXT, thesis TEXT DEFAULT '', notes TEXT DEFAULT '',
                invalidation_level TEXT DEFAULT '',
                expected_horizon TEXT DEFAULT '',
                risk_reason TEXT DEFAULT '',
                entry_reason TEXT DEFAULT '',
                exit_plan TEXT DEFAULT '',
                confidence_before REAL,
                emotional_state TEXT DEFAULT '',
                mistake_tags TEXT DEFAULT '',
                lesson TEXT DEFAULT ''
            );
            CREATE TABLE reconciliation_results (
                reconciliation_id TEXT PRIMARY KEY,
                trade_id TEXT, event_id TEXT,
                reconciled_at TEXT, actual_fill_price REAL, actual_quantity REAL,
                outcome_notes TEXT DEFAULT '', pnl_estimate REAL DEFAULT 0.0,
                outcome_status TEXT DEFAULT 'UNKNOWN',
                outcome_quality TEXT DEFAULT '',
                process_error TEXT DEFAULT '',
                process_error_notes TEXT DEFAULT '',
                mistake_tags TEXT DEFAULT '',
                lesson TEXT DEFAULT ''
            );
            """
        )
        for i in range(manual_n):
            conn.execute(
                "INSERT INTO manual_trades (trade_id, event_id, ticker, side, quantity, price,"
                " executed_at, thesis) VALUES (?,?,?,?,?,?,?,?)",
                (f"T{i}", f"EV{i}", "QQQ", "BUY", 10, 100.0,
                 "2026-05-10T00:00:00Z", "test"),
            )
        for i in range(reconciled_n):
            conn.execute(
                "INSERT INTO reconciliation_results (reconciliation_id, trade_id, event_id,"
                " reconciled_at, actual_fill_price, actual_quantity, outcome_notes,"
                " pnl_estimate, outcome_status) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"R{i}", f"T{i}", f"EV{i}", "2026-05-11T00:00:00Z", 100.5, 10,
                 "ok", 5.0, "WIN" if i % 2 == 0 else "LOSS"),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Confidence band thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "very_low"),
        (9, "very_low"),
        (10, "low"),
        (29, "low"),
        (30, "medium"),
        (99, "medium"),
        (100, "higher_but_contextual"),
        (250, "higher_but_contextual"),
    ],
)
def test_confidence_band_maps_correctly(n, expected):
    assert rcr._confidence_band(n) == expected


# ---------------------------------------------------------------------------
# Empty / missing DB
# ---------------------------------------------------------------------------


def test_missing_db_returns_graceful_payload(tmp_path):
    payload = rcr.build_report(tmp_path / "absent.db")
    assert payload["db_available"] is False
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False
    assert "db_missing" in payload["limitations"]


def test_empty_db_yields_very_low_confidence(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=0)
    payload = rcr.build_report(db)
    assert payload["db_available"] is True
    assert payload["reconciled_count"] == 0
    assert payload["confidence_band"] == "very_low"
    assert "no_reconciled_trades_yet" in payload["limitations"]
    assert "sample_size_too_small_for_calibration_claims" in payload["limitations"]


# ---------------------------------------------------------------------------
# Confidence transitions on real data
# ---------------------------------------------------------------------------


def test_low_band_when_some_data_present(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=12)
    payload = rcr.build_report(db)
    assert payload["reconciled_count"] == 12
    assert payload["confidence_band"] == "low"


def test_medium_band_at_30(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=30)
    payload = rcr.build_report(db)
    assert payload["confidence_band"] == "medium"


def test_higher_band_at_100(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=100)
    payload = rcr.build_report(db)
    assert payload["confidence_band"] == "higher_but_contextual"


# ---------------------------------------------------------------------------
# Safety contract
# ---------------------------------------------------------------------------


def test_calibration_never_unlocks_execution(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=150)
    payload = rcr.build_report(db)
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False


def test_payload_has_explicit_non_claims(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=5)
    payload = rcr.build_report(db)
    assert "non_claims" in payload
    nc_blob = " ".join(payload["non_claims"]).lower()
    # Honest non-claims must explicitly admit what is NOT computed.
    assert "reactor_hit_rate" in nc_blob
    assert "gallardo_block" in nc_blob
    assert "calibration" in nc_blob


def test_missing_decision_fields_are_reported(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=5)
    payload = rcr.build_report(db)
    # No migration has added these columns; the report should list them.
    assert payload["missing_decision_fields"]
    assert "reactor_state_at_decision" in payload["missing_decision_fields"]
    assert (
        "reactor_at_decision_fields_not_persisted" in payload["limitations"]
    )


# ---------------------------------------------------------------------------
# Read-only / no DB writes
# ---------------------------------------------------------------------------


def test_build_report_does_not_write_db(tmp_path):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=3)
    size_before = db.stat().st_size
    mtime_before = db.stat().st_mtime
    rcr.build_report(db)
    assert db.stat().st_size == size_before
    assert db.stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_json_mode(tmp_path, capsys):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=2)
    rc = rcr.main(["--db-path", str(db), "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["advisory_status"] == "ADVISORY_ONLY"
    assert parsed["execution_gate"] == "LOCKED"
    assert rc in (0, 1)


def test_cli_text_mode(tmp_path, capsys):
    db = tmp_path / "mvp.db"
    _make_db(db, reconciled_n=2)
    rcr.main(["--db-path", str(db)])
    out = capsys.readouterr().out
    assert "Reactor Calibration Report" in out
    assert "Confidence band" in out
    assert "ADVISORY" in out or "advisory" in out


def test_cli_returns_nonzero_when_db_missing(tmp_path):
    rc = rcr.main(["--db-path", str(tmp_path / "absent.db")])
    assert rc != 0
