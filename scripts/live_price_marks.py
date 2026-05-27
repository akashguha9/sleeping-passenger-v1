"""Live price marks — advisory-only live/delayed price ingestion.

Capital Rotation Engine — live price layer.

This module is the read-only price-mark layer that the Capital Rotation
Engine consults to decide whether mechanical exit / TP / stop math may
run on current prices.  It never executes a trade, never calls a broker
API, never opens a new external dependency: the only providers it can
use are the read-only helpers that already exist in this repo
(`scripts.yahoo_market_data_adapter`, the daily market snapshot, the
release-summary live_price field, the manual-trade SQLite mirror).

The output is an advisory-only LiveMarkResult.  Every LiveMark carries
the canonical safety stamps so the downstream summary writer and the
HTTP routes don't have to re-attach them.

Contract — pure module
----------------------
- Importing has no side effects.
- No broker call.  No order placement.  No execution.
- Network reads are *opt-in* via ``allow_network=True``; tests run with
  ``allow_network=False`` and pass an explicit ``fetcher``.
- Stale / unusable marks are labelled honestly; the module never
  hallucinates a price.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:
    from scripts.runtime_common import REPO_ROOT
    from scripts.daily_payload import load_market_snapshot
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from runtime_common import REPO_ROOT  # type: ignore
    from daily_payload import load_market_snapshot  # type: ignore
    from advisory_contract import advisory_safety_stamps  # type: ignore


DEFAULT_DB_PATH = REPO_ROOT / "runtime" / "mvp_local.db"
DEFAULT_RELEASE_DIR = REPO_ROOT / "runtime" / "release"

LIVE_MARK_SUMMARY_FILENAME = "live_price_marks_summary.json"


# ---------------------------------------------------------------------------
# Source-health vocabulary + reason codes
# ---------------------------------------------------------------------------

LIVE_VERIFIED = "LIVE_VERIFIED"
DELAYED_BUT_USABLE = "DELAYED_BUT_USABLE"
PARTIAL = "PARTIAL"
STALE_PRICE = "STALE_PRICE"
NO_LIVE_MARK = "NO_LIVE_MARK"

DEGRADED = "DEGRADED"
NO_LIVE_MARKS = "NO_LIVE_MARKS"

ALL_SOURCE_HEALTHS: tuple[str, ...] = (
    LIVE_VERIFIED,
    DELAYED_BUT_USABLE,
    PARTIAL,
    STALE_PRICE,
    NO_LIVE_MARK,
)

CONSENSUS_TIGHT = "CONSENSUS_TIGHT"
CONSENSUS_ACCEPTABLE = "CONSENSUS_ACCEPTABLE"
CONSENSUS_CONFLICT = "CONSENSUS_CONFLICT"
CONSENSUS_SINGLE_PROVIDER = "SINGLE_PROVIDER"

REASON_LIVE_MARK_MISSING = "LIVE_MARK_MISSING"
REASON_LIVE_MARK_STALE = "LIVE_MARK_STALE"
REASON_LIVE_MARK_UNUSABLE = "LIVE_MARK_UNUSABLE"
REASON_LIVE_MARK_PROVIDER_DISAGREEMENT = "LIVE_MARK_PROVIDER_DISAGREEMENT"
REASON_LIVE_MARK_FROM_YFINANCE = "LIVE_MARK_FROM_YFINANCE"
REASON_LIVE_MARK_FROM_SNAPSHOT = "LIVE_MARK_FROM_SNAPSHOT"
REASON_LIVE_MARK_FROM_DB = "LIVE_MARK_FROM_DB"
REASON_LIVE_MARK_FROM_RELEASE = "LIVE_MARK_FROM_RELEASE"
REASON_LIVE_MARK_MERGED = "LIVE_MARK_MERGED"
REASON_CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
REASON_MARKET_CALENDAR_UNKNOWN = "MARKET_CALENDAR_UNKNOWN"
REASON_NO_USABLE_LIVE_MARK = "NO_USABLE_LIVE_MARK"
REASON_STATIC_SYMBOL_ONLY_NO_PRICE = "STATIC_SYMBOL_ONLY_NO_PRICE"
REASON_COVERAGE_FULL = "LIVE_MARK_COVERAGE_FULL"
REASON_COVERAGE_PARTIAL = "LIVE_MARK_COVERAGE_PARTIAL"
REASON_COVERAGE_LOW = "LIVE_MARK_COVERAGE_LOW"
REASON_NO_LIVE_MARKS = "NO_LIVE_MARKS"
REASON_SOME_MARKS_STALE = "SOME_MARKS_STALE"
REASON_SOME_MARKS_MISSING = "SOME_MARKS_MISSING"
REASON_NETWORK_DISALLOWED = "NETWORK_DISALLOWED"

PROVIDER_WEIGHT_DEFAULTS: dict[str, float] = {
    "canonical_db_live_mark": 1.00,
    "existing_yfinance_provider": 0.85,
    "today_market_snapshot": 0.75,
    "signal_events_market_mark": 0.75,
    "release_summary": 0.65,
    "fallback_static": 0.00,
    "fixture": 0.85,
}

DEFAULT_STALE_HOURS = 48.0
DEFAULT_MARKET_CLOSED_TOLERANCE_HOURS = 96.0


# ---------------------------------------------------------------------------
# Ticker normalization and market inference
# ---------------------------------------------------------------------------


_YAHOO_SUFFIXES = (
    ".NS",
    ".BO",
    ".DE",
    ".PA",
    ".AS",
    ".MI",
    ".L",
    ".SW",
    ".TO",
    ".HK",
    ".T",
    ".AX",
)


_EXCHANGE_PREFIX_MAP: dict[str, dict[str, Any]] = {
    "NASDAQ": {"country": "United States", "currency": "USD", "tz": "America/New_York"},
    "NYSE": {"country": "United States", "currency": "USD", "tz": "America/New_York"},
    "NYSEARCA": {"country": "United States", "currency": "USD", "tz": "America/New_York"},
    "AMEX": {"country": "United States", "currency": "USD", "tz": "America/New_York"},
    "BATS": {"country": "United States", "currency": "USD", "tz": "America/New_York"},
    "ARCA": {"country": "United States", "currency": "USD", "tz": "America/New_York"},
    "OTC": {"country": "United States", "currency": "USD", "tz": "America/New_York"},
    "NSE": {
        "country": "India",
        "currency": "INR",
        "tz": "Asia/Kolkata",
        "yahoo_suffix": ".NS",
    },
    "BSE": {
        "country": "India",
        "currency": "INR",
        "tz": "Asia/Kolkata",
        "yahoo_suffix": ".BO",
    },
    "ETR": {
        "country": "Germany",
        "currency": "EUR",
        "tz": "Europe/Berlin",
        "yahoo_suffix": ".DE",
    },
    "FRA": {
        "country": "Germany",
        "currency": "EUR",
        "tz": "Europe/Berlin",
        "yahoo_suffix": ".DE",
    },
    "EPA": {
        "country": "France",
        "currency": "EUR",
        "tz": "Europe/Paris",
        "yahoo_suffix": ".PA",
    },
    "AMS": {
        "country": "Netherlands",
        "currency": "EUR",
        "tz": "Europe/Amsterdam",
        "yahoo_suffix": ".AS",
    },
    "LON": {
        "country": "United Kingdom",
        "currency": "GBP",
        "tz": "Europe/London",
        "yahoo_suffix": ".L",
    },
    "BIT": {
        "country": "Italy",
        "currency": "EUR",
        "tz": "Europe/Rome",
        "yahoo_suffix": ".MI",
    },
    "SWX": {
        "country": "Switzerland",
        "currency": "CHF",
        "tz": "Europe/Zurich",
        "yahoo_suffix": ".SW",
    },
    "TSE": {
        "country": "Japan",
        "currency": "JPY",
        "tz": "Asia/Tokyo",
        "yahoo_suffix": ".T",
    },
    "HKG": {
        "country": "Hong Kong",
        "currency": "HKD",
        "tz": "Asia/Hong_Kong",
        "yahoo_suffix": ".HK",
    },
    "TSX": {
        "country": "Canada",
        "currency": "CAD",
        "tz": "America/Toronto",
        "yahoo_suffix": ".TO",
    },
    "ASX": {
        "country": "Australia",
        "currency": "AUD",
        "tz": "Australia/Sydney",
        "yahoo_suffix": ".AX",
    },
}

_YAHOO_SUFFIX_TO_MARKET: dict[str, dict[str, Any]] = {
    ".NS": {"country": "India", "currency": "INR", "market_code": "NSE", "tz": "Asia/Kolkata"},
    ".BO": {"country": "India", "currency": "INR", "market_code": "BSE", "tz": "Asia/Kolkata"},
    ".DE": {"country": "Germany", "currency": "EUR", "market_code": "ETR", "tz": "Europe/Berlin"},
    ".PA": {"country": "France", "currency": "EUR", "market_code": "EPA", "tz": "Europe/Paris"},
    ".AS": {"country": "Netherlands", "currency": "EUR", "market_code": "AMS", "tz": "Europe/Amsterdam"},
    ".L": {"country": "United Kingdom", "currency": "GBP", "market_code": "LON", "tz": "Europe/London"},
    ".MI": {"country": "Italy", "currency": "EUR", "market_code": "BIT", "tz": "Europe/Rome"},
    ".SW": {"country": "Switzerland", "currency": "CHF", "market_code": "SWX", "tz": "Europe/Zurich"},
    ".T": {"country": "Japan", "currency": "JPY", "market_code": "TSE", "tz": "Asia/Tokyo"},
    ".HK": {"country": "Hong Kong", "currency": "HKD", "market_code": "HKG", "tz": "Asia/Hong_Kong"},
    ".TO": {"country": "Canada", "currency": "CAD", "market_code": "TSX", "tz": "America/Toronto"},
    ".AX": {"country": "Australia", "currency": "AUD", "market_code": "ASX", "tz": "Australia/Sydney"},
}


@dataclass
class MarketInfo:
    market_code: str
    country: str
    exchange_hint: str | None
    provider_symbol: str
    trading_currency: str
    expected_timezone: str | None
    stale_after_hours: float
    asset_type: str  # "EQUITY" | "ETF" | "UNKNOWN"


def _strip_exchange_prefix(text: str) -> tuple[str, str | None]:
    """Return ``(bare_symbol, exchange_prefix_or_None)``.

    ``NASDAQ:GOOGL`` → ``("GOOGL", "NASDAQ")``.  ``GOOGL`` → ``("GOOGL", None)``.
    """
    if ":" in text:
        prefix, _, rest = text.partition(":")
        return rest.strip(), prefix.strip().upper() or None
    return text, None


def _yahoo_suffix(text: str) -> str | None:
    upper = text.upper()
    for suffix in _YAHOO_SUFFIXES:
        if upper.endswith(suffix):
            return suffix
    return None


def normalize_ticker_for_market_data(
    ticker: str,
    country: str | None = None,
    currency: str | None = None,
) -> str:
    """Map an operator/holding ticker into the Yahoo-style provider symbol.

    Rules:
      * Strip exchange prefix (``NASDAQ:GOOGL`` → ``GOOGL``).
      * If the bare symbol already carries a known Yahoo suffix, keep it.
      * Map exchange prefix → Yahoo suffix when one applies
        (``ETR:SAP`` → ``SAP.DE``, ``EPA:AIR`` → ``AIR.PA``,
        ``NSE:RELIANCE`` → ``RELIANCE.NS``).
      * Convert ``BRK.B``-style class shares to provider hyphen form
        when the suffix is ambiguous (Yahoo uses ``BRK-B``).
      * Empty / None in → empty out.
    """
    if ticker is None:
        return ""
    text = str(ticker).strip().upper()
    if not text:
        return ""
    bare, prefix = _strip_exchange_prefix(text)
    if not bare:
        return ""

    existing_suffix = _yahoo_suffix(bare)
    if existing_suffix:
        return bare

    if prefix and prefix in _EXCHANGE_PREFIX_MAP:
        cfg = _EXCHANGE_PREFIX_MAP[prefix]
        suffix = cfg.get("yahoo_suffix")
        if suffix:
            return f"{bare}{suffix}"
        # US exchanges — Yahoo uses the bare symbol with class share
        # dots converted to hyphens.
        if "." in bare:
            head, _, tail = bare.rpartition(".")
            if head and tail and len(tail) <= 2:
                return f"{head}-{tail}"
        return bare

    country_text = (country or "").strip().lower()
    currency_text = (currency or "").strip().upper()
    if country_text == "india" or currency_text == "INR":
        return f"{bare}.NS"
    if country_text == "germany" or (
        currency_text == "EUR" and prefix in {"FRA", "ETR"}
    ):
        return f"{bare}.DE"
    if country_text == "france":
        return f"{bare}.PA"
    if country_text == "united kingdom" or currency_text == "GBP":
        return f"{bare}.L"

    # US-style class shares without a Yahoo suffix.
    if "." in bare and not existing_suffix:
        head, _, tail = bare.rpartition(".")
        if head and tail and len(tail) <= 2 and (
            currency_text == "USD" or country_text == "united states"
        ):
            return f"{head}-{tail}"
    return bare


def infer_market_from_ticker(
    ticker: str,
    country: str | None = None,
    currency: str | None = None,
) -> MarketInfo:
    """Best-effort market inference for a position ticker.

    Returns conservative defaults when nothing matches; the
    ``stale_after_hours`` field is the budget the freshness math will
    use.
    """
    text = (str(ticker or "")).strip().upper()
    bare, prefix = _strip_exchange_prefix(text)
    provider_symbol = normalize_ticker_for_market_data(text, country, currency)
    suffix = _yahoo_suffix(provider_symbol)

    market_code = prefix or ""
    market_country = (country or "").strip()
    trading_currency = (currency or "").strip().upper()
    timezone_hint: str | None = None
    stale = DEFAULT_STALE_HOURS
    asset_type = "EQUITY"

    if prefix and prefix in _EXCHANGE_PREFIX_MAP:
        cfg = _EXCHANGE_PREFIX_MAP[prefix]
        market_code = prefix
        if not market_country:
            market_country = cfg["country"]
        if not trading_currency:
            trading_currency = cfg["currency"]
        timezone_hint = cfg.get("tz")
        if prefix in {"NSE", "BSE", "ETR", "EPA", "AMS", "LON", "BIT", "SWX"}:
            stale = 36.0
        else:
            stale = 36.0
    elif suffix and suffix in _YAHOO_SUFFIX_TO_MARKET:
        cfg = _YAHOO_SUFFIX_TO_MARKET[suffix]
        market_code = cfg["market_code"]
        if not market_country:
            market_country = cfg["country"]
        if not trading_currency:
            trading_currency = cfg["currency"]
        timezone_hint = cfg.get("tz")
        stale = 36.0
    else:
        # No prefix and no Yahoo suffix — assume US listing.
        if not market_country:
            market_country = "United States"
        if not trading_currency:
            trading_currency = "USD"
        market_code = market_code or "US"
        timezone_hint = "America/New_York"
        stale = 36.0

    if not market_country:
        market_country = "UNKNOWN"
    if not trading_currency:
        trading_currency = "UNKNOWN"
    if not market_code:
        market_code = "UNKNOWN"

    return MarketInfo(
        market_code=market_code,
        country=market_country,
        exchange_hint=prefix,
        provider_symbol=provider_symbol or bare,
        trading_currency=trading_currency,
        expected_timezone=timezone_hint,
        stale_after_hours=stale,
        asset_type=asset_type,
    )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LiveMark:
    """One advisory-only price observation for a single ticker.

    The ``is_usable`` flag is the single boolean the lifecycle classifier
    consults to decide whether mechanical exit / TP / stop math may run.
    Stale or unverified marks set ``is_usable=False`` and explain why
    via ``reason_codes``.
    """

    ticker: str
    raw_ticker: str = ""
    provider_symbol: str = ""
    economic_exposure_key: str = ""
    live_price: float | None = None
    previous_close: float | None = None
    open_price: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    currency: str | None = None
    provider: str = ""
    source_health: str = NO_LIVE_MARK
    consensus_status: str = ""
    fetched_at: str | None = None
    market_time: str | None = None
    age_hours: float | None = None
    freshness_score: float = 0.0
    live_mark_quality_score: float = 0.0
    is_usable: bool = False
    is_stale: bool = False
    is_market_closed_tolerated: bool = False
    reason_codes: list[str] = field(default_factory=list)
    advisory_only: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    human_execution_required: bool = True
    execution_permission: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LiveMarkResult:
    """Bag of LiveMarks plus aggregate diagnostics."""

    marks: dict[str, LiveMark] = field(default_factory=dict)
    requested_tickers: list[str] = field(default_factory=list)
    resolved_tickers: list[str] = field(default_factory=list)
    missing_tickers: list[str] = field(default_factory=list)
    stale_tickers: list[str] = field(default_factory=list)
    provider_status: dict[str, Any] = field(default_factory=dict)
    aggregate_source_health: str = NO_LIVE_MARKS
    coverage_ratio: float = 0.0
    usable_coverage_ratio: float = 0.0
    average_quality_score: float = 0.0
    generated_at: str = ""
    reason_codes: list[str] = field(default_factory=list)
    advisory_only: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    human_execution_required: bool = True
    execution_permission: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        out = {
            "marks": [m.to_dict() for m in self.marks.values()],
            "requested_tickers": list(self.requested_tickers),
            "resolved_tickers": list(self.resolved_tickers),
            "missing_tickers": list(self.missing_tickers),
            "stale_tickers": list(self.stale_tickers),
            "provider_status": dict(self.provider_status),
            "aggregate_source_health": self.aggregate_source_health,
            "coverage_ratio": self.coverage_ratio,
            "usable_coverage_ratio": self.usable_coverage_ratio,
            "average_quality_score": self.average_quality_score,
            "generated_at": self.generated_at,
            "reason_codes": list(self.reason_codes),
            "advisory_only": self.advisory_only,
            "broker_api_called": self.broker_api_called,
            "ai_execution_count": self.ai_execution_count,
            "human_execution_required": self.human_execution_required,
            "execution_permission": self.execution_permission,
        }
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _utc_now_iso(now_utc: datetime | None = None) -> str:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_position_ticker(ticker: Any) -> str:
    """Position-key normaliser used to merge marks back into positions.

    Mirrors ``scripts.position_context.normalize_position_ticker``
    behaviour without an import cycle.
    """
    if ticker is None:
        return ""
    text = str(ticker).strip().upper()
    if not text:
        return ""
    if ":" in text:
        text = text.rsplit(":", 1)[-1].strip()
    return text


# ---------------------------------------------------------------------------
# Quality math (Section 4 of the sprint brief)
# ---------------------------------------------------------------------------


def _freshness_score(age_hours: float | None, stale_hours: float) -> float:
    if age_hours is None:
        return 0.0
    if stale_hours <= 0:
        stale_hours = DEFAULT_STALE_HOURS
    return math.exp(-max(0.0, age_hours) / float(stale_hours))


def _currency_compatibility(
    returned_currency: str | None,
    expected_currency: str | None,
    ticker: str,
) -> tuple[float, list[str]]:
    expected = (expected_currency or "").strip().upper()
    returned = (returned_currency or "").strip().upper()
    reasons: list[str] = []
    if not expected or expected == "UNKNOWN":
        if not returned:
            return 0.7, []
        return 1.0 if returned else 0.7, []
    if not returned:
        return 0.7, []
    if returned == expected:
        return 1.0, []
    # ADR / dual-listing tolerance.
    if expected in {"USD", "EUR", "GBP", "INR", "JPY"} and returned in {
        "USD",
        "EUR",
        "GBP",
        "INR",
        "JPY",
    } and ticker:
        # If the operator-side currency is unknown or the symbol carries
        # a Yahoo suffix that matches the returned currency, treat the
        # mismatch as explainable.
        suffix = _yahoo_suffix(ticker)
        if suffix:
            cfg = _YAHOO_SUFFIX_TO_MARKET.get(suffix)
            if cfg and cfg.get("currency") == returned:
                reasons.append(REASON_CURRENCY_MISMATCH)
                return 0.4, reasons
    reasons.append(REASON_CURRENCY_MISMATCH)
    return 0.0, reasons


def _market_compatibility(provider_symbol: str, market: MarketInfo) -> float:
    if not provider_symbol or provider_symbol.upper() == market.provider_symbol.upper():
        return 1.0
    if _yahoo_suffix(provider_symbol) == _yahoo_suffix(market.provider_symbol):
        return 0.8
    if provider_symbol.upper().startswith(market.provider_symbol.upper().split(".")[0]):
        return 0.5
    return 0.5


def compute_live_mark_quality(
    *,
    price: float | None,
    age_hours: float | None,
    stale_after_hours: float,
    returned_currency: str | None,
    expected_currency: str | None,
    provider_symbol: str,
    market: MarketInfo,
    provider_weight: float,
    market_closed_tolerated: bool,
    ticker: str,
) -> tuple[float, float, float, list[str]]:
    """Return ``(quality_score, freshness_score, currency_score, reasons)``.

    All inputs are simple numbers / strings; the function never reaches
    out to the network or DB.
    """
    reasons: list[str] = []
    valid = (
        price is not None
        and price > 0
        and math.isfinite(price)
    )
    if not valid:
        return 0.0, 0.0, 0.0, reasons

    stale = stale_after_hours
    if market_closed_tolerated:
        stale = max(stale, DEFAULT_MARKET_CLOSED_TOLERANCE_HOURS)
    freshness = _freshness_score(age_hours, stale)
    currency_score, currency_reasons = _currency_compatibility(
        returned_currency, expected_currency, ticker
    )
    reasons.extend(currency_reasons)
    market_score = _market_compatibility(provider_symbol, market)
    weight = max(0.0, min(1.0, float(provider_weight)))

    raw = (
        0.35 * freshness
        + 0.25 * currency_score
        + 0.20 * market_score
        + 0.20 * weight
    )
    quality = _clamp(raw, 0.0, 1.0)
    return quality, freshness, currency_score, reasons


def _classify_source_health(quality: float, valid: bool) -> str:
    if not valid:
        return NO_LIVE_MARK
    if quality >= 0.80:
        return LIVE_VERIFIED
    if quality >= 0.60:
        return DELAYED_BUT_USABLE
    if quality >= 0.40:
        return PARTIAL
    return STALE_PRICE


# ---------------------------------------------------------------------------
# Provider readers (read-only)
# ---------------------------------------------------------------------------


def _read_market_snapshot_marks(
    snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Walk a market snapshot for per-ticker price fields.

    The canonical daily snapshot generally does NOT carry per-position
    marks today, but operators may pre-populate ``live_marks`` /
    ``prices`` / ``tickers`` blocks for testing.  We accept several
    shapes defensively.
    """
    if not isinstance(snapshot, dict):
        return []
    out: list[dict[str, Any]] = []
    fetched = snapshot.get("snapshot_timestamp_utc") or snapshot.get("fetched_at")
    for collection_key in ("live_marks", "prices", "tickers"):
        collection = snapshot.get(collection_key)
        if isinstance(collection, dict):
            for raw_key, value in collection.items():
                if isinstance(value, dict):
                    price = _safe_float(
                        value.get("live_price")
                        or value.get("current_price")
                        or value.get("price")
                    )
                    out.append(
                        {
                            "ticker": str(raw_key),
                            "live_price": price,
                            "currency": value.get("currency"),
                            "fetched_at": value.get("fetched_at") or fetched,
                            "market_time": value.get("market_time"),
                            "previous_close": _safe_float(value.get("previous_close")),
                            "open": _safe_float(value.get("open")),
                            "day_high": _safe_float(value.get("day_high")),
                            "day_low": _safe_float(value.get("day_low")),
                        }
                    )
                else:
                    price = _safe_float(value)
                    if price is not None:
                        out.append(
                            {
                                "ticker": str(raw_key),
                                "live_price": price,
                                "fetched_at": fetched,
                            }
                        )
        elif isinstance(collection, list):
            for row in collection:
                if not isinstance(row, dict):
                    continue
                key = (
                    row.get("ticker")
                    or row.get("symbol")
                    or row.get("normalized_ticker")
                )
                price = _safe_float(
                    row.get("live_price")
                    or row.get("current_price")
                    or row.get("price")
                )
                if not key:
                    continue
                out.append(
                    {
                        "ticker": str(key),
                        "live_price": price,
                        "currency": row.get("currency"),
                        "fetched_at": row.get("fetched_at") or fetched,
                        "market_time": row.get("market_time"),
                        "previous_close": _safe_float(row.get("previous_close")),
                        "open": _safe_float(row.get("open")),
                        "day_high": _safe_float(row.get("day_high")),
                        "day_low": _safe_float(row.get("day_low")),
                    }
                )
    return out


