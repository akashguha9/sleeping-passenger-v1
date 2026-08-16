"""Quant hackathon — returns / abnormal returns / horizon ladder.

Mathematical contract
---------------------
Inputs: daily close series per symbol as ``{date_iso: close}`` built from
canonical ``signal_events`` market_data rows (bar timestamp = bar date;
``fetched_at`` = availability time — the no-lookahead boundary).

Formulas:
    R_{i,t→t+h}   = ln(S_{i,t+h} / S_{i,t})            (log return, DERIVED)
    AR_{i,t→t+h}  = R_{i,t→t+h} − R_{m,t→t+h}          (market-adjusted, DERIVED)
    CAR_{i,[t,t+h]} = Σ_τ AR_{i,τ}                      (DERIVED)

Null semantics: a missing bar within the tolerance window ⇒ the return is
``None`` (UNKNOWN), never 0.  Horizons are TRADING-day offsets over the
symbol's own bar calendar (only daily bars exist in this repo — intraday
horizons are honestly unsupported, not simulated).

Leakage rule: forward returns computed at t use only bars with
bar_date > t; the caller must never feed a signal whose availability
timestamp exceeds t (see quant_walk_forward_split for the enforcement
helper).  Advisory-only; no execution.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

EPS = 1e-9
OK = "OK"
UNKNOWN = "UNKNOWN"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Supported horizons in TRADING days (daily bars only — documented).
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)


def load_close_series(db_path: Path, *, min_days: int = 20,
                      ) -> dict[str, dict[str, float]]:
    """Extract per-symbol daily close series from canonical signal_events.

    Uses the LAST observation per (symbol, bar_date).  Symbols with fewer
    than ``min_days`` bars are dropped (reported by caller via keys diff).
    Read-only.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT raw_payload FROM signal_events "
            "WHERE source_name='market_data'").fetchall()
    finally:
        conn.close()
    series: dict[str, dict[str, float]] = {}
    for (rp,) in rows:
        try:
            d = json.loads(rp)
        except ValueError:
            continue
        sym = d.get("symbol")
        close = d.get("close")
        ts = str(d.get("timestamp") or "")[:10]
        if not sym or not isinstance(close, (int, float)) or close <= 0 or not ts:
            continue
        series.setdefault(sym, {})[ts] = float(close)
    return {s: bars for s, bars in series.items() if len(bars) >= min_days}


def log_return(series: dict[str, float], start: str, end: str,
               ) -> float | None:
    """ln(S_end / S_start); None (UNKNOWN) when either bar is missing."""
    a, b = series.get(start), series.get(end)
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return math.log(b / a)


def forward_return(series: dict[str, float], t: str, h: int,
                   ) -> dict[str, Any]:
    """Forward log return over h TRADING days on the symbol's own calendar.

    t must be an existing bar date; the h-th following bar is the exit.
    Missing entry/exit bar ⇒ UNKNOWN, never zero.
    """
    days = sorted(series)
    if t not in series:
        return {"status": UNKNOWN, "reason": f"no bar at {t}"}
    i = days.index(t)
    if i + h >= len(days):
        return {"status": UNKNOWN, "reason": "horizon beyond data end"}
    exit_day = days[i + h]
    r = log_return(series, t, exit_day)
    if r is None:
        return {"status": UNKNOWN, "reason": "missing bar"}
    return {"status": OK, "r": r, "entry_day": t, "exit_day": exit_day,
            "h_trading_days": h}


def abnormal_return(series_i: dict[str, float],
                    series_m: dict[str, float],
                    t: str, h: int) -> dict[str, Any]:
    """AR = R_i − R_m over the same [t, t+h] window (market-adjusted).

    The benchmark window is aligned on CALENDAR dates: the benchmark
    return spans the security's entry/exit dates; if the benchmark lacks
    either bar the result is UNKNOWN (never silently raw return).
    """
    fwd = forward_return(series_i, t, h)
    if fwd["status"] != OK:
        return {"status": UNKNOWN, "reason": fwd.get("reason")}
    rm = log_return(series_m, fwd["entry_day"], fwd["exit_day"])
    if rm is None:
        return {"status": UNKNOWN, "reason": "benchmark bar missing"}
    return {"status": OK, "ar": fwd["r"] - rm, "r_raw": fwd["r"],
            "r_benchmark": rm, "entry_day": fwd["entry_day"],
            "exit_day": fwd["exit_day"], "h_trading_days": h,
            "adjustment": "MARKET_ADJUSTED", "epistemic_status": "DERIVED"}


def car(series_i: dict[str, float], series_m: dict[str, float],
        t: str, h: int) -> dict[str, Any]:
    """Cumulative abnormal return: Σ of per-bar ARs from t to t+h.

    With log returns, summing per-bar ARs equals the window AR when all
    bars exist; per-bar decomposition is kept for event-study CAAR curves.
    """
    days = sorted(series_i)
    if t not in series_i:
        return {"status": UNKNOWN, "reason": f"no bar at {t}"}
    i = days.index(t)
    if i + h >= len(days):
        return {"status": UNKNOWN, "reason": "horizon beyond data end"}
    path = []
    total = 0.0
    for step in range(1, h + 1):
        a, b = days[i + step - 1], days[i + step]
        ri = log_return(series_i, a, b)
        rm = log_return(series_m, a, b)
        if ri is None or rm is None:
            return {"status": UNKNOWN, "reason": f"missing bar {a}->{b}"}
        total += ri - rm
        path.append({"day": b, "ar": ri - rm, "car": total})
    return {"status": OK, "car": total, "path": path,
            "h_trading_days": h, "epistemic_status": "DERIVED"}


def daily_volatility(series: dict[str, float], *, n_min: int = 10,
                     ) -> dict[str, Any]:
    """Realized daily log-return volatility (for PEG^Z normalization)."""
    days = sorted(series)
    rets = []
    for a, b in zip(days, days[1:]):
        r = log_return(series, a, b)
        if r is not None:
            rets.append(r)
    if len(rets) < n_min:
        return {"status": INSUFFICIENT_DATA, "n": len(rets), "n_min": n_min}
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return {"status": OK, "n": len(rets), "sigma_daily": math.sqrt(var)}
