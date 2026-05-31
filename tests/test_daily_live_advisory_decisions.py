"""Tests — daily live advisory decision batch (Phase 4).

Deterministic, offline.  Proves the batch records probability snapshots from
fresh canonical rows, grows ``n_valid_p`` only for rows that carry a real score
vector, preserves advisory-only safety, never executes, and reports block
reasons + the no-fresh-rows case honestly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_daily_live_advisory_decisions import (
    NO_FRESH_ROWS,
    extract_axes,
    run_daily_decision_batch,
)
from scripts.decision_probability_snapshot import count_valid_p


_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.45, "LS": 0.5, "EFS": 0.5, "APS": 0.5}


def _event(event_id: str, *, with_axes: bool = True, **extra) -> dict:
    payload = {"headline": "x"}
    if with_axes:
        payload["axes"] = dict(_AXES)
    return {"event_id": event_id, "source_name": "test", "raw_payload": payload, **extra}


def _assert_locked(summary: dict) -> None:
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["human_execution_required"] is True
    assert summary["predictive_claim_allowed"] is False


# --- 1. records a snapshot from fixture rows ------------------------------ #

def test_daily_decision_batch_records_probability_snapshot_from_fixture_rows(tmp_path):
    db = tmp_path / "mvp.db"
    events = [_event("E1"), _event("E2")]
    summary = run_daily_decision_batch(db_path=db, events=events, write=True)
    assert summary["decisions_attempted"] == 2
    assert summary["decisions_recorded"] == 2
    # The snapshots were persisted with a valid model_probability.
    assert count_valid_p(db) == 2


# --- 2. increments n_valid_p ---------------------------------------------- #

def test_batch_increments_n_valid_p(tmp_path):
    db = tmp_path / "mvp.db"
    summary = run_daily_decision_batch(
        db_path=db, events=[_event("A"), _event("B"), _event("C")], write=True
    )
    assert summary["n_valid_p_before"] == 0
    assert summary["n_valid_p_after"] == 3
    assert summary["delta_n_valid_p"] == 3


def test_rows_without_score_vector_do_not_grow_valid_p(tmp_path):
    db = tmp_path / "mvp.db"
    events = [_event("NOAXES", with_axes=False)]
    summary = run_daily_decision_batch(db_path=db, events=events, write=True)
    # Recorded (honest audit) but NULL probability => no valid_p.
    assert summary["decisions_recorded"] == 1
    assert summary["delta_n_valid_p"] == 0
    assert count_valid_p(db) == 0


# --- 3. preserves advisory-only stamps ------------------------------------ #

def test_batch_preserves_advisory_only_stamps(tmp_path):
    db = tmp_path / "mvp.db"
    summary = run_daily_decision_batch(db_path=db, events=[_event("S")], write=True)
    _assert_locked(summary)


# --- 4. does not execute or create orders --------------------------------- #

def test_batch_does_not_execute_or_create_orders(tmp_path):
    import json

    db = tmp_path / "mvp.db"
    summary = run_daily_decision_batch(db_path=db, events=[_event("S")], write=True)
    blob = json.dumps(summary).lower()
    for word in ("place order", "broker_execute", "buy now", "sell now", "execute trade"):
        assert word not in blob
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


# --- 5. reports no-fresh-rows truthfully ---------------------------------- #

def test_batch_reports_no_fresh_rows_truthfully(tmp_path):
    db = tmp_path / "mvp.db"
    summary = run_daily_decision_batch(db_path=db, events=[], write=True)
    assert summary["decisions_recorded"] == 0
    assert summary["delta_n_valid_p"] == 0
    assert summary["reason"] == NO_FRESH_ROWS
    _assert_locked(summary)


# --- 6. counts block reasons ---------------------------------------------- #

def test_batch_summary_counts_block_reasons(tmp_path):
    db = tmp_path / "mvp.db"
    # No capital context => capacity is UNKNOWN => every decision is capacity-blocked.
    summary = run_daily_decision_batch(
        db_path=db, events=[_event("A"), _event("B")], write=True
    )
    assert summary["blocked_by_capacity"] == 2
    assert summary["blocked_by_freshness"] >= 0
    assert summary["blocked_by_moltbook"] >= 0


# --- 7. predictive claim stays locked below the gate ---------------------- #

def test_batch_predictive_claim_stays_locked_below_gate(tmp_path):
    db = tmp_path / "mvp.db"
    summary = run_daily_decision_batch(
        db_path=db, events=[_event(f"E{i}") for i in range(5)], write=True
    )
    assert summary["predictive_claim_allowed"] is False
    assert count_valid_p(db) == 5  # far below the N=200 gate


# --- axes extraction unit ------------------------------------------------- #

def test_extract_axes_from_nested_and_top_level():
    assert extract_axes({"axes": _AXES}) == {k: float(v) for k, v in _AXES.items()}
    assert extract_axes({"score_vector": _AXES}) is not None
    assert extract_axes(dict(_AXES)) is not None
    assert extract_axes({"headline": "no axes"}) is None
    # incomplete vector -> None (never fabricate)
    assert extract_axes({"EMS": 0.5}) is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