def _read_db_live_marks(db_path: Path | None) -> list[dict[str, Any]]:
    """Look for a canonical ``live_marks`` table in the local SQLite DB.

    Schema is operator-defined; we accept a few common shapes and return
    an empty list if the table is missing.  Never raises for "DB not
    present".
    """
    if not db_path or not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name FROM sqlite_master
             WHERE type='table'
               AND name IN ('live_marks','live_price_marks','market_marks')
            """
        )
        tables = [row[0] for row in cur.fetchall()]
        marks: list[dict[str, Any]] = []
        for table in tables:
            try:
                cur.execute(f"SELECT * FROM {table}")
                for row in cur.fetchall():
                    record = dict(row)
                    marks.append(
                        {
                            "ticker": record.get("ticker")
                            or record.get("symbol")
                            or record.get("normalized_ticker"),
                            "live_price": _safe_float(
                                record.get("live_price")
                                or record.get("price")
                                or record.get("last_price")
                            ),
                            "currency": record.get("currency"),
                            "fetched_at": record.get("fetched_at")
                            or record.get("observed_at")
                            or record.get("created_at"),
                            "market_time": record.get("market_time")
                            or record.get("observed_at"),
                            "previous_close": _safe_float(record.get("previous_close")),
                            "open": _safe_float(record.get("open_price") or record.get("open")),
                            "day_high": _safe_float(record.get("day_high")),
                            "day_low": _safe_float(record.get("day_low")),
                        }
                    )
            except sqlite3.DatabaseError:
                continue
        conn.close()
        return marks
    except sqlite3.DatabaseError:
        return []


def _read_release_summary_marks(release_dir: Path | None) -> list[dict[str, Any]]:
    """Scan release-dir artefacts for live price / current price fields.

    Reads JSON files matching a small list of well-known names and
    extracts ``live_price`` / ``current_price`` per row.
    """
    base = Path(release_dir) if release_dir else DEFAULT_RELEASE_DIR
    if not base.exists():
        return []
    candidates = [
        "capital_rotation_summary.json",
        "exit_review_summary.json",
        "operator_daily_signal.json",
        "today_candidates.json",
        "yesterday_final_candidates.json",
    ]
    out: list[dict[str, Any]] = []
    for name in candidates:
        path = base / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in _iter_release_rows(payload):
            ticker = (
                row.get("ticker")
                or row.get("symbol")
                or row.get("normalized_ticker")
            )
            price = _safe_float(
                row.get("live_price") or row.get("current_price")
            )
            if not ticker or price is None:
                continue
            out.append(
                {
                    "ticker": str(ticker),
                    "live_price": price,
                    "currency": row.get("currency"),
                    "fetched_at": row.get("fetched_at")
                    or row.get("generated_at")
                    or payload.get("generated_at_utc")
                    if isinstance(payload, dict)
                    else None,
                    "market_time": row.get("market_time"),
                }
            )
    return out


def _iter_release_rows(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in (
            "rows",
            "exit_review_rows",
            "candidates",
            "movers",
            "positions",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                for row in value:
                    if isinstance(row, dict):
                        yield row
        for nested_key in (
            "exit_review_board",
            "buy_admission_board",
            "summary",
        ):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                yield from _iter_release_rows(nested)


YfinanceFetcher = Callable[[str], dict[str, Any]]


def _read_yfinance_marks(
    tickers: Sequence[str],
    *,
    fetcher: YfinanceFetcher | None,
    allow_network: bool,
    now_utc: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pull marks via the existing Yahoo adapter (or an injected fetcher).

    Honest about network access: when ``allow_network=False`` and no
    fetcher was injected, returns an empty list with a status flag.
    """
    status: dict[str, Any] = {
        "provider": "existing_yfinance_provider",
        "ok": False,
        "calls": 0,
        "failures": 0,
        "reason": None,
    }
    rows: list[dict[str, Any]] = []
    if not tickers:
        status["reason"] = "no_tickers"
        return rows, status

    fetch_fn = fetcher
    if fetch_fn is None:
        if not allow_network:
            status["reason"] = REASON_NETWORK_DISALLOWED
            return rows, status
        try:  # pragma: no cover — exercised by integration only
            from scripts.yahoo_market_data_adapter import (
                _fetch_symbol_with_yfinance as _yf_fetch,
            )
        except Exception as exc:  # pragma: no cover
            status["reason"] = f"adapter_unavailable:{type(exc).__name__}"
            return rows, status
        fetch_fn = _yf_fetch

    fetched_at = _utc_now_iso(now_utc)
    for symbol in tickers:
        sym = (symbol or "").strip().upper()
        if not sym:
            continue
        status["calls"] += 1
        try:
            payload = fetch_fn(sym) or {}
        except Exception as exc:  # pragma: no cover — defensive
            status["failures"] += 1
            rows.append(
                {
                    "ticker": sym,
                    "live_price": None,
                    "currency": None,
                    "fetched_at": fetched_at,
                    "market_time": None,
                    "error": str(exc),
                }
            )
            continue
        last_price = _safe_float(payload.get("last_price"))
        rows.append(
            {
                "ticker": sym,
                "live_price": last_price,
                "currency": payload.get("currency"),
                "fetched_at": fetched_at,
                "market_time": payload.get("regular_market_time"),
                "previous_close": _safe_float(payload.get("previous_close")),
                "open": _safe_float(payload.get("open")),
                "day_high": _safe_float(payload.get("day_high")),
                "day_low": _safe_float(payload.get("day_low")),
            }
        )
    status["ok"] = status["failures"] < status["calls"]
    return rows, status


