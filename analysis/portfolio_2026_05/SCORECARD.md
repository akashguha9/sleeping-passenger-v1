# MVP upgrade + segmented scorecard

Evidence trail: the 61-position 2026-05/06 paper book (imported as PAPER journal
evidence). This documents the legitimate MVP improvements made from that trail and
the resulting segmented scores. No scores, returns, or provenance were fabricated;
advisory invariants (no execution, broker_api_called=False, gate LOCKED) hold
throughout.

## 1. What was upgraded (and what could not be)

| Dimension | Before | After | How |
|---|---|---|---|
| **Securities coverage (J)** | 0.00 (CRITICAL, 0/40) | **1.00 (COMPLETE_ENOUGH, 60/60)** | Completed `configs/securities_seed_universe.yaml` with the 20 missing tracked names from the book; ran the sanctioned master seed |
| **Persistence (P)** | 0.50 | **1.00** | Wiring fix: exposed the documented `sqlite_is_canonical=True / jsonl_is_canonical=False` invariant as module attributes the readiness gate actually reads |
| **Calibration (C)** | 0.00 | 0.00 (unchanged) | **Cannot** improve honestly — needs `score_at_entry` per outcome; book has none and operator chose journal-only |

## 2. Segmented readiness dimensions (after)

| Seg | Score | Weight | Dimension |
|---|---|---|---|
| A | 1.00 | 0.15 | advisory invariant |
| E | 1.00 | 0.15 | no execution surface |
| P | **1.00** | 0.10 | persistence (was 0.50) |
| L | 1.00 | 0.10 | leverage governance |
| J | **1.00** | 0.10 | securities/jurisdiction coverage (was 0.00) |
| C | **0.00** | 0.15 | **calibration — sole remaining gap** |
| F | 1.00 | 0.10 | feedback loop |
| T | 1.00 | 0.10 | test confidence |
| B | 1.00 | 0.03 | backup |
| U | 1.00 | 0.02 | ui clarity |

- **Raw readiness: 7.0 → 8.5** (clamped to the 8.0 MVP ceiling; every dimension maxed but C).
- **Gated score: 6.5 / 8.0, mode `TINY_MANUAL_PROBE_ONLY` — unchanged**, because the
  `C=0` calibration cap (6.5) binds. Warnings dropped from 2 to **1** (`scores_uncalibrated`);
  `securities_coverage_weak` cleared.
- **The MVP is now green on every dimension except calibration.** That single lever
  needs scored, resolved outcomes (paper → ~7.0 SMALL ceiling; ≥50 REAL outcomes → 8.0).

## 3. Securities coverage (segmented)
`C=1.00` resolvable · `M=1.00` completeness · `J=1.00` jurisdiction-resolvable →
`S=1.000 COMPLETE_ENOUGH`, 60/60, 0 gaps. Durable via the committed seed YAML;
reproduce the master with `python scripts/securities_master_coverage.py --seed`.

## 4. Paper-book performance (segmented scores)

### By region
| Region | n | dep € | P/L € | P/L % | win % | TP | SL |
|---|---|---|---|---|---|---|---|
| Europe (DE/FR) | 6 | 300 | +5.50 | **+1.83%** | 67% | 2 | 0 |
| US | 29 | 1450 | +12.93 | +0.89% | 52% | 9 | 4 |
| Korea | 11 | 550 | +4.76 | +0.87% | 27% | 2 | 0 |
| Canada | 1 | 50 | +0.27 | +0.55% | 100% | 0 | 0 |
| Japan | 7 | 350 | -0.66 | -0.19% | 14% | 0 | 0 |
| UK | 2 | 100 | -2.46 | -2.46% | 0% | 0 | 0 |
| India | 5 | 250 | -5.61 | **-2.24%** | 0% | 0 | 1 |

### By asset class
| Class | n | dep € | P/L € | P/L % | win % |
|---|---|---|---|---|---|
| Equity | 57 | 2850 | +14.27 | +0.50% | 39% |
| ETF | 4 | 200 | +0.46 | +0.23% | 50% |

**Read:** Europe and US carried the book (every TP-book and all 5 stops sit in US +
India). India is the worst segment (−2.24%, the only stop outside the US). Japan/Korea
are near-flat — partly genuine (1–3 day holds) and partly low-confidence data. Caveat:
the same confidence flags from `REPORT.md` apply to these segment numbers.
