"""Strong, pure validation for manual-trade records (operational hardening).

The existing ``signal_inbox_api.log_manual_trade`` already rejects empty
tickers, non-BUY/SELL sides, non-positive price/quantity, and seed/fixture
provenance markers.  This module adds the *next* layer of operator-mistake
defence that was previously missing:

  * **Ticker canonicalization** to a single ``EXCHANGE:SYMBOL`` form, so an
    Indian "AIR" on EPA cannot silently collide with a German "AIR" on ETR,
    and ``8306.T`` maps to ``TYO:8306`` instead of two different keys.
  * **Bare-symbol detection** — a symbol with no exchange and no resolvable
    suffix cannot be canonicalized and is flagged, instead of silently passing.
  * **Exchange → currency** derivation from an explicit, auditable mapping
    (no guessing from country), so reconciliation P/L is never computed across
    mismatched currencies.
  * **Whole-record validation** — invalid dates, exit-before-entry, unsupported
    exchange, missing provenance/mode, and a stable **natural key** for
    duplicate detection.

Pure module: no DB, no network, no broker calls, no side effects on import.
It is advisory-only infrastructure — it validates record-keeping, it never
places or authorizes a trade.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.supported_currencies import (  # type: ignore
        SUPPORTED_CURRENCY_CODES,
        UNKNOWN_CURRENCY,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from supported_currencies import (  # type: ignore[no-redef]
        SUPPORTED_CURRENCY_CODES,
        UNKNOWN_CURRENCY,
    )

# ---------------------------------------------------------------------------
# Authoritative exchange vocabulary.  Sourced from configs/jurisdictions.yaml
# (exchange_codes + primary_currency) and the global securities master, plus
# the explicit exchanges named in the operational-readiness spec.  Keep this
# explicit — deriving currency from country is exactly the ambiguity we are
# trying to remove.
# ---------------------------------------------------------------------------
EXCHANGE_CURRENCY: dict[str, str] = {
    # India
    "NSE": "INR", "BSE": "INR",
    # United States
    "NASDAQ": "USD", "NYSE": "USD", "NYSEARCA": "USD", "AMEX": "USD",
    "BATS": "USD", "CBOE": "USD",
    # United Kingdom
    "LSE": "GBP",
    # Euro area
    "ETR": "EUR", "XETRA": "EUR", "FRA": "EUR", "EPA": "EUR", "EURONEXT": "EUR",
    "AMS": "EUR", "EBR": "EUR", "BME": "EUR", "BIT": "EUR", "MCE": "EUR",
    # Japan
    "TYO": "JPY", "TSE": "JPY", "JPX": "JPY",
    # Korea
    "KRX": "KRW", "KOSPI": "KRW", "KOSDAQ": "KRW",
    # Greater China / HK / SG
    "HKG": "HKD", "HKEX": "HKD", "SSE": "CNY", "SZSE": "CNY", "SGX": "SGD",
    # Rest of world
    "ASX": "AUD", "TSX": "CAD", "SIX": "CHF", "STO": "SEK", "OSL": "NOK",
    "CPH": "DKK", "TWSE": "TWD", "BVMF": "BRL", "JSE": "ZAR", "TASE": "ILS",
}
KNOWN_EXCHANGES: frozenset[str] = frozenset(EXCHANGE_CURRENCY)

# yfinance-style suffix -> exchange code.  Lets ``8306.T`` canonicalize to
# ``TYO:8306`` and ``RELIANCE.NS`` to ``NSE:RELIANCE``.
SUFFIX_EXCHANGE: dict[str, str] = {
    ".NS": "NSE", ".BO": "BSE",
    ".T": "TYO", ".KS": "KRX", ".KQ": "KRX",
    ".L": "LSE",
    ".DE": "ETR", ".F": "FRA", ".PA": "EPA", ".AS": "AMS", ".MI": "BIT",
    ".MC": "MCE", ".BR": "EBR",
    ".HK": "HKG", ".SS": "SSE", ".SZ": "SZSE", ".SI": "SGX",
    ".AX": "ASX", ".TO": "TSX", ".SW": "SIX", ".ST": "STO", ".OL": "OSL",
    ".CO": "CPH", ".TW": "TWSE", ".SA": "BVMF", ".JO": "JSE", ".TA": "TASE",
}

# Allowed provenance / mode vocabularies for a manual-trade record.
ALLOWED_PROVENANCE_TYPES: frozenset[str] = frozenset(
    {"LIVE_MANUAL", "PAPER", "IMPORTED_BACKTEST", "SYNTHETIC"}
)
ALLOWED_DIRECTIONS: frozenset[str] = frozenset({"LONG", "SHORT", "BUY", "SELL"})


class TickerResolution:
    """Result of canonicalizing a ticker. Falsy ``ok`` means it was rejected."""

    __slots__ = ("ok", "canonical", "exchange", "symbol", "currency", "reason")

    def __init__(
        self,
        ok: bool,
        canonical: str | None = None,
        exchange: str | None = None,
        symbol: str | None = None,
        currency: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.ok = ok
        self.canonical = canonical
        self.exchange = exchange
        self.symbol = symbol
        self.currency = currency
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "canonical": self.canonical,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "currency": self.currency,
            "reason": self.reason,
        }


def canonical_ticker(raw: Any, exchange: Any = None) -> TickerResolution:
    """Resolve ``raw`` (+ optional ``exchange``) to a single EXCHANGE:SYMBOL.

    Resolution order:
      1. ``EXCHANGE:SYMBOL`` already → validate the exchange.
      2. Known suffix (``8306.T``) → map suffix to exchange.
      3. Explicit ``exchange`` argument + bare symbol → combine.
      4. Bare symbol, no exchange, no suffix → **rejected** (could collide
         across exchanges; the operator must say which exchange).
    """
    sym_raw = str(raw or "").strip().upper()
    if not sym_raw:
        return TickerResolution(False, reason="empty_ticker")

    exch_arg = str(exchange or "").strip().upper()

    # 1. Explicit EXCHANGE:SYMBOL form.
    if ":" in sym_raw:
        exch, _, sym = sym_raw.partition(":")
        exch = exch.strip()
        sym = sym.strip()
        if not sym:
            return TickerResolution(False, reason="empty_symbol_after_exchange")
        if exch not in KNOWN_EXCHANGES:
            return TickerResolution(False, reason=f"unsupported_exchange:{exch}")
        return _resolved(exch, sym)

    # 2. Known yfinance suffix (longest match first so ``.TWO`` beats ``.TW``).
    for suffix in sorted(SUFFIX_EXCHANGE, key=len, reverse=True):
        if sym_raw.endswith(suffix):
            sym = sym_raw[: -len(suffix)]
            if not sym:
                return TickerResolution(False, reason="empty_symbol_before_suffix")
            return _resolved(SUFFIX_EXCHANGE[suffix], sym)

    # 3. Explicit exchange argument + bare symbol.
    if exch_arg:
        if exch_arg not in KNOWN_EXCHANGES:
            return TickerResolution(False, reason=f"unsupported_exchange:{exch_arg}")
        return _resolved(exch_arg, sym_raw)

    # 4. Bare symbol with no exchange and no suffix — ambiguous, reject.
    return TickerResolution(
        False, symbol=sym_raw, reason="bare_symbol_no_exchange",
    )


def _resolved(exch: str, sym: str) -> TickerResolution:
    return TickerResolution(
        True,
        canonical=f"{exch}:{sym}",
        exchange=exch,
        symbol=sym,
        currency=EXCHANGE_CURRENCY.get(exch, UNKNOWN_CURRENCY),
        reason=None,
    )


def currency_for_exchange(exchange: Any) -> str | None:
    """Authoritative currency for an exchange code, or None if unknown."""
    return EXCHANGE_CURRENCY.get(str(exchange or "").strip().upper())


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        # Date-only ISO (YYYY-MM-DD) is acceptable.
        try:
            return datetime.fromisoformat(text + "T00:00:00")
        except ValueError:
            return None


def _to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_manual_trade(record: dict[str, Any]) -> list[str]:
    """Return a list of violation codes for a manual-trade record (empty = OK).

    Checks (each maps to one stable violation code):
      missing_ticker, bare_symbol_no_exchange / unsupported_exchange,
      non_positive_entry_price, non_positive_quantity, invalid_entry_date,
      exit_before_entry, missing_or_invalid_currency, currency_exchange_mismatch,
      invalid_direction, missing_provenance_type, unknown_mode.
    """
    violations: list[str] = []

    # Ticker / exchange canonicalization.
    res = canonical_ticker(record.get("ticker"), record.get("exchange"))
    if not res.ok:
        violations.append(res.reason or "ticker_not_canonical")

    # Prices / quantities must be strictly positive.
    entry_price = _to_number(record.get("entry_price"))
    if entry_price is None or entry_price <= 0:
        violations.append("non_positive_entry_price")

    qty = _to_number(record.get("quantity"))
    notional = _to_number(record.get("notional"))
    if (qty is None or qty <= 0) and (notional is None or notional <= 0):
        violations.append("non_positive_quantity")

    # Dates.
    entry_dt = _parse_date(record.get("entry_date"))
    if record.get("entry_date") not in (None, "") and entry_dt is None:
        violations.append("invalid_entry_date")
    exit_raw = record.get("exit_date")
    if exit_raw not in (None, ""):
        exit_dt = _parse_date(exit_raw)
        if exit_dt is None:
            violations.append("invalid_exit_date")
        elif entry_dt is not None and exit_dt < entry_dt:
            violations.append("exit_before_entry")

    # Currency must be supported and consistent with the resolved exchange.
    currency = str(record.get("currency") or "").strip().upper()
    if currency and currency != UNKNOWN_CURRENCY and currency not in SUPPORTED_CURRENCY_CODES:
        violations.append("missing_or_invalid_currency")
    elif res.ok and res.currency and res.currency != UNKNOWN_CURRENCY:
        if currency and currency not in (UNKNOWN_CURRENCY, res.currency):
            violations.append("currency_exchange_mismatch")
    elif not currency:
        violations.append("missing_or_invalid_currency")

    # Direction.
    direction = str(record.get("direction") or record.get("side") or "").strip().upper()
    if direction and direction not in ALLOWED_DIRECTIONS:
        violations.append("invalid_direction")

    # Provenance / mode.
    prov = str(record.get("provenance_type") or "").strip().upper()
    if not prov:
        violations.append("missing_provenance_type")
    elif prov not in ALLOWED_PROVENANCE_TYPES:
        violations.append("unknown_mode")

    return violations


def is_valid_manual_trade(record: dict[str, Any]) -> bool:
    return not validate_manual_trade(record)


def manual_trade_natural_key(record: dict[str, Any]) -> str:
    """Stable natural key for duplicate detection (sha256 hex).

    Built from the *canonical* ticker so the same economic trade logged with
    ``RELIANCE.NS`` and ``NSE:RELIANCE`` collapses to one key, while ``AIR`` on
    EPA and ETR stay distinct.  Two records with the same key are duplicates.
    """
    res = canonical_ticker(record.get("ticker"), record.get("exchange"))
    canonical = res.canonical or f"RAW:{str(record.get('ticker') or '').strip().upper()}"
    entry_price = _to_number(record.get("entry_price"))
    price_str = f"{entry_price:.6f}" if entry_price is not None else "NA"
    direction = str(record.get("direction") or record.get("side") or "").strip().upper()
    provenance = str(record.get("provenance_type") or "").strip().upper()
    source = str(
        record.get("source_signal_id")
        or record.get("event_id")
        or record.get("manual_entry_id")
        or "MANUAL"
    ).strip()
    entry_date = str(record.get("entry_date") or "").strip()
    parts = [canonical, entry_date, price_str, direction, provenance, source]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


__all__ = [
    "EXCHANGE_CURRENCY",
    "KNOWN_EXCHANGES",
    "SUFFIX_EXCHANGE",
    "ALLOWED_PROVENANCE_TYPES",
    "ALLOWED_DIRECTIONS",
    "TickerResolution",
    "canonical_ticker",
    "currency_for_exchange",
    "validate_manual_trade",
    "is_valid_manual_trade",
    "manual_trade_natural_key",
]
