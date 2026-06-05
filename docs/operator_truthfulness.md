# Operator Truthfulness

> How Sleeping Passenger avoids lying to the operator. Advisory-only: nothing
> here executes trades.

The operational-readiness audit (`scripts/operational_readiness_audit.py`)
exists to answer one question: *can the system survive a real day-to-day manual
trading workflow without misleading the operator?* This note records the
truthfulness invariants the audit measures and the modules that enforce them.

## 1. No fabricated performance numbers

- Performance metrics are **sample-size gated** (`scripts/performance_truthfulness.py`):
  win rate needs ≥10 closed outcomes, Sharpe/Sortino ≥30 returns (Sortino also
  ≥5 downside points), max drawdown ≥10 equity points, calibration ≥30 eligible
  outcomes. Below threshold a metric returns `INSUFFICIENT_SAMPLE` / `NO_DATA`
  with `value = None` — never a fabricated figure.
- `scripts/score_calibration.py` already returns `win_rate = None` and
  `score_should_drive_sizing = False` at n = 0 (proven by
  `tests/test_score_calibration.py`).
- Every emitted metric carries `provenance_type`, `sample_size`, `mode`, and a
  finite display state, so a number can never appear without saying where it
  came from and how much evidence backs it.

## 2. Honest provenance separation

- `scripts/outcome_evidence.py` tags every outcome `REAL_MANUAL_TRADE`,
  `PAPER_TRADE`, `IMPORTED_BACKTEST`, or `SYNTHETIC_FIXTURE`. Synthetic fixtures
  are **never** calibration-eligible. Quality weights (1.0 / 0.8 / 0.6 / 0.0)
  keep classes from being silently mixed.
- The audit's evidence-quality penalty means static-only structure cannot
  masquerade as field evidence: `evidence_quality_score` stays low until real
  outcomes exist.

## 3. Calibration is evidence-gated, not faked

- Brier score, expected calibration error, and the Murphy
  reliability/resolution/uncertainty decomposition are implemented and tested
  (`scripts/calibration_map.py`, `scripts/score_calibration.py`,
  `tests/test_calibration_metrics.py`, `tests/test_calibration_decomposition.py`).
- With < 30 real/imported outcomes the audit reports calibration as `NO_DATA`,
  and `scripts/calibration_gate.py` emits `NO_REAL_OUTCOME_EVIDENCE`.

## 4. Strong manual-trade record-keeping

- `scripts/manual_trade_validation.py` canonicalizes tickers to a single
  `EXCHANGE:SYMBOL` form (so `AIR` on EPA can't collide with `AIR` on ETR, and
  `8306.T` maps to `TYO:8306`), rejects bare symbols and unsupported exchanges,
  derives currency from an explicit exchange→currency map, and computes a stable
  natural key for duplicate detection.

## 5. Auditable exports

- `scripts/export_envelope.py` wraps any export in metadata
  (`schema_version`, `generated_at_utc`, `provenance_type`, `source_count`,
  `content_checksum`) and round-trips losslessly with tamper detection.

## 6. Fail-closed + governed artifacts

- Runtime failures degrade to `NO_DATA`/`ERROR`, never a crash.
- `scripts/reset_local_logs.py` stays dry-run-by-default, role-guarded,
  allowlisted, safe-path-checked, and backed up before any delete.
- New runtime artifacts (`coordination_audit.json`,
  `operational_readiness_audit.json`) are governance-stamped so the
  artifact-coherence check treats them as managed, not legacy pollution.

## The honest bottom line

Code-level operational readiness can be high while **trading edge stays
unproven**. The audit reflects that: a strong `raw_readiness_score` with a low
`evidence_quality_score` yields a low `readiness_score` and a
`_NO_REAL_OUTCOMES` grade suffix until real operator outcomes exist. That is the
truth the operator is owed.
