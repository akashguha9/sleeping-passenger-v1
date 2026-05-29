"""External-evidence calibration backfill — dry-run + idempotent apply proofs."""
from __future__ import annotations

from pathlib import Path

import scripts.persistence as persistence
import scripts.external_evidence_persistence as eep
import scripts.external_evidence_calibration_backfill as backfill

GEN_AT = "2026-05-22T10:00:00+00:00"
RUN_DATE = "2026-05-22"


def _seed_closed_trade_with_snapshot(
    db: Path,
    *,
    trade_id="T1",
    event_id="EV1",
    ticker="AAPL",
    entry=100.0,
    exit_=110.0,
    reconciled_at="2026-05-25T10:00:00+00:00",
):
    persistence.insert_manual_trade(
        trade_id, event_id, ticker, "BUY", 10.0, entry,
        "2026-05-22T09:00:00+00:00", "thesis", "notes", "human",
        db_path=db,
    )
    persistence.insert_reconciliation(
        f"REC_{trade_id}", trade_id, event_id, reconciled_at,
        exit_, 10.0, "closed", (exit_ - entry) * 10.0, "CLOSED",
        db_path=db,
    )
    item = {
        "source_name": "kronos",
        "evidence_type": "CANDLESTICK_FORECAST",
        "status": "ACCEPTED_EVIDENCE_ONLY",
        "route_decision": "WATCH",
        "execution_permission": "WATCH_ONLY",
        "score_delta": 0.12,
        "alignment_score": 1.0,
        "reliability_weight": 0.8,
        "router_safety_multiplier": 0.25,
        "evidence_quality_multiplier": 0.7,
        "proof_status": "ACCEPTED_EVIDENCE_ONLY",
        "reason": "test",
        "payload_summary": {
            "KRONOS_FORECAST_RETURN_PCT": 5.0,
            "KRONOS_CONFIDENCE_CALIBRATED": 0.6,
            "KRONOS_DOWNSIDE_PATH_RISK": 0.1,
            "KRONOS_MODE": "stub_safe",
        },
    }
    bundle = {
        "external_evidence_enabled": True,
        "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
        "external_evidence_items": [item],
        "generated_at_utc": GEN_AT,
    }
    eep.persist_external_evidence_bundle(
        bundle,
        {"daily_run_id": RUN_DATE, "signal_id": event_id, "ticker": ticker},
        db_path=db,
    )


def _count(db: Path, table: str) -> int:
    conn = eep._open(db)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------- test 16
def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _seed_closed_trade_with_snapshot(db)
    report = backfill.run_backfill(apply=False, db_path=db)
    assert report["dry_run"] is True
    assert report["scanned_trades"] == 1
    assert report["records_would_create"] == 1
    assert report["records_created"] == 0
    # Nothing written.
    assert _count(db, "external_evidence_outcomes") == 0
    assert _count(db, "external_evidence_calibration_buckets") == 0
    # Safety stamps in the report.
    assert report["real_money_sizing_impact"] == "PROHIBITED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0


# ---------------------------------------------------------------------- test 17
def test_backfill_apply_writes_idempotently(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _seed_closed_trade_with_snapshot(db)

    first = backfill.run_backfill(apply=True, db_path=db)
    assert first["records_created"] == 1
    assert first["buckets_updated"] == 1
    assert _count(db, "external_evidence_outcomes") == 1
    assert _count(db, "external_evidence_calibration_buckets") == 1

    # Second apply creates zero duplicates.
    second = backfill.run_backfill(apply=True, db_path=db)
    assert second["records_created"] == 0
    assert _count(db, "external_evidence_outcomes") == 1
    assert _count(db, "external_evidence_calibration_buckets") == 1


# ----------------------------------------------------------- open trade guard
def test_backfill_does_not_touch_trades_or_open_positions(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    _seed_closed_trade_with_snapshot(db)
    trades_before = persistence.get_all_manual_trades(db_path=db)
    backfill.run_backfill(apply=True, db_path=db)
    trades_after = persistence.get_all_manual_trades(db_path=db)
    # The backfill never mutates trade rows.
    assert trades_before == trades_after
