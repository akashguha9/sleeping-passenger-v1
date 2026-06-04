# Hackathon sprint — scorecard & deltas

One sprint to close the gaps/leakages/blockages from the audit, plus exit-alpha
and discovery discipline. Honesty preserved throughout: advisory-only, no
execution, nothing fabricated. Where a number can't honestly move, it doesn't —
and that's called out.

## A. Gaps / leakages / blockages — status

| # | Issue (from audit) | Before | After |
|---|---|---|---|
| 9 | Preflight reconciliation subcheck silently broken (f-string SyntaxError on Py3.11) → backlog blocker never fired | **BROKEN** (4 tests red) | **FIXED** — subcheck imports & blocks; 12/12 preflight tests green |
| 8 | `test_confidence` assumed pass when no result supplied | Assumed `T=1.0` | **Reads recorded status**; unknown→0.7+warning, red→0.0+blocker |
| 6 | Runtime state ephemeral; lost on container recycle | No rebuild | **`bootstrap_runtime.py` + SessionStart hook** self-heal every session |
| 5 | "Canonical" SQLite store empty; truth lived in JSON | `manual_trades=0` | **Holdings ingested → `manual_trades=10`**; securities=60; outcomes=61 |
| 7 | `*.csv` blanket ignore silently dropped evidence | Dropped | **Carve-out** `!analysis/**/*.csv`; evidence tracked |
| — | Persistence dimension under-wired (prior turn) | `P=0.50` | `P=1.00` (truth model exposed to the gate) |
| — | Securities coverage (prior turn) | `J=0.00` | `J=1.00` (60/60) |

## B. Readiness — segmented dimensions

| Dim | Before sprint | After sprint | Note |
|---|---|---|---|
| A advisory invariant | 1.00 | 1.00 | |
| E no-execution surface | 1.00 | 1.00 | |
| P persistence | 1.00 | 1.00 | now also *backed* by a populated canonical store |
| L leverage governance | 1.00 | 1.00 | |
| J securities coverage | 1.00 | 1.00 | |
| **C calibration** | **0.00** | **0.00** | sole remaining cap — needs scored outcomes |
| T test confidence | 1.00 *(assumed)* | **1.00 (verified)** | now read from a real run, not assumed |
| B backup | 1.00 | 1.00 | |
| U ui clarity | 1.00 | 1.00 | |

**Gated score: 6.5 → 6.5 (unchanged), raw 8.5, mode `TINY_MANUAL_PROBE_ONLY`.**
This is the honest headline: the *score* can't rise because calibration (`C=0`)
binds, and only real scored outcomes lift it. **What changed is the integrity of
that 6.5** — three previously fake-green or broken items (reconciliation, test
confidence, durable/canonical state) are now genuinely green. The number is the
same; it is now *trustworthy*, and the latent blockers that would have bitten the
moment calibration unlocked are gone.

## C. Book performance — strategy & discovery deltas (in-sample)

| Variant | n | win % | net P/L | on deployed |
|---|---|---|---|---|
| v1 baseline | 61 | 39.3% | +€14.74 | +0.48% |
| **+ strategy v2** (breakeven-after-TP1 + trailing runner) | 61 | 39.3% | **+€18.53** | **+0.61%** |
| **+ discovery v2** (drop 10 unpriceable names) | 51 | **45.1%** | +€15.48 | +0.61% |

- **Win rate +5.8pp (39.3%→45.1%)** by refusing to trade names with no clean,
  current quote (10 thin Tokyo/Korea tickers). Leak-free discipline, not curve-fit.
- **Exit alpha +26%** on realized P/L (e.g. AVGO ran +16% then gave it back —
  the trailing runner books +8% instead of −1.7%; INFY/RHM similar).
- **Honest limits:** absolute winner *count* is 24→23 — discovery raises win
  *rate* and capital efficiency by trading fewer/better names, not raw count.
  More absolute winners requires a larger *validated* universe + forward
  (out-of-sample) discovery testing. `TRAIL_KEEP=0.5` is untuned; sensitivity
  (0.3/0.5/0.7 → +17.6/+18.5/+19.7) is reported in `engine_v2.py`.

## D. New capabilities shipped
- `scripts/bootstrap_runtime.py` — idempotent durable-state rebuild (+ hook).
- `scripts/discovery_v2.py` — transparent multi-factor candidate scorer with a
  hard priceability gate (+ `tests/test_discovery_v2.py`).
- `analysis/.../engine_v2.py` — improved exit management with measured deltas.
- Readiness gate hardened to **fail closed** (unknown ≠ pass).

## E. The one lever left
Calibration. It needs `score_at_entry` on resolved outcomes (paper → ~7.0 SMALL
ceiling; ≥50 real → 8.0). Everything else is now green and durable. Capturing the
engine's score at entry on new signals is the single highest-leverage next step.
