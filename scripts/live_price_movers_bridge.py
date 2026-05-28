"""Bridge — live price / price-mover discovery into the daily payload.

``today_price_movers.json`` was a static fallback with null prices because the
synthesis path never consumed any price provider. This bridge reads canonical
``market_data`` rows already persisted in SQLite ``signal_events`` (the same
store the market-data loader writes) and turns them into honest price-mover
rows. It is read-only and advisory:
    * never mutates SQLite, never creates the DB, never calls a network/broker
    * never fabricates a price — a missing mark yields ``price=null`` plus an
      explicit ``failure_reason`` (PRICE_PROVIDER_UNAVAILABLE / ...)
    * current holdings are price-reviewed but kept SEPARATE from new candidates

Validity (verbatim from the sprint spec)::

    valid_price(t) = 1[ price not null and timestamp not null
                        and age_minutes <= max_age_minutes_for_market_state(t)
                        and currency not null ]
    valid_mover(t) = valid_price(t) and (
                        |return_1d| >= mover_threshold
                        or |return_5d| >= swing_threshold
                        or abnormal_volume_score >= volume_threshold )
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.top30_country_coverage import canonical_country, country_from_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from top30_country_coverage import canonical_country, country_from_ticker


MARKET_DATA_SOURCE = "market_data"
DEFAULT_MOVER_THRESHOLD = 0.03      # 3% 1d
DEFAULT_SWING_THRESHOLD = 0.07      # 7% 5d
DEFAULT_VOLUME_THRESHOLD = 1.5      # 1.5x avg volume
OPEN_MAX_AGE_MIN = 60.0
CLOSED_MAX_AGE_MIN = 96.0 * 60.0    # 96h post-close tolerance
UNKNOWN_MAX_AGE_MIN = 24.0 * 60.0   # conservative 24h when market state unknown

# Currency inference from ticker suffix (advisory only; never authoritative).
_SUFFIX_CURRENCY: dict[str, str] = {
    ".NS": "INR", ".BO": "INR", ".T": "JPY", ".KS": "KRW", ".KQ": "KRW",
    ".L": "GBP", ".DE": "EUR", ".F": "EUR", ".PA": "EUR", ".AS": "EUR",
    ".HK": "HKD", ".TW": "TWD", ".TWO": "TWD", ".SS": "CNY", ".SZ": "CNY",
    ".TO": "CAD", ".V": "CAD", ".AX": "AUD", ".SA": "BRL", ".MX": "MXN",
    ".SR": "SAR", ".SI": "SGD", ".SW": "CHF", ".MI": "EUR", ".MC": "EUR",
    ".ST": "SEK", ".BR": "EUR", ".VI": "EUR", ".WA": "PLN", ".IS": "TRY",
    ".TA": "ILS", ".BA": "ARS",
}


def infer_currency(ticker: str) -> str:
    text = str(ticker or "").strip().upper()
    for suffix, cur in _SUFFIX_CURRENCY.items():
        if text.endswith(suffix.upper()):
            return cur
    return "USD"  # bare/US-listed tickers


def max_age_minutes_for_market_state(market_state: str) -> tuple[float, str | None]:
    """Return ``(max_age_minutes, health_flag)`` for the market state."""
    state = str(market_state or "unknown").strip().lower()
    if state == "open":
        return OPEN_MAX_AGE_MIN, None
    if state == "closed":
        return CLOSED_MAX_AGE_MIN, None
    return UNKNOWN_MAX_AGE_MIN, "DEGRADED_MARKET_STATE_UNKNOWN"


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def valid_price(
    price: float | None,
    timestamp_iso: str | None,
    currency: str | None,
    age_minutes: float | None,
    max_age_minutes: float,
) -> bool:
    return bool(
        price is not None
        and timestamp_iso
        and currency
        and age_minutes is not None
        and age_minutes <= max_age_minutes
    )


def _read_symbol_candles(symbol: str, db_path: Path, limit: int = 8) -> list[dict[str, Any]]:
    try:
        try:
            from scripts.persistence import get_signal_events_for_symbol
        except ModuleNotFoundError:  # pragma: no cover
            from persistence import get_signal_events_for_symbol  # type: ignore
        return get_signal_events_for_symbol(
            symbol, source_name=MARKET_DATA_SOURCE, limit=limit, db_path=db_path
        )
    except Exception:
        return []


def _candle_fields(row: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    """Return ``(close, volume, timestamp_iso)`` from a market_data row."""
    raw = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else row
    close = _safe_float(raw.get("close") if raw.get("close") is not None else raw.get("price"))
    if close is None:
        close = _safe_float(raw.get("last") or raw.get("value"))
    volume = _safe_float(raw.get("volume"))
    ts = raw.get("timestamp") or raw.get("published_at") or row.get("fetched_at")
    dt = _parse_dt(ts)
    return close, volume, dt.isoformat() if dt else None


def build_price_row(
    ticker: str,
    *,
    db_path: Path | None,
    now_utc: datetime,
    market_state: str = "unknown",
    country: str | None = None,
    mover_threshold: float = DEFAULT_MOVER_THRESHOLD,
    swing_threshold: float = DEFAULT_SWING_THRESHOLD,
    volume_threshold: float = DEFAULT_VOLUME_THRESHOLD,
) -> dict[str, Any]:
    """Build one honest price row for ``ticker`` from SQLite market_data."""
    norm = str(ticker or "").strip().upper()
    currency = infer_currency(norm)
    resolved_country = country or canonical_country(country) or country_from_ticker(norm) or "United States"
    max_age, market_health = max_age_minutes_for_market_state(market_state)

    failure_reason: str | None = None
    candles: list[dict[str, Any]] = []
    if not db_path or not Path(db_path).exists():
        failure_reason = "PRICE_PROVIDER_UNAVAILABLE"
    else:
        candles = _read_symbol_candles(norm, Path(db_path))
        if not candles:
            failure_reason = "MARKET_CLOSED_NO_RECENT_MARK"

    price = price_ts = None
    volume = avg_volume = return_1d = return_5d = abnormal_volume_score = None
    age_minutes = None
    if candles:
        closes: list[float] = []
        volumes: list[float] = []
        for row in candles:
            c, v, ts = _candle_fields(row)
            if c is not None:
                closes.append(c)
            if v is not None:
                volumes.append(v)
            if price is None and c is not None:
                price, price_ts = c, ts
        if closes:
            volume = volumes[0] if volumes else None
            if len(closes) >= 2 and closes[1]:
                return_1d = round((closes[0] - closes[1]) / closes[1], 6)
            if len(closes) >= 6 and closes[5]:
                return_5d = round((closes[0] - closes[5]) / closes[5], 6)
            if len(volumes) >= 2:
                avg_volume = round(sum(volumes[1:]) / max(1, len(volumes[1:])), 4)
                if avg_volume:
                    abnormal_volume_score = round(volumes[0] / avg_volume, 4)
        if price_ts:
            dt = _parse_dt(price_ts)
            if dt is not None:
                age_minutes = round((now_utc - dt).total_seconds() / 60.0, 4)
                if age_minutes < 0:
                    age_minutes = 0.0

    is_valid_price = valid_price(price, price_ts, currency, age_minutes, max_age)
    if not is_valid_price and failure_reason is None:
        if price is None:
            failure_reason = "PRICE_PROVIDER_UNAVAILABLE"
        elif age_minutes is not None and age_minutes > max_age:
            failure_reason = "MARKET_CLOSED_NO_RECENT_MARK"
        else:
            failure_reason = "STALE_MARK"

    is_valid_mover = bool(
        is_valid_price
        and (
            (return_1d is not None and abs(return_1d) >= mover_threshold)
            or (return_5d is not None and abs(return_5d) >= swing_threshold)
            or (abnormal_volume_score is not None and abnormal_volume_score >= volume_threshold)
        )
    )

    source_health = "LIVE_VERIFIED" if is_valid_price else (market_health or "PRICE_FALLBACK")
    return {
        "ticker": norm,
        "exchange": "",
        "country": resolved_country,
        "currency": currency,
        "price": price,
        "price_timestamp_utc": price_ts,
        "return_1d": return_1d,
        "return_5d": return_5d,
        "volume": volume,
        "avg_volume": avg_volume,
        "abnormal_volume_score": abnormal_volume_score,
        "provider": MARKET_DATA_SOURCE if candles else "STATIC_UNIVERSE_FALLBACK",
        "source_health": source_health,
        "is_live": bool(is_valid_price),
        "data_quality": 0.6 if is_valid_price else 0.25,
        "valid_price": is_valid_price,
        "valid_mover": is_valid_mover,
        "market_state": market_state,
        "failure_reason": failure_reason,
        "advisory_only": True,
        "human_review_required": True,
    }


def build_live_price_movers(
    db_path: Path | None,
    *,
    now_utc: datetime | None = None,
    holdings: Iterable[str] | None = None,
    candidate_tickers: Iterable[str] | None = None,
    holding_countries: dict[str, str] | None = None,
    market_state: str = "unknown",
    mover_threshold: float = DEFAULT_MOVER_THRESHOLD,
) -> dict[str, Any]:
    """Build the price-review payload, separating holdings from new candidates."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    holding_countries = holding_countries or {}

    existing_rows: list[dict[str, Any]] = []
    for ticker in dict.fromkeys(t.strip().upper() for t in (holdings or []) if t):
        row = build_price_row(
            ticker, db_path=db_path, now_utc=now_utc, market_state=market_state,
            country=holding_countries.get(ticker), mover_threshold=mover_threshold,
        )
        row["row_class"] = "EXISTING_POSITION_REVIEW"
        existing_rows.append(row)

    holding_set = {r["ticker"] for r in existing_rows}
    candidate_rows: list[dict[str, Any]] = []
    for ticker in dict.fromkeys(t.strip().upper() for t in (candidate_tickers or []) if t):
        if ticker in holding_set:
            continue  # never re-classify a holding as a new candidate
        row = build_price_row(
            ticker, db_path=db_path, now_utc=now_utc, market_state=market_state,
            mover_threshold=mover_threshold,
        )
        row["row_class"] = "NEW_CANDIDATE_PRICE_MOVER"
        candidate_rows.append(row)

    valid_marks = [r for r in existing_rows + candidate_rows if r["valid_price"]]
    holdings_missing = [r["ticker"] for r in existing_rows if not r["valid_price"]]
    any_valid = bool(valid_marks)
    meta = {
        "is_live": any_valid,
        "source_health": "LIVE_VERIFIED" if any_valid else "PRICE_PROVIDER_UNAVAILABLE",
        "provider": MARKET_DATA_SOURCE if any_valid else "STATIC_UNIVERSE_FALLBACK",
        "valid_price_count": len(valid_marks),
        "valid_mover_count": sum(1 for r in candidate_rows if r["valid_mover"]),
        "existing_holdings_checked": len(existing_rows),
        "existing_holdings_missing_price": holdings_missing,
        "existing_risk_visibility_degraded": bool(holdings_missing),
        "market_state": market_state,
        "fallback_reason": None if any_valid else "PRICE_PROVIDER_UNAVAILABLE",
    }
    return {
        "existing_position_price_review": existing_rows,
        "new_candidate_price_movers": candidate_rows,
        "meta": meta,
        "safety": advisory_safety_stamps(),
    }


__all__ = [
    "MARKET_DATA_SOURCE",
    "DEFAULT_MOVER_THRESHOLD",
    "infer_currency",
    "max_age_minutes_for_market_state",
    "valid_price",
    "build_price_row",
    "build_live_price_movers",
]