# ---------------------------------------------------------------------------
# Consensus + merge
# ---------------------------------------------------------------------------


def _build_consensus(
    provider_rows: list[tuple[str, dict[str, Any], float, float]],
) -> tuple[float | None, float, str, list[str]]:
    """Combine multiple usable provider marks into one consensus price.

    ``provider_rows`` is a list of ``(provider, row, price, quality)``.
    Returns ``(consensus_price, avg_quality, status, reason_codes)``.
    """
    if not provider_rows:
        return None, 0.0, "", []
    if len(provider_rows) == 1:
        _, _, price, q = provider_rows[0]
        return price, q, CONSENSUS_SINGLE_PROVIDER, []
    total_weight = sum(q for _, _, _, q in provider_rows)
    if total_weight <= 0:
        return None, 0.0, "", []
    weighted_price = sum(q * p for _, _, p, q in provider_rows) / total_weight
    variance = sum(q * (p - weighted_price) ** 2 for _, _, p, q in provider_rows) / total_weight
    dispersion = math.sqrt(variance) / weighted_price if weighted_price else 1.0
    reasons: list[str] = []
    if dispersion <= 0.005:
        status = CONSENSUS_TIGHT
    elif dispersion <= 0.02:
        status = CONSENSUS_ACCEPTABLE
    else:
        status = CONSENSUS_CONFLICT
        reasons.append(REASON_LIVE_MARK_PROVIDER_DISAGREEMENT)
    avg_quality = total_weight / len(provider_rows)
    return weighted_price, avg_quality, status, reasons


