"""Reconciliation math + idempotency integrity (Phase 12 items 18-21).

Net P&L sign, realized return %, holding period, idempotent reconciliation,
and duplicate-reconciliation behaviour. Uses a throwaway temp DB and the
existing persistence + paper_reconciliation helpers — no live DB, no broker.
"""
from __future__ import annotations

import importlib

import pytest

pr = importlib.import_module("scripts.paper_reconciliation")
oe = importlib.import_module("scripts.outcome_evidence")
persistence = importlib.import_module("scripts.persistence")


# --- realized return % (20) ------------------------------------------------
def test_realized_return_long():
    # long 100 -> 110 = +10%
    assert pr._compute_realized_return_pct(100.0, 110.0, "BUY") == pytest.approx(10.0)


def test_realized_return_short():
    # short 100 -> 90 = +10% (price fell, short wins)
    assert pr._compute_realized_return_pct(100.0, 90.0, "SELL") == pytest.approx(10.0)


def test_realized_return_guards_zero_and_missing():
    assert pr._compute_realized_return_pct(0.0, 110.0, "BUY") is None  # no div0
    assert pr._compute_realized_return_pct(100.0, None, "BUY") is None


# --- net P&L sign via the canonical return model (19) ----------------------
def test_net_pnl_sign_long_and_short():
    long_win = oe.compute_return("LONG", 100.0, 120.0)
    assert long_win is not None and long_win > 0
    short_win = oe.compute_return("SHORT", 100.0, 80.0)
    assert short_win is not None and short_win > 0
    short_loss = oe.compute_return("SHORT", 100.0, 120.0)
    assert short_loss is not None and short_loss < 0


def test_unknown_direction_cannot_be_signed():
    assert oe.compute_return("SIDEWAYS", 100.0, 120.0) is None


# --- holding period in reconciliation context ------------------------------
def test_holding_period_same_day_and_multiday():
    assert pr._compute_holding_period_days("2026-01-10T09:00:00+00:00",
                                           "2026-01-10T09:00:00+00:00") == 0.0
    assert pr._compute_holding_period_days("2026-01-10T00:00:00+00:00",
                                           "2026-01-13T00:00:00+00:00") == 3.0


def test_holding_period_rejects_exit_before_entry():
    assert pr._compute_holding_period_days("2026-01-10T00:00:00+00:00",
                                           "2026-01-05T00:00:00+00:00") is None


# --- idempotent reconciliation (21) ----------------------------------------
def test_reconciliation_is_idempotent(tmp_path):
    db = tmp_path / "recon.db"
    args = dict(
        reconciliation_id="R1", trade_id="T1", event_id="E1",
        reconciled_at="2026-01-10T00:00:00+00:00", actual_fill_price=101.0,
        actual_quantity=10.0, outcome_notes="", pnl_estimate=10.0,
        outcome_status="WIN", db_path=db,
    )
    persistence.insert_reconciliation(**args)
    persistence.insert_reconciliation(**args)  # same PK again
    rows = [r for r in persistence.get_all_reconciliations(db)
            if r.get("reconciliation_id") == "R1"]
    assert len(rows) == 1  # INSERT OR IGNORE collapsed the duplicate


def test_duplicate_reconciliation_same_trade_distinct_ids_are_visible(tmp_path):
    """A second reconciliation row for the same trade under a NEW id is not
    silently merged — it is a distinct, auditable row (a correction event must
    carry its own id), but the original is never overwritten."""
    db = tmp_path / "recon2.db"
    base = dict(
        trade_id="T9", event_id="E9", reconciled_at="2026-01-10T00:00:00+00:00",
        actual_fill_price=100.0, actual_quantity=5.0, outcome_notes="",
        pnl_estimate=5.0, outcome_status="WIN", db_path=db,
    )
    persistence.insert_reconciliation(reconciliation_id="RA", **base)
    persistence.insert_reconciliation(reconciliation_id="RB", **{**base, "pnl_estimate": 6.0})
    rows = [r for r in persistence.get_all_reconciliations(db)
            if r.get("trade_id") == "T9"]
    # Original RA is preserved (not overwritten by RB).
    by_id = {r["reconciliation_id"]: r for r in rows}
    assert by_id["RA"]["pnl_estimate"] == 5.0
