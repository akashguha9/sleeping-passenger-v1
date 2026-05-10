"""
Phase E.2 — Deterministic local OHLCV seed for chart structure demo.

Generates 120 daily candles per symbol into the local SQLite DB
(signal_events table, source_name='market_data').

Idempotent: stable event IDs "seed_ohlcv_{symbol}_{YYYY-MM-DD}" combined with
INSERT OR IGNORE ensure a second run inserts nothing new.

No internet dependency. No broker logic. Advisory-only.

Usage
-----
    python scripts/seed_chart_ohlcv_history.py --write   # persist to DB
    python scripts/seed_chart_ohlcv_history.py           # dry-run, print JSON
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SYMBOLS: list[str] = ["AAPL", "GLD", "TLT", "BTC-USD", "SPY"]
N_CANDLES: int = 120

_BASE_PRICES: dict[str, float] = {
    "AAPL": 185.0,
    "GLD": 220.0,
    "TLT": 90.0,
    "BTC-USD": 65_000.0,
    "SPY": 520.0,
}
_DAILY_VOL: dict[str, float] = {
    "AAPL": 0.012,
    "GLD": 0.008,
    "TLT": 0.007,
    "BTC-USD": 0.030,
    "SPY": 0.010,
}
_BASE_VOLUME: dict[str, int] = {
    "AAPL": 55_000_000,
    "GLD": 8_000_000,
    "TLT": 12_000_000,
    "BTC-USD": 25_000,
    "SPY": 75_000_000,
}

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0


# ---------------------------------------------------------------------------
# Pure deterministic PRNG (Linear Congruential Generator) — no external deps
# ---------------------------------------------------------------------------

class _LCG:
    """Simple deterministic LCG seeded per symbol — stdlib-only."""

    def __init__(self, seed: int) -> None:
        self._state = int(seed) % (2 ** 31)

    def _next(self) -> int:
        self._state = (1_664_525 * self._state + 1_013_904_223) % (2 ** 32)
        return self._state

    def next_float(self) -> float:
        return self._next() / (2 ** 32)

    def next_normal(self) -> float:
        u1 = max(self.next_float(), 1e-12)
        u2 = self.next_float()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _symbol_seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)


# ---------------------------------------------------------------------------
# Candle generation
# ---------------------------------------------------------------------------

def generate_candles(symbol: str, n: int = N_CANDLES) -> list[dict]:
    """Return n deterministic daily OHLCV candle dicts for *symbol*.

    Each call with the same (symbol, n) produces identical output.
    No network, no broker logic.
    """
    rng = _LCG(_symbol_seed(symbol))
    price = _BASE_PRICES[symbol]
    vol = _DAILY_VOL[symbol]
    vol_base = _BASE_VOLUME[symbol]

    today = date.today()
    start = today - timedelta(days=n - 1)

    candles: list[dict] = []
    for i in range(n):
        day = start + timedelta(days=i)
        date_str = day.isoformat()

        daily_ret = rng.next_normal() * vol
        open_p = round(price, 4)
        close_p = round(price * (1.0 + daily_ret), 4)
        intraday = abs(rng.next_normal()) * vol * price * 0.5
        high_p = round(max(open_p, close_p) + intraday, 4)
        low_p = round(min(open_p, close_p) - intraday, 4)
        volume = max(1000, int(vol_base * (0.7 + rng.next_float() * 0.6)))

        candles.append({
            "symbol": symbol,
            "timestamp": f"{date_str}T16:00:00Z",
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": volume,
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": _EXECUTION_GATE,
            "human_review_required": True,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "broker_api_called": False,
            "broker_order_id": "NONE",
        })
        price = close_p

    return candles


# ---------------------------------------------------------------------------
# Event ID (stable, idempotent)
# ---------------------------------------------------------------------------

def _event_id(symbol: str, date_str: str) -> str:
    """Stable event ID for a seeded candle — safe for INSERT OR IGNORE."""
    clean = symbol.replace("-", "_").replace("/", "_").lower()
    return f"seed_ohlcv_{clean}_{date_str}"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def seed_symbol(
    symbol: str,
    write: bool = False,
    db_path: Path | None = None,
) -> int:
    """Generate and optionally persist candles for *symbol*.

    Returns the number of candles inserted (0 on dry-run or duplicate run).
    """
    candles = generate_candles(symbol)

    if not write:
        for c in candles:
            print(json.dumps(c))
        return len(candles)

    try:
        from scripts.persistence import insert_signal_event
    except ModuleNotFoundError:
        from persistence import insert_signal_event  # type: ignore[no-redef]

    kwargs: dict = {} if db_path is None else {"db_path": db_path}
    inserted = 0
    for c in candles:
        date_str = c["timestamp"][:10]
        eid = _event_id(symbol, date_str)
        ok = insert_signal_event(
            event_id=eid,
            source_name="market_data",
            raw_payload=c,
            fetched_at=c["timestamp"],
            **kwargs,
        )
        if ok:
            inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Seed deterministic local OHLCV history for chart structure demo.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write candles to DB (default: dry-run, prints JSON to stdout).",
    )
    args = parser.parse_args(argv)

    total = 0
    for sym in SYMBOLS:
        count = seed_symbol(sym, write=args.write)
        total += count
        if args.write:
            print(f"  {sym}: {count} new candles inserted")

    if args.write:
        print(f"Done. Total inserted: {total} candle events.")
    else:
        print(
            f"[dry-run] {total} candles across {len(SYMBOLS)} symbols."
            "  Use --write to persist.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