def _normalize_provider_rows(
    rows: list[dict[str, Any]],
    provider: str,
) -> dict[str, dict[str, Any]]:
    """Key provider rows by normalised ticker so we can merge across sources."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ticker = (
            row.get("ticker")
            or row.get("symbol")
            or row.get("normalized_ticker")
        )
        if not ticker:
            continue
        key = _normalize_position_ticker(ticker)
        if not key:
            continue
        out.setdefault(
            key,
            {
                "provider": provider,
                "ticker_norm": key,
                "ticker_raw": str(ticker),
                "live_price": _safe_float(row.get("live_price")),
                "currency": row.get("currency"),
                "fetched_at": row.get("fetched_at"),
                "market_time": row.get("market_time"),
                "previous_close": _safe_float(row.get("previous_close")),
                "open": _safe_float(row.get("open") or row.get("open_price")),
                "day_high": _safe_float(row.get("day_high")),
                "day_low": _safe_float(row.get("day_low")),
            },
        )
    return out


def _age_hours(now_utc: datetime, fetched_at: str | None, market_time: str | None) -> tuple[float | None, str | None]:
    """Pick the most recent of ``fetched_at`` / ``market_time`` and return age
    in hours plus the chosen reference timestamp ISO string.
    """
    candidates = [_parse_iso_dt(fetched_at), _parse_iso_dt(market_time)]
    valid = [c for c in candidates if c is not None]
    if not valid:
        return None, None
    ref = max(valid)
    delta = (now_utc - ref).total_seconds() / 3600.0
    age = max(0.0, delta)
    return age, ref.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _build_mark_for_ticker(
    *,
    ticker: str,
    raw_ticker: str,
    market: MarketInfo,
    provider_rows: list[tuple[str, dict[str, Any]]],
    now_utc: datetime,
    expected_currency: str | None,
    market_closed_tolerated: bool,
    provider_weights: dict[str, float],
    economic_exposure_key: str = "",
) -> LiveMark:
    usable_provider_rows: list[tuple[str, dict[str, Any], float, float]] = []
    all_reasons: list[str] = []
    best_freshness = 0.0
    best_currency: str | None = None
    best_provider_symbol = market.provider_symbol
    best_previous_close: float | None = None
    best_open: float | None = None
    best_high: float | None = None
    best_low: float | None = None
    best_fetched: str | None = None
    best_market_time: str | None = None
    fallback_quality = 0.0
    fallback_price: float | None = None
    fallback_provider = ""
    for provider, row in provider_rows:
        price = _safe_float(row.get("live_price"))
        currency = row.get("currency")
        provider_symbol = (
            row.get("provider_symbol")
            or row.get("ticker_raw")
            or row.get("ticker")
            or market.provider_symbol
        )
        weight = provider_weights.get(provider, PROVIDER_WEIGHT_DEFAULTS.get(provider, 0.5))
        age_h, ref_iso = _age_hours(now_utc, row.get("fetched_at"), row.get("market_time"))
        quality, freshness, currency_score, reasons = compute_live_mark_quality(
            price=price,
            age_hours=age_h,
            stale_after_hours=market.stale_after_hours,
            returned_currency=currency,
            expected_currency=expected_currency,
            provider_symbol=str(provider_symbol),
            market=market,
            provider_weight=weight,
            market_closed_tolerated=market_closed_tolerated,
            ticker=ticker,
        )
        all_reasons.extend(reasons)
        if price is None or price <= 0 or not math.isfinite(price):
            continue
        # Track best non-usable mark for stale display.
        if quality > fallback_quality:
            fallback_quality = quality
            fallback_price = price
            fallback_provider = provider
            best_provider_symbol = str(provider_symbol)
            best_currency = currency
            best_fetched = row.get("fetched_at") or ref_iso
            best_market_time = row.get("market_time") or ref_iso
            best_previous_close = row.get("previous_close")
            best_open = row.get("open")
            best_high = row.get("day_high")
            best_low = row.get("day_low")
            best_freshness = freshness
        if quality >= 0.60:
            usable_provider_rows.append((provider, row, price, quality))

    consensus_price, avg_quality, consensus_status, consensus_reasons = (
        _build_consensus(usable_provider_rows)
    )

    is_valid = consensus_price is not None
    if is_valid:
        live_price = consensus_price
        quality_score = max(avg_quality, fallback_quality)
        live_provider = usable_provider_rows[0][0]
        if best_provider_symbol == market.provider_symbol and usable_provider_rows:
            best_provider_symbol = str(
                usable_provider_rows[0][1].get("provider_symbol")
                or usable_provider_rows[0][1].get("ticker_raw")
                or market.provider_symbol
            )
        source_health = _classify_source_health(quality_score, True)
        is_stale = False
        is_usable = True
    elif fallback_price is not None:
        live_price = fallback_price
        quality_score = fallback_quality
        live_provider = fallback_provider
        source_health = _classify_source_health(quality_score, True)
        is_stale = True
        is_usable = False
    else:
        live_price = None
        quality_score = 0.0
        live_provider = ""
        source_health = NO_LIVE_MARK
        is_stale = False
        is_usable = False

    reason_codes: list[str] = []
    seen: set[str] = set()
    for code in all_reasons + consensus_reasons:
        if code and code not in seen:
            reason_codes.append(code)
            seen.add(code)
    if consensus_status:
        if consensus_status not in seen:
            reason_codes.append(consensus_status)
            seen.add(consensus_status)
    if live_provider == "existing_yfinance_provider":
        reason_codes.append(REASON_LIVE_MARK_FROM_YFINANCE)
    elif live_provider == "today_market_snapshot":
        reason_codes.append(REASON_LIVE_MARK_FROM_SNAPSHOT)
    elif live_provider == "canonical_db_live_mark":
        reason_codes.append(REASON_LIVE_MARK_FROM_DB)
    elif live_provider == "release_summary":
        reason_codes.append(REASON_LIVE_MARK_FROM_RELEASE)
    if is_stale:
        reason_codes.append(REASON_LIVE_MARK_STALE)
    if not is_valid and live_price is None:
        reason_codes.append(REASON_LIVE_MARK_MISSING)
        reason_codes.append(REASON_NO_USABLE_LIVE_MARK)
    if market.market_code == "UNKNOWN":
        reason_codes.append(REASON_MARKET_CALENDAR_UNKNOWN)
    if not is_usable and is_valid:
        reason_codes.append(REASON_LIVE_MARK_UNUSABLE)

    age_h, _ = _age_hours(now_utc, best_fetched, best_market_time)
    mark = LiveMark(
        ticker=ticker,
        raw_ticker=raw_ticker,
        provider_symbol=best_provider_symbol,
        economic_exposure_key=economic_exposure_key,
        live_price=live_price,
        previous_close=best_previous_close,
        open_price=best_open,
        day_high=best_high,
        day_low=best_low,
        currency=best_currency,
        provider=live_provider,
        source_health=source_health,
        consensus_status=consensus_status or "",
        fetched_at=best_fetched,
        market_time=best_market_time,
        age_hours=round(age_h, 3) if age_h is not None else None,
        freshness_score=round(best_freshness, 4),
        live_mark_quality_score=round(quality_score, 4),
        is_usable=is_usable,
        is_stale=is_stale,
        is_market_closed_tolerated=market_closed_tolerated,
        reason_codes=reason_codes,
    )
    return mark


def _build_no_data_mark(
    *,
    ticker: str,
    raw_ticker: str,
    market: MarketInfo,
    reason: str | None = None,
    economic_exposure_key: str = "",
) -> LiveMark:
    reasons = [REASON_LIVE_MARK_MISSING, REASON_NO_USABLE_LIVE_MARK]
    if reason:
        reasons.append(reason)
    if market.market_code == "UNKNOWN":
        reasons.append(REASON_MARKET_CALENDAR_UNKNOWN)
    return LiveMark(
        ticker=ticker,
        raw_ticker=raw_ticker,
        provider_symbol=market.provider_symbol,
        economic_exposure_key=economic_exposure_key,
        live_price=None,
        currency=None,
        provider="",
        source_health=NO_LIVE_MARK,
        fetched_at=None,
        market_time=None,
        age_hours=None,
        freshness_score=0.0,
        live_mark_quality_score=0.0,
        is_usable=False,
        is_stale=False,
        is_market_closed_tolerated=False,
        reason_codes=reasons,
    )


# ---------------------------------------------------------------------------
# Top-level public API
# ---------------------------------------------------------------------------


def fetch_live_marks(
    tickers: Iterable[str],
    *,
    provider: str | None = None,
    db_path: Path | None = None,
    release_dir: Path | None = None,
    market_snapshot: dict[str, Any] | None = None,
    now_utc: datetime | None = None,
    allow_network: bool = True,
    fallback_to_snapshot: bool = True,
    fetcher: YfinanceFetcher | None = None,
    snapshot_loader: Callable[[], dict[str, Any]] | None = None,
    provider_weights: dict[str, float] | None = None,
    ticker_metadata: dict[str, dict[str, Any]] | None = None,
) -> LiveMarkResult:
    """Resolve a list of tickers into LiveMarks.

    Provider priority is:

    1. Canonical ``live_marks`` table in the local SQLite DB.
    2. Existing yfinance/Yahoo adapter (if ``allow_network`` or
       ``fetcher`` is provided).
    3. ``today_market_snapshot.json`` if it carries per-ticker prices.
    4. Release-summary live_price fields.

    The function never raises for missing providers — degraded
    coverage is reflected in ``aggregate_source_health`` and per-mark
    reason codes.

    ``ticker_metadata`` is a per-ticker ``{country, currency, raw_ticker,
    economic_exposure_key}`` map the caller may pass to inform market
    inference / currency compatibility.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    weights = dict(PROVIDER_WEIGHT_DEFAULTS)
    if provider_weights:
        weights.update(provider_weights)
    metadata = dict(ticker_metadata or {})

    raw_tickers = [str(t).strip() for t in tickers if str(t or "").strip()]
    normalized: list[str] = []
    raw_lookup: dict[str, str] = {}
    for raw in raw_tickers:
        key = _normalize_position_ticker(raw)
        if not key:
            continue
        if key not in normalized:
            normalized.append(key)
        raw_lookup.setdefault(key, raw)

    snapshot_payload: dict[str, Any] | None = None
    snapshot_status = {"provider": "today_market_snapshot", "ok": False, "rows": 0}
    if fallback_to_snapshot:
        if market_snapshot is not None:
            snapshot_payload = market_snapshot
        elif snapshot_loader is not None:
            try:
                snapshot_payload = snapshot_loader()
            except Exception:  # pragma: no cover — defensive only
                snapshot_payload = None
        else:
            try:
                snapshot_payload = load_market_snapshot()
            except Exception:  # pragma: no cover — defensive only
                snapshot_payload = None
    snapshot_rows = _read_market_snapshot_marks(snapshot_payload)
    snapshot_status["rows"] = len(snapshot_rows)
    snapshot_status["ok"] = len(snapshot_rows) > 0
    snapshot_marks = _normalize_provider_rows(snapshot_rows, "today_market_snapshot")

    db_rows = _read_db_live_marks(db_path or DEFAULT_DB_PATH)
    db_status = {
        "provider": "canonical_db_live_mark",
        "ok": len(db_rows) > 0,
        "rows": len(db_rows),
    }
    db_marks = _normalize_provider_rows(db_rows, "canonical_db_live_mark")

    release_rows = _read_release_summary_marks(release_dir)
    release_status = {
        "provider": "release_summary",
        "ok": len(release_rows) > 0,
        "rows": len(release_rows),
    }
    release_marks = _normalize_provider_rows(release_rows, "release_summary")

    # Yfinance — pull only for tickers we don't already have a high-weight
    # mark for, but for simplicity always query them; we still respect
    # ``allow_network``.
    provider_symbols: list[str] = []
    symbol_to_ticker: dict[str, str] = {}
    for key in normalized:
        meta = metadata.get(key, {})
        symbol = normalize_ticker_for_market_data(
            raw_lookup.get(key, key),
            country=meta.get("country"),
            currency=meta.get("currency"),
        )
        if symbol and symbol not in provider_symbols:
            provider_symbols.append(symbol)
        symbol_to_ticker.setdefault(symbol, key)
    yf_rows, yf_status = _read_yfinance_marks(
        provider_symbols,
        fetcher=fetcher,
        allow_network=allow_network,
        now_utc=now,
    )
    # Map yfinance rows back to position-normalised tickers.
    yf_position_rows: list[dict[str, Any]] = []
    for row in yf_rows:
        sym = str(row.get("ticker") or "").strip().upper()
        target = symbol_to_ticker.get(sym)
        if not target:
            target = _normalize_position_ticker(sym)
        yf_position_rows.append({**row, "ticker": target, "provider_symbol": sym})
    yf_marks = _normalize_provider_rows(yf_position_rows, "existing_yfinance_provider")
    for sym, target in symbol_to_ticker.items():
        if target in yf_marks:
            yf_marks[target]["provider_symbol"] = sym

    marks: dict[str, LiveMark] = {}
    resolved: list[str] = []
    missing: list[str] = []
    stale_list: list[str] = []
    total_quality = 0.0
    usable_count = 0
    for ticker in normalized:
        meta = metadata.get(ticker, {})
        country = meta.get("country")
        currency = meta.get("currency")
        market = infer_market_from_ticker(
            raw_lookup.get(ticker, ticker),
            country=country,
            currency=currency,
        )
        provider_rows: list[tuple[str, dict[str, Any]]] = []
        if ticker in db_marks:
            provider_rows.append(("canonical_db_live_mark", db_marks[ticker]))
        if ticker in yf_marks:
            provider_rows.append(("existing_yfinance_provider", yf_marks[ticker]))
        if ticker in snapshot_marks:
            provider_rows.append(("today_market_snapshot", snapshot_marks[ticker]))
        if ticker in release_marks:
            provider_rows.append(("release_summary", release_marks[ticker]))

        if not provider_rows:
            mark = _build_no_data_mark(
                ticker=ticker,
                raw_ticker=raw_lookup.get(ticker, ticker),
                market=market,
                economic_exposure_key=meta.get("economic_exposure_key", ""),
            )
            missing.append(ticker)
        else:
            mark = _build_mark_for_ticker(
                ticker=ticker,
                raw_ticker=raw_lookup.get(ticker, ticker),
                market=market,
                provider_rows=provider_rows,
                now_utc=now,
                expected_currency=currency,
                market_closed_tolerated=True,
                provider_weights=weights,
                economic_exposure_key=meta.get("economic_exposure_key", ""),
            )
            resolved.append(ticker)
            if mark.is_usable:
                usable_count += 1
                total_quality += mark.live_mark_quality_score
            else:
                if mark.live_price is None:
                    if ticker not in missing:
                        missing.append(ticker)
                else:
                    stale_list.append(ticker)
        marks[ticker] = mark

    open_count = max(1, len(normalized))
    coverage_ratio = len([k for k in resolved if marks[k].live_price is not None]) / open_count
    usable_coverage_ratio = usable_count / open_count
    average_quality = total_quality / usable_count if usable_count else 0.0

    aggregate_health: str
    if usable_coverage_ratio >= 0.95 and average_quality >= 0.80:
        aggregate_health = LIVE_VERIFIED
    elif usable_coverage_ratio >= 0.80 and average_quality >= 0.60:
        aggregate_health = DELAYED_BUT_USABLE
    elif usable_coverage_ratio >= 0.40:
        aggregate_health = PARTIAL
    elif usable_coverage_ratio > 0:
        aggregate_health = DEGRADED
    else:
        aggregate_health = NO_LIVE_MARKS

    agg_reasons: list[str] = []
    if not normalized:
        aggregate_health = NO_LIVE_MARKS
        agg_reasons.append(REASON_NO_LIVE_MARKS)
    if usable_coverage_ratio >= 0.95:
        agg_reasons.append(REASON_COVERAGE_FULL)
    elif usable_coverage_ratio >= 0.40:
        agg_reasons.append(REASON_COVERAGE_PARTIAL)
    elif usable_coverage_ratio > 0:
        agg_reasons.append(REASON_COVERAGE_LOW)
    else:
        agg_reasons.append(REASON_NO_LIVE_MARKS)
    if missing:
        agg_reasons.append(REASON_SOME_MARKS_MISSING)
    if stale_list:
        agg_reasons.append(REASON_SOME_MARKS_STALE)
    if yf_status.get("reason") == REASON_NETWORK_DISALLOWED:
        agg_reasons.append(REASON_NETWORK_DISALLOWED)

    provider_status = {
        "yfinance": yf_status,
        "market_snapshot": snapshot_status,
        "canonical_db": db_status,
        "release_summary": release_status,
    }

    result = LiveMarkResult(
        marks=marks,
        requested_tickers=normalized,
        resolved_tickers=resolved,
        missing_tickers=missing,
        stale_tickers=stale_list,
        provider_status=provider_status,
        aggregate_source_health=aggregate_health,
        coverage_ratio=round(coverage_ratio, 4),
        usable_coverage_ratio=round(usable_coverage_ratio, 4),
        average_quality_score=round(average_quality, 4),
        generated_at=_utc_now_iso(now),
        reason_codes=agg_reasons,
    )
    return result


