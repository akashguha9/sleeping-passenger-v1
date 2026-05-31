# Real Evidence Bundle — sleeping-passenger-v1

> **ADVISORY ONLY. NOT real-money ready. No trading edge is claimed.**
> This system places no orders and calls no broker API (`execution_gate = LOCKED`, `broker_api_called = false`).

- Generated (UTC): `2026-05-31T11:17:12Z`
- Repo commit: `39a4dd7e158228fc138ea48c491a766aa8dfb31f`
- Predictive claim allowed: **False**
- Real-money ready: **False**

## Source activation
- Real canary activation: **0** []
- Fixture-backed activation: **0** []
- C_global: 0.0

## Real-row scoring
- Real canonical rows scored: **49** / 10000 (scoring_coverage 0.0049)
- Complete six-axis vectors: 49 (score_quality_coverage 0.0049)
- Sources scored: ['market_data', 'sec_edgar', 'yfinance']
- Decision-time valid probabilities (n_valid_p): **57**
- Score vector / model version: `real-row-score-v1` / `advisory-logistic-v1`
- Real rows are now scored AND consumed into decision snapshots; the probabilities are advisory-only and **uncalibrated**.
- Calibration status: **INSUFFICIENT_EVIDENCE** (N_real_forward < 200 ⇒ predictive claim LOCKED).
- Signal edge is **NOT proven**. Real-money readiness is **NO**.

## Decision snapshots & outcomes
- Decision snapshots: 210 (valid p: 57)
- Real-forward (p, y) pairs: **0**
- Historical-proxy pairs (research only): 0
- Excluded: 0 {}

## Calibration

```
Brier = (1/N) Σ (p_i - y_i)^2
ECE   = Σ (n_b/N) |acc(b) - conf(b)|
CalibrationAllowed = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)
```

- N_real_forward: 0
- Brier: None  ECE: None  LogLoss: None
- Status: **INSUFFICIENT_EVIDENCE**
- Predictive claim allowed: **False**

## Evidence score (documentation metric, NOT a trading claim)
- S_evidence = **0.05798**
- Components: {'source_truth_score': 0.0, 'scoring_coverage': 0.0049, 'snapshot_coverage': 0.285, 'outcome_coverage': 0.0, 'calibration_gate_score': 0.0, 'reproducibility_score': 0.0}
- Weights: {'source': 0.2, 'scoring': 0.2, 'snapshot': 0.2, 'outcome': 0.2, 'calibration': 0.1, 'reproducibility': 0.1}

## Reproducibility

```
python scripts/real_evidence_canary.py --sources yfinance,gdelt,polymarket --write && python scripts/real_calibration_evidence.py --write && python scripts/real_evidence_bundle.py --write
```
- Commit hash present: True
- Tests green: False

## Limitations

- Real forward calibration corpus is below N=200; no predictive claim is made.
- Source activation may be fixture-backed; real canary rows require REAL_EVIDENCE_CANARY=1 with live network access.
- Historical-proxy metrics (if any) are research-only and never unlock the gate.
- This system is ADVISORY ONLY. It places no orders and calls no broker API.
- This is NOT real-money ready and makes no claim of trading edge.
