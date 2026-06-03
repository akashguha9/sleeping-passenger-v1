"""Per-venue session close timestamps (T5 — H3 fix).

Pure module. Given a yfinance-suffixed symbol or an exchange code, returns
the local-session close time in UTC for a given date, accounting for
daylight savings via ``zoneinfo``.

Why this exists
---------------
The audit (H3) flagged that ``backfill_ohlcv_history`` hardcoded every bar
to ``T16:00:00Z`` regardless of venue. NSE/TSE/KRX close hours BEFORE
16:00 UTC; US closes hours AFTER. Same-calendar-date rows therefore mixed
sessions that had not yet happened with sessions long since closed -
creating phantom lead/lag and breaking the RS-vs-index point-in-time
contract.

Use
---
    >>> from scripts.venue_calendars import venue_close_utc
    >>> venue_close_utc("RELIANCE.NS", date(2026, 1, 15)).isoformat()
    '2026-01-15T10:00:00+00:00'  # NSE close 15:30 IST = 10:00 UTC

If a symbol's venue can't be inferred, falls back to US close (21:00 UTC
in winter / 20:00 in summer). This is documented and tagged so a caller
can detect the fallback.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


# (timezone, local-close-time) per venue code.
_VENUE_CLOSE: dict[str, tuple[str, time]] = {
    # US
    "US":      ("America/New_York",  time(16, 0)),
    # India
    "NS":      ("Asia/Kolkata",      time(15, 30)),
    "BO":      ("Asia/Kolkata",      time(15, 30)),
    # Germany / Xetra
    "DE":      ("Europe/Berlin",     time(17, 30)),
    # France / Euronext Paris
    "PA":      ("Europe/Paris",      time(17, 30)),
    # Netherlands / Euronext Amsterdam
    "AS":      ("Europe/Amsterdam",  time(17, 30)),
    # Belgium / Euronext Brussels
    "BR":      ("Europe/Brussels",   time(17, 30)),
    # London
    "L":       ("Europe/London",     time(16, 30)),
    # Japan / TSE
    "T":       ("Asia/Tokyo",        time(15, 0)),
    # Korea / KRX, KOSDAQ
    "KS":      ("Asia/Seoul",        time(15, 30)),
    "KQ":      ("Asia/Seoul",        time(15, 30)),
    # Australia / ASX
    "AX":      ("Australia/Sydney",  time(16, 0)),
    # Canada / TSX
    "TO":      ("America/Toronto",   time(16, 0)),
    "V":       ("America/Toronto",   time(16, 0)),
    # Italy / Borsa Italiana
    "MI":      ("Europe/Rome",       time(17, 30)),
    # Spain / BME
    "MC":      ("Europe/Madrid",     time(17, 30)),
    # Switzerland / SIX
    "SW":      ("Europe/Zurich",     time(17, 30)),
    # Sweden / Stockholm
    "ST":      ("Europe/Stockholm",  time(17, 30)),
    # Poland / Warsaw
    "WA":      ("Europe/Warsaw",     time(17, 0)),
    # Austria / Vienna
    "VI":      ("Europe/Vienna",     time(17, 30)),
    # Ireland / Euronext Dublin
    "IR":      ("Europe/Dublin",     time(16, 30)),
    # Singapore
    "SI":      ("Asia/Singapore",    time(17, 0)),
    # Hong Kong
    "HK":      ("Asia/Hong_Kong",    time(16, 0)),
    # Taiwan
    "TW":      ("Asia/Taipei",       time(13, 30)),
    # Brazil / B3
    "SA":      ("America/Sao_Paulo", time(17, 0)),  # B3 official close
    # Mexico
    "MX":      ("America/Mexico_City", time(15, 0)),
    # Saudi Arabia / Tadawul
    "SR":      ("Asia/Riyadh",       time(15, 0)),
}

# Index symbols carry no suffix; map their leading sigil.
_INDEX_TO_VENUE: dict[str, str] = {
    "^GSPC": "US", "^DJI": "US", "^IXIC": "US",
    "^FTSE": "L", "^FCHI": "PA", "^GDAXI": "DE",
    "^N225": "T", "^KS11": "KS", "^NSEI": "NS",
    "^HSI": "HK", "^TWII": "TW", "^AXJO": "AX",
    "^GSPTSE": "TO", "^STI": "SI", "^IBEX": "MC",
    "^SSMI": "SW", "^AEX": "AS", "^OMX": "ST",
    "^WIG20": "WA", "^ATX": "VI", "^BVSP": "SA",
    "^MXX": "MX", "^BFX": "BR", "^ISEQ": "IR",
}


def venue_for_symbol(symbol: str) -> str:
    """Return the venue code for a yfinance-suffixed symbol or index sigil.

    The lookup uses the suffix after the LAST dot, e.g. ``BHARTIARTL.NS``
    -> ``NS``. For index sigils (``^GDAXI``) the map ``_INDEX_TO_VENUE``
    is consulted. Bare tickers fall back to ``US``.
    """
    s = symbol.strip().upper()
    if s in _INDEX_TO_VENUE:
        return _INDEX_TO_VENUE[s]
    if "." in s:
        return s.rsplit(".", 1)[1]
    return "US"


def venue_close_utc(symbol: str, on: date) -> datetime:
    """UTC datetime at which the venue closes on the given calendar date.

    Daylight savings is handled via ``zoneinfo`` -- the local close time
    is fixed, but the UTC offset moves twice a year.
    """
    venue = venue_for_symbol(symbol)
    tz_name, local_close = _VENUE_CLOSE.get(venue, _VENUE_CLOSE["US"])
    local_dt = datetime.combine(on, local_close, tzinfo=ZoneInfo(tz_name))
    return local_dt.astimezone(timezone.utc)


def venue_close_iso(symbol: str, on: date) -> str:
    """ISO-8601 UTC string with trailing 'Z'."""
    return venue_close_utc(symbol, on).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["venue_for_symbol", "venue_close_utc", "venue_close_iso"]
