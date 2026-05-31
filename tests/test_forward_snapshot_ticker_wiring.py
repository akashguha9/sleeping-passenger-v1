"""Phase 2 — ticker is preserved from scored real rows into snapshots."""
from __future__ import annotations

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_score_vector,
)
from scripts.forward_snapshot_contract import REASON_MISSING_TICKER
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_NOW = "2026-05-10T00:00:00Z"
_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.5, "LS": 0.45, "EFS": 0.6, "APS": 0.5}


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _run(db, events):
    return run_daily_decision_batch(db_path=db, events=events, now_iso=_NOW, write=True)


def test_daily_decision_snapshot_preserves_ticker_from_signal_event(db):
    # Top-level event ticker wins; axes come from the payload (legacy path).
    ev = event_row("ev_event_ticker", ticker="MSFT", payload={"axes": _AXES})
    _run(db, [ev])
    snap = read_snapshot(db, signal_id="ev_event_ticker")
    assert snap is not None
    assert snap["ticker"] == "MSFT"


def test_daily_decision_snapshot_preserves_ticker_from_score_vector(db):
    # No event/payload ticker; the side-table SCORED vector supplies it.
    seed_score_vector(db, event_id="ev_sv", ticker="AAPL")
    ev = event_row("ev_sv", payload={})
    _run(db, [ev])
    snap = read_snapshot(db, signal_id="ev_sv")
    assert snap is not None
    assert snap["ticker"] == "AAPL"


def test_payload_symbol_fallback_used_when_event_ticker_missing(db):
    # No event ticker, no side vector — payload `symbol` is the fallback.
    ev = event_row("ev_payload_sym", payload={"symbol": "aapl", "axes": _AXES})
    _run(db, [ev])
    snap = read_snapshot(db, signal_id="ev_payload_sym")
    assert snap is not None
    assert snap["ticker"] == "AAPL"  # normalized (uppercased)


def test_invalid_unknown_ticker_blocks_forward_outcome_eligibility(db):
    ev = event_row("ev_unknown", ticker="UNKNOWN", payload={"axes": _AXES})
    summary = _run(db, [ev])
    snap = read_snapshot(db, signal_id="ev_unknown")
    assert snap is not None
    assert snap["ticker"] is None  # "UNKNOWN" is never a valid ticker
    assert snap["forward_outcome_eligible"] == 0
    assert snap["forward_outcome_unavailable_reason"] == REASON_MISSING_TICKER
    assert summary["forward_outcome_unavailable_reasons"].get(REASON_MISSING_TICKER) == 1


def test_ticker_normalization_preserves_exchange_prefixes(db):
    seed_score_vector(db, event_id="ev_ns", ticker="reliance.ns")
    _run(db, [event_row("ev_ns", payload={})])
    snap = read_snapshot(db, signal_id="ev_ns")
    assert snap["ticker"] == "RELIANCE.NS"

    seed_score_vector(db, event_id="ev_nse", ticker="NSE:SBIN")
    _run(db, [event_row("ev_nse", payload={})])
    snap2 = read_snapshot(db, signal_id="ev_nse")
    assert snap2["ticker"] == "NSE:SBIN"


def test_ticker_present_in_decision_probability_snapshot(db):
    seed_score_vector(db, event_id="ev_present", ticker="AAPL")
    summary = _run(db, [event_row("ev_present", payload={})])
    snap = read_snapshot(db, signal_id="ev_present")
    assert snap["ticker"] == "AAPL"
    assert summary["ticker_present_count"] == 1


def test_no_ticker_results_in_forward_contract_unavailable_reason(db):
    # No ticker anywhere -> snapshot recorded but forward-ineligible w/ reason.
    ev = event_row("ev_no_ticker", payload={"axes": _AXES})
    summary = _run(db, [ev])
    snap = read_snapshot(db, signal_id="ev_no_ticker")
    assert snap["ticker"] is None
    assert snap["forward_outcome_eligible"] == 0
    assert snap["forward_outcome_unavailable_reason"] == REASON_MISSING_TICKER
    assert summary["ticker_present_count"] == 0
