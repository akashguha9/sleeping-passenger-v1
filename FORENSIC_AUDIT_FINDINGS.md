# Forensic Audit — `sleeping-passenger-v1`

**Mode:** AUDIT ONLY. No code changed. Findings below; awaiting approval before any fix.
**Date:** 2026-06-03 · **Branch:** `claude/great-ramanujan-CI8G3`

All in-sample numbers are **directional only** (n tiny, one ~3-week regime). Nothing here was tuned against the 37-trade sample.

---

## 0. Headline

The single most important finding: **the only backtest path that runs inside this repo fabricates its edge.** The real OHLCV dataset (`data/processed/output_timeseries_dataset.csv`) is **absent** (`data/processed/` contains only `.gitkeep`). The one executable path — `backtest_signals.milk_test()` — generates random forward returns and then **injects a +1.2% edge by hand** into the "good" rows:

```python
# scripts/backtest_signals.py:177-188
"future_return_5d":  np.random.randn(n) * 0.02,
...
df.loc[good, "future_return_5d"] += 0.012   # <-- planted edge
```

`+= 0.012` ≈ the "+1.23%/trade gross edge" cited as the headline result. **The repo cannot reproduce the 37-trade backtest at all** — the data it needs isn't here, and the in-repo fallback is synthetic-with-planted-alpha. Every downstream conclusion ("gross +1.23%", "winners", hit-rates) is unverifiable from this tree.

Two structural truths follow:
1. **The described entry gate (above-SMA200 + rising-SMA50 + RS>0 + not-extended) does not exist in this codebase.** The real gate is a band/vol/trend filter over three symbols. The 37-trade gate must live in an external harness or an earlier revision.
2. **The "stock picker" trades an ETF, an index, and an ETF** — `CHAMPION_SYMBOLS = {"GLD", "^GDAXI", "USO"}` (`scripts/config.py:34`). GLD = gold ETF, USO = oil ETF, ^GDAXI = the DAX index (not even tradeable). None is a single stock.

---

## 1. Ranked Findings

### CRITICAL

**C1 — Backtest edge is synthetic / unreproducible.**
`scripts/backtest_signals.py:160-188`, `scripts/signal_engine.py:176-189`, `data/processed/` (empty).
The real dataset is missing; the only runnable path (`milk_test`) builds random `future_return_*d` and adds `+0.012` to the qualifying rows. The headline "+1.23% gross" matches the planted constant. *Why it matters:* there is no in-repo evidence any edge exists; the number quoted as a result is an artifact of the self-test. *Confidence: High* (code read + empty data dir).

**C2 — Backtest models forward-return-at-fixed-horizon, NOT the actual exit plan.**
`scripts/backtest_signals.py:88-125`. The engine takes `future_return_{h}d` and subtracts one flat cost. It **never simulates TP1 +5%/TP2 +8%/20% runner/−5% stop**. *Why it matters:* the strategy that is "evaluated" is not the strategy that is run. Path-dependent outcomes (which fills hit, in what order, gaps through the stop) are entirely absent, so reported hit-rates describe a different system than the advisory plan. *Confidence: High.*

**C3 — Cost model is single-deduction; the booking plan is multi-fill.**
`scripts/backtest_signals.py:60,99` (`cost = COST_PER_TRADE_BPS/1e4`; `net = sub - cost`), `scripts/config.py:43` (`COST_PER_TRADE_BPS = 20`).
A TP1/TP2/runner trade fires **3–4 commissioned exits**, each likely hitting a commission minimum on a €50 notional, plus FX both legs, plus spread. The backtest charges ~20 bps **once**. *Why it matters:* this is the Monte-Carlo killer — at €50/position, 3–4 fills × a per-order minimum can dwarf the (claimed) €0.62 gross. Realistic net expectancy is plausibly ≤ 0. *Confidence: High.*

**C4 — Money-preflight backlog gate does not fire (fails OPEN).**
`scripts/pre_real_money_preflight.py:164-180,310`; tests `tests/test_pre_real_money_preflight.py:139-183`.
Confirmed by running: 4 failures, all `assert ... is False` getting `True`. With an unreconciled backlog at/above BLOCK (25) and FULL_REVIEW (50) thresholds, `run_preflight` still returns `ok=True`. The `reconciliation_queue` subcheck's `unreconciled_count` does not reflect the rows the test inserts into `manual_trades`, so no blocking issue is appended. *Why it matters:* this is a **real-money go/no-go safety gate failing in the dangerous direction** — it would clear deployment while reconciliation is broken. **Per guardrail #2 the fix is to make the gate actually block, never to relax the test.** *Confidence: High* (reproduced).

