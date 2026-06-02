"""Tests for scripts/google_sheet_schema.py — messy Google-Sheet CSV normalization."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.google_sheet_schema import (
    CAPITAL_AFTER_ROW_NOT_EQUITY,
    MISSING_TICKER,
    OPEN_WITH_SELL_PRICE,
    UNKNOWN_TRADE_STATE,
    load_trade_log_csv,
    map_headers,
    normalize_header,
    normalize_rows,
    parse_cumulative_pl,
    parse_date,
    parse_number,
    parse_percent,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trade_log_sample.csv"


# --------------------------------------------------------------------------- #
# Scalar parsers
# --------------------------------------------------------------------------- #
def test_parse_number_handles_commas_currency_and_parens():
    assert parse_number("1,883.50") == 1883.50
    assert parse_number("€1234.5") == 1234.5
    assert parse_number("(12.5)") == -12.5
    assert parse_number("") is None
    assert parse_number(None) is None
    with pytest.raises(ValueError):
        parse_number("n/a")


def test_parse_percent_mixed_formats_normalize_identically():
    assert parse_percent("80%") == 0.8
    assert parse_percent("80.00%") == 0.8
    assert parse_percent("0.8") == 0.8
    assert parse_percent("80") == 0.8  # bare >1 treated as percent figure
    assert parse_percent("1") == 1.0
    assert parse_percent("100.00%") == 1.0
    assert parse_percent("") is None


def test_parse_date_day_first_iso_and_garbage():
    assert parse_date("14-05-2026") == date(2026, 5, 14)
    assert parse_date("2026-05-14") == date(2026, 5, 14)
    assert parse_date("2026-05-14T09:30:00Z") == date(2026, 5, 14)
    assert parse_date("") is None
    with pytest.raises(ValueError):
        parse_date("not-a-date")


def test_parse_cumulative_pl_from_text():
    assert parse_cumulative_pl("OPEN | Cum P/L: 29.76") == 29.76
    assert parse_cumulative_pl("29.76") == 29.76
    assert parse_cumulative_pl("Cum P/L: -12.5") == -12.5
    assert parse_cumulative_pl("") is None
    with pytest.raises(ValueError):
        parse_cumulative_pl("no number here")


def test_header_mapping_is_tolerant_of_spacing_and_punctuation():
    assert normalize_header("CAPITAL PRE-TRADE") == "CAPITALPRETRADE"
    assert normalize_header("PROFIT/LOSS") == "PROFITLOSS"
    mapping = map_headers(
        ["SL. No.", "DATE", "TICKER", "BUY PRICE", "CUMULATIVE P/L", "CAPITAL AFTER ROW"]
    )
    assert mapping["ticker"] == "TICKER"
    assert mapping["cumulative_pl"] == "CUMULATIVE P/L"
    assert mapping["capital_after_row"] == "CAPITAL AFTER ROW"


# --------------------------------------------------------------------------- #
# Fixture-driven parse
# --------------------------------------------------------------------------- #
def test_fixture_parses_eleven_rows():
    result = load_trade_log_csv(FIXTURE)
    assert len(result.rows) == 11
    # No hard ERRORs in a clean fixture.
    assert result.errors() == []


def test_fixture_mixed_percent_and_comma_numbers():
    rows = {r.ticker: r for r in load_trade_log_csv(FIXTURE).rows}
    # DELTA used "80%", EPSILON used "0.8" -> identical normalized booked pct.
    assert rows["DELTA"].booked_pct == pytest.approx(0.8)
    assert rows["EPSILON"].booked_pct == pytest.approx(0.8)
    # Comma number parsed.
    assert rows["EPSILON"].buy_price == pytest.approx(1883.50)


def test_fixture_cumulative_pl_text_in_final_row():
    rows = load_trade_log_csv(FIXTURE).rows
    assert rows[-1].cumulative_pl == pytest.approx(29.76)


def test_fixture_remaining_fraction_inference():
    rows = {r.ticker: r for r in load_trade_log_csv(FIXTURE).rows}
    # DELTA: remaining blank, booked 0.8 -> inferred 0.2.
    assert rows["DELTA"].remaining_pct == pytest.approx(0.2)
    # ZETA: open, remaining "1" -> 1.0.
    assert rows["ZETA"].remaining_pct == pytest.approx(1.0)
    # ALPHA: closed -> remaining 0.0.
    assert rows["ALPHA"].remaining_pct == pytest.approx(0.0)


def test_capital_after_row_not_equity_info_emitted():
    result = load_trade_log_csv(FIXTURE)
    codes = {i.code for i in result.issues}
    assert CAPITAL_AFTER_ROW_NOT_EQUITY in codes


# --------------------------------------------------------------------------- #
# Validation issues
# --------------------------------------------------------------------------- #
def test_missing_ticker_is_error():
    result = normalize_rows([{"TICKER": "", "DATE": "14-05-2026", "PROFIT/LOSS": "1"}])
    assert any(i.code == MISSING_TICKER and i.severity == "ERROR" for i in result.issues)


def test_open_with_sell_price_warns():
    result = normalize_rows(
        [{"TICKER": "XYZ", "TRADE STATE": "OPEN", "SELL PRICE": "10", "DATE": "14-05-2026"}]
    )
    assert any(i.code == OPEN_WITH_SELL_PRICE for i in result.issues)


def test_unknown_trade_state_warns():
    result = normalize_rows([{"TICKER": "XYZ", "TRADE STATE": "TELEPORTED"}])
    assert any(i.code == UNKNOWN_TRADE_STATE for i in result.issues)
