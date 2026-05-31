"""Phase 6 — daily batch produces forward-eligible / pending-horizon snapshots."""
from __future__ import annotations

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_market_bar,
    seed_score_vector,
)
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_NOW = "2026-05-10T00:00:00Z"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _seed_priceable(db, event_id="ev1", ticker="AAPL"):
    seed_score_vector(db, event_id=event_id, ticker=ticker)
    seed_market_bar(db, symbol=ticker, timestamp="2026-05-09T00:00:00Z", close=190.0)


def _run(db, events):
    return run_daily_decision_batch(db_path=db, events=events, now_iso=_NOW, write=True)


def test_batch_creates_forward_eligible_snapshot_from_scored_row_with_price(db):
    _seed_priceable(db)
    summary = _run(db, [event_row("ev1", payload={})])
    assert summary["forward_outcome_eligible_count"] == 1
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["forward_outcome_eligible"] == 1
    assert snap["ticker"] == "AAPL"
    assert snap["entry_price"] == 190.0


def test_batch_creates_pending_horizon_for_new_live_snapshot(db):
    _seed_priceable(db)
    summary = _run(db, [event_row("ev1", payload={})])
    # A brand-new live decision's 5-day horizon has not elapsed -> pending.
    assert summary["n_pending_horizon"] == 1
    assert summary["forward_outcome_eligible_count"] == 1


def test_batch_does_not_backdate_snapshot_to_force_outcome(db):
    _seed_priceable(db)
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    # The decision timestamp equals the batch clock (now), never moved back, and
    # no outcome is attached by the decision batch itself.
    assert snap["timestamp_utc"] == _NOW
    assert snap["outcome_label"] is None


def test_batch_counts_ticker_horizon_target_entry_price(db):
    _seed_priceable(db, "ev1", "AAPL")
    seed_score_vector(db, event_id="ev2", ticker="NVDA")  # no price bars for NVDA
    summary = _run(db, [event_row("ev1", payload={}), event_row("ev2", payload={})])
    assert summary["decisions_recorded"] == 2
    assert summary["ticker_present_count"] == 2
    assert summary["horizon_present_count"] == 2
    assert summary["price_target_present_count"] == 2
    assert summary["entry_price_present_count"] == 1  # only AAPL had a bar


def test_batch_reports_forward_unavailable_reasons(db):
    seed_score_vector(db, event_id="ev2", ticker="NVDA")  # no price -> MISSING_ENTRY_PRICE
    summary = _run(db, [event_row("ev2", payload={})])
    assert summary["forward_outcome_eligible_count"] == 0
    assert summary["forward_outcome_ineligible_count"] == 1
    assert summary["forward_outcome_unavailable_reasons"].get("MISSING_ENTRY_PRICE") == 1


def test_batch_preserves_predictive_claim_locked(db):
    _seed_priceable(db)
    summary = _run(db, [event_row("ev1", payload={})])
    assert summary["predictive_claim_allowed"] is False
    assert summary["calibration_status"] == "INSUFFICIENT_EVIDENCE"


def test_batch_no_execution_fields_unlocked(db):
    _seed_priceable(db)
    summary = _run(db, [event_row("ev1", payload={})])
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["human_execution_required"] is True