**C5 — Split/dividend adjustment is a frozen snapshot; explains the ~5× glitch.**
`scripts/backfill_ohlcv_history.py:70-135` (`yf.Ticker(symbol).history(...)` with no explicit `auto_adjust`, stored verbatim, never re-adjusted).
yfinance returns prices adjusted **as of fetch time**. A corporate action (e.g., 5:1 split) **after** backfill is never propagated to stored candles, so a stored entry/buy price sits ~5× above later (re-adjusted) market data — exactly the reported "name showing ~5× its buy price." There is no adjustment-version tag and no `adj_close`/`close_unadj` split, so feature space (adjusted vs nominal) is ambiguous across the table. *Why it matters:* corrupts entry levels, stops, TP triggers, and any % return for any name that had a corporate action. *Confidence: High* for the mechanism; *Medium* on which exact symbol.
> Note: the sub-agent's specific claim that "Close is adjusted but OHL are not" is **not** how modern yfinance behaves (`auto_adjust=True` adjusts all four). The real defect is the missing re-adjustment over time + untagged price space, not intra-row inconsistency.

### HIGH

**H1 — No FX cost, and cross-currency returns risk being compared raw.**
No `convert_to_base_currency` exists (searched `scripts/supported_currencies.py`, ranking, P/L). Currencies (INR/JPY/KRW/EUR/GBP/USD) are stored as metadata only (`scripts/signal_inbox_api.py:226-229`). A €-investor pays FX round-trip on every non-EUR name (≈40 bps developed, 50–100 bps EM) on **both** entry and exit — unmodeled. *Why it matters:* compounds C3; also any place a local-% return is treated as a base-currency return mis-ranks names. *Confidence: Medium-High.*

**H2 — No `.shift(1)` on features → likely same-bar leakage in the real builder.**
`scripts/build_dataset.py:253-257` computes `pct_change`, rolling vol/trend/momentum **including bar t** with no backward shift. If the absent labeler defines `future_return_5d` as `[t … t+5]` (overlapping bar t), entry features and the outcome window share the signal bar. *Why it matters:* this is the classic mechanism that manufactures fake winners. *Confidence: High the shift is absent; Medium on net leakage* because the label code itself is out-of-tree (see "Could not verify").

**H3 — Timezone collapse: every bar stamped `T16:00:00Z`.**
`scripts/backfill_ohlcv_history.py:139` hardcodes `date + "T16:00:00Z"` for all venues. NSE/TSE/KRX/LSE close hours before 16:00 UTC; US closes after. *Why it matters:* same-calendar-date rows mix an Asian session that already closed with a US session that hasn't — phantom lead/lag and the RS-vs-index alignment (US benchmark close vs same-date Asia signal) becomes lookahead. *Confidence: Medium-High.*

**H4 — Per-market costs/taxes ignored.**
`scripts/config.py:43` flat 20 bps for all venues; `configs/global_securities_master.yaml` has **no** commission/fee/tax table. India STT (~10 bps on sells), KR/JP brokerage, UK stamp duty, FX — none modeled. *Why it matters:* understates cost most in exactly the EM names the universe leans on. *Confidence: Medium-High.*

### MEDIUM

**M1 — `dropna()` selection bias toward clean-history names.**
`scripts/signal_engine.py:246` (`sub = champ[fwd].dropna()`), `scripts/data_void_engine.py:156`. Names with gappy histories (EM) get silently dropped from stats, tilting selection toward developed markets on data completeness rather than edge. *Confidence: Medium.*

**M2 — No liquidity (ADV) floor enforced.**
`scripts/fresh_market_discovery.py` (CQS includes a soft `liquidity_quality` 0.10 weight, no hard cutoff), `scripts/asset_durability_filter.py:~119` (liquidity contributes to score, no exclusion). A thin micro-cap scoring high on narrative can promote to the Buy board. *Why it matters:* compounds slippage on top of C3. *Confidence: Medium-High.*

