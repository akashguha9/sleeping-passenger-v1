# Quant Research Report — 2026-08-16

RESEARCH_ONLY — no experiment output may feed a trade decision.

## E1_pm_calibration
- verdict: **ACCEPTED**
- Kalshi settlement prices beat the constant-base-rate baseline by 0.0564 Brier points (N=42)

## E2_lead_lag
- verdict: **REJECTED**
- 0/8 pre-registered pairs show out-of-sample predictive lead; 7 of 8 correlation peaks survive BH-FDR at 5%

## E3_momentum_decay
- verdict: **INCONCLUSIVE**
- momentum rank-IC by horizon: h=1: -0.007 (N=101886), h=3: -0.017 (N=101241), h=5: -0.017 (N=101354), h=10: 0.000 (N=101309), h=20: 0.013 (N=101950)

## E4_peg
- verdict: **BLOCKED_BY_DATA**
- REAL propagation-gap observations: N=0 — no real PEG alpha claim is possible; machinery demonstrated on fixture rows only
