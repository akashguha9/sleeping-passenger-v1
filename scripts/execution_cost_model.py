"""Per-market, per-fill execution cost model.

Pure module. No I/O, no broker, no network. Given a market code (US, IN, JP,
KR, GB, DE, FR, NL, CH, IT, ES, BR, CA, AU, MX, SE, PL, AT, IE, BE, SG, HK,
TW, SA), notional, and side, returns the per-fill cost broken down into:

    * commission (incl. per-order minimum)
    * exchange/regulatory fees (e.g. India STT on sells, UK stamp on buys)
    * bid-ask half-spread cost (one-side)
    * slippage (basis points on notional)
    * FX round-trip (only on the LEG that converts; modelled here as one-half
      per leg if convert_currency=True)

The cost model is deliberately CONSERVATIVE: the audit Monte Carlo showed
costs likely EXCEED the gross per-trade edge, so the floor is "realistic
retail broker on €50 notional", not "institutional rate". Values are sourced
from public broker schedules and venue rules circa 2025.

Booking plan reminder (TP1 +5% books 50%, TP2 +8% books 30%, 20% runner,
hard -5% stop) -> a winner produces 3 commissioned exits, not 1. The
``book_trade_cost`` helper sums per-fill costs across the full lifecycle so
the backtest can charge each fill its own commission minimum.

All thresholds are stored in ``config/execution_costs.yaml`` and overridable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT


# ---------------------------------------------------------------------------
# Conservative defaults — per market.
# All values are in basis points unless they are absolute currency minimums.
# "commission_min_eur" is the per-order floor in EUR (operator's base ccy).
# "fx_rt_bps" is the round-trip FX cost charged on the WHOLE notional once
# per trade lifecycle (entry + exit ladder) when the market currency != EUR.
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, dict[str, float]] = {
    # US (NYSE/NASDAQ) — Lynx/IBKR Lite retail typical: ~1-2 bps + $1 min.
    "US": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 3.0, "slippage_bps": 2.0, "fx_rt_bps": 40.0},
    # India (NSE/BSE) — broker 3 bps + STT 10 bps on sells + stamp 1.5 bps.
    "IN": {"commission_bps": 3.0, "commission_min_eur": 0.5,
           "exchange_fee_buy_bps": 1.5, "exchange_fee_sell_bps": 11.5,
           "spread_bps": 6.0, "slippage_bps": 4.0, "fx_rt_bps": 80.0},
    # Japan (TSE) — retail commission ~2 bps, no per-trade tax.
    "JP": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 60.0},
    # Korea (KRX) — commission 3 bps + securities transaction tax 18 bps sells.
    "KR": {"commission_bps": 3.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 18.0,
           "spread_bps": 5.0, "slippage_bps": 4.0, "fx_rt_bps": 70.0},
    # UK (LSE) — commission 2 bps + stamp duty 50 bps on buys.
    "GB": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 50.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 30.0},
    # Germany / France / Netherlands / Belgium / Italy / Spain / Ireland /
    # Austria — Euronext / Xetra, EUR-denominated so no FX.
    "DE": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 0.0},
    "FR": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 30.0, "exchange_fee_sell_bps": 0.0,  # FR FTT
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 0.0},
    "NL": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 0.0},
    "BE": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 35.0, "exchange_fee_sell_bps": 35.0,  # BE TOB
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 0.0},
    "IT": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 10.0, "exchange_fee_sell_bps": 0.0,  # IT FTT
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 0.0},
    "ES": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 20.0, "exchange_fee_sell_bps": 0.0,  # ES FTT
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 0.0},
    "AT": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 5.0, "slippage_bps": 4.0, "fx_rt_bps": 0.0},
    "IE": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 100.0, "exchange_fee_sell_bps": 0.0,  # IE stamp 1%
           "spread_bps": 5.0, "slippage_bps": 4.0, "fx_rt_bps": 0.0},
    # Switzerland — CHF, FX needed.
    "CH": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 7.5, "exchange_fee_sell_bps": 7.5,  # CH stamp
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 30.0},
    "SE": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 5.0, "slippage_bps": 4.0, "fx_rt_bps": 30.0},
    "PL": {"commission_bps": 3.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 10.0, "exchange_fee_sell_bps": 10.0,  # PL TT
           "spread_bps": 6.0, "slippage_bps": 5.0, "fx_rt_bps": 50.0},
    "AU": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 40.0},
    "CA": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 30.0},
    "BR": {"commission_bps": 3.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 2.5, "exchange_fee_sell_bps": 2.5,
           "spread_bps": 8.0, "slippage_bps": 6.0, "fx_rt_bps": 80.0},
    "MX": {"commission_bps": 3.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 6.0, "slippage_bps": 5.0, "fx_rt_bps": 60.0},
    "SG": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 40.0},
    "HK": {"commission_bps": 2.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 13.0, "exchange_fee_sell_bps": 13.0,  # HK stamp
           "spread_bps": 4.0, "slippage_bps": 3.0, "fx_rt_bps": 40.0},
    "TW": {"commission_bps": 3.0, "commission_min_eur": 1.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 30.0,  # TW TT sell
           "spread_bps": 5.0, "slippage_bps": 4.0, "fx_rt_bps": 50.0},
    "SA": {"commission_bps": 5.0, "commission_min_eur": 2.0,
           "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
           "spread_bps": 8.0, "slippage_bps": 6.0, "fx_rt_bps": 70.0},
}

# Fallback used when a market code is unknown. Conservative.
_FALLBACK: dict[str, float] = {
    "commission_bps": 3.0, "commission_min_eur": 1.5,
    "exchange_fee_buy_bps": 0.0, "exchange_fee_sell_bps": 0.0,
    "spread_bps": 6.0, "slippage_bps": 5.0, "fx_rt_bps": 60.0,
}

_CONFIG_PATH = REPO_ROOT / "config" / "execution_costs.yaml"


def load_cost_config() -> dict[str, dict[str, float]]:
    """Return the per-market cost table, optionally overridden by yaml.

    Yaml shape (all keys optional):
        execution_costs:
          US: {commission_bps: 1.5, slippage_bps: 1.0, ...}
          ...
    """
    out = {k: dict(v) for k, v in _DEFAULTS.items()}
    try:
        from src.utils.config_loader import load_yaml_config

        cfg = load_yaml_config(_CONFIG_PATH)
    except Exception:
        return out
    block = cfg.get("execution_costs") if isinstance(cfg, dict) else None
    if not isinstance(block, dict):
        return out
    for market, overrides in block.items():
        if not isinstance(overrides, dict):
            continue
        market = str(market).upper()
        base = dict(out.get(market, _FALLBACK))
        base.update({k: float(v) for k, v in overrides.items() if isinstance(v, (int, float))})
        out[market] = base
    return out


@dataclass(frozen=True)
class FillCost:
    """Per-fill cost breakdown, all in EUR on the leg's notional."""
    notional_eur: float
    side: str            # "BUY" or "SELL"
    market: str
    commission_eur: float
    exchange_fee_eur: float
    spread_eur: float
    slippage_eur: float
    total_eur: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "notional_eur": round(self.notional_eur, 4),
            "side": self.side, "market": self.market,
            "commission_eur": round(self.commission_eur, 4),
            "exchange_fee_eur": round(self.exchange_fee_eur, 4),
            "spread_eur": round(self.spread_eur, 4),
            "slippage_eur": round(self.slippage_eur, 4),
            "total_eur": round(self.total_eur, 4),
        }


