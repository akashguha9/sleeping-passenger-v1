"""Close the Outcome Loop Sprint — Phase 4 tests.

A real-forward outcome closes the learning loop: a bad outcome creates a
Moltbook failure-pattern entry, a good outcome can record good-process evidence,
duplicates never double-write, and Moltbook feedback never unlocks execution.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import persistence
from scripts.outcome_moltbook_feedback import (
    compute_feedback_idempotency_key,
    is_bad_outcome,
    record_outcome_feedback,
)


def _count_moltbook(db: Path, ticker: str | None = None) -> int:
    return len(persistence.get_moltbook_entries(ticker=ticker, db_path=db))


# --- 1. bad outcome creates a learning event ------------------------------ #

def test_bad_real_forward_outcome_creates_moltbook_learning_event(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    res = record_outcome_feedback(
        decision_id="DPS_BAD_1", ticker="SPY", outcome_y=0,
        realized_return=-0.08, entry_price=100.0, exit_price=92.0,
        outcome_timestamp_utc="2026-01-10T00:00:00Z", scoring_version="v1",
        db_path=db, jsonl_path=tmp_path / "mb.jsonl",
    )
    assert res["bad_outcome"] is True
    assert res["status"] in ("created", "updated")
    assert res["moltbook_entry_id"]
    assert _count_moltbook(db, "SPY") == 1
    assert is_bad_outcome(outcome_y=0) is True


# --- 2. good outcome can record good-process ------------------------------ #

def test_good_real_forward_outcome_can_record_good_process(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    res = record_outcome_feedback(
        decision_id="DPS_GOOD_1", ticker="QQQ", outcome_y=1,
        realized_return=0.06, entry_price=100.0, exit_price=106.0,
        outcome_timestamp_utc="2026-01-10T00:00:00Z", scoring_version="v1",
        record_good_process=True, db_path=db, jsonl_path=tmp_path / "mb.jsonl",
    )
    assert res["bad_outcome"] is False
    assert res["status"] in ("created", "updated")
    assert _count_moltbook(db, "QQQ") == 1

    # With good-process recording disabled, a good outcome writes no entry.
    res2 = record_outcome_feedback(
        decision_id="DPS_GOOD_2", ticker="GLD", outcome_y=1,
        realized_return=0.03, entry_price=100.0, exit_price=103.0,
        outcome_timestamp_utc="2026-01-10T00:00:00Z", scoring_version="v1",
        record_good_process=False, db_path=db, jsonl_path=tmp_path / "mb.jsonl",
    )
    assert res2["status"] == "skipped_good_process_disabled"
    assert _count_moltbook(db, "GLD") == 0


# --- 3. duplicate outcome does not duplicate moltbook --------------------- #

def test_duplicate_outcome_does_not_duplicate_moltbook(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    kwargs = dict(
        decision_id="DPS_DUP", ticker="SPY", outcome_y=0,
        realized_return=-0.05, entry_price=100.0, exit_price=95.0,
        outcome_timestamp_utc="2026-01-10T00:00:00Z", scoring_version="v1",
        db_path=db, jsonl_path=tmp_path / "mb.jsonl",
    )
    first = record_outcome_feedback(**kwargs)
    second = record_outcome_feedback(**kwargs)
    assert first["status"] in ("created", "updated")
    assert second["status"] == "skipped_duplicate"
    assert _count_moltbook(db, "SPY") == 1
    # Same components -> same key.
    k1 = compute_feedback_idempotency_key(
        decision_id="DPS_DUP", outcome_y=0,
        outcome_timestamp_utc="2026-01-10T00:00:00Z", scoring_version="v1")
    assert first["idempotency_key"] == k1 == second["idempotency_key"]


# --- 4. feedback preserves advisory-only ---------------------------------- #

def test_moltbook_feedback_preserves_advisory_only(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    res = record_outcome_feedback(
        decision_id="DPS_ADV", ticker="SPY", outcome_y=0,
        realized_return=-0.02, entry_price=100.0, exit_price=98.0,
        outcome_timestamp_utc="2026-01-10T00:00:00Z", scoring_version="v1",
        db_path=db, jsonl_path=tmp_path / "mb.jsonl",
    )
    assert res["advisory_status"] == "ADVISORY_ONLY"
    assert res["human_execution_required"] is True


# --- 5. feedback does not unlock execution -------------------------------- #

def test_moltbook_feedback_does_not_unlock_execution(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    res = record_outcome_feedback(
        decision_id="DPS_EXE", ticker="SPY", outcome_y=0,
        realized_return=-0.02, entry_price=100.0, exit_price=98.0,
        outcome_timestamp_utc="2026-01-10T00:00:00Z", scoring_version="v1",
        db_path=db, jsonl_path=tmp_path / "mb.jsonl",
    )
    assert res["execution_gate"] == "LOCKED"
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0
    assert res["execution_permission"] is False
    assert res["can_execute"] is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
