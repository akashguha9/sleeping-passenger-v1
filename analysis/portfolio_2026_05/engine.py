#!/usr/bin/env python3
"""TP1/TP2/runner/stop portfolio simulator for the 2026-05/06 paper book.

Strategy (per user spec)
------------------------
- Equal EUR 50 deployed per position at the entry price.
- TP1 = entry * 1.05  -> book 50% of the original position.
- TP2 = entry * 1.08  -> book 30% of the original position.
- Runner = remaining 20% -> let it run (marked at today's price).
- Stop  = entry * 0.95  -> standing stop on whatever shares remain.
  The stop is NOT moved to breakeven; it stays at entry-5% the whole time.

Data reality / assumptions
--------------------------
True intraday (1-min) tick order is NOT obtainable for 61 global tickers in
this sandbox, so each position is scored from three numbers gathered per
ticker: today's price (C), the highest price since entry (H) and the lowest
price since entry (L).

Because we only have the extremes (not their time order) the simulator
reports TWO valuations whenever the path is ambiguous:

  * base       - "stops are real": if L <= stop at any time, the still-running
                 shares are treated as stopped at -5%. Conservative.
  * optimistic - the runner only counts as stopped if it is still below the
                 stop TODAY (C <= stop); otherwise it is marked at C.

A position is flagged ORDER-AMBIGUOUS when a take-profit AND the stop were
both touched in the window (the two valuations can disagree there).

FX between entry and today is ignored: P/L is local-return * EUR 50.
"""
from __future__ import annotations

import csv
import os
import sys

EUR_PER_POSITION = 50.0
TP1_LVL, TP1_W = 0.05, 0.50
TP2_LVL, TP2_W = 0.08, 0.30
RUNNER_W = 0.20
STOP_LVL = -0.05

HERE = os.path.dirname(os.path.abspath(__file__))


def f(x):
    if x is None or str(x).strip() in ("", "NA", "na", "?"):
        return None
    return float(str(x).replace(",", "").strip())


def score(entry, current, high, low):
    """Return (base_ret, opt_ret, status, ambiguous) as fractions of position."""
    tp1 = entry * (1 + TP1_LVL)
    tp2 = entry * (1 + TP2_LVL)
    stop = entry * (1 + STOP_LVL)

    tp1_hit = high is not None and high >= tp1
    tp2_hit = high is not None and high >= tp2
    sl_hit = low is not None and low <= stop
    cur_ret = (current / entry - 1) if current is not None else 0.0

    ambiguous = bool((tp1_hit or tp2_hit) and sl_hit)

    # --- no take-profit reached ---------------------------------------
    if not tp1_hit:
        if sl_hit:
            return STOP_LVL, STOP_LVL, "STOPPED -5% (no TP)", False
        return cur_ret, cur_ret, "OPEN (no TP, no stop)", False

    # --- TP1 booked (50% at +5%) --------------------------------------
    booked = TP1_W * TP1_LVL
    parts = ["TP1 +5% (50%)"]
    remaining_w = TP1_W  # 50% still on the table after TP1

    if tp2_hit:
        booked += TP2_W * TP2_LVL
        parts.append("TP2 +8% (30%)")
        remaining_w = RUNNER_W  # only the 20% runner left

    # value of the still-running shares
    if sl_hit:
        base_runner = STOP_LVL                       # stops are real
        opt_runner = STOP_LVL if (current is not None and current <= stop) else cur_ret
        parts_base = parts + [f"runner {int(remaining_w*100)}% stopped -5%"]
        parts_opt = parts + [
            f"runner {int(remaining_w*100)}% " +
            ("stopped -5%" if (current is not None and current <= stop) else f"open {cur_ret*100:+.1f}%")
        ]
    else:
        base_runner = opt_runner = cur_ret
        parts_base = parts_opt = parts + [f"runner {int(remaining_w*100)}% open {cur_ret*100:+.1f}%"]

    base = booked + remaining_w * base_runner
    opt = booked + remaining_w * opt_runner
    status = " + ".join(parts_base) if not ambiguous else " + ".join(parts_base) + "  [order?]"
    return base, opt, status, ambiguous


def main():
    pos = {}
    with open(os.path.join(HERE, "positions.csv")) as fh:
        for r in csv.DictReader(fh):
            pos[(r["exchange"], r["ticker"])] = r

    mkt = {}
    mpath = os.path.join(HERE, "market_data.csv")
    if os.path.exists(mpath):
        with open(mpath) as fh:
            for r in csv.DictReader(fh):
                mkt[(r["exchange"], r["ticker"])] = r

    rows = []
    tot_base = tot_opt = deployed = 0.0
    wins = losses = flat = scored = missing = 0

    for key, p in pos.items():
        entry = f(p["entry_price"])
        deployed += EUR_PER_POSITION
        m = mkt.get(key)
        if not m or f(m.get("current_price")) is None:
            rows.append((p, None, None, None, None, "NO DATA", None, m.get("confidence") if m else ""))
            missing += 1
            continue
        cur, hi, lo = f(m["current_price"]), f(m.get("period_high")), f(m.get("period_low"))
        base, opt, status, amb = score(entry, cur, hi, lo)
        pl_base = EUR_PER_POSITION * base
        pl_opt = EUR_PER_POSITION * opt
        tot_base += pl_base
        tot_opt += pl_opt
        scored += 1
        if base > 1e-9:
            wins += 1
        elif base < -1e-9:
            losses += 1
        else:
            flat += 1
        rows.append((p, cur, hi, lo, base, status, pl_base, m.get("confidence", "")))

    # ---- print per-position table ------------------------------------
    print(f"{'DATE':10} {'TICKER':16} {'ENTRY':>10} {'NOW':>10} {'RET%':>7} {'P/L€':>7}  STATUS")
    print("-" * 120)
    for (p, cur, hi, lo, base, status, pl, conf) in rows:
        tk = f"{p['exchange']}:{p['ticker']}"
        if cur is None:
            print(f"{p['buy_date']:10} {tk:16} {f(p['entry_price']):>10.2f} {'--':>10} {'--':>7} {'--':>7}  {status} {conf}")
        else:
            print(f"{p['buy_date']:10} {tk:16} {f(p['entry_price']):>10.2f} {cur:>10.2f} {base*100:>6.1f}% {pl:>6.1f}  {status}  ({conf})")

    print("-" * 120)
    n = len(pos)
    win_rate = (wins / scored * 100) if scored else 0
    print(f"\nPositions: {n}   scored: {scored}   missing data: {missing}")
    print(f"Capital deployed (scored only): EUR {scored*EUR_PER_POSITION:,.0f}   (full book EUR {deployed:,.0f})")
    print(f"Wins: {wins}   Losses: {losses}   Flat: {flat}   Win rate: {win_rate:.1f}% (of scored)")
    print(f"\nNET P/L  base (stops real):   EUR {tot_base:+,.2f}   = {tot_base/(scored*EUR_PER_POSITION)*100:+.2f}% on deployed")
    print(f"NET P/L  optimistic (runner):  EUR {tot_opt:+,.2f}   = {tot_opt/(scored*EUR_PER_POSITION)*100:+.2f}% on deployed")


if __name__ == "__main__":
    main()
