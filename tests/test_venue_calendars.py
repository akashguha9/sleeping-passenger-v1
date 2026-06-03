"""T5 (H3) — per-venue session-close timestamps replace the hardcoded
T16:00:00Z. Pins that NSE / TSE / KRX / LSE / NYSE / Xetra each land in
their own UTC window, and that daylight savings is respected.
"""
from __future__ import annotations

from datetime import date

from scripts.venue_calendars import (
    venue_close_iso,
    venue_close_utc,
    venue_for_symbol,
)


# ---------------------------------------------------------------------------
# Suffix and sigil resolution
# ---------------------------------------------------------------------------


def test_venue_inferred_from_yfinance_suffix():
    assert venue_for_symbol("BHARTIARTL.NS") == "NS"
    assert venue_for_symbol("7203.T") == "T"
    assert venue_for_symbol("SAP.DE") == "DE"
    assert venue_for_symbol("HSBA.L") == "L"
    assert venue_for_symbol("005930.KS") == "KS"


def test_bare_us_ticker_defaults_to_us():
    assert venue_for_symbol("AAPL") == "US"
    assert venue_for_symbol("nvda") == "US"


def test_index_sigils_map_to_their_venues():
    assert venue_for_symbol("^GDAXI") == "DE"
    assert venue_for_symbol("^N225") == "T"
    assert venue_for_symbol("^NSEI") == "NS"
    assert venue_for_symbol("^FTSE") == "L"
    assert venue_for_symbol("^GSPC") == "US"


# ---------------------------------------------------------------------------
# Each venue closes at its own UTC time -- this is the H3 invariant.
# ---------------------------------------------------------------------------


def test_close_times_are_venue_specific_not_global_16z():
    d = date(2026, 1, 15)  # winter (no DST anywhere)
    nse = venue_close_iso("RELIANCE.NS", d)
    tse = venue_close_iso("7203.T", d)
    krx = venue_close_iso("005930.KS", d)
    lse = venue_close_iso("HSBA.L", d)
    nyse = venue_close_iso("AAPL", d)
    xetra = venue_close_iso("SAP.DE", d)
    # NONE should be the old 16:00Z fallback for every venue. At least these
    # three (NSE, TSE, KRX) close BEFORE 16:00Z, and US closes AFTER.
    assert nse < "2026-01-15T16:00:00Z", f"NSE should close before 16Z, got {nse}"
    assert tse < "2026-01-15T16:00:00Z", f"TSE should close before 16Z, got {tse}"
    assert krx < "2026-01-15T16:00:00Z", f"KRX should close before 16Z, got {krx}"
    assert nyse > "2026-01-15T16:00:00Z", f"NYSE should close after 16Z in EST, got {nyse}"
    # London closes ~16:30 GMT == 16:30Z in winter.
    assert lse == "2026-01-15T16:30:00Z"
    # Xetra closes 17:30 CET == 16:30Z in winter.
    assert xetra == "2026-01-15T16:30:00Z"


def test_nse_winter_close_is_1000z():
    """NSE closes 15:30 IST = 10:00 UTC year-round (IST has no DST)."""
    assert venue_close_iso("RELIANCE.NS", date(2026, 1, 15)) == "2026-01-15T10:00:00Z"
    assert venue_close_iso("RELIANCE.NS", date(2026, 7, 15)) == "2026-07-15T10:00:00Z"


def test_tse_close_is_0600z():
    """TSE closes 15:00 JST = 06:00 UTC year-round (JST has no DST)."""
    assert venue_close_iso("7203.T", date(2026, 1, 15)) == "2026-01-15T06:00:00Z"


def test_daylight_savings_shifts_us_close_one_hour():
    """NYSE closes 16:00 ET. In winter (EST) that's 21:00Z; in summer
    (EDT) that's 20:00Z. The function must respect DST."""
    winter = venue_close_utc("AAPL", date(2026, 1, 15))
    summer = venue_close_utc("AAPL", date(2026, 7, 15))
    assert winter.hour == 21
    assert summer.hour == 20


# ---------------------------------------------------------------------------
# Regression: backfill_ohlcv_history must no longer hardcode 'T16:00:00Z'.
# ---------------------------------------------------------------------------


def test_backfill_no_longer_hardcodes_16z():
    from pathlib import Path
    src = Path("scripts/backfill_ohlcv_history.py").read_text(encoding="utf-8")
    # The literal that previously stamped every venue at 16:00 UTC.
    assert 'date_str + "T16:00:00Z"' not in src, (
        "backfill_ohlcv_history must use venue-specific close timestamps "
        "(scripts/venue_calendars.venue_close_iso) — the hardcoded "
        "'T16:00:00Z' is the H3 bug and must not reappear."
    )
    # And it must import the venue helper.
    assert "venue_close_iso" in src, "backfill must use venue_close_iso"
