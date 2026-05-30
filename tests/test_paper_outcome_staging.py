"""Tests — canonical paper_outcome_staging table + helpers (Workstream A).

Proves the schema is idempotent, a valid closed outcome stages, a duplicate
(same content key) is skipped not doubled, open trades are detectable, and
every staged row carries the advisory / no-execution / real-money-prohibited
stamps.  No fabricated outcomes; real-money sizing PROHIBITED.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.external_evidence_persistence as eep
import scripts.paper_outcome_staging as staging
from scripts.paper_outcome_intake import validate_outcome


def _valid_record(**overrides):
    raw = {
        "trade_id": "T-1",
        "signal_id": "S-1",
        "ticker": "AAPL",
        "entry_timestamp_utc": "2026-05-01T00:00:00Z",
        "exit_timestamp_utc": "2026-05-06T00:00:00Z",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "exit_reason": "target",
        "realized_return_pct": 10.0,
        "realized_r_multiple": 2.0,
        "outcome_y_0_or_1": 1,
        "proof_status": "PAPER_VERIFIED",
    }
    raw.update(overrides)
    return validate_outcome(raw)


def _staged(db: Path):
    return staging.load_staging_rows(db)


# --- 1: schema idempotent ----------------------------------------------------
def test_staging_schema_idempotent(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    conn = eep._open(db)
    # Running ensure twice must not raise or duplicate the table.
    eep.ensure_external_evidence_schema(conn)
    eep.ensure_external_evidence_schema(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(paper_outcome_staging)")}
    conn.close()
    assert {"staging_key", "trade_id", "ticker", "valid_for_calibration"} <= cols


# --- 2: staging inserts a valid paper outcome --------------------------------
def test_staging_inserts_valid_outcome(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    row = staging.build_staging_row(_valid_record(), link_status="AUTO_LINK", link_confidence=0.95)
    assert staging.insert_staging_row(row, db_path=db) == "inserted"
    rows = _staged(db)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "T-1"
    assert rows[0]["valid_for_calibration"] == 1
    assert rows[0]["link_status"] == "AUTO_LINK"
    # Auto-linked + valid → no outstanding operator review.
    assert rows[0]["operator_review_required"] == 0


# --- 3: staging skips a duplicate (same content key) -------------------------
def test_staging_skips_duplicate(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    row = staging.build_staging_row(_valid_record())
    assert staging.insert_staging_row(row, db_path=db) == "inserted"
    # Same content → same staging_key → skipped, never doubled.
    assert staging.insert_staging_row(row, db_path=db) == "skipped_duplicate"
    assert len(_staged(db)) == 1

    # A different price changes the content hash → a new (distinct) row.
    other = staging.build_staging_row(_valid_record(exit_price=120.0, realized_return_pct=20.0))
    assert other["staging_key"] != row["staging_key"]


# --- 4: staging preserves advisory / no-execution stamps ---------------------
def test_staging_preserves_advisory_stamps(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    staging.insert_staging_row(staging.build_staging_row(_valid_record()), db_path=db)
    r = _staged(db)[0]
    assert r["advisory_only"] == 1
    assert r["human_execution_required"] == 1
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] == 0
    assert r["ai_execution_count"] == 0
    assert r["real_money_sizing_impact"] == "PROHIBITED"
    assert r["real_money_weight_allowed"] == 0


# --- open-trade detection (never staged as closed) ---------------------------
def test_is_open_outcome_detects_missing_exit():
    open_rec = _valid_record(exit_price=None, exit_timestamp_utc="")
    assert staging.is_open_outcome(open_rec) is True
    closed_rec = _valid_record()
    assert staging.is_open_outcome(closed_rec) is False


# --- count_staging summary is honest -----------------------------------------
def test_count_staging_summary(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    staging.insert_staging_row(
        staging.build_staging_row(_valid_record(), link_status="AUTO_LINK"), db_path=db
    )
    summary = staging.count_staging(db)
    assert summary["staged_outcomes_count"] == 1
    assert summary["valid_count"] == 1
    assert summary["auto_link_count"] == 1
    assert summary["calibration_ready_count"] == 1
    assert summary["real_money_sizing_impact"] == "PROHIBITED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
