# Model pipeline map

Advisory-only decision-intelligence pipeline of `sleeping-passenger-v1`.
Machine-readable companion: [`model_registry.json`](../model_registry.json)
(34 registered models, all `execution_capable: false`, owner Akash Guha;
guarded by `tests/test_model_registry.py`).

## 1. Input sources

| Source | Kind | Entry point |
| --- | --- | --- |
| Yahoo OHLCV | market data | `scripts/ingestion/`, `ohlcv_bars` table |
| SEC EDGAR / EDINET / OpenDART | filings | ingestion loaders (env-keyed, read-only) |
| GDELT / NewsAPI | news | ingestion loaders |
| Polymarket / Kalshi / Blockscout / Etherscan | public read-only APIs | adapters |
| Grok/xAI + five-model reports | **LLM** | `scripts/grok_xai_adapter.py`, `scripts/ai_report_ingestion.py` |
| Operator | manual journal | manual trade log, reconciliation, moltbook |
| Pass-4 evidence ledger | typed evidence | `scripts/data_quality.py` → `runtime/evidence_ledger.jsonl` |

## 2. Transformation steps (happy path)

```
ingestion → signal_events table
  → fresh_market_discovery (CQS) → candidate_memory_decay (ACQS)
  → component scorers (EQS/DS/LS/EMS/EFS, src/scoring/)
  → model_probability + NSV + APS (src/scoring/net_signal_value.py)
  → daily_scoring (FCS/ERS) → tier: EXECUTABLE*|WATCHLIST|NOT_EXECUTABLE|BLOCKED
  → signal_reactor criticality state → signal inbox (human)
  → HUMAN logs manual trade → reconciliation → outcome_evidence
  → score_calibration / calibration_map / calibration_gate
* "EXECUTABLE" is a journal-tier label; nothing in the system executes.
```

## 3. Scoring formulas (canonical, with file:line provenance)

- `CQS = 0.20·signal_strength + 0.15·narrative_velocity + 0.15·price_momentum + 0.10·filing_materiality + 0.10·liquidity_quality + 0.10·freshness + 0.10·data_quality − 0.05·chaos − 0.05·crowding` — `scripts/fresh_market_discovery.py:41-109`, weights `config/thresholds.yaml:2-9`
- `ACQS = CQS·exp(−0.25·days_stale)` — `scripts/daily_scoring.py:75-81`
- `model_prob = clip(0.50 + 0.25(EQS−0.5) + 0.20(DS−0.5) − 0.15·EMS − 0.10·EFS, 0.01, 0.99)` — `src/scoring/net_signal_value.py:9-15`
- `NSV = clip(mispricing·EQS·DS·LS − 0.35·EMS − 0.25·EFS, −1, 1)` — `src/scoring/net_signal_value.py:36-40`
- `FCS = 0.25·ACQS + 0.20·mean_model + 0.15·agreement + 0.15·why_today + 0.10·data_quality + 0.10·freshness + 0.05·liquidity − penalties` — `scripts/daily_scoring.py:30-109`
- `ModelReliability = 0.35·hit_rate + 0.25·invalidation + 0.20·source_diversity + 0.10·calibration + 0.10·moltbook_conversion` — `scripts/model_reliability_ledger.py:47-52`
- Calibration: ECE/Brier/LogLoss/Wilson/Bayesian posterior/Murphy decomposition — `scripts/score_calibration.py:253-488`; Pass-4 standalone metrics in `scripts/model_calibration.py`
- Backtest (Pass 4): `R=(P_exit−P_entry)/P_entry`, `R^net=R−c−s`, hit rate, expectancy, Sharpe, Sortino, MDD, walk-forward train/val/test — `scripts/backtest_advisory_signals.py`

## 4. Human decision points

1. Signal inbox: validate / reflect / decide (`POST /signals/{id}/...`).
2. Manual trade log — the ONLY place a position enters the journal; the
   human placed it elsewhere, with their own broker, themselves.
3. Reconciliation: human records actual fills and outcomes.
4. Moltbook post-mortem: mistakes, lessons, rule updates.
5. Pass-4 decision memo (`scripts/generate_decision_memo.py`) with a
   blank "Human decision" line by construction.

## 5. Stored artifacts

`runtime/mvp_local.db` tables: `signal_events`, `signal_decisions`,
`manual_trades` (with `score_at_entry`, `reactor_state_at_decision`),
`reconciliation_results`, `moltbook_entries`, `imported_outcomes`,
`model_runs`, `ohlcv_bars`, `global_securities`. JSON artifacts:
`runtime/model_reliability_ledger.json`, signal ledger, refinery/trend
reports. Pass 4 adds `runtime/evidence_ledger.jsonl` (hashed, redacted
evidence) and `logs/audit_log.jsonl` (Pass 3, hash-chained).

## 6. Output objects

Advisory tiers, reactor states, calibration summaries with sample-size
ladders, decision memos, backtest/calibration/scorecard reports — every
one stamped `ADVISORY_ONLY / execution_gate=LOCKED / broker_api_called=false`.

## 7. Known blind spots

- Most weights/thresholds are hand-set priors (table of ~50 in the
  registry agent survey; key ones in `config/thresholds.yaml`) with no
  empirical fit yet — sensitivity analysis (Pass 4) measures their
  fragility but cannot justify them.
- Real outcome sample size is far below the CALIBRATED_MIN=50 ladder
  rung; every probability is provisional.
- Leverage jurisdiction heuristic can misclassify dual-listed tickers.
- `data_quality` is inferred when explicit fields are missing — can
  overstate confidence.
- Friction model (EFS) is an assumption, not a fill model.

## 8. Where leakage could occur

- Operator backfilling moltbook/reconciliation after seeing outcomes
  (survivorship + hindsight); mitigated by quality weighting and now by
  the temporal guard's `t_observed` discipline.
- Revised/restated financials re-ingested under original IDs — caught by
  `t_published > t_observed` checks in `scripts/temporal_guard.py`.
- Timezone-naive timestamps (IST/CET/UTC) — refused outright by the
  guard and the evidence ledger.
- Trend engine regression over snapshots would be biased if snapshots
  ever contained forward-looking fields (they don't today).
- Legacy backtests are safe by construction (`history[:i+1]`,
  `tests/test_backtest_calibration.py`); the Pass-4 backtester adds the
  guard + walk-forward split + reported rejects on top.

## 9. Where hallucination could enter

- Grok/xAI extracted claims and five-model stances are ingested without
  fact-checking. **Pass-4 control:** `scripts/llm_grounding_guard.py` —
  unsourced claims carry structurally zero scoring weight, speculation
  is note-only, and tickers absent from the evidence-backed universe are
  rejected outright.
- Model reliability ledger's neutral prior (0.5) is a prior, not earned
  trust — flagged `is_prior`.

## 10. Advisory-only boundary

Every output above is advisory. There is no broker module, no order
route, no execution path; `tests/test_api_token_gate_contract.py`,
`tests/test_advisory_contract.py`, the release gate, the compliance
preflight, and `tests/test_model_registry.py` (no model may declare
`execution_capable: true`) all pin this. The "EXECUTABLE" tier names a
journal-review category, not an action.
