"""NBI price-validation adapter — wires exposures to real price/volume data.

Closes "price validation is only an interface".  Pure math over injectable
price series (the snapshot_maturity_scanner pattern: pure logic + network
strictly opt-in behind the CLI flag), producing the fields the engine's
``evaluate_price_validation`` requires:

    ZMove   = (Return_ticker - Return_benchmark) / (sigma_lookback + eps)
    PD      = |P_model - P_implied| * |ZMove|      (computed by the engine)

Implied probability resolution order (source always disclosed):
    explicit market-implied input          -> "MARKET"
    proxy 0.5 + clamp(z/10)                -> "WEAK_PROXY" (disclosed, weak)
    nothing                                -> price_valid stays True but the
                                              engine has no PD inputs -> the
                                              exposure stays WATCH_ONLY.

Fail-closed rules (tested):
* missing/short price series -> price_valid=False -> engine WATCH_ONLY;
* explicitly illiquid (adv below floor) -> liquidity_ok=False -> engine
  zeroes the exposure (NO_ACTIONABLE_EXPOSURE path);
* adapter/fetch failure in the CLI -> BLOCKED report, never invented data.

Advisory-only.  No broker calls, no order surface.
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Any

LIQUIDITY_ADV_FLOOR_USD = 1_000_000.0
_EPS = 1e-9
_MIN_LOOKBACK_POINTS = 5


def _returns(series: dict[int, float], start: int, end: int) -> float | None:
    p0, p1 = series.get(start), series.get(end)
    if p0 is None or p1 is None or p0 <= 0:
        return None
    return (p1 - p0) / p0


def _daily_relative_returns(
    ticker: dict[int, float], benchmark: dict[int, float],
    end_day: int, lookback: int,
) -> list[float]:
    rels: list[float] = []
    for day in range(end_day - lookback, end_day):
        rt = _returns(ticker, day, day + 1)
        rb = _returns(benchmark, day, day + 1)
        if rt is not None and rb is not None:
            rels.append(rt - rb)
    return rels


def build_price_validation(
    ticker: str,
    *,
    prices: dict[int, float] | None,
    benchmark_prices: dict[int, float] | None,
    event_day: int,
    as_of_day: int,
    lookback: int = 20,
    implied_probability: float | None = None,
    average_daily_volume_usd: float | None = None,
    data_source: str = "injected",
) -> dict[str, Any]:
    """Pure price validation for one ticker around one event day."""
    notes: list[str] = []
    result: dict[str, Any] = {
        "ticker": (ticker or "").upper(),
        "price_valid": False,
        "liquidity_ok": None,
        "event_return": None,
        "benchmark_return": None,
        "realized_move_zscore": None,
        "market_implied_probability": None,
        "implied_probability_source": "NONE",
        "current_price": None,
        "data_source": data_source,
        "event_day": event_day,
        "as_of_day": as_of_day,
        "notes": notes,
    }

    if average_daily_volume_usd is not None:
        result["liquidity_ok"] = average_daily_volume_usd >= LIQUIDITY_ADV_FLOOR_USD
        if not result["liquidity_ok"]:
            notes.append(
                f"ADV {average_daily_volume_usd:.0f} < floor "
                f"{LIQUIDITY_ADV_FLOOR_USD:.0f} -> NO_ACTIONABLE_EXPOSURE"
            )

    if not prices or not benchmark_prices:
        notes.append("price/benchmark series missing -> price_valid=False (WATCH_ONLY)")
        return result

    event_return = _returns(prices, event_day, as_of_day)
    benchmark_return = _returns(benchmark_prices, event_day, as_of_day)
    if event_return is None or benchmark_return is None:
        notes.append("event-window prices incomplete -> price_valid=False (WATCH_ONLY)")
        return result

    rels = _daily_relative_returns(prices, benchmark_prices, event_day, lookback)
    if len(rels) < _MIN_LOOKBACK_POINTS:
        notes.append(
            f"only {len(rels)} lookback points (<{_MIN_LOOKBACK_POINTS}) "
            "-> price_valid=False (WATCH_ONLY)"
        )
        return result
    mean = sum(rels) / len(rels)
    sigma = math.sqrt(sum((r - mean) ** 2 for r in rels) / len(rels))
    zscore = (event_return - benchmark_return) / (sigma + _EPS)

    result.update({
        "price_valid": True,
        "event_return": round(event_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "realized_move_zscore": round(zscore, 4),
        "current_price": prices.get(as_of_day),
        "lookback_points": len(rels),
        "lookback_sigma": round(sigma, 6),
    })

    if implied_probability is not None:
        result["market_implied_probability"] = max(0.0, min(1.0, implied_probability))
        result["implied_probability_source"] = "MARKET"
    else:
        proxy = max(0.05, min(0.95, 0.5 + zscore / 10.0))
        result["market_implied_probability"] = round(proxy, 4)
        result["implied_probability_source"] = "WEAK_PROXY"
        notes.append(
            "implied probability proxied from z-move (WEAK_PROXY) — "
            "treat resulting dislocation as low-confidence"
        )
    return result


def attach_price_validation(
    exposure: dict[str, Any],
    validation: dict[str, Any],
    *,
    model_probability: float | None = None,
) -> dict[str, Any]:
    """Return a copy of the exposure with price fields attached fail-closed.

    Only a ``price_valid`` validation fills the engine's PD inputs; anything
    else leaves them absent so the engine caps the ticker WATCH_ONLY.
    liquidity_ok=False always propagates (hard zero beats missing data).
    """
    out = dict(exposure)
    if validation.get("liquidity_ok") is not None:
        out["liquidity_ok"] = validation["liquidity_ok"]
    if not validation.get("price_valid"):
        out.pop("realized_move_zscore", None)
        out.pop("market_implied_probability", None)
        return out
    out["realized_move_zscore"] = validation["realized_move_zscore"]
    out["market_implied_probability"] = validation["market_implied_probability"]
    out["implied_probability_source"] = validation["implied_probability_source"]
    if model_probability is not None:
        out["model_probability"] = max(0.0, min(1.0, model_probability))
    return out


def _fetch_yfinance_series(ticker: str) -> dict[int, float]:  # pragma: no cover
    """Live fetch, CLI-only, explicit opt-in.  Failure raises to the caller
    which reports BLOCKED — data is never invented."""
    import yfinance as yf

    hist = yf.Ticker(ticker).history(period="3mo", interval="1d")
    return {
        int(ts.timestamp()) // 86400: float(close)
        for ts, close in hist["Close"].items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NBI price validation (pure by default; --live-yfinance is the "
            "only network path and fails closed)."
        )
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--event-day", type=int, required=True,
                        help="Epoch day of the event")
    parser.add_argument("--as-of-day", type=int, required=True)
    parser.add_argument("--live-yfinance", action="store_true")
    args = parser.parse_args(argv)

    prices: dict[int, float] | None = None
    benchmark: dict[int, float] | None = None
    status = "OK"
    blocker = None
    if args.live_yfinance:
        try:
            prices = _fetch_yfinance_series(args.ticker)
            benchmark = _fetch_yfinance_series(args.benchmark)
        except Exception as exc:  # noqa: BLE001 - fail closed, disclose
            status, blocker = "BLOCKED", f"PRICE_FETCH_FAILED: {type(exc).__name__}"
    validation = build_price_validation(
        args.ticker, prices=prices, benchmark_prices=benchmark,
        event_day=args.event_day, as_of_day=args.as_of_day,
        data_source="yfinance" if args.live_yfinance else "none",
    )
    print(json.dumps({
        "status": status, "blocker": blocker, "validation": validation,
        "advisory_status": "ADVISORY_ONLY",
    }, indent=2))
    return 0


__all__ = [
    "LIQUIDITY_ADV_FLOOR_USD",
    "build_price_validation", "attach_price_validation", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