**M3 — Survivorship: static hardcoded universes, no point-in-time membership.**
`scripts/config.py:34` (3 symbols), `scripts/minimum_daily_universe.py` (~60 tickers = names that exist today). No delisted/halted/renamed handling, no point-in-time index membership. *Confidence: High the universe is static; Medium on materiality given the tiny symbol set.*

**M4 — Exit engine books a single REDUCE at one `take_profit`.**
`scripts/action_engine.py:190-227`: `_price_reached_target` → one `REDUCE`; `_price_breached_stop` → `EXIT_NOW`. There is **no TP1/TP2 ladder, no 20% runner, no trailing logic.** The booking plan in the spec is not implemented end-to-end. *Why it matters:* the live advisory path and the backtest both diverge from the stated plan, in different ways. *Confidence: High.*

### LOW

**L1 — Diversity is neither tiebreaker nor quota — it's absent.**
`scripts/fresh_market_discovery.py:206` ranks `(-cqs, ticker)` only. The good news: **no country quota injects names** (guardrail-compliant). The gap: no diversity tiebreaker either, so picks can fully concentrate. *Confidence: High.*
**L2 — Dead `simulated_friction` parameter.** `src/paper/paper_trade_engine.py:53-66` accepts friction but every caller passes 0.0. *Confidence: Medium.*

---

## 2. Fake-Edge Risk

| Reported result | Most likely artifact of | Survives fixes? |
|---|---|---|
| "+1.23% gross/trade" | **Planted synthetic constant** (`+=0.012`) and/or cost-blindness | Unknown — not reproducible in-repo (C1) |
| "Winners through the gate" | Fixed-horizon return ≠ TP/stop path (C2); same-bar leakage if labeler overlaps (H2) | Many likely vanish once C2+C3 applied |
| Any per-name % return | Split-snapshot corruption (C5), no FX normalization (H1) | Names with corporate actions / non-EUR ccy unreliable |
| Hit-rate / Sharpe | Single-regime, n≈37, gross-of-realistic-cost | Directional only; not decision-grade |

**Bottom line:** before any fix, treat **all** current performance numbers as non-evidence. The edge claim rests on a planted constant (C1) and a strategy mismatch (C2), wrapped in an unrealistic cost model (C3).

---

## 3. Country Coverage (tradeable single-stock vs ETF-only vs none)

Sources: `configs/global_securities_master.yaml`, `configs/jurisdictions.yaml`, `scripts/minimum_daily_universe.py`.

| # | Country | Single stock? | ETF proxy | Status |
|--|--|--|--|--|
|1|United States|✅ (AAPL, MSFT, NVDA, XOM…)|SPY/QQQ/GLD|**FULL**|
|2|China|✅ (600519.SS, 000858.SZ)|FXI|**FULL**|
|3|Germany|✅ (SAP.DE, VOW3.DE)|—|**FULL**|
|4|Japan|✅ (7203.T, 6758.T)|EWJ|**FULL**|
|5|United Kingdom|✅ (SHEL.L, HSBA.L)|—|**FULL**|
|6|India|✅ (RELIANCE.NS, INFY.NS, TCS.NS…)|INDA|**FULL**|
|7|France|✅ (MC.PA)|—|**FULL**|
|8|Italy|❌|❌|**MISSING**|
|9|Russia|⛔ sanctioned (MOEX listed, no securities seeded)|⛔|**BLOCKED — untradeable**|
|10|Brazil|✅ (PETR4.SA, VALE3.SA)|EWZ|**FULL**|
|11|Canada|✅ (RY.TO, SHOP.TO)|—|**FULL**|
|12|Australia|✅ (BHP.AX, CBA.AX)|EWA|**FULL**|
|13|Mexico|✅ (AMXL.MX)|EWW|**FULL**|
|14|Spain|❌|❌|**MISSING**|
|15|South Korea|✅ (005930.KS)|EWY|**FULL**|
|16|Turkey|⚠️ IST exchange listed, no stock seeded|❌|**INCOMPLETE**|
|17|Indonesia|✅ (BBCA.JK)|—|**PARTIAL**|
|18|Netherlands|✅ (ASML.AS)|—|**FULL**|
|19|Saudi Arabia|✅ (2222.SR)|—|**PARTIAL** (access limits)|
|20|Switzerland|✅ (NESN.SW, ROG.SW)|—|**FULL**|
|21|Poland|⚠️ WSE listed, no stock seeded|❌|**MISSING**|
|22|Taiwan|✅ (2330.TW; ADR TSM)|EWT|**FULL**|
|23|Ireland|❌|❌|**MISSING**|
|24|Belgium|❌|❌|**MISSING**|
|25|Sweden|❌|❌|**MISSING**|
|26|Israel|❌|❌|**MISSING**|
|27|Argentina|⚠️ MERVAL listed, no stock seeded|EWW (indirect)|**PARTIAL**|
|28|Singapore|✅ (D05.SI)|EWS|**FULL**|
|29|Austria|❌|❌|**MISSING**|
|30|UAE|⚠️ DFM listed, no stock seeded|❌|**PARTIAL**|

