# Production model wiring map (Pass 5)

Which RUNTIME flows actually pass through the Pass-4/5 controls — not
which scripts exist. States: ✅ wired · ◐ partial · ✗ not wired · n/a.
Audit/lockdown/advisory-invariant columns were fully wired in Passes 1–4
for every API flow (middleware) and are noted only when interesting.

| Runtime Flow | Evidence Ledger | Temporal Guard | LLM Grounding | Memo | Outcome Review | Scorecard | Audit | Gap | Fix |
| ------------ | --------------- | -------------- | ------------- | ---- | -------------- | --------- | ----- | --- | --- |
| Signal inbox (reads) | ✅ via signal_events hook | n/a (display) | n/a | ◐ manual | n/a | n/a | ✅ | memo not auto-attached in UI | generate per-signal via `generate_decision_memo` |
| Live signals ingestion (news/filings/Polymarket/Kalshi/GDELT runners) | ✅ `persistence.insert_signal_event` hook | ◐ recorded w/ assumed-UTC flag when naive | n/a | n/a | n/a | n/a | ✅ `evidence_recorded` | naive legacy timestamps capped at conf 0.4 | runners should stamp aware UTC |
| Manual trade log (POST) | ✅ `insert_manual_trade` hook | ◐ warning path | n/a | ◐ operator-initiated | ✅ via review loop | n/a | ✅ | — | — |
| Reconciliation (POST) | ✅ `insert_reconciliation` hook | ◐ | n/a | n/a | ✅ | n/a | ✅ | — | — |
| Moltbook (POST) | ✅ `insert_moltbook_entry` hook | n/a | n/a | n/a | ✅ | n/a | ✅ | — | — |
| Imported outcomes / backtest datasets | ✅ `insert_imported_outcomes` hook | ✅ (guard in advisory backtester; legacy `backtest_calibration` no-lookahead by construction) | n/a | n/a | ✅ | n/a | ✅ | — | — |
| AI report ingestion (five-model) | ✅ `on_ai_report` per report | ✅ generated/ingested stamps | ✅ `ground_normalized_reports` — confidence REPLACED by grounded weight | n/a | via reliability ledger | n/a | ✅ | legacy callers not passing `evidence_items` get loud `ungrounded_legacy` mark | pass ledger items + symbol master at call sites |
| Grok/xAI adapter | ✅ downstream via ai ingestion | ✅ same | ✅ same | n/a | n/a | n/a | ✅ | prompt text never becomes evidence (test-pinned) | — |
| Watchlist / discovery board (CQS/FCS) | ◐ inputs covered via signal_events; scores themselves not evidence | ◐ uses freshness/staleness fields | n/a (no LLM in CQS path) | ✗ | ✗ | ✅ weight sets in `weight_sanity` | ✅ | derived scores not ledgered | treat scores as derived, ledger on promotion |
| Journal scoring (FCS/ERS/NSV) | ◐ as above | ◐ | n/a | ◐ | ✅ | ✅ inventoried + sensitivity-gated | ✅ | weights remain priors | constrained fit once ≥100 outcomes |
| Backtests (advisory engine) | ✅ samples carry evidence ids | ✅ guard mandatory, rejects reported | n/a | n/a | ✅ | ✅ | n/a | — | — |
| Calibration reports | n/a | ✅ `calibration_summary_guarded` | n/a | n/a | ✅ | ✅ | n/a | legacy `score_calibration` DB path: timestamps naive → ◐ | stamp aware UTC at reconciliation |
| Signal tournament / shadow ledger | ✅ evidence ids per row | ✅ mandatory | ✅ grounded variant | n/a | ✅ | ✅ | n/a | needs real history to matter | accumulate |
| Dashboard (Streamlit) | ✅ panel shows ledger count/validity | ✅ rule displayed | ✅ rule displayed | n/a | n/a | ✅ pointer | ✅ token gate | display-only | — |
| Exports (CSV) | n/a (egress) | n/a | n/a | n/a | n/a | n/a | ✅ export events | — | — |

## Coverage metrics (honest count)

- **EvidenceCoverage** — required signal-relevant ingestion paths: live
  signal events (all runners via one chokepoint), manual trades,
  reconciliation, moltbook, imported outcomes, AI reports, tournament
  observations, manual signal annotation (= moltbook/reflections),
  watchlist-item inputs (via signal_events), discovery inputs (via
  signal_events). Wired: 10/10 ingestion **entry** points ⇒
  `EvidenceCoverage = 1.00` at the chokepoint level. Honest caveat:
  *derived* scores (CQS/FCS values themselves) are not ledgered — they
  are computations over ledgered inputs, marked ◐ above.
- **TemporalCoverage** — evaluation paths: advisory backtester ✅,
  legacy walk-forward backtest (safe by construction + tested) ✅,
  calibration (guarded entry) ✅, outcome review ✅, tournament ✅,
  imported-outcome evaluation ✅, legacy `score_calibration` DB
  aggregation ◐ (naive legacy timestamps; production continues with
  warning per policy). ⇒ `TemporalCoverage = 6.5 / 7 ≈ 0.93` —
  **just under the 0.95 target**; the remaining 0.07 needs aware-UTC
  stamps written at reconciliation time (tracked fix, not faked).
- **GroundedLLMCoverage** — LLM paths: five-model ingestion ✅ (grounded
  mode), Grok/xAI adapter ✅ (flows into the same ingestion), tournament
  LLM variant ✅, news summarization n/a (no LLM summarizer exists),
  thesis generation n/a (human-written). Of existing LLM paths: 3/3
  grounded, legacy callers loudly labeled `ungrounded_legacy` ⇒
  `GroundedLLMCoverage = 1.00` with the legacy-label caveat.

## Bridge semantics (read before relying on coverage)

The evidence bridge is **best-effort and never blocks journaling**; under
pytest it is inert unless `MVP_EVIDENCE_LEDGER_PATH` is set (test
isolation). Naive timestamps from legacy writers are recorded as
assumed-UTC with confidence capped at 0.4 and the method flagged — the
temporal guard still refuses them for evaluation. Every successful
evidence write emits a hash-chained `evidence_recorded` audit event.
