"""Phase 5 — forward-eligible throughput tests (offline, advisory-only)."""
from __future__ import annotations

import pytest

from scripts.forward_eligibility_diagnostics import forward_throughput_summary
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch
from tests._forward_snapshot_helpers import (
    event_row,
    init_db,
    seed_market_bar,
    seed_score_vector,
)

_NOW = "2026-05-22T00:00:00Z"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    return p


def _batch(db, events):
    return run_daily_decision_batch(
        db_path=db, events=events, now_iso=_NOW, write=True, max_decisions=50
    )


def test_forward_eligibility_increases_when_tickers_resolved(db):
    # A scored sec_edgar row whose ticker is only a company name + OHLCV present.
    seed_score_vector(db, event_id="e1", source_name="sec_edgar", ticker="Apple Inc.")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-20 00:00:00-04:00", close=200.0)
    # Without the score vector / ticker, an unscored event is ineligible.
    out_unscored = _batch(db, [event_row("nope", payload={"headline": "macro"})])
    assert out_unscored["forward_outcome_eligible_count"] == 0
    # The scored, ticker-resolvable, priceable event IS eligible.
    out = _batch(db, [event_row("e1", payload={})])
    assert out["forward_outcome_eligible_count"] == 1


def test_forward_eligibility_increases_when_ohlcv_added(db):
    seed_score_vector(db, event_id="e1", source_name="sec_edgar", ticker="NVIDIA CORP")
    # No OHLCV for NVDA yet -> MISSING_ENTRY_PRICE.
    out_no_px = _batch(db, [event_row("e1", payload={})])
    assert out_no_px["forward_outcome_eligible_count"] == 0
    assert out_no_px["forward_outcome_unavailable_reasons"].get("MISSING_ENTRY_PRICE") == 1
    # Add a real NVDA bar -> now eligible.
    seed_market_bar(db, symbol="NVDA", timestamp="2026-05-20 00:00:00-04:00", close=210.0)
    out_px = _batch(db, [event_row("e1", payload={})])
    assert out_px["forward_outcome_eligible_count"] == 1


def test_missing_ticker_reduction_calculated():
    s = forward_throughput_summary(
        forward_eligible_before=4, forward_eligible_after=49,
        decisions_before=150, decisions_after=170,
        reasons_before={"MISSING_TICKER": 119, "MISSING_ENTRY_PRICE": 25},
        reasons_after={"MISSING_TICKER": 119, "MISSING_ENTRY_PRICE": 0},
    )
    assert s["reason_reductions"]["MISSING_TICKER"] == 0


def test_missing_entry_price_reduction_calculated():
    s = forward_throughput_summary(
        forward_eligible_before=4, forward_eligible_after=49,
        decisions_before=150, decisions_after=170,
        reasons_before={"MISSING_ENTRY_PRICE": 25},
        reasons_after={"MISSING_ENTRY_PRICE": 0},
    )
    assert s["reason_reductions"]["MISSING_ENTRY_PRICE"] == 25
    assert s["eligibility_gain"] == 45


def test_missing_probability_reduction_calculated():
    s = forward_throughput_summary(
        forward_eligible_before=4, forward_eligible_after=49,
        decisions_before=150, decisions_after=170,
        reasons_before={"MISSING_PROBABILITY": 2},
        reasons_after={"MISSING_PROBABILITY": 2},
    )
    assert s["reason_reductions"]["MISSING_PROBABILITY"] == 0


def test_no_backdating_to_create_due_outcomes(db):
    # A freshly-created eligible snapshot's horizon must still be PENDING — never
    # backdated to manufacture a due/closed outcome.
    seed_score_vector(db, event_id="e1", source_name="sec_edgar", ticker="Apple Inc.")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-20 00:00:00-04:00", close=200.0)
    out = _batch(db, [event_row("e1", payload={})])
    assert out["forward_outcome_eligible_count"] == 1
    assert out["n_pending_horizon"] == 1  # pending, not due


def test_pending_horizon_count_increases_for_new_eligible_snapshots(db):
    seed_score_vector(db, event_id="e1", source_name="sec_edgar", ticker="Apple Inc.")
    seed_score_vector(db, event_id="e2", source_name="sec_edgar", ticker="MICROSOFT CORP")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-20 00:00:00-04:00", close=200.0)
    seed_market_bar(db, symbol="MSFT", timestamp="2026-05-20 00:00:00-04:00", close=400.0)
    out = _batch(db, [event_row("e1", payload={}), event_row("e2", payload={})])
    assert out["forward_outcome_eligible_count"] == 2
    assert out["n_pending_horizon"] == 2


def test_predictive_claim_stays_locked(db):
    seed_score_vector(db, event_id="e1", source_name="sec_edgar", ticker="Apple Inc.")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-20 00:00:00-04:00", close=200.0)
    out = _batch(db, [event_row("e1", payload={})])
    assert out["predictive_claim_allowed"] is False
    assert out["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert out["broker_api_called"] is False
    assert out["execution_gate"] == "LOCKED"


def test_n_needed_to_200_reported():
    s = forward_throughput_summary(
        forward_eligible_before=4, forward_eligible_after=49,
        decisions_before=150, decisions_after=170,
        n_real_forward_pairs=0,
    )
    assert s["n_needed_to_200"] == 200
    assert s["real_money_ready"] is False
