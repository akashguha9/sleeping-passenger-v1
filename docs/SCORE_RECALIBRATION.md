# Score Recalibration & Backtest Evidence

The hackathon upgrade: scores are now made **honestly better**, not just measured.

## Recalibration map (`scripts/calibration_map.py`)
Learns `calibrated_p = f(raw_score)` from resolved outcomes and validates it
**out of sample** (train/test split; keep isotonic or Platt only if it beats
raw Brier on held-out data, else `identity`).
- **Isotonic** — Pool-Adjacent-Violators, non-parametric, monotone.
- **Platt** — logistic `sigmoid(A·s + B)`.
Surfaced at `GET /api/calibration-map`; `score_output_contract` exposes
`recalibrated_score` + `recalibration_method`. A recalibrated probability is
**advisory** — it never enables sizing (provenance gating still applies).

## Calibration rigor (`scripts/score_calibration.py`)
- **Murphy decomposition**: Brier = Reliability − Resolution + Uncertainty
  (exact on binned predictions).
- **Bootstrap 95% CI** on ECE (deterministic seed).
- **Reliability diagram** points (confidence vs accuracy per bucket).

## Backtest evidence (`scripts/backtest_calibration.py`)
Walk-forward over historical OHLCV → `IMPORTED_BACKTEST` outcomes with **real
forward returns** and **zero lookahead** (score at t uses bars[:t+1]; return
uses bar t+horizon). Provenance is **required and explicit**: synthetic prices
can never be promoted to backtest evidence.

Backtest evidence calibrates the **scores** and counts toward **signal
quality** — but **never** lifts real-money readiness, which keys on `real_n`
alone. A test proves a fully-calibrated backtest stays capped at 7.0 readiness.

## End-to-end
`python scripts/run_calibration_pipeline.py [--backtest] [--json]` runs
outcomes → metrics → recalibration → recommendation → signal quality.
