# Model card — Sleeping Passenger advisory signal stack

Owner: **Akash Guha** · Registry: [`model_registry.json`](model_registry.json) (34 models) ·
Governance: [`docs/MODEL_GOVERNANCE.md`](docs/MODEL_GOVERNANCE.md)

## Purpose

Help one human evaluate stocks/signals: surface candidates, score
evidence quality, flag manipulation and staleness, journal decisions, and
review outcomes honestly. It is a decision-intelligence aid, not a
trading system.

## Intended use

Single owner, local machine, advisory journal. Outputs are inputs to a
human decision, recorded in decision memos with a blank human-decision
line.

## Prohibited use

- Trade execution of any kind — **there is no execution path to misuse**;
  no broker module, no order route, and CI gates fail if one appears.
- Automated buying/selling, order sizing for live execution, multi-user
  or commercial advisory service (see PROPRIETARY_NOTICE.md).
- Quoting any backtest number without its assumptions block and
  out-of-sample basis label.

## Data sources

Public read-only APIs (Yahoo OHLCV, SEC EDGAR, EDINET, OpenDART, GDELT,
NewsAPI, Polymarket, Kalshi, Etherscan/Blockscout), optional LLM reports
(Grok/xAI + five-model synthesis), and the owner's own journal. No
broker data, no private feeds. Evidence is hashed, redacted, and
timestamped into `runtime/evidence_ledger.jsonl`.

## Known limitations

- **Weights are priors, not fits**: scoring weights/thresholds are
  hand-set (`config/thresholds.yaml`); sensitivity analysis measures
  their fragility but no empirical optimization has been performed.
- **Calibration is provisional**: real-outcome sample size is below the
  CALIBRATED ladder rung (n≥50); every probability is labeled with its
  sample-size status and must be read that way.
- **LLM content can hallucinate**: mitigated structurally — unsourced
  claims carry zero scoring weight, speculation is note-only,
  out-of-universe tickers are rejected (`llm_grounding_guard`).
- **Friction is assumed**, not measured; reference prices are
  observation points, not fills.
- Jurisdiction/leverage heuristics can misclassify dual-listed tickers.

## Validation status

Synthetic-data validation: comprehensive (114 Pass-4 tests with known
mathematical answers; ~6,700 total backend tests). Historical
out-of-sample validation: **available via the walk-forward backtester
but not yet accumulated on real signal history** — until it is, no
performance claim exists. Independent validation: none.

## Calibration status

UNCALIBRATED→CALIBRATING ladder enforced by `score_calibration.py`;
Pass-4 `model_calibration.py` adds ECE/Brier/log-loss/reliability-bin
reports with small-sample refusals (ECE not even computed below N=10).

## Human review requirement

Every output: `human_review_required = true`. Decision memos require a
human decision entry; the sensitivity analyzer recommends ABSTAIN on
unstable scores; the review loop scores the human+model pair afterwards.

## Advisory-only boundary / no-execution guarantee

`ADVISORY_ONLY=true`, `HUMAN_EXECUTION_REQUIRED=true`,
`execution_gate=LOCKED`, `broker_api_called=false`,
`ai_execution_count=0` — pinned by tests, CI gates, the release
manifest, and `tests/test_model_registry.py` (no registered model may be
execution-capable). This boundary is permanent.

## Failure modes

Stale evidence driving fresh conviction (guarded: freshness decay +
review loop); lookahead in evaluation (guarded: temporal guard);
hallucinated claims (guarded: grounding guard); overconfident scores
(guarded: calibration ladder + abstention analysis); fragile
single-feature scores (guarded: sensitivity ABSTAIN); silent threshold
drift (guarded: config contract + registry).

## Update & rollback procedure

Update: change → tests green → scorecard regenerated → registry entry
versioned → commit (see governance doc). Rollback: `git revert` of the
model change; journal data is never coupled to model versions, and
backups (`docs/BACKUP_RESTORE.md`) restore state independently.
