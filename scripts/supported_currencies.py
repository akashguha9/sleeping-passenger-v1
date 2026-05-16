"""
Supported currency catalogue for the Manual Trade Log.

Single source of truth for "which currency may an operator-entered manual
trade carry".  The catalogue covers the currencies of the top 30
economies the operator is most likely to trade — sharing currencies
(EUR) are deduplicated to one entry with a list of countries.

Used by:
  - scripts/signal_inbox_api.log_manual_trade   (normalisation)
  - scripts/api_server.py                       (config endpoint)
  - tests/test_supported_currencies.py          (matrix coverage)
  - frontend/src/lib/supportedCurrencies.ts     (dropdown options —
    duplicated by design so the frontend builds without a backend call;
    a cross-side test asserts both lists stay in sync)

Safety contract: record-keeping only.  Storing a currency on a manual
trade never grants execution permission and never calls a broker.
"""
from __future__ import annotations

from typing import Any


# (code, name, [country labels]) — country labels are the human-readable
# anchor for the operator; the code is what we persist.  EUR groups all
# eurozone countries into one entry.  The list order is intentionally
# top-30-economies ranked, with the sharing-EUR group bubbled to its
# first occurrence and unique entries following in order.
_SUPPORTED_CURRENCIES: tuple[dict[str, Any], ...] = (
    {"code": "USD", "name": "United States dollar", "countries": ["United States"]},
    {"code": "CNY", "name": "Chinese yuan",         "countries": ["China"]},
    {"code": "EUR", "name": "Euro",                 "countries": [
        "Germany", "France", "Italy", "Spain",
        "Netherlands", "Ireland", "Belgium", "Austria",
    ]},
    {"code": "JPY", "name": "Japanese yen",         "countries": ["Japan"]},
    {"code": "GBP", "name": "British pound",        "countries": ["United Kingdom"]},
    {"code": "INR", "name": "Indian rupee",         "countries": ["India"]},
    {"code": "RUB", "name": "Russian ruble",        "countries": ["Russia"]},
    {"code": "BRL", "name": "Brazilian real",       "countries": ["Brazil"]},
    {"code": "CAD", "name": "Canadian dollar",      "countries": ["Canada"]},
    {"code": "AUD", "name": "Australian dollar",    "countries": ["Australia"]},
    {"code": "MXN", "name": "Mexican peso",         "countries": ["Mexico"]},
    {"code": "KRW", "name": "South Korean won",     "countries": ["South Korea"]},
    {"code": "TRY", "name": "Turkish lira",         "countries": ["Turkey"]},
    {"code": "IDR", "name": "Indonesian rupiah",    "countries": ["Indonesia"]},
    {"code": "SAR", "name": "Saudi riyal",          "countries": ["Saudi Arabia"]},
    {"code": "CHF", "name": "Swiss franc",          "countries": ["Switzerland"]},
    {"code": "PLN", "name": "Polish zloty",         "countries": ["Poland"]},
    {"code": "TWD", "name": "New Taiwan dollar",    "countries": ["Taiwan"]},
    {"code": "SEK", "name": "Swedish krona",        "countries": ["Sweden"]},
    {"code": "ILS", "name": "Israeli new shekel",   "countries": ["Israel"]},
    {"code": "ARS", "name": "Argentine peso",       "countries": ["Argentina"]},
    {"code": "SGD", "name": "Singapore dollar",     "countries": ["Singapore"]},
    {"code": "AED", "name": "UAE dirham",           "countries": ["United Arab Emirates"]},
)


SUPPORTED_CURRENCY_CODES: frozenset[str] = frozenset(
    c["code"] for c in _SUPPORTED_CURRENCIES
)

# Special sentinel — operators may legitimately log a trade in a
# currency we don't yet recognise; storing UNKNOWN is preferable to
# silently defaulting to USD.  Legacy rows without a stored currency
# also normalise to UNKNOWN on read.
UNKNOWN_CURRENCY: str = "UNKNOWN"

# Symbol-suffix → currency convenience map.  Used to *suggest* a default
# in the dropdown for tickers like ``BHARTIARTL.NS`` → INR.  The
# operator must still confirm the selection — we never silently submit
# an inferred currency.  Keep in sync with the chart-structure suffix
# map (different convention but same suffix→currency idea).
SYMBOL_SUFFIX_CURRENCY: dict[str, str] = {
    ".NS": "INR", ".BO": "INR",
    ".DE": "EUR", ".PA": "EUR", ".AS": "EUR", ".MI": "EUR",
    ".MC": "EUR", ".BR": "EUR", ".LS": "EUR", ".HE": "EUR",
    ".VI": "EUR", ".IR": "EUR", ".F": "EUR", ".BE": "EUR",
    ".HM": "EUR", ".MU": "EUR", ".SG": "EUR",
    ".L": "GBP", ".IL": "GBP",
    ".TO": "CAD", ".V": "CAD",
    ".AX": "AUD", ".NZ": "NZD",
    ".HK": "HKD",
    ".T": "JPY",
    ".KS": "KRW", ".KQ": "KRW",
    ".SW": "CHF", ".ST": "SEK", ".OL": "NOK", ".CO": "DKK",
    ".SS": "CNY", ".SZ": "CNY",
    ".TW": "TWD", ".TWO": "TWD",
    ".SI": "SGD",
    ".BK": "THB", ".JK": "IDR", ".KL": "MYR",
    ".MX": "MXN", ".SA": "BRL", ".SN": "CLP", ".BA": "ARS",
    ".JO": "ZAR", ".TA": "ILS",
}


def supported_currencies() -> list[dict[str, Any]]:
    """Return the dropdown catalogue as a list of dicts (immutable copy)."""
    return [dict(c, countries=list(c["countries"])) for c in _SUPPORTED_CURRENCIES]


def normalise_currency(value: Any) -> str:
    """Coerce arbitrary input into a canonical currency code.

    Rules:
      - None / empty / whitespace → UNKNOWN
      - Matches a supported code (case-insensitive)  → that code
      - Anything else (legacy, hostile, typo)        → UNKNOWN

    This is the persistence-boundary check.  Storing UNKNOWN beats
    storing a misspelt symbol that later confuses reconciliation P/L.
    """
    if value is None:
        return UNKNOWN_CURRENCY
    text = str(value).strip().upper()
    if not text:
        return UNKNOWN_CURRENCY
    if text in SUPPORTED_CURRENCY_CODES:
        return text
    return UNKNOWN_CURRENCY


def suggest_currency_for_symbol(symbol: str | None) -> str | None:
    """Best-effort currency guess from a yfinance-style symbol.

    Returns a supported currency code or ``None`` when we cannot
    confidently guess.  Bare US tickers (no dot, no dash) → USD.
    The caller must still let the operator override the suggestion.
    """
    if not symbol:
        return None
    sym = str(symbol).strip().upper()
    if not sym:
        return None
    for suffix, cur in SYMBOL_SUFFIX_CURRENCY.items():
        if sym.endswith(suffix):
            return cur if cur in SUPPORTED_CURRENCY_CODES else None
    if "-" in sym:
        parts = sym.split("-")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isalpha():
            return parts[1] if parts[1] in SUPPORTED_CURRENCY_CODES else None
    if "." not in sym and "-" not in sym:
        return "USD"
    return None


__all__ = [
    "SUPPORTED_CURRENCY_CODES",
    "SYMBOL_SUFFIX_CURRENCY",
    "UNKNOWN_CURRENCY",
    "supported_currencies",
    "normalise_currency",
    "suggest_currency_for_symbol",
]