def live_mark_result_to_summary(result: LiveMarkResult) -> dict[str, Any]:
    """Render a ``LiveMarkResult`` into the release-summary shape."""
    marks_list = []
    for mark in result.marks.values():
        marks_list.append(
            {
                "ticker": mark.ticker,
                "raw_ticker": mark.raw_ticker,
                "provider_symbol": mark.provider_symbol,
                "economic_exposure_key": mark.economic_exposure_key,
                "live_price": mark.live_price,
                "previous_close": mark.previous_close,
                "open_price": mark.open_price,
                "day_high": mark.day_high,
                "day_low": mark.day_low,
                "currency": mark.currency,
                "provider": mark.provider,
                "source_health": mark.source_health,
                "consensus_status": mark.consensus_status,
                "fetched_at": mark.fetched_at,
                "market_time": mark.market_time,
                "age_hours": mark.age_hours,
                "freshness_score": mark.freshness_score,
                "live_mark_quality_score": mark.live_mark_quality_score,
                "is_usable": mark.is_usable,
                "is_stale": mark.is_stale,
                "is_market_closed_tolerated": mark.is_market_closed_tolerated,
                "reason_codes": list(mark.reason_codes),
            }
        )
    payload = {
        "generated_at": result.generated_at,
        "aggregate_source_health": result.aggregate_source_health,
        "coverage_ratio": result.coverage_ratio,
        "usable_coverage_ratio": result.usable_coverage_ratio,
        "average_quality_score": result.average_quality_score,
        "requested_tickers": list(result.requested_tickers),
        "resolved_tickers": list(result.resolved_tickers),
        "missing_tickers": list(result.missing_tickers),
        "stale_tickers": list(result.stale_tickers),
        "provider_status": dict(result.provider_status),
        "marks": marks_list,
        "reason_codes": list(result.reason_codes),
    }
    payload.update(advisory_safety_stamps())
    payload["advisory_only"] = True
    payload["broker_api_called"] = False
    payload["ai_execution_count"] = 0
    payload["human_execution_required"] = True
    payload["execution_permission"] = "ADVISORY_ONLY"
    return payload


