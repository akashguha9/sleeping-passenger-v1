"""Close the Outcome Loop Sprint — real price evidence for outcome attachment.

This is the missing wire of the outcome loop: it reads *real* OHLCV price bars
that were already ingested into ``signal_events`` (``source_name='market_data'``)
and turns them into the entry/exit price evidence that
:func:`scripts.attach_due_outcomes.attach_due_outcomes` consumes when a decision
horizon has elapsed.

Hard honesty rules (all enforced):

* It reads only *real* ingested price bars — it never fetches the network here
  and never fabricates a price.  A missing bar yields ``None`` (the caller then
  records the decision as ``EXCLUDED`` with ``NO_PRICE_EVIDENCE``).
* Entry price is the last real bar at/before the decision timestamp; exit price
  is the last real bar at/before the horizon-close timestamp.  Both must exist
  *and* sit within ``max_gap_days`` of their anchor, or the evidence is ``None``.
* If the horizon-close timestamp is still in the future relative to ``now`` the
  evidence is ``None`` — an unresolved horizon is never labelled.
* No broker, no order, no execution: this module only reads prices.

The realized-return / label math itself lives in
:mod:`scripts.outcome_labeling_flow` and is reused by ``attach_due_outcomes``;
this module only supplies the real ``entry_price`` / ``exit_price`` pair.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

try:  # package layout
    from scripts.decision_probability_snapshot import TABLE, ensure_schema
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from decision_probability_snapshot import TABLE, ensure_schema  # type: ignore[no-redef]

MARKET_DATA_SOURCE = "market_data"
# How far a real bar may sit from its anchor timestamp and still count as the
# price "at" that moment.  Real daily bars are sparse (weekends/holidays); a
# week of slack keeps us honest without inventing prices.
DEFAULT_MAX_GAP_DAYS = 7.0

# Light, explicit name -> symbol map so the messy ticker strings the scorer
# persists ("Apple Inc.", "MICROSOFT CORP") can still resolve to a symbol that
# has a real price series.  Only exact, well-known mappings — never a guess.
_NAME_TO_SYMBOL = {
    "APPLE INC.": "AAPL",
    "APPLE INC": "AAPL",
    "MICROSOFT CORP": "MSFT",
    "MICROSOFT CORPORATION": "MSFT",
    "NVIDIA CORP": "NVDA",
    "NVIDIA CORPORATION": "NVDA",
    "TESLA, INC.": "TSLA",
    "TESLA INC": "TSLA",
}


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    text = str(ts).strip()
    # Yahoo bars look like "2026-05-08 00:00:00-04:00"; ISO snapshots look like
    # "2026-05-31T10:57:14Z".  Normalise both.
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Last resort: take the leading date.
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_symbol(ticker: Any) -> str | None:
    """Resolve a (possibly messy) ticker string to a price-series symbol key."""
    if not ticker:
        return None
    raw = str(ticker).strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in _NAME_TO_SYMBOL:
        return _NAME_TO_SYMBOL[upper]
    # A bare symbol (letters, optional .SUFFIX or -SUFFIX) is used verbatim.
    return upper


def _bar_close(payload: Mapping[str, Any]) -> float | None:
    """Pull a real close price from a market_data bar payload, or None."""
    for key in ("close", "latest_price"):
        val = payload.get(key)
        if val is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return None


def load_price_series(
    db_path: Any,
    *,
    symbols: set[str] | None = None,
) -> dict[str, list[tuple[datetime, float]]]:
    """Load real OHLCV close series per symbol from ``signal_events``.

    Returns ``{symbol: [(utc_dt, close), ...]}`` sorted ascending by time.  Only
    bars carrying a real positive close (or latest_price) are kept; rows with a
    null price are honestly dropped (never zero-filled).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT raw_payload FROM signal_events WHERE source_name = ?",
            (MARKET_DATA_SOURCE,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    series: dict[str, list[tuple[datetime, float]]] = {}
    for r in rows:
        try:
            payload = json.loads(r["raw_payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        sym = normalize_symbol(payload.get("symbol"))
        if sym is None:
            continue
        if symbols is not None and sym not in symbols:
            continue
        dt = _parse_iso(payload.get("timestamp"))
        close = _bar_close(payload)
        if dt is None or close is None:
            continue
        series.setdefault(sym, []).append((dt, close))

    for sym in series:
        series[sym].sort(key=lambda t: t[0])
    return series


def price_point_on_or_before(
    bars: list[tuple[datetime, float]],
    target: datetime,
    *,
    max_gap_days: float = DEFAULT_MAX_GAP_DAYS,
) -> tuple[datetime, float] | None:
    """Last real ``(timestamp, close)`` at/before ``target`` within tolerance."""
    best: tuple[datetime, float] | None = None
    for dt, close in bars:  # bars are sorted ascending
        if dt <= target:
            best = (dt, close)
        else:
            break
    if best is None:
        return None
    if (target - best[0]) > timedelta(days=max_gap_days):
        return None
    return best


def price_on_or_before(
    bars: list[tuple[datetime, float]],
    target: datetime,
    *,
    max_gap_days: float = DEFAULT_MAX_GAP_DAYS,
) -> float | None:
    """Last real close at/before ``target`` within ``max_gap_days``, else None."""
    point = price_point_on_or_before(bars, target, max_gap_days=max_gap_days)
    return point[1] if point is not None else None


def resolve_entry_price(
    db_path: Any,
    *,
    ticker: Any,
    decision_timestamp_utc: Any,
    max_lookback_days: float = DEFAULT_MAX_GAP_DAYS,
    series_by_symbol: Mapping[str, list[tuple[datetime, float]]] | None = None,
) -> dict[str, Any] | None:
    """Resolve a real entry/reference price for a decision, or ``None``.

    The entry price is the last real OHLCV close at/before the decision timestamp
    whose bar sits within ``max_lookback_days``.  It is NEVER taken from a bar
    after the decision timestamp (no look-ahead), and is never fabricated — a
    missing/stale series yields ``None`` so the caller records
    ``MISSING_ENTRY_PRICE``.

    Returns ``{entry_price, entry_price_timestamp_utc, entry_price_source,
    symbol}``.
    """
    sym = normalize_symbol(ticker)
    if sym is None:
        return None
    decision_dt = _parse_iso(decision_timestamp_utc)
    if decision_dt is None:
        return None

    if series_by_symbol is None:
        series_by_symbol = load_price_series(db_path, symbols={sym})
    bars = series_by_symbol.get(sym)
    if not bars:
        return None

    point = price_point_on_or_before(bars, decision_dt, max_gap_days=max_lookback_days)
    if point is None:
        return None
    entry_dt, entry_close = point
    if entry_close is None or entry_close <= 0:
        return None
    return {
        "entry_price": float(entry_close),
        "entry_price_timestamp_utc": entry_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entry_price_source": "real_ohlcv_signal_events",
        "symbol": sym,
    }


def build_real_price_evidence(
    snapshot: Mapping[str, Any],
    series_by_symbol: Mapping[str, list[tuple[datetime, float]]],
    *,
    now_utc: datetime,
    benchmark_symbol: str | None = None,
    max_gap_days: float = DEFAULT_MAX_GAP_DAYS,
) -> dict[str, Any] | None:
    """Build entry/exit price evidence for one snapshot from real bars.

    Returns ``None`` (no fabrication) when the ticker is missing/unknown, the
    horizon is missing/non-positive, the horizon has not elapsed, or a real
    entry/exit bar cannot be found within tolerance.
    """
    sym = normalize_symbol(snapshot.get("ticker"))
    if sym is None or sym not in series_by_symbol:
        return None

    decision_dt = _parse_iso(snapshot.get("timestamp_utc"))
    if decision_dt is None:
        return None
    try:
        horizon_days = float(snapshot.get("prediction_horizon_days"))
    except (TypeError, ValueError):
        return None
    if horizon_days <= 0:
        return None

    exit_dt = decision_dt + timedelta(days=horizon_days)
    if exit_dt > now_utc:
        # Horizon still open in real calendar time — never label it.
        return None

    bars = series_by_symbol[sym]
    entry = price_on_or_before(bars, decision_dt, max_gap_days=max_gap_days)
    exit_ = price_on_or_before(bars, exit_dt, max_gap_days=max_gap_days)
    if entry is None or exit_ is None:
        return None

    evidence: dict[str, Any] = {
        "entry_price": entry,
        "exit_price": exit_,
        "outcome_timestamp": exit_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome_source": "real_ohlcv_signal_events",
        "outcome_kind": "real_forward",
        "is_real_outcome": True,
        "trade_open": False,
        "symbol": sym,
    }

    if benchmark_symbol:
        b_bars = series_by_symbol.get(normalize_symbol(benchmark_symbol) or "")
        if b_bars:
            b_entry = price_on_or_before(b_bars, decision_dt, max_gap_days=max_gap_days)
            b_exit = price_on_or_before(b_bars, exit_dt, max_gap_days=max_gap_days)
            if b_entry is not None and b_exit is not None:
                evidence["benchmark_entry"] = b_entry
                evidence["benchmark_exit"] = b_exit
    return evidence


def make_real_price_evidence_provider(
    db_path: Any,
    *,
    now_utc: str | None = None,
    benchmark_symbol: str | None = None,
    max_gap_days: float = DEFAULT_MAX_GAP_DAYS,
) -> Callable[[str], dict[str, Any] | None]:
    """Return a ``decision_id -> evidence|None`` provider over real price bars.

    The provider reads each decision snapshot's ticker / timestamp / horizon and
    looks up real entry/exit closes.  It is the default real-evidence source for
    ``attach_due_outcomes`` — supplying nothing fabricated.
    """
    now_dt = _parse_iso(now_utc) or datetime.now(timezone.utc)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        rows = conn.execute(
            f"SELECT snapshot_id, ticker, timestamp_utc, prediction_horizon_days"
            f" FROM {TABLE}"
        ).fetchall()
    finally:
        conn.close()
    snap_by_id = {r["snapshot_id"]: dict(r) for r in rows}

    wanted: set[str] = set()
    for snap in snap_by_id.values():
        sym = normalize_symbol(snap.get("ticker"))
        if sym:
            wanted.add(sym)
    if benchmark_symbol:
        bsym = normalize_symbol(benchmark_symbol)
        if bsym:
            wanted.add(bsym)

    series = load_price_series(db_path, symbols=wanted or None)

    def _provider(decision_id: str) -> dict[str, Any] | None:
        snap = snap_by_id.get(decision_id)
        if snap is None:
            return None
        return build_real_price_evidence(
            snap, series, now_utc=now_dt,
            benchmark_symbol=benchmark_symbol, max_gap_days=max_gap_days,
        )

    return _provider


def price_coverage_summary(
    db_path: Any,
    *,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Honest accounting of how many due snapshots have real price coverage.

    Read-only; advisory.  ``due`` counts elapsed-horizon snapshots; ``priceable``
    counts those for which real entry+exit bars exist.  This never attaches an
    outcome — it only reports whether the loop *could* close on real prices.
    """
    now_dt = _parse_iso(now_utc) or datetime.now(timezone.utc)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT snapshot_id, ticker, timestamp_utc,"
                f" prediction_horizon_days FROM {TABLE}"
            ).fetchall()
        ]
    finally:
        conn.close()

    wanted = {s for s in (normalize_symbol(r.get("ticker")) for r in rows) if s}
    series = load_price_series(db_path, symbols=wanted or None)

    n_snapshots = len(rows)
    n_with_ticker = 0
    n_with_horizon = 0
    n_priceable = 0
    for snap in rows:
        if normalize_symbol(snap.get("ticker")):
            n_with_ticker += 1
        try:
            if float(snap.get("prediction_horizon_days")) > 0:
                n_with_horizon += 1
        except (TypeError, ValueError):
            pass
        ev = build_real_price_evidence(snap, series, now_utc=now_dt)
        if ev is not None:
            n_priceable += 1

    return {
        "n_snapshots": n_snapshots,
        "n_with_ticker": n_with_ticker,
        "n_with_horizon": n_with_horizon,
        "n_priceable": n_priceable,
        "price_symbols_available": sorted(series.keys()),
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


__all__ = [
    "MARKET_DATA_SOURCE",
    "DEFAULT_MAX_GAP_DAYS",
    "normalize_symbol",
    "load_price_series",
    "price_on_or_before",
    "price_point_on_or_before",
    "resolve_entry_price",
    "build_real_price_evidence",
    "make_real_price_evidence_provider",
    "price_coverage_summary",
]
