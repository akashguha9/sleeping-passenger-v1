"""Legacy timestamp migration proofs (Pass 6, Phase 2)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from scripts import migrate_legacy_timestamps as mig


@pytest.fixture
def db(tmp_path, monkeypatch):
    import scripts.persistence as persistence

    path = tmp_path / "db.sqlite"
    monkeypatch.setattr(persistence, "DB_PATH", path, raising=False)
    persistence.init_schema(path)
    monkeypatch.setenv("MVP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO reconciliation_results (reconciliation_id, trade_id,"
        " event_id, reconciled_at, actual_fill_price, actual_quantity,"
        " outcome_notes, pnl_estimate, outcome_status)"
        " VALUES ('R_NAIVE','T1','E1','2026-05-01T10:00:00',100,1,'',1,'WIN')"
    )
    conn.execute(
        "INSERT INTO reconciliation_results (reconciliation_id, trade_id,"
        " event_id, reconciled_at, actual_fill_price, actual_quantity,"
        " outcome_notes, pnl_estimate, outcome_status)"
        " VALUES ('R_AWARE','T2','E2','2026-05-01T10:00:00+00:00',100,1,'',1,'WIN')"
    )
    conn.execute(
        "INSERT INTO reconciliation_results (reconciliation_id, trade_id,"
        " event_id, reconciled_at, actual_fill_price, actual_quantity,"
        " outcome_notes, pnl_estimate, outcome_status)"
        " VALUES ('R_BAD','T3','E3','not-a-date',100,1,'',1,'WIN')"
    )
    conn.commit()
    conn.close()
    return path


def test_classify_timestamp():
    assert mig.classify_timestamp("2026-05-01T10:00:00") == "naive"
    assert mig.classify_timestamp("2026-05-01T10:00:00+00:00") == "aware"
    assert mig.classify_timestamp("2026-05-01T10:00:00Z") == "aware"
    assert mig.classify_timestamp("garbage") == "unparsable"
    assert mig.classify_timestamp("") == "empty"


def test_scan_detects_naive_and_uncertain(db):
    report = mig.scan(db)
    recon = report["tables"]["reconciliation_results"]
    assert {e["pk"] for e in recon["naive"]} == {"R_NAIVE"}
    assert {e["pk"] for e in recon["temporal_uncertain"]} == {"R_BAD"}
    assert recon["aware"] == 1


def test_naive_conversion_requires_explicit_timezone(db):
    report = mig.migrate(db, apply=True, assume_timezone=None)
    assert "refusal" in report
    assert report["converted"] == 0
    # Nothing was touched.
    assert mig.scan(db)["naive_total"] == 1


def test_dry_run_writes_no_changes(db):
    report = mig.migrate(db, assume_timezone="Asia/Kolkata", apply=False)
    assert report["mode"] == "dry_run" and report["converted"] == 0
    assert mig.scan(db)["naive_total"] == 1


def test_conversion_stores_utc_and_is_idempotent(db, tmp_path):
    report = mig.migrate(db, assume_timezone="Asia/Kolkata", apply=True)
    assert report["converted"] == 1
    conn = sqlite3.connect(db)
    value = conn.execute(
        "SELECT reconciled_at FROM reconciliation_results"
        " WHERE reconciliation_id='R_NAIVE'").fetchone()[0]
    conn.close()
    # 10:00 IST == 04:30 UTC.
    assert value == "2026-05-01T04:30:00+00:00"
    # Idempotent: a second run converts nothing, aware rows untouched.
    again = mig.migrate(db, assume_timezone="Asia/Kolkata", apply=True)
    assert again["converted"] == 0
    # Audit event recorded for the applied run.
    audit = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert any(e["action"] == "migrate_legacy_timestamps" for e in audit)


def test_uncertain_rows_never_converted_and_stay_excluded(db):
    mig.migrate(db, assume_timezone="Asia/Kolkata", apply=True)
    conn = sqlite3.connect(db)
    value = conn.execute(
        "SELECT reconciled_at FROM reconciliation_results"
        " WHERE reconciliation_id='R_BAD'").fetchone()[0]
    conn.close()
    assert value == "not-a-date"  # no fabricated precision, ever
    # And score_calibration excludes it (plus any remaining naive rows).
    from scripts.score_calibration import compute_score_calibration

    rows = [{"reconciled_at": "not-a-date", "outcome_status": "WIN"},
            {"reconciled_at": "2026-05-01T04:30:00+00:00",
             "outcome_status": "WIN", "pnl_estimate": 1.0}]
    summary = compute_score_calibration(rows)
    assert summary["temporal_uncertain_excluded"] == 1
    assert summary["sample_size"] == 1


def test_score_calibration_excludes_naive_rows():
    from scripts.score_calibration import compute_score_calibration

    rows = [{"reconciled_at": "2026-05-01T10:00:00", "outcome_status": "WIN"},
            {"reconciled_at": "2026-05-01T10:00:00+05:30",
             "outcome_status": "LOSS", "pnl_estimate": -1.0}]
    summary = compute_score_calibration(rows)
    assert summary["temporal_uncertain_excluded"] == 1
    assert summary["sample_size"] == 1
    assert summary["losses"] == 1
