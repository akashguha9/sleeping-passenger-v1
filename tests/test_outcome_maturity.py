"""Tests for scripts/outcome_maturity.py — young trades must not be judged."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.google_sheet_schema import load_trade_log_csv
from scripts.outcome_maturity import (
    MATURITY_CLOSED,
    MATURITY_EVENT,
    MATURITY_MATURE_OPEN,
    MATURITY_PENDING,
    MATURITY_UNKNOWN,
    classify_maturity,
    summarize_maturity,
    trading_days_between,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trade_log_sample.csv"
REPORT = date(2026, 6, 2)


def _row(**kw):
    base = {"ticker": "X", "trade_state": "", "exit_stage_v2": "", "date": None}
    base.update(kw)
    return base


def test_trading_days_between_weekday_only():
    # Fri 2026-05-15 -> Mon 2026-05-18 = 1 trading day (Sat/Sun skipped).
    assert trading_days_between(date(2026, 5, 15), date(2026, 5, 18)) == 1
    assert trading_days_between(date(2026, 6, 2), date(2026, 6, 2)) == 0


def test_recent_open_rows_are_pending_not_failures():
    # Entries on 01-06 and 02-06 with report 02-06 and no event -> PENDING.
    for d in (date(2026, 6, 1), date(2026, 6, 2)):
        c = classify_maturity(_row(trade_state="OPEN", date=d), REPORT)
        assert c["maturity"] == MATURITY_PENDING
        assert c["score_eligible"] is False


def test_closed_row_is_score_eligible():
    c = classify_maturity(_row(trade_state="CLOSED", date=date(2026, 5, 14)), REPORT)
    assert c["maturity"] == MATURITY_CLOSED
    assert c["score_eligible"] is True


def test_tp_event_row_is_score_eligible():
    c = classify_maturity(
        _row(trade_state="PARTIAL_TP_LOGGED", exit_stage_v2="RUNNER / PROTECTED",
             date=date(2026, 6, 1)),
        REPORT,
    )
    assert c["maturity"] == MATURITY_EVENT
    assert c["score_eligible"] is True


def test_old_open_row_becomes_mature_open():
    c = classify_maturity(_row(trade_state="OPEN", date=date(2026, 5, 14)), REPORT)
    assert c["maturity"] == MATURITY_MATURE_OPEN
    assert c["score_eligible"] is True


def test_missing_date_is_unknown():
    c = classify_maturity(_row(trade_state="OPEN", date=None), REPORT)
    assert c["maturity"] == MATURITY_UNKNOWN


def test_summarize_fixture_has_pending_and_closed():
    rows = load_trade_log_csv(FIXTURE).rows
    summary = summarize_maturity(rows, REPORT)
    assert summary["total_rows"] == 11
    # 02-06 rows IOTA + LAMBDA pending; ALPHA/BETA/GAMMA closed.
    assert summary["pending_horizon"] >= 2
    assert summary["closed"] == 3
    # Advisory-only stamps carried.
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["human_execution_required"] is True
