"""Tests — calibration corpus builder (Workstream C).

Proves the dry-run-first pipeline: dry-run reports only and writes nothing,
--apply records only valid + closed + auto-linked outcomes, open trades are
skipped (never recorded), and the record/bucket update is idempotent.  No
fabricated outcomes; real-money sizing PROHIBITED.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.external_evidence_persistence as eep
from scripts.calibration_corpus_builder import run_corpus_build

GEN_AT = "2026-05-22T10:00:00+00:00"


def _persist_snapshot(db: Path, *, signal_id="S-1", ticker="AAPL"):
    item = {
        "source_name": "kronos",
        "evidence_type": "CANDLESTICK_FORECAST",
        "status": "ACCEPTED_EVIDENCE_ONLY",
        "route_decision": "WATCH",
        "execution_permission": "WATCH_ONLY",
        "score_delta": 0.12,
        "proof_status": "ACCEPTED_EVIDENCE_ONLY",
        "payload_summary": {
            "KRONOS_STATUS": "SUPPORTIVE",
            "KRONOS_FORECAST_RETURN_PCT": 5.0,
            "KRONOS_CONFIDENCE_CALIBRATED": 0.6,
        },
    }
    bundle = {
        "external_evidence_enabled": True,
        "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
        "external_evidence_items": [item],
        "generated_at_utc": GEN_AT,
    }
    eep.persist_external_evidence_bundle(
        bundle, {"signal_id": signal_id, "ticker": ticker}, db_path=db
    )


def _sheet_row(**overrides):
    row = {
        "TRADE_ID": "T-1",
        "SIGNAL_ID": "S-1",
        "TICKER": "AAPL",
        "ENTRY_TIMESTAMP_UTC": "2026-05-23T00:00:00Z",
        "EXIT_TIMESTAMP_UTC": "2026-05-25T00:00:00Z",
        "BUY PRICE": "100.0",
        "SELL PRICE": "110.0",
        "EXIT_REASON": "target",
        "REALIZED_RETURN_%": "10.0",
        "OUTCOME_Y_0_OR_1": "1",
        "PROOF_STATUS": "PAPER_VERIFIED",
    }
    row.update(overrides)
    return row


def _outcomes(db: Path):
    conn = eep._open(db)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM external_evidence_outcomes"
        )]
    finally:
        conn.close()


def _buckets(db: Path):
    conn = eep._open(db)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM external_evidence_calibration_buckets"
        )]
    finally:
        conn.close()


def _staged(db: Path):
    conn = eep._open(db)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM paper_outcome_staging"
        )]
    finally:
        conn.close()


# --- 9: dry-run reports only, writes nothing --------------------------------
def test_corpus_builder_dry_run_reports_only(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    _persist_snapshot(db)

    report = run_corpus_build([_sheet_row()], apply=False, db_path=db)
    assert report["mode"] == "DRY_RUN"
    assert report["rows_seen"] == 1
    assert report["valid_for_calibration"] == 1
    assert report["linked_auto"] == 1
    assert report["outcomes_recorded"] == 0
    # Nothing written to the advisory outcome table.
    assert _outcomes(db) == []
    assert report["real_money_sizing_impact"] == "PROHIBITED"


# --- 10: apply records only valid + linked closed outcomes ------------------
def test_corpus_builder_apply_records_valid_linked(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    _persist_snapshot(db)

    report = run_corpus_build([_sheet_row()], apply=True, db_path=db)
    assert report["mode"] == "APPLY"
    assert report["linked_auto"] == 1
    assert report["outcomes_recorded"] == 1
    assert report["buckets_updated"] == 1
    rows = _outcomes(db)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "T-1"
    assert rows[0]["real_money_sizing_impact"] == "PROHIBITED"


# --- 11: open trades are skipped (never recorded) ---------------------------
def test_corpus_builder_skips_open_trades(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    _persist_snapshot(db)

    # No exit price + no exit timestamp → an open trade; intake never validates.
    open_row = _sheet_row()
    del open_row["SELL PRICE"]
    del open_row["EXIT_TIMESTAMP_UTC"]

    report = run_corpus_build([open_row], apply=True, db_path=db)
    assert report["valid_for_calibration"] == 0
    assert report["skipped_open_or_invalid"] >= 1
    assert report["outcomes_recorded"] == 0
    assert _outcomes(db) == []


# --- 12: bucket update is idempotent ----------------------------------------
def test_corpus_builder_idempotent_buckets(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    _persist_snapshot(db)

    first = run_corpus_build([_sheet_row()], apply=True, db_path=db)
    assert first["outcomes_recorded"] == 1
    buckets_after_first = _buckets(db)
    assert len(buckets_after_first) == 1
    assert buckets_after_first[0]["sample_count"] == 1

    # Re-running the same row records nothing new and leaves the bucket intact.
    second = run_corpus_build([_sheet_row()], apply=True, db_path=db)
    assert second["outcomes_recorded"] == 0
    assert second["buckets_updated"] == 0
    buckets_after_second = _buckets(db)
    assert len(buckets_after_second) == 1
    assert buckets_after_second[0]["sample_count"] == 1
    assert len(_outcomes(db)) == 1


# --- 11: builder dry-run simulates staging (writes nothing) -----------------
def test_corpus_builder_dry_run_simulates_staging(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    _persist_snapshot(db)

    report = run_corpus_build([_sheet_row()], apply=False, db_path=db)
    assert report["mode"] == "DRY_RUN"
    # Dry-run simulates the staging count but writes nothing.
    assert report["staged_count"] == 1
    assert _staged(db) == []


# --- 12: builder apply writes staging + advisory outcomes idempotently ------
def test_corpus_builder_apply_stages_idempotently(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    _persist_snapshot(db)

    first = run_corpus_build([_sheet_row()], apply=True, db_path=db)
    assert first["staged_count"] == 1
    assert first["outcomes_recorded"] == 1
    staged = _staged(db)
    assert len(staged) == 1
    assert staged[0]["trade_id"] == "T-1"
    assert staged[0]["link_status"] == "AUTO_LINK"
    assert staged[0]["moltbook_learning_status"] == "RECORDED"
    assert staged[0]["real_money_sizing_impact"] == "PROHIBITED"

    # Re-running the same row stages nothing new (idempotent content key).
    second = run_corpus_build([_sheet_row()], apply=True, db_path=db)
    assert second["staged_count"] == 0
    assert second["staged_skipped_duplicate"] == 1
    assert len(_staged(db)) == 1


# --- 13: builder skips open trades (never staged) ---------------------------
def test_corpus_builder_open_trade_not_staged(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    _persist_snapshot(db)

    open_row = _sheet_row()
    del open_row["SELL PRICE"]
    del open_row["EXIT_TIMESTAMP_UTC"]

    report = run_corpus_build([open_row], apply=True, db_path=db)
    assert report["staged_count"] == 0
    assert _staged(db) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
