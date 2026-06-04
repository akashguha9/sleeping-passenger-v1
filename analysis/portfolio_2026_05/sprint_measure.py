#!/usr/bin/env python3
"""Measure the hackathon sprint deltas on the 2026 book: v1 vs strategy-v2 vs
discovery-v2 + strategy-v2. Leak-free factors only (liquidity/priceability +
regime; momentum/risk neutral). In-sample evaluation — directional evidence."""
import csv, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
import discovery_v2 as dv

def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
e = _load("engine"); e2 = _load("engine_v2")

COUNTRY = {"NSE":"IN","NASDAQ":"US","NYSE":"US","NYSEARCA":"US","ETR":"DE","EPA":"FR",
           "LON":"GB","TYO":"JP","KRX":"KR","KOSDAQ":"KR","TSE":"CA"}
# Names with no clean, current quote available at entry -> uninvestable for real money.
UNPRICEABLE = {("TYO","291A"),("TYO","5445"),("TYO","6877"),("KRX","003550"),
               ("KRX","079550"),("KRX","454910"),("KRX","078930"),("KRX","003240"),
               ("KRX","009310"),("KRX","016880")}

pos = {(r["exchange"],r["ticker"]):r for r in csv.DictReader(open(os.path.join(HERE,"positions.csv")))}
mkt = {(r["exchange"],r["ticker"]):r for r in csv.DictReader(open(os.path.join(HERE,"market_data.csv")))}

def liq_tier(k):
    return "unpriceable" if k in UNPRICEABLE else mkt[k]["confidence"]

def metrics(keys, exits):
    n=w=0; pl=0.0
    for k in keys:
        p=pos[k]; m=mkt[k]
        E,C,H,L = e.f(p["entry_price"]), e.f(m["current_price"]), e.f(m["period_high"]), e.f(m["period_low"])
        b = e.score(E,C,H,L)[0] if exits=="v1" else e2.score_v2(E,C,H,L)[0]
        n+=1; w+=1 if b>1e-9 else 0; pl+=50*b
    return n, w, pl

allk = list(pos)
kept = [k for k in allk if dv.score_candidate(liquidity_tier=liq_tier(k), region=COUNTRY[k[0]])["tier"] != "SKIP"]
skipped = [k for k in allk if k not in kept]

def line(label, keys, exits):
    n,w,pl = metrics(keys, exits); dep=n*50
    return f"{label:46} n={n:2}  win%={w/n*100:4.1f}  wins={w:2}  net={pl:+6.2f} ({pl/dep*100:+.2f}%)"

if __name__ == "__main__":
    print(line("v1 baseline (all 61, v1 exits)", allk, "v1"))
    print(line("strategy-v2 (all 61, better exits)", allk, "v2"))
    print(line("discovery-v2 + strategy-v2 (priceable only)", kept, "v2"))
    print()
    print(f"discovery dropped {len(skipped)} unpriceable names:")
    print("  " + ", ".join(f"{a}:{b}" for a,b in skipped))
