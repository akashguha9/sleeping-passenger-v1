#!/usr/bin/env python3
"""Strategy v2 — better exit management, measured against v1 on the same book.

v1 (baseline, as the operator ran it):
  TP1 +5% book 50%, TP2 +8% book 30%, 20% runner, fixed entry-5% stop on
  whatever remains; runner marked at today's price.

v2 (this module) keeps entries and TP levels identical and changes ONLY the
management of shares that remain after TP1 — so any delta is pure exit alpha,
not entry cherry-picking (no look-ahead beyond the realized high/low we already
used in v1):

  * Breakeven stop after TP1: once TP1 books 50%, the stop on the remainder
    moves to entry. A booked winner can no longer round-trip into a loss.
  * Trailing runner: the remainder also trails the realized peak, locking in
    TRAIL_KEEP (=0.5) of the peak run. If price gave back past the trail it
    exits at the trail level; otherwise it marks at today's price. Floored at
    breakeven.

Honesty: this is an IN-SAMPLE evaluation of an exit rule on realized paths.
TRAIL_KEEP is a round 0.5 (not tuned per name); sensitivity is reported. It is
evidence the rule has edge here, not a validated forward result.
"""
from __future__ import annotations

import csv
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("engine", os.path.join(HERE, "engine.py"))
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)
f = engine.f

TP1_LVL, TP1_W = 0.05, 0.50
TP2_LVL, TP2_W = 0.08, 0.30
RUNNER_W = 0.20
STOP_LVL = -0.05
TRAIL_KEEP = 0.50  # fraction of the peak run locked in by the trailing stop


def score_v2(entry, current, high, low):
    """Return (ret_fraction, status) for v2 management."""
    tp1 = entry * (1 + TP1_LVL)
    tp2 = entry * (1 + TP2_LVL)
    stop = entry * (1 + STOP_LVL)
    tp1_hit = high is not None and high >= tp1
    tp2_hit = high is not None and high >= tp2
    sl_hit = low is not None and low <= stop
    cur = (current / entry - 1) if current is not None else 0.0

    if not tp1_hit:
        # unchanged from v1: standing -5% stop, else open
        if sl_hit:
            return STOP_LVL, "STOPPED -5% (no TP)"
        return cur, "OPEN (no TP)"

    booked = TP1_W * TP1_LVL
    parts = ["TP1 +5%"]
    remaining_w = TP1_W
    if tp2_hit:
        booked += TP2_W * TP2_LVL
        parts.append("TP2 +8%")
        remaining_w = RUNNER_W

    # v2 runner: trail locks TRAIL_KEEP of the realized peak run; breakeven floor.
    peak_ret = (high / entry - 1) if high is not None else cur
    trail_ret = max(0.0, TRAIL_KEEP * peak_ret)  # >=0 => breakeven floor
    if cur <= trail_ret:
        runner_ret = trail_ret
        parts.append(f"runner {int(remaining_w*100)}% trailed +{trail_ret*100:.1f}%")
    else:
        runner_ret = cur
        parts.append(f"runner {int(remaining_w*100)}% open {cur*100:+.1f}%")

    return booked + remaining_w * runner_ret, " + ".join(parts)


def _load():
    pos = {(r["exchange"], r["ticker"]): r for r in csv.DictReader(open(os.path.join(HERE, "positions.csv")))}
    mkt = {(r["exchange"], r["ticker"]): r for r in csv.DictReader(open(os.path.join(HERE, "market_data.csv")))}
    return pos, mkt


def run(trail_keep=TRAIL_KEEP):
    global TRAIL_KEEP
    TRAIL_KEEP = trail_keep
    pos, mkt = _load()
    v1_pl = v2_pl = 0.0
    v1_w = v2_w = 0
    n = 0
    rows = []
    for k, p in pos.items():
        m = mkt.get(k)
        if not m:
            continue
        E, C, H, L = f(p["entry_price"]), f(m["current_price"]), f(m["period_high"]), f(m["period_low"])
        b1, _o, _s, _a = engine.score(E, C, H, L)
        b2, s2 = score_v2(E, C, H, L)
        v1_pl += 50 * b1
        v2_pl += 50 * b2
        v1_w += 1 if b1 > 1e-9 else 0
        v2_w += 1 if b2 > 1e-9 else 0
        n += 1
        rows.append((f"{k[0]}:{k[1]}", 50 * b1, 50 * b2, s2))
    return {"n": n, "v1_pl": v1_pl, "v2_pl": v2_pl, "v1_w": v1_w, "v2_w": v2_w, "rows": rows}


if __name__ == "__main__":
    r = run()
    dep = r["n"] * 50
    print("Per-position changers (v1 -> v2):")
    for name, pl1, pl2, s2 in sorted(r["rows"], key=lambda x: x[2] - x[1], reverse=True):
        if abs(pl2 - pl1) > 1e-6:
            print(f"  {name:16} {pl1:+6.2f} -> {pl2:+6.2f}  (Δ{pl2-pl1:+5.2f})  {s2}")
    print("-" * 70)
    print(f"n={r['n']}  deployed EUR{dep}")
    print(f"v1  net {r['v1_pl']:+.2f} ({r['v1_pl']/dep*100:+.2f}%)  wins {r['v1_w']}  win% {r['v1_w']/r['n']*100:.1f}")
    print(f"v2  net {r['v2_pl']:+.2f} ({r['v2_pl']/dep*100:+.2f}%)  wins {r['v2_w']}  win% {r['v2_w']/r['n']*100:.1f}")
    print(f"Δ   net {r['v2_pl']-r['v1_pl']:+.2f}  wins {r['v2_w']-r['v1_w']:+d}")
    print()
    print("TRAIL_KEEP sensitivity (net P/L, win%):")
    for tk in (0.3, 0.5, 0.7):
        rr = run(tk)
        print(f"  keep={tk}:  net {rr['v2_pl']:+.2f}  win% {rr['v2_w']/rr['n']*100:.1f}")