def write_live_mark_summary(
    result: LiveMarkResult,
    *,
    release_dir: Path | None = None,
) -> Path:
    """Write the release-summary JSON.  Returns the path it wrote to."""
    base = Path(release_dir) if release_dir else DEFAULT_RELEASE_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / LIVE_MARK_SUMMARY_FILENAME
    payload = live_mark_result_to_summary(result)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


__all__ = [
    # vocabulary
    "LIVE_VERIFIED",
    "DELAYED_BUT_USABLE",
    "PARTIAL",
    "STALE_PRICE",
    "NO_LIVE_MARK",
    "DEGRADED",
    "NO_LIVE_MARKS",
    "ALL_SOURCE_HEALTHS",
    "CONSENSUS_TIGHT",
    "CONSENSUS_ACCEPTABLE",
    "CONSENSUS_CONFLICT",
    "CONSENSUS_SINGLE_PROVIDER",
    # reason codes
    "REASON_LIVE_MARK_MISSING",
    "REASON_LIVE_MARK_STALE",
    "REASON_LIVE_MARK_UNUSABLE",
    "REASON_LIVE_MARK_PROVIDER_DISAGREEMENT",
    "REASON_LIVE_MARK_FROM_YFINANCE",
    "REASON_LIVE_MARK_FROM_SNAPSHOT",
    "REASON_LIVE_MARK_FROM_DB",
    "REASON_LIVE_MARK_FROM_RELEASE",
    "REASON_LIVE_MARK_MERGED",
    "REASON_CURRENCY_MISMATCH",
    "REASON_MARKET_CALENDAR_UNKNOWN",
    "REASON_NO_USABLE_LIVE_MARK",
    "REASON_STATIC_SYMBOL_ONLY_NO_PRICE",
    "REASON_COVERAGE_FULL",
    "REASON_COVERAGE_PARTIAL",
    "REASON_COVERAGE_LOW",
    "REASON_NO_LIVE_MARKS",
    "REASON_SOME_MARKS_STALE",
    "REASON_SOME_MARKS_MISSING",
    "REASON_NETWORK_DISALLOWED",
    # provider weights
    "PROVIDER_WEIGHT_DEFAULTS",
    # dataclasses + entry points
    "MarketInfo",
    "LiveMark",
    "LiveMarkResult",
    "normalize_ticker_for_market_data",
    "infer_market_from_ticker",
    "compute_live_mark_quality",
    "fetch_live_marks",
    "live_mark_result_to_summary",
    "write_live_mark_summary",
    "LIVE_MARK_SUMMARY_FILENAME",
]
