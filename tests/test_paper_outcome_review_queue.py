"""Tests — operator review queue (Workstream C).

Proves the read-only review queue surfaces the right blockers (missing
signal_id, bad return math, …), ranks the top blockers by frequency, emits
next operator actions, and never writes / never enables sizing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.paper_outcome_staging as staging
from scripts.paper_outcome_intake import validate_outcome
from scripts.paper_outcome_review_queue import (
    build_from_db,
    build_review_queue,
    row_blockers,
)


def _record(**overrides):
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
        "outcome_y_0_or_1": 1,
        "proof_status": "PAPER_VERIFIED",
    }
    raw.update(overrides)
    return validate_outcome(raw)


def _row(link_status="NO_LINK", **overrides):
    return staging.build_staging_row(_record(**overrides), link_status=link_status)


# --- 8: review queue lists missing signal_id --------------------------------
def test_review_queue_lists_missing_signal_id():
    row = _row(signal_id="")
    blockers = row_blockers(row)
    assert "missing_signal_id" in blockers


# --- 9: review queue lists bad return math ----------------------------------
def test_review_queue_lists_bad_return_math():
    # realized return says 50% but (110-100)/100 = 10% → bad math.
    row = _row(realized_return_pct=50.0)
    blockers = row_blockers(row)
    assert "bad_return_math" in blockers


# --- 10: review queue ranks top blockers ------------------------------------
def test_review_queue_ranks_top_blockers():
    rows = [
        _row(trade_id="A", signal_id=""),  # missing_signal_id
        _row(trade_id="B", signal_id=""),  # missing_signal_id
        _row(trade_id="C", realized_return_pct=99.0),  # bad_return_math
    ]
    report = build_review_queue(rows)
    top = {b["blocker"]: b["count"] for b in report["top_blockers"]}
    # missing_signal_id appears twice → ranks above a single bad_return_math.
    assert top.get("missing_signal_id") == 2
    assert report["top_blockers"][0]["blocker"] != "bad_return_math"
    # No AUTO_LINK rows here → every row needs an evidence link.
    assert report["blocker_counts"]["missing_external_evidence_link"] == 3
    assert report["review_required_count"] >= 1
    assert report["real_money_sizing_impact"] == "PROHIBITED"
    assert report["next_5_operator_actions"]


# --- calibration-ready vs review-required counts ----------------------------
def test_review_queue_calibration_ready_vs_review():
    # A clean, auto-linked, Moltbook-recorded row is calibration-ready.
    ready = staging.build_staging_row(
        _record(), link_status="AUTO_LINK", moltbook_learning_status="RECORDED"
    )
    blocked = _row(trade_id="T-2", signal_id="")
    report = build_review_queue([ready, blocked])
    assert report["calibration_ready_count"] == 1
    assert report["review_required_count"] == 1


# --- build_from_db is read-only and empty-safe ------------------------------
def test_review_queue_from_db_empty_safe(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    report = build_from_db(db)
    assert report["staged_outcomes_count"] == 0
    assert report["calibration_ready_count"] == 0
    assert report["top_blockers"] == []
    assert report["next_5_operator_actions"]  # honest "stage outcomes" guidance


def test_review_queue_from_db_reads_staged(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    staging.insert_staging_row(_row(signal_id=""), db_path=db)
    report = build_from_db(db)
    assert report["staged_outcomes_count"] == 1
    assert "missing_signal_id" in report["blocker_counts"]
    assert report["blocker_counts"]["missing_signal_id"] == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
