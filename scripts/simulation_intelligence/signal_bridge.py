"""Priority 1 — Signal reactor / OHLCV → validated MarketObservation bridge.

Turns live, canonical DB state into a `MarketObservation` the council can run on,
WITHOUT letting incomplete data look complete. The daily-discovery flow (or the
API) can invoke the council for a ticker without an operator hand-typing the
observation.

Fail-closed design:
* returns/volumes/price are reconstructed ONLY from real OHLCV bars (or live
  `market_data` events); nothing is invented.
* freshness is UNKNOWN unless the caller supplies today's session date — the
  bridge never claims FRESH without knowing "now".
* every absent numeric field is recorded in ``missing_fields`` so lenses fail
  closed (INSUFFICIENT_DATA) rather than fabricating confidence.
* the parent signal id is preserved end-to-end so a simulation run links back to
  the candidate it came from.

It NEVER creates a trade action, never sizes, never executes.

Split into a PURE core (`build_observation_from_bars`, DB-free, unit-testable)
and a persistence-backed entry point (`build_observation_for_ticker`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import (
        MarketObservation, FreshnessStatus,
    )
    from scripts.simulation_intelligence.api_surface import build_observation
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        MarketObservation, FreshnessStatus,
    )
    from simulation_intelligence.api_surface import build_observation  # type: ignore[no-redef]

# Reuse the repo's freshness thresholds so the bridge agrees with the rest of the
# system on what "stale" means.
_DELAYED_DAYS = 10.0
_STALE_DAYS = 30.0
_MAX_BARS = 260  # ~1 trading year, bounded


def _num(x: Any) -> float | None:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _returns_from_closes(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev and prev == prev and closes[i] == closes[i]:
            out.append(closes[i] / prev - 1.0)
    return out


def _stdev(xs: list[float]) -> float | None:
    xs = [x for x in xs if x == x]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _map_market(jurisdiction_group: str, exchange: str, currency: str) -> str:
    jg = (jurisdiction_group or "").upper()
    if jg == "INDIA":
        return "IN"
    ex = (exchange or "").upper()
    cur = (currency or "").upper()
    if ex in ("NASDAQ", "NYSE", "NYSEARCA", "AMEX", "BATS") or cur == "USD":
        return "US"
    if jg == "ROW":
        return "ROW"
    return "UNKNOWN"


def _freshness(latest_date: str, session_date: str | None) -> str:
    """FRESH/AGING/STALE/UNKNOWN from the gap between latest bar and today.
    UNKNOWN (fail-closed) when we do not know today's date or can't parse."""
    if not session_date or not latest_date:
        return FreshnessStatus.UNKNOWN.value
    import datetime as _dt

    def _p(s: str) -> _dt.date | None:
        try:
            return _dt.date.fromisoformat(str(s)[:10])
        except (ValueError, TypeError):
            return None

    a, b = _p(latest_date), _p(session_date)
    if a is None or b is None:
        return FreshnessStatus.UNKNOWN.value
    age = (b - a).days
    if age < 0:
        return FreshnessStatus.UNKNOWN.value  # future bar → suspicious, fail closed
    if age <= _DELAYED_DAYS:
        return FreshnessStatus.FRESH.value
    if age <= _STALE_DAYS:
        return FreshnessStatus.AGING.value
    return FreshnessStatus.STALE.value


@dataclass(slots=True)
class BridgeResult:
    observation: MarketObservation
    parent_signal_id: str
    ok: bool
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.to_dict(),
            "parent_signal_id": self.parent_signal_id,
            "ok": self.ok, "warnings": self.warnings, "source": self.source,
        }


def build_observation_from_bars(
    ticker: str,
    bars: list[dict[str, Any]],
    *,
    market: str = "UNKNOWN",
    sector: str = "",
    session_date: str | None = None,
    parent_signal_id: str = "",
    catalysts: list[dict[str, Any]] | None = None,
    narrative_sources: list[str] | None = None,
    dependencies: list[dict[str, Any]] | None = None,
    provenance: dict[str, str] | None = None,
) -> BridgeResult:
    """PURE core: build a validated observation from OHLCV bar dicts.

    ``bars`` are ascending-by-date dicts with keys date/close/adjusted_close/
    volume/exchange/currency (as returned by ``persistence.get_ohlcv_bars``).
    """
    warnings: list[str] = []
    bars = list(bars or [])[-_MAX_BARS:]
    closes: list[float] = []
    volumes: list[float] = []
    latest_date = ""
    exchange = currency = ""
    for b in bars:
        c = _num(b.get("adjusted_close")) or _num(b.get("close"))
        if c is not None:
            closes.append(c)
            volumes.append(_num(b.get("volume")) or 0.0)
            latest_date = str(b.get("date", latest_date)) or latest_date
            exchange = str(b.get("exchange", exchange)) or exchange
            currency = str(b.get("currency", currency)) or currency

    returns = _returns_from_closes(closes)
    price = closes[-1] if closes else None
    prev_close = closes[-2] if len(closes) >= 2 else None
    vol = _stdev(returns)
    adv = None
    if closes and volumes:
        pv = [c * v for c, v in zip(closes[-20:], volumes[-20:]) if v]
        adv = sum(pv) / len(pv) if pv else None

    prov = dict(provenance or {})
    prov.setdefault("price_source", "ohlcv_bars")
    if latest_date:
        prov.setdefault("latest_bar_date", str(latest_date)[:10])
    if exchange:
        prov.setdefault("exchange", exchange[:32])
    if currency:
        prov.setdefault("currency", currency[:16])

    freshness = _freshness(latest_date, session_date)
    if freshness == FreshnessStatus.UNKNOWN.value:
        warnings.append("freshness UNKNOWN (no session_date or unparseable bar date) — fail closed")
    elif freshness == FreshnessStatus.STALE.value:
        warnings.append(f"latest bar {latest_date} is STALE relative to {session_date}")

    payload: dict[str, Any] = {
        "ticker": ticker, "market": market or "UNKNOWN",
        "as_of": session_date or (str(latest_date)[:10] if latest_date else ""),
        "data_cutoff": str(latest_date)[:10] if latest_date else "",
        "returns": returns, "volumes": volumes,
        "sector": sector, "source_count": len(narrative_sources or []),
        "narrative_sources": narrative_sources or [],
        "catalysts": catalysts or [], "dependencies": dependencies or [],
        "freshness_status": freshness, "provenance": prov,
    }
    if price is not None:
        payload["price"] = price
    if prev_close is not None:
        payload["prev_close"] = prev_close
    if vol is not None:
        payload["volatility"] = vol
    if adv is not None:
        payload["adv_usd"] = adv

    obs = build_observation(payload)
    # Extend missing_fields for anything OHLCV could not supply.
    missing = list(obs.missing_fields)
    for fld, val in (("volatility", vol), ("adv_usd", adv), ("prev_close", prev_close)):
        if val is None and fld not in missing:
            missing.append(fld)
    if len(returns) < 2 and "returns" not in missing:
        missing.append("returns")
    obs.missing_fields = missing
    ok = bool(closes) and len(returns) >= 2
    if not ok:
        warnings.append("insufficient OHLCV history to reconstruct returns — "
                        "observation will fail closed in lenses")
    return BridgeResult(observation=obs, parent_signal_id=parent_signal_id,
                        ok=ok, warnings=warnings, source="ohlcv_bars")


def build_observation_for_ticker(
    ticker: str,
    *,
    session_date: str | None = None,
    parent_signal_id: str = "",
    sector: str = "",
    db_path: Any = None,
) -> BridgeResult:
    """Persistence-backed entry point: pull canonical OHLCV (fallback to live
    market_data events) and build a validated observation. Runtime-reached via
    the ``/api/simulation/observation/{ticker}`` route."""
    try:
        from scripts import persistence as P
        from scripts import leverage_governance as lg
    except ModuleNotFoundError:  # pragma: no cover
        import persistence as P  # type: ignore[no-redef]
        import leverage_governance as lg  # type: ignore[no-redef]

    tkr = str(ticker).strip().upper()
    warnings: list[str] = []
    try:
        bars = P.get_ohlcv_bars(tkr) if db_path is None else P.get_ohlcv_bars(tkr, db_path=db_path)
    except Exception:  # fail soft — no bars
        bars = []

    source = "ohlcv_bars"
    if not bars:
        # Fallback: live market_data events (descending → reverse to ascending).
        try:
            evs = (P.get_signal_events_for_symbol(tkr, source_name="market_data")
                   if db_path is None else
                   P.get_signal_events_for_symbol(tkr, source_name="market_data", db_path=db_path))
        except Exception:
            evs = []
        rows = []
        for e in reversed(evs or []):
            payload = e.get("raw_payload", {}) if isinstance(e, dict) else {}
            if not isinstance(payload, dict):
                continue
            rows.append({
                "date": str(payload.get("timestamp", ""))[:10],
                "close": payload.get("close", payload.get("latest_price")),
                "volume": payload.get("volume"),
                "exchange": payload.get("exchange", ""),
                "currency": payload.get("currency", ""),
            })
        bars = rows
        source = "market_data_events"
        if not bars:
            warnings.append(f"no OHLCV bars or live market_data for {tkr}")

    # Resolve market/jurisdiction.
    market = "UNKNOWN"
    try:
        resolved = lg.resolve_leverage_ceiling(tkr)
        market = _map_market(resolved.get("jurisdiction_group", "UNKNOWN"),
                             bars[0].get("exchange", "") if bars else "",
                             bars[0].get("currency", "") if bars else "")
    except Exception:
        pass

    result = build_observation_from_bars(
        tkr, bars, market=market, sector=sector, session_date=session_date,
        parent_signal_id=parent_signal_id,
        provenance={"resolution": "signal_bridge", "bridge_source": source})
    result.source = source
    result.warnings = warnings + result.warnings
    return result


__all__ = [
    "BridgeResult", "build_observation_from_bars", "build_observation_for_ticker",
]