**Tally:** Direct single-name ≈18/30 · ETF-only/partial/exchange-without-seed ≈11/30 · Sanctioned/untradeable 1/30 (Russia).
**Flags:** Missing entirely — Italy, Spain, Ireland, Belgium, Sweden, Israel, Austria. ETF/exchange-listed-without-a-real-name (label honestly, not a stock pick) — Russia, Turkey, Poland, Argentina, UAE. Note the *executing* universe (`CHAMPION_SYMBOLS`) is just GLD/USO/^GDAXI — two ETFs and an index — so practical single-stock coverage today is **zero**.

---

## 4. Prioritized Fix Plan (principle-justified, cheapest-and-riskiest first — NO curve-fitting)

1. **Make the backtest evaluate the real strategy (C2).** Replace fixed-horizon `future_return_Nd` with an event-driven simulator that walks bars and books TP1/TP2/runner/stop with gap handling (open-through-stop fills at open, not trigger). *Principle: correctness.* Until this exists, no performance number is meaningful.
2. **Realistic, per-fill, per-market cost+FX model (C3, H1, H4).** Charge each booked leg a commission + minimum, spread, slippage, and FX round-trip from a per-venue table. Then recompute net expectancy at €50, **per market**, and flag markets where round-trip cost > gross edge. *Principle: cost realism.*
3. **Fix the money-preflight backlog gate to actually block (C4).** Root-cause the `manual_trades` → `reconciliation_queue.build_queue` count mismatch so `unreconciled_count` reflects reality; the gate must fail-closed. **Do not relax the failing tests.** *Principle: safety invariant.*
4. **Fix the adjustment path (C5).** Store both adjusted and unadjusted closes with an adjustment-version stamp; re-adjust (or invalidate) stored history on corporate actions; assert entry/stop/TP and current price share one price space. *Principle: data correctness.*
5. **Eliminate same-bar leakage (H2) + timezone collapse (H3).** Shift all entry features to ≤ prior close; stamp bars at each venue's real session close in UTC; align the RS benchmark point-in-time per venue. *Principle: point-in-time.*
6. **Add a hard per-market ADV floor (M2)** and replace silent `dropna()` with explicit, logged handling (M1). *Principle: liquidity / no silent bias.*
7. **Universe honesty (M3, coverage):** point-in-time membership + delisted/halted flags; swap ETFs/indices for real single names or label them explicitly; fill the 7 missing countries with real listings (don't quota-inject — diversity stays a tiebreaker only). *Principle: survivorship / honest labeling.*
8. **Forward, out-of-sample harness (deliverable F):** shadow-log daily picks, each gate's *would-block* decision, and realized net-of-cost outcomes; accumulate **≥100 trades across ≥1 non-trending regime** before judging any rule. *Principle: no in-sample optimization.*

All proposed parameters above are justified by leakage/cost/liquidity/correctness — none by "raises the backtest number."

---

## 5. Could Not Verify (need data/access)

- **The real 37-trade backtest.** `data/processed/output_timeseries_dataset.csv` / `final_dataset.csv` are absent. Need: the actual dataset **and** the labeler that builds `future_return_*d` to confirm/deny feature↔outcome window overlap (H2).
- **The described SMA200/SMA50/RS/52w gate.** Not present in this tree. Need: the external/older harness that produced the 37 trades, to audit the gate that "blocked the winners."
- **Which exact symbol shows ~5×.** Mechanism confirmed (C5); the specific name needs the populated OHLCV store + a corporate-action log.
- **Live RS benchmark series provenance/timezone.** RS-vs-index is referenced but not implemented in-tree.
- **Real per-broker commission schedules & FX spreads** to parameterize the cost model (C3/H4) — currently no config exists.
