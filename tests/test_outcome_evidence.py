"""Behavioural tests for the outcome-evidence model + return/quality math."""
from __future__ import annotations

import math

from scripts import outcome_evidence as oe


# --- return formulas --------------------------------------------------------

def test_long_return_formula():
    assert oe.compute_return("LONG", 100.0, 110.0) == 0.10


def test_short_return_formula():
    assert oe.compute_return("SHORT", 100.0, 90.0) == 0.10


def test_short_loss_when_price_rises():
    assert oe.compute_return("SHORT", 100.0, 110.0) == -0.10


def test_levered_return_via_build():
    o = oe.build_outcome(
        outcome_id="o1", source_type=oe.REAL_MANUAL_TRADE, ticker="AAPL",
        direction="LONG", entry_price=100.0, exit_price=110.0, leverage=3.0,
        score_at_entry=0.7, opened_at="2026-01-01", closed_at="2026-01-05",
    )
    assert math.isclose(o.realized_return, 0.10)
    assert math.isclose(o.realized_levered_return, 0.30)


def test_pnl_fallback_when_no_prices():
    r = oe.compute_return("LONG", None, None, realized_pnl=50.0, capital_at_risk=1000.0)
    assert r == 0.05


def test_return_none_when_undeterminable():
    assert oe.compute_return("LONG", None, None) is None
    assert oe.compute_return("UNKNOWN", 100.0, 110.0) is None


# --- epsilon boundaries -----------------------------------------------------

def test_win_loss_breakeven_boundaries():
    assert oe.label_outcome(0.002) == oe.WIN
    assert oe.label_outcome(-0.002) == oe.LOSS
    assert oe.label_outcome(0.0005) == oe.BREAKEVEN
    assert oe.label_outcome(0.001) == oe.BREAKEVEN  # |r| <= eps
    assert oe.label_outcome(None) == oe.OPEN


# --- quality / eligibility --------------------------------------------------

def test_complete_real_manual_trade_quality_high():
    o = oe.build_outcome(
        outcome_id="o", source_type=oe.REAL_MANUAL_TRADE, ticker="AAPL",
        direction="LONG", entry_price=100.0, exit_price=110.0,
        opened_at="2026-01-01", closed_at="2026-01-05", score_at_entry=0.8,
    )
    assert o.quality >= 0.9
    assert o.is_calibration_eligible is True


def test_missing_score_reduces_quality_and_blocks_eligibility():
    o = oe.build_outcome(
        outcome_id="o", source_type=oe.REAL_MANUAL_TRADE, ticker="AAPL",
        direction="LONG", entry_price=100.0, exit_price=110.0,
        opened_at="2026-01-01", closed_at="2026-01-05", score_at_entry=None,
    )
    assert o.quality < 1.0
    assert o.is_calibration_eligible is False
    assert o.ineligible_reason == "missing_score_at_entry"


def test_missing_exit_evidence_makes_open_and_ineligible():
    o = oe.build_outcome(
        outcome_id="o", source_type=oe.REAL_MANUAL_TRADE, ticker="AAPL",
        direction="LONG", entry_price=100.0, exit_price=None, score_at_entry=0.8,
        opened_at="2026-01-01",
    )
    assert o.outcome_label == oe.OPEN
    assert o.is_calibration_eligible is False
    assert o.ineligible_reason == "outcome_not_resolved"


def test_synthetic_fixture_never_eligible():
    o = oe.build_outcome(
        outcome_id="o", source_type=oe.SYNTHETIC_FIXTURE, ticker="AAPL",
        direction="LONG", entry_price=100.0, exit_price=110.0,
        opened_at="2026-01-01", closed_at="2026-01-05", score_at_entry=0.8,
    )
    assert o.outcome_label == oe.WIN  # it IS resolved
    assert o.is_calibration_eligible is False
    assert o.ineligible_reason == "synthetic_fixture_never_calibration_eligible"


def test_low_quality_excluded():
    # paper trade, missing opened/closed timestamps -> lower quality.
    o = oe.build_outcome(
        outcome_id="o", source_type=oe.IMPORTED_BACKTEST, ticker="X",
        direction="LONG", entry_price=100.0, exit_price=101.0,
        score_at_entry=0.5,  # present
        # no opened_at/closed_at
        q_min=0.95,  # force a high bar
    )
    assert o.is_calibration_eligible is False
    assert o.ineligible_reason.startswith("quality_below_q_min")


def test_open_trade_excluded():
    o = oe.build_outcome(
        outcome_id="o", source_type=oe.PAPER_TRADE, ticker="X",
        direction="LONG", entry_price=100.0, exit_price=None, score_at_entry=0.6,
    )
    assert o.outcome_label == oe.OPEN
    assert o.is_calibration_eligible is False


def test_advisory_stamps_preserved():
    o = oe.build_outcome(
        outcome_id="o", source_type=oe.REAL_MANUAL_TRADE, ticker="X",
        direction="LONG", entry_price=100.0, exit_price=110.0, score_at_entry=0.7,
        opened_at="a", closed_at="b",
    )
    d = o.to_dict()
    assert d["advisory_only"] is True
    assert d["human_execution_required"] is True
    assert d["broker_api_called"] is False


def test_provenance_counts():
    outs = [
        oe.build_outcome(outcome_id="1", source_type=oe.REAL_MANUAL_TRADE, ticker="A",
                         direction="LONG", entry_price=1, exit_price=2, score_at_entry=0.5,
                         opened_at="a", closed_at="b"),
        oe.build_outcome(outcome_id="2", source_type=oe.PAPER_TRADE, ticker="B",
                         direction="LONG", entry_price=1, exit_price=2, score_at_entry=0.5,
                         opened_at="a", closed_at="b"),
        oe.build_outcome(outcome_id="3", source_type=oe.SYNTHETIC_FIXTURE, ticker="C",
                         direction="LONG", entry_price=1, exit_price=2, score_at_entry=0.5,
                         opened_at="a", closed_at="b"),
    ]
    counts = oe.provenance_counts(outs)
    assert counts["real_n"] == 1
    assert counts["paper_n"] == 1
    assert counts["synthetic_n"] == 1
    assert counts["eligible_n"] == 2  # synthetic excluded
