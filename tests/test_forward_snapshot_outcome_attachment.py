"""Phase 7 — forward snapshots attach real outcomes after the horizon closes."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_market_bar,
    seed_score_vector,
)
from scripts.attach_due_outcomes import REASON_MISSING_EXIT_PRICE, attach_due_outcomes
from scripts.real_price_outcome_evidence import build_real_price_evidence
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_NOW = "2026-05-10T00:00:00Z"          # decision time
_AFTER_HORIZON = "2026-05-20T00:00:00Z"  # well past the 5-day horizon close
_BEFORE_HORIZON = "2026-05-12T00:00:00Z"  # horizon (05-15) not yet closed


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _make_eligible_snapshot(db, *, exit_close: float, event_id="ev1", ticker="AAPL"):
    """Seed a scored, priceable row and create one forward-eligible snapshot."""
    seed_score_vector(db, event_id=event_id, ticker=ticker)
    seed_market_bar(db, symbol=ticker, timestamp="2026-05-09T00:00:00Z", close=190.0)
    # Exit bar at the horizon close (decision 05-10 + 5d = 05-15).
    seed_market_bar(db, symbol=ticker, timestamp="2026-05-15T00:00:00Z", close=exit_close)
    run_daily_decision_batch(db_path=db, events=[event_row(event_id, payload={})],
                             now_iso=_NOW, write=True)


def test_due_forward_snapshot_attaches_y_one(db):
    _make_eligible_snapshot(db, exit_close=200.0)  # up -> y=1
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True,
    )
    assert summary["outcomes_attached"] == 1
    assert summary["delta_n_real_forward"] == 1
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["outcome_label"] == 1
    assert snap["outcome_kind"] == "real_forward"
    assert snap["is_real_outcome"] == 1


def test_due_forward_snapshot_attaches_y_zero(db):
    _make_eligible_snapshot(db, exit_close=180.0)  # down -> y=0
    attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True,
    )
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["outcome_label"] == 0


def test_not_due_forward_snapshot_remains_pending(db):
    _make_eligible_snapshot(db, exit_close=200.0)
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_BEFORE_HORIZON, write=True,
    )
    assert summary["outcomes_attached"] == 0
    assert summary["pending_horizon"] == 1
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["outcome_label"] is None


def test_missing_exit_price_excluded(db):
    # A due eligible snapshot, but the evidence map has entry without an exit.
    _make_eligible_snapshot(db, exit_close=200.0)
    snap = read_snapshot(db, signal_id="ev1")
    summary = attach_due_outcomes(
        db_path=db,
        evidence_by_id={snap["snapshot_id"]: {"entry_price": 190.0}},  # no exit_price
        now_utc=_AFTER_HORIZON, write=True,
    )
    assert summary["outcomes_attached"] == 0
    assert summary["excluded_missing_exit_price"] == 1
    assert any(d.get("reason") == REASON_MISSING_EXIT_PRICE for d in summary["details"])


def test_exit_price_after_horizon_not_used(db):
    # build_real_price_evidence must use the on/before-close bar as exit, never a
    # bar dated after the horizon close.
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-25T00:00:00Z", close=999.0)
    from scripts.real_price_outcome_evidence import load_price_series

    series = load_price_series(db, symbols={"AAPL"})
    snap = {"ticker": "AAPL", "timestamp_utc": _NOW, "prediction_horizon_days": 5}
    ev = build_real_price_evidence(
        snap, series, now_utc=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    assert ev is not None
    # exit is the 05-09 bar (last on/before the 05-15 close), NOT the 05-25 bar.
    assert ev["exit_price"] == 190.0
    assert ev["exit_price"] != 999.0


def test_real_forward_pair_counts_only_when_due_and_prices_valid(db):
    _make_eligible_snapshot(db, exit_close=200.0)
    # Not due yet -> 0 real-forward pairs.
    not_due = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_BEFORE_HORIZON, write=True,
    )
    assert not_due["n_real_forward_after"] == 0
    # Now due with valid prices -> exactly 1.
    due = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True,
    )
    assert due["n_real_forward_after"] == 1


def test_new_live_snapshot_does_not_attach_until_horizon_elapsed(db):
    _make_eligible_snapshot(db, exit_close=200.0)
    # Immediately after creation (now == decision time) the horizon is open.
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["outcomes_attached"] == 0
    assert summary["pending_horizon"] == 1


def test_no_backdated_outcome_creation(db):
    _make_eligible_snapshot(db, exit_close=200.0)
    before = read_snapshot(db, signal_id="ev1")
    attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_BEFORE_HORIZON, write=True,
    )
    after = read_snapshot(db, signal_id="ev1")
    # The decision timestamp is never moved and no outcome is fabricated early.
    assert after["timestamp_utc"] == before["timestamp_utc"] == _NOW
    assert after["outcome_label"] is None
