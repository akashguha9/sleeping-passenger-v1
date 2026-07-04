"""Real-Forward Outcome Maturation Sprint — Phase 3 due-attachment tests.

Verifies that the existing attach machinery attaches a real-forward outcome ONLY
when a horizon has truly elapsed and a real entry+exit price exists, with the
exact outcome math::

    r_i = (P_exit_i - P_entry_i) / P_entry_i
    y_i = I(r_i >= target_return_threshold_i)        (default threshold 0.0)

No backdating, no fabricated outcome, no price after horizon close, idempotent.
"""
from __future__ import annotations

import sqlite3

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_market_bar,
    seed_score_vector,
)
from scripts.attach_due_outcomes import REASON_MISSING_EXIT_PRICE, attach_due_outcomes
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_DECISION = "2026-05-10T00:00:00Z"
_AFTER_HORIZON = "2026-05-20T00:00:00Z"   # past the 5-day close (05-15)
_BEFORE_HORIZON = "2026-05-12T00:00:00Z"  # horizon still open


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _seed(db, *, exit_close, entry_close=190.0, event_id="ev1", ticker="AAPL"):
    seed_score_vector(db, event_id=event_id, ticker=ticker)
    seed_market_bar(db, symbol=ticker, timestamp="2026-05-09T00:00:00Z", close=entry_close)
    seed_market_bar(db, symbol=ticker, timestamp="2026-05-15T00:00:00Z", close=exit_close)
    run_daily_decision_batch(
        db_path=db, events=[event_row(event_id, payload={})], now_iso=_DECISION, write=True
    )


def test_due_snapshot_attaches_y_one_with_real_exit_price(db):
    _seed(db, exit_close=200.0)  # r = (200-190)/190 > 0 -> y=1
    out = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True
    )
    assert out["outcomes_attached"] == 1
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["outcome_label"] == 1
    assert snap["is_real_outcome"] == 1
    assert snap["outcome_kind"] == "real_forward"


def test_due_snapshot_attaches_y_zero_with_real_exit_price(db):
    _seed(db, exit_close=180.0)  # r < 0 -> y=0
    attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True
    )
    assert read_snapshot(db, signal_id="ev1")["outcome_label"] == 0


def test_not_due_snapshot_remains_pending(db):
    _seed(db, exit_close=200.0)
    out = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_BEFORE_HORIZON, write=True
    )
    assert out["outcomes_attached"] == 0
    assert out["pending_horizon"] == 1
    assert read_snapshot(db, signal_id="ev1")["outcome_label"] is None


def test_exit_price_after_horizon_is_rejected(db):
    # Entry 05-09; the only post-decision bar is 05-25, far after the 05-15 close.
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-25T00:00:00Z", close=999.0)
    run_daily_decision_batch(
        db_path=db, events=[event_row("ev1", payload={})], now_iso=_DECISION, write=True
    )
    from scripts.real_price_outcome_evidence import build_real_price_evidence, load_price_series
    from datetime import datetime, timezone

    series = load_price_series(db, symbols={"AAPL"})
    snap = {"ticker": "AAPL", "timestamp_utc": _DECISION, "prediction_horizon_days": 5}
    ev = build_real_price_evidence(
        snap, series, now_utc=datetime(2026, 5, 30, tzinfo=timezone.utc)
    )
    # exit is the on/before-close 05-09 bar (190), never the 05-25 bar (999).
    assert ev["exit_price"] == 190.0
    assert ev["exit_price"] != 999.0


def test_missing_exit_price_excluded_with_reason(db):
    _seed(db, exit_close=200.0)
    snap = read_snapshot(db, signal_id="ev1")
    out = attach_due_outcomes(
        db_path=db,
        evidence_by_id={snap["snapshot_id"]: {"entry_price": 190.0}},  # no exit
        now_utc=_AFTER_HORIZON, write=True,
    )
    assert out["outcomes_attached"] == 0
    assert out["excluded_missing_exit_price"] == 1
    assert any(d.get("reason") == REASON_MISSING_EXIT_PRICE for d in out["details"])


def test_duplicate_attach_is_idempotent(db):
    _seed(db, exit_close=200.0)
    first = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True
    )
    second = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True
    )
    assert first["outcomes_attached"] == 1
    assert second["outcomes_attached"] == 0  # already labelled -> skipped
    assert second["n_real_forward_after"] == 1


def test_real_forward_pair_count_increments(db):
    _seed(db, exit_close=200.0)
    not_due = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_BEFORE_HORIZON, write=True
    )
    assert not_due["n_real_forward_after"] == 0
    due = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True
    )
    assert due["n_real_forward_after"] == 1


def test_no_backdating_allowed(db):
    _seed(db, exit_close=200.0)
    before = read_snapshot(db, signal_id="ev1")
    attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_BEFORE_HORIZON, write=True
    )
    after = read_snapshot(db, signal_id="ev1")
    assert after["timestamp_utc"] == before["timestamp_utc"] == _DECISION
    assert after["outcome_label"] is None  # never fabricated early


def test_attach_preserves_advisory_only_stamps(db):
    _seed(db, exit_close=200.0)
    out = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True
    )
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["predictive_claim_allowed"] is False


def test_attach_has_no_execution_language(db):
    import json

    _seed(db, exit_close=200.0)
    out = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_AFTER_HORIZON, write=True
    )
    blob = json.dumps(out).lower()
    for forbidden in ("place order", "execute trade", "auto-trade", "buy now", "sell now"):
        assert forbidden not in blob
