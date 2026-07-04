"""Phase 4 — entry/reference price resolution from real OHLCV bars."""
from __future__ import annotations

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_market_bar,
    seed_score_vector,
)
from scripts.forward_snapshot_contract import REASON_MISSING_ENTRY_PRICE
from scripts.real_price_outcome_evidence import resolve_entry_price
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_NOW = "2026-05-10T00:00:00Z"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _run(db, events):
    return run_daily_decision_batch(db_path=db, events=events, now_iso=_NOW, write=True)


# ----- resolve_entry_price unit behaviour ---------------------------------- #
def test_entry_price_resolved_on_or_before_decision_timestamp(db):
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-08T00:00:00Z", close=185.0)
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    ev = resolve_entry_price(db, ticker="AAPL", decision_timestamp_utc=_NOW)
    assert ev is not None
    assert ev["entry_price"] == 190.0  # latest bar on-or-before the decision
    assert ev["entry_price_timestamp_utc"] == "2026-05-09T00:00:00Z"


def test_entry_price_rejects_price_after_decision_timestamp(db):
    # Only a bar AFTER the decision timestamp exists -> no look-ahead entry.
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-12T00:00:00Z", close=200.0)
    ev = resolve_entry_price(db, ticker="AAPL", decision_timestamp_utc=_NOW)
    assert ev is None


def test_entry_price_rejects_stale_beyond_lookback(db):
    # Last bar is 30 days before the decision -> beyond the 7-day lookback.
    seed_market_bar(db, symbol="AAPL", timestamp="2026-04-10T00:00:00Z", close=170.0)
    ev = resolve_entry_price(db, ticker="AAPL", decision_timestamp_utc=_NOW)
    assert ev is None


def test_entry_price_requires_positive_price(db):
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=0.0)
    ev = resolve_entry_price(db, ticker="AAPL", decision_timestamp_utc=_NOW)
    assert ev is None  # zero/non-positive close is dropped, never used


def test_entry_price_preserves_source_timestamp(db):
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    ev = resolve_entry_price(db, ticker="AAPL", decision_timestamp_utc=_NOW)
    assert ev["entry_price_timestamp_utc"] == "2026-05-09T00:00:00Z"
    assert ev["entry_price_source"] == "real_ohlcv_signal_events"


def test_entry_price_uses_real_ohlcv_not_mock(db):
    # The series is read from real market_data bars; an unknown symbol with no
    # bar yields no price (never a fabricated/mock value).
    ev = resolve_entry_price(db, ticker="NOSUCHSYM", decision_timestamp_utc=_NOW)
    assert ev is None


# ----- batch stamping integration ------------------------------------------ #
def test_entry_price_stamped_on_snapshot(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["entry_price"] == 190.0
    assert snap["entry_price_timestamp_utc"] == "2026-05-09T00:00:00Z"
    assert snap["entry_price_source"] == "real_ohlcv_signal_events"


def test_missing_entry_price_marks_snapshot_not_forward_eligible(db):
    # Scored, ticker-bearing row, but no price series for the symbol.
    seed_score_vector(db, event_id="ev1", ticker="NVDA")  # no NVDA bars seeded
    summary = _run(db, [event_row("ev1", payload={})])
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["entry_price"] is None
    assert snap["forward_outcome_eligible"] == 0
    assert snap["forward_outcome_unavailable_reason"] == REASON_MISSING_ENTRY_PRICE
    assert summary["forward_outcome_unavailable_reasons"].get(REASON_MISSING_ENTRY_PRICE) == 1
