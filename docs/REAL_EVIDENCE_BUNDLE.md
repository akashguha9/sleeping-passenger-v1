# Real Evidence Bundle — sleeping-passenger-v1

> **ADVISORY ONLY. NOT real-money ready. No trading edge is claimed.**
> This system places no orders and calls no broker API (`execution_gate = LOCKED`, `broker_api_called = false`).

- Generated (UTC): `2026-05-31T09:33:34Z`
- Repo commit: `7e8d5c30950a15392d98731d26f4c0ca2c73cc64`
- Predictive claim allowed: **False**
- Real-money ready: **False**

## Source activation
- Real canary activation: **3** ['yfinance', 'polymarket', 'sec_edgar']
- Fixture-backed activation: **0** []
- C_global: 0.75

## Decision snapshots & outcomes
- Decision snapshots: 0 (valid p: 0)
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
- S_evidence = **0.35**
- Components: {'source_truth_score': 1.0, 'snapshot_coverage': 0.0, 'outcome_coverage': 0.0, 'calibration_gate_score': 0.0, 'reproducibility_score': 1.0}
- Weights: {'source': 0.25, 'snapshot': 0.2, 'outcome': 0.25, 'calibration': 0.2, 'reproducibility': 0.1}

## Reproducibility

```
python scripts/real_evidence_canary.py --sources yfinance,gdelt,polymarket --write && python scripts/real_calibration_evidence.py --write && python scripts/real_evidence_bundle.py --write
```
- Commit hash present: True
- Tests green: True

## Limitations

- Real forward calibration corpus is below N=200; no predictive claim is made.
- Source activation may be fixture-backed; real canary rows require REAL_EVIDENCE_CANARY=1 with live network access.
- Historical-proxy metrics (if any) are research-only and never unlock the gate.
- This system is ADVISORY ONLY. It places no orders and calls no broker API.
- This is NOT real-money ready and makes no claim of trading edge.
