# Real Data Readiness — 2026-08-16

RESEARCH_ONLY. Gates: BLOCKED_BY_DATA / INSUFFICIENT(<20) / EXPLORATORY_ONLY(<80) / TESTABLE(>=80).

## Prediction-market temporal depth

- Observations: 1906 raw rows across 425 contracts on 2 distinct days (2026-07-02 → 2026-08-16, 45 elapsed calendar days)
- Contracts by depth: ≥2 days: 210 | ≥3: 0 | ≥7: 0 | ≥14: 0 | ≥21: 0
- Max depth: 2 days | median: 1 day(s)
- Feature capability: {'DELTA_AND_VELOCITY_POSSIBLE': 210, 'LEVEL_ONLY': 215}
- Per venue: {'kalshi': {'contracts': 325, 'ge_2_days': 210}, 'polymarket': {'contracts': 100, 'ge_2_days': 0}}

## Event → equity / PEG

- Frozen exposure-map versions: 0
- Real PEG observations (LIVE): 0
- Horizon maturity (matured LIVE ARs): {1: 0, 3: 0, 5: 0, 10: 0, 21: 0}
- Hop distribution: {} | filing confirmation: {}

| Experiment | N | Unit | Status |
|---|--:|---|---|
| peg_forward_ar | 0 | matured 5d LIVE PEG observations | **BLOCKED_BY_DATA** |
| probability_dynamics | 0 | markets with >=7 daily observations | **BLOCKED_BY_DATA** _EARLY_LONGITUDINAL: 210 contracts have 2-day depth (ΔP/velocity only); acceleration needs 3, Z-shock needs 10_ |
| cross_venue_divergence | 0 | matched multi-day Kalshi x Polymarket pairs | **BLOCKED_BY_DATA** |
| hop_lag_wave | 0 | matured hop>=2 LIVE observations | **BLOCKED_BY_DATA** |
| filing_confirmation | 0 | matured STRONG-filing LIVE observations | **BLOCKED_BY_DATA** |
| threshold_titration | 0 | persisted titration time-series days | **BLOCKED_BY_DATA** |
| halflife | 0 | matured PEG observations (same corpus, horizon ladder) | **BLOCKED_BY_DATA** |
