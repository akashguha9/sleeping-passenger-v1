"""Phase 3 — daily decision snapshots carry horizon + price-based target."""
from __future__ import annotations

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_market_bar,
    seed_score_vector,
)
from scripts.forward_snapshot_contract import (
    DEFAULT_TARGET_EVENT_DEFINITION,
    PRICE_BASED_TARGETS,
    TARGET_SOURCE,
    horizon_close_utc,
)
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_NOW = "2026-05-10T00:00:00Z"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _run(db, events):
    return run_daily_decision_batch(db_path=db, events=events, now_iso=_NOW, write=True)


def test_daily_decision_snapshot_sets_default_5_day_horizon(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["prediction_horizon_days"] == 5


def test_daily_decision_snapshot_sets_forward_return_target(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["target_event_definition"] == DEFAULT_TARGET_EVENT_DEFINITION
    assert snap["target_event_definition"] in PRICE_BASED_TARGETS


def test_target_threshold_default_is_zero(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["target_return_threshold"] == 0.0


def test_target_source_is_explicit(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    summary = _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["target_source"] == TARGET_SOURCE == "DEFAULT_FORWARD_SNAPSHOT_CONTRACT_V1"
    assert summary["target_source"] == TARGET_SOURCE


def test_horizon_close_computed_from_decision_timestamp(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["horizon_close_utc"] == "2026-05-15T00:00:00Z"
    assert snap["horizon_close_utc"] == horizon_close_utc(_NOW, 5)


def test_live_decision_timestamp_not_backdated(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    # The live decision timestamp is "now" (the batch clock), never moved back,
    # and the horizon close is strictly after the decision timestamp.
    assert snap["timestamp_utc"] == _NOW
    assert snap["horizon_close_utc"] > snap["timestamp_utc"]


def test_prediction_horizon_required_for_forward_eligibility(db):
    # A complete row (ticker + horizon + price target + entry price) is eligible;
    # its horizon is present and positive.
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["prediction_horizon_days"] == 5
    assert snap["forward_outcome_eligible"] == 1


def test_manual_reconciliation_target_not_used_for_forward_calibration(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    # The forward batch never stamps a manual/reconciliation target.
    assert snap["target_event_definition"] != "manual_trade_reconciliation_win_loss"
    assert "manual" not in snap["target_event_definition"]