def fill_cost(
    *,
    notional_eur: float,
    side: str,
    market: str,
    config: dict[str, dict[str, float]] | None = None,
) -> FillCost:
    """Charge a single fill.

    Cost = max(commission_bps * notional, commission_min) + exchange_fee_bps *
        notional + spread_bps/2 * notional (half-spread) + slippage_bps *
        notional. Half-spread because a market order crosses the bid-ask
        midpoint once; the other half is paid on the opposite leg.
    """
    cfg = config or load_cost_config()
    table = cfg.get(market.upper()) or _FALLBACK
    side_u = side.upper()
    if side_u not in {"BUY", "SELL"}:
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    bps_commission = float(table.get("commission_bps", 0.0)) / 10_000
    commission = max(notional_eur * bps_commission,
                     float(table.get("commission_min_eur", 0.0)))
    fee_bps = float(table.get(
        "exchange_fee_buy_bps" if side_u == "BUY" else "exchange_fee_sell_bps",
        0.0)) / 10_000
    exchange_fee = notional_eur * fee_bps
    half_spread = notional_eur * float(table.get("spread_bps", 0.0)) / 10_000 / 2
    slippage = notional_eur * float(table.get("slippage_bps", 0.0)) / 10_000
    total = commission + exchange_fee + half_spread + slippage
    return FillCost(
        notional_eur=notional_eur, side=side_u, market=market.upper(),
        commission_eur=commission, exchange_fee_eur=exchange_fee,
        spread_eur=half_spread, slippage_eur=slippage, total_eur=total,
    )


