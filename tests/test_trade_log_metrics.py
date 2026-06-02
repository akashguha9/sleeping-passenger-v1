"""Tests for scripts/trade_log_metrics.py — core trade-log math from the fixture."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.google_sheet_schema import TradeLogRow, load_trade_log_csv
from scripts.trade_log_metrics import (
    build_report,
    compute_capital,
    compute_country_concentration,
    compute_expectancy,
    compute_r_metrics,
    compute_win_rates,
    model_cohort,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trade_log_sample.csv"
REPORT = date(2026, 6, 2)
START = 4000.0


@pytest.fixture()
def rows():
    return load_trade_log_csv(FIXTURE).rows


# --------------------------------------------------------------------------- #
# Capital
# --------------------------------------------------------------------------- #
def test_marked_equity_is_start_plus_cumulative_pl(rows):
    cap = compute_capital(rows, START)
    assert cap["total_pl"] == pytest.approx(29.76)
    assert cap["marked_equity"] == pytest.approx(4029.76)


def test_free_cash_is_not_total_equity(rows):
    cap = compute_capital(rows, START)
    assert cap["free_cash"] == pytest.approx(2623.934293)
    assert cap["capital_after_row_is_total_equity"] is False
    # Free cash must differ from marked equity.
    assert cap["free_cash"] != cap["marked_equity"]


def test_allocated_open_between_zero_and_total(rows):
    cap = compute_capital(rows, START)
    assert cap["allocated_open_capital"] == pytest.approx(1480.0)


# --------------------------------------------------------------------------- #
# Win rates
# --------------------------------------------------------------------------- #
def test_win_rate_triad(rows):
    wr = compute_win_rates(rows)
    assert (wr["wins"], wr["losses"], wr["flats"]) == (4, 4, 3)
    assert wr["marked_win_rate_ex_flat"] == pytest.approx(0.5)
    assert wr["all_row_win_rate"] == pytest.approx(4 / 11, abs=1e-4)
    # Closed-only is separate and smaller: 1 win / (1 win + 2 losses).
    assert wr["closed_rows"] == 3
    assert wr["closed_win_rate"] == pytest.approx(1 / 3, abs=1e-4)


def test_flats_excluded_from_marked_win_rate(rows):
    wr = compute_win_rates(rows)
    # 4/(4+4) = 0.5, not 4/11.
    assert wr["marked_win_rate_ex_flat"] != wr["all_row_win_rate"]


# --------------------------------------------------------------------------- #
# Expectancy / R
# --------------------------------------------------------------------------- #
def test_profit_factor_and_expectancy(rows):
    exp = compute_expectancy(rows)
    assert exp["gross_profit"] == pytest.approx(120.26)
    assert exp["gross_loss"] == pytest.approx(90.50)
    assert exp["profit_factor"] == pytest.approx(120.26 / 90.50, abs=1e-4)
    # p=0.5, avg_win=30.065, avg_loss_abs=22.625 -> 3.72
    assert exp["expectancy_per_trade"] == pytest.approx(3.72, abs=1e-2)


def test_r_metrics(rows):
    r = compute_r_metrics(rows)
    assert r["r_wins"] == 3
    assert r["r_losses"] == 3
    assert r["r_win_rate"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Country concentration
# --------------------------------------------------------------------------- #
def test_country_concentration_no_us_warning_at_45pct(rows):
    conc = compute_country_concentration(rows)
    assert conc["us_share"] == pytest.approx(5 / 11, abs=1e-4)
    assert conc["country_warning"] is None  # 0.45 < 0.50
    assert 0.0 <= conc["country_diversity_score"] <= 100.0


def test_us_heavy_and_overconcentrated_warnings():
    def mkrow(country):
        return TradeLogRow(
            row_number=1, date=date(2026, 6, 1), ticker="T", buy_price=1.0,
            sell_price=None, leverage=1.0, country=country, currency="USD",
            model_used="m", money_allocated=100.0, capital_pre_trade=None,
            profit_loss=0.0, live_price=None, cumulative_pl=None,
            trade_state="OPEN", exit_stage_v2="", action_required_v2="",
            booked_pct=0.0, remaining_pct=1.0, cash_released=0.0,
            capital_after_row=None,
        )
    heavy = [mkrow("United States")] * 6 + [mkrow("Japan")] * 4
    assert compute_country_concentration(heavy)["country_warning"] == "US_HEAVY"
    over = [mkrow("United States")] * 7 + [mkrow("Japan")] * 3
    assert compute_country_concentration(over)["country_warning"] == "US_OVERCONCENTRATED"


# --------------------------------------------------------------------------- #
# Model cohorts + report
# --------------------------------------------------------------------------- #
def test_model_cohort_by_date():
    def d(day):
        return TradeLogRow(
            row_number=1, date=day, ticker="T", buy_price=None, sell_price=None,
            leverage=1.0, country="US", currency="USD", model_used="m",
            money_allocated=0.0, capital_pre_trade=None, profit_loss=0.0,
            live_price=None, cumulative_pl=None, trade_state="OPEN",
            exit_stage_v2="", action_required_v2="", booked_pct=0.0,
            remaining_pct=1.0, cash_released=0.0, capital_after_row=None,
        )
    assert model_cohort(d(date(2026, 5, 15))) == "v2026_05_early"
    assert model_cohort(d(date(2026, 5, 22))) == "v2026_05_override"
    assert model_cohort(d(date(2026, 5, 27))) == "v2026_05_recalibration"
    assert model_cohort(d(date(2026, 6, 2))) == "v2026_06_global_watchlist"


def test_build_report_is_advisory_and_complete(rows):
    report = build_report(rows, START, REPORT)
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["human_execution_required"] is True
    assert report["real_money_sizing_impact"] == "PROHIBITED"
    # Low closed sample must be flagged immature, not conclusive.
    assert "CLOSED_ONLY_EVIDENCE_IMMATURE" in report["warnings"]
    assert report["outcome_maturity"]["pending_horizon"] >= 2
    assert set(report["model_version_performance"]).issuperset(
        {"v2026_05_early", "v2026_06_global_watchlist"}
    )
