# Real Evidence Bundle — sleeping-passenger-v1

> **ADVISORY ONLY. NOT real-money ready. No trading edge is claimed.**
> This system places no orders and calls no broker API (`execution_gate = LOCKED`, `broker_api_called = false`).

- Generated (UTC): `2026-05-20T00:00:00Z`
- Repo commit: `584133942e6357fc7926554ef714f2eb65c3f808`
- Predictive claim allowed: **False**
- Real-money ready: **False**

## Source activation
- Real canary activation: **0** []
- Fixture-backed activation: **0** []
- C_global: 0.0

## Real-row scoring
- Real canonical rows scored: **1** / 1 (scoring_coverage 1.0)
- Complete six-axis vectors: 1 (score_quality_coverage 1.0)
- Sources scored: ['sec_edgar']
- Decision-time valid probabilities (n_valid_p): **1**
- Score vector / model version: `real-row-score-v1` / `advisory-logistic-v1`
- Real rows are now scored AND consumed into decision snapshots; the probabilities are advisory-only and **uncalibrated**.
- Calibration status: **TOO_FEW_OUTCOMES** (N_real_forward < 200 ⇒ predictive claim LOCKED).
- Signal edge is **NOT proven**. Real-money readiness is **NO**.

## Decision snapshots & outcomes (the forward loop)
- Decision snapshots: 1 (valid p: 1)
- Real-forward (p, y) pairs: **1**
- Historical-proxy pairs (research only): 0
- Excluded: 0 {}
- Outcome coverage: 0.005 (needed to reach 200: 199)
- A real-forward pair is created ONLY when a decision's horizon has elapsed in real calendar time AND a real entry/exit price exists; historical proxy / open / unresolved decisions never count.

## Forward snapshot contract (outcome-eligibility)
- Forward-outcome-eligible snapshots: **1** / 1 valid-p (coverage 1.0)
- Pending horizon: 0  Due forward: 0  Entry-price present: 1
- Forward-ineligible: 0 {}
- Target: `forward_return_ge_threshold` (threshold 0.0, horizon 5d, source `DEFAULT_FORWARD_SNAPSHOT_CONTRACT_V1`)
- Eligibility is **structural only** — a snapshot becoming eligible means a binary outcome can be measured after its horizon closes; it is NOT a predictive claim and NOT an edge claim.

## Forward-eligible throughput (Increase Forward-Eligible Throughput Sprint)
- Forward-eligible: **4 → 1** (gain -3)
- Throughput improvement score (reported, NOT a gate): 0.0
- Sprint-start reason baseline: {'MISSING_TICKER': 119, 'MISSING_ENTRY_PRICE': 25, 'MISSING_PROBABILITY': 2}
- Top missing-OHLCV scored tickers (now): [{'key': 'AAPL', 'count': 1}]
- Pending horizon: 0  Real-forward pairs: 1  Needed to 200: 199
- Throughput improvement raises *eligibility*, never calibration. It does NOT unlock a predictive claim, an edge claim, or real-money readiness.

## Real-forward maturation (Real-Forward Outcome Maturation Sprint)
- Forward-eligible: 1  Pending horizon: 0  Due now: 0
- Real-forward pairs: **1** (needed to 200: 199, attached last run: 1)
- Next horizon becomes due in: None hours (earliest close None)
- Brier: 0.136708  ECE: 0.36974  LogLoss: 0.461622
- Status: **TOO_FEW_OUTCOMES** / FIRST_REAL_FORWARD_PAIRS_ATTACHED_BUT_BELOW_GATE
- The calibration gate stays **LOCKED** below N=200 real-forward pairs; no predictive claim is made and this is **NOT real-money ready**.
- Outcomes attach only after a real horizon elapses — pending horizons are never backdated and no outcome is ever fabricated.

## Calibration

```
Brier = (1/N) Σ (p_i - y_i)^2
ECE   = Σ (n_b/N) |acc(b) - conf(b)|
CalibrationAllowed = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)
```

- N_real_forward: 1
- Brier: 0.136708  ECE: 0.36974  LogLoss: 0.461622
- Status: **TOO_FEW_OUTCOMES**
- Predictive claim allowed: **False**

## Evidence score (documentation metric, NOT a trading claim)
- S_evidence = **0.3516**
- Components: {'source_truth_score': 0.0, 'scoring_coverage': 1.0, 'snapshot_coverage': 0.005, 'forward_eligibility_coverage': 1.0, 'outcome_coverage': 0.005, 'calibration_gate_score': 0.0, 'daily_maturation_loop_score': 1.0, 'reproducibility_score': 0.0}
- Weights: {'source': 0.1, 'scoring': 0.1, 'snapshot': 0.12, 'forward_eligibility': 0.15, 'outcome': 0.2, 'calibration': 0.18, 'daily_maturation': 0.1, 'reproducibility': 0.05}

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