@dataclass
class LifecycleCost:
    """Sum of all fills + FX round-trip for one position's lifecycle."""
    fills: list[FillCost] = field(default_factory=list)
    fx_rt_eur: float = 0.0
    n_fills: int = 0
    total_eur: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_fills": self.n_fills,
            "fx_rt_eur": round(self.fx_rt_eur, 4),
            "fills_total_eur": round(self.total_eur - self.fx_rt_eur, 4),
            "total_eur": round(self.total_eur, 4),
            "fills": [f.as_dict() for f in self.fills],
        }


def book_trade_cost(
    *,
    alloc_eur: float,
    market: str,
    leg_fractions: list[tuple[str, float]],
    config: dict[str, dict[str, float]] | None = None,
    needs_fx: bool | None = None,
) -> LifecycleCost:
    """Sum cost across an entire position lifecycle.

    `leg_fractions` is an ordered list of (side, fraction_of_initial_notional)
    tuples for each fill. For a TP1+TP2+runner winner:

        [("BUY", 1.0),
         ("SELL", 0.50),  # TP1 books 50% of initial notional
         ("SELL", 0.30),  # TP2 books 30%
         ("SELL", 0.20)]  # runner mark-out at as-of

    For a stopped trade: [("BUY", 1.0), ("SELL", 1.0)] (single stop fill).

    FX round-trip: charged ONCE on the full alloc when market is not EUR. If
    `needs_fx=None` it's inferred from the market: any non-EUR market gets it.
    """
    cfg = config or load_cost_config()
    table = cfg.get(market.upper()) or _FALLBACK
    fills: list[FillCost] = []
    total = 0.0
    for side, frac in leg_fractions:
        if frac <= 0:
            continue
        leg_notional = alloc_eur * float(frac)
        f = fill_cost(notional_eur=leg_notional, side=side, market=market,
                      config=cfg)
        fills.append(f)
        total += f.total_eur
    eur_markets = {"DE", "FR", "NL", "BE", "IT", "ES", "AT", "IE"}
    if needs_fx is None:
        needs_fx = market.upper() not in eur_markets
    fx_rt = 0.0
    if needs_fx:
        fx_rt = alloc_eur * float(table.get("fx_rt_bps", 0.0)) / 10_000
        total += fx_rt
    return LifecycleCost(fills=fills, fx_rt_eur=fx_rt, n_fills=len(fills),
                         total_eur=total)


__all__ = [
    "FillCost",
    "LifecycleCost",
    "book_trade_cost",
    "fill_cost",
    "load_cost_config",
]
