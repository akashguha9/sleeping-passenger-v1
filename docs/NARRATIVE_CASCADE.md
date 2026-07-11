# Narrative Cascade Layer

**Modules:** `scripts/narrative_observation.py`, `scripts/prediction_market_impulse.py`,
`scripts/linguistic_state_engine.py`, `scripts/narrative_state_engine.py`,
`scripts/causal_event_graph.py`, `scripts/entity_security_resolver.py`,
`scripts/narrative_cascade_engine.py`
**Config:** `config/causal_event_graph.json` (curated transmission graph v1)
**Storage:** `narrative_probability_snapshots` (additive table; written on every
live refresh by `live_source_runner._persist_events`)
**API:** `GET /api/narrative/cascade` (TTL-cached 60s)
**Extraction:** `deterministic_lexical_v1` — **no LLM calls** in this layer.

## What it does

Moves discovery from "headline mentions ticker" to:

```
signal_events (polymarket / gdelt / newsapi / filings ...)
  → InformationObservation (typed, UTC, deterministic IDs, explicit missingness)
  → deduplication (exact fingerprint → URL → near-title Jaccard)
      independence weight I_c = 1/(1+ln(1+n_c));  cluster size kept as ATTENTION
  → prediction-market impulses: L=ln(p/(1-p)) ε-bounded; ΔL, velocity,
      acceleration, reversal; PMI = |ΔL|·Q·I;  DRIFT/SHIFT/SHOCK classes
  → linguistic state (direction, certainty, modality, urgency, escalation,
      causal assertiveness) + NLP-INSPIRED FRAMING HEURISTICS
      (presupposition, inevitability, scarcity/threat/opportunity frames,
      authority/consensus, future pacing) — every framing feature stamps
      FEATURE_TYPE=LINGUISTIC_HEURISTIC, VALIDATION_STATUS=UNVALIDATED
  → narrative clusters + NarrativeState (strength = reliability×independence
      decayed mass; velocity/acceleration over 24h checkpoints; novelty;
      persistence; contradiction band; source entropy; narrative temperature;
      configured half-life priors; linguistic inflection early→late)
  → trigger-keyword event activation (word-boundary matching) → curated
      causal graph propagation (max depth 4, confidence floor, cycle
      detection, e^(−λ·len) length penalty, tanh-bounded impacts)
  → security exposures with depth class (FIRST/SECOND/THIRD_ORDER/
      MACRO_PROPAGATED), direction, broad lag class (IMMEDIATE…STRUCTURAL —
      ordinal upper bound, no invented precision), upstream score,
      full strongest path + relations
  → narrative recognition (explicit mentions, independent mention mass,
      attention velocity, price recognition from imported OHLCV when present;
      missing components listed)
  → NPAG = |latent impact| − recognition;
      combined PAG = 0.5·market PAG + 0.5·NPAG (configurable weights)
  → market titration state for the same ticker (real engine call)
  → narrative×titration interaction priority → operator action
      IGNORE / WATCH / RESEARCH / PRIORITIZE / NO_EDGE
  → counterfactuals (bull/bear/null/alternative — all labelled HYPOTHESIS)
      + invalidation conditions
```

## Honesty contract

* **Curated ≠ proven.** Every causal edge is `validation_status=CURATED`
  (an economic-transmission prior); each candidate carries its full
  assumption path (`path_assumptions=curated_transmission_priors_v1`) for
  the operator to reject. Correlation-type edges are excluded from
  propagation. No lead-lag/Granger claim exists anywhere in this layer —
  that research is **BLOCKED** until narrative + response history
  accumulates (quantified in the titration calibration report).
* **NLP terminology:** Natural Language Processing here means the
  deterministic lexical layer. Neuro-Linguistic-Programming-inspired
  features are *unvalidated text descriptors*; they claim nothing about
  psychological influence. The open research question they serve: do
  framing changes precede attention/probability/response changes?
* **Probability integrity:** log-odds impulses describe belief-aggregate
  shifts in prediction markets; nothing in this layer is a probability of
  any market outcome, and each payload says so (`non_claims`).
* Reserved narrative regimes (DORMANT/COHERING/SATURATED/REVERSING) need
  cross-run narrative identity; they are exported, documented, and never
  assigned.
* Syndication is never independence: 100 copies of one wire story count
  as ~1 fact and full attention.

## The ingestion fix that makes impulses possible

Before this sprint, `live_source_runner._normalize_polymarket_record`
**dropped** the loader's `implied_probability`, and the constant
per-market `event_id` under `INSERT OR IGNORE` meant re-refreshes were
no-ops — no probability time series could ever accumulate. Now: the
persisted payload keeps `implied_probability(+source)/question/category`,
and every refresh writes a row to `narrative_probability_snapshots`
(PK market_id+source+fetched_at). Each 6-hourly operator refresh
accumulates the series that powers log-odds impulses.

## Environment reality

This development container's egress proxy blocks all market/news hosts
(Polymarket/GDELT/SEC probes: CONNECT 403 / 000), so live observation
counts here are honest zeros; the full chain is proven end-to-end by
deterministic fixtures through the real DB schema and the real API. On
the operator's machine, `python scripts/refresh_live_signals.py --write`
(key-free CORE set: polymarket, gdelt, sec_edgar, india, market_data)
begins populating observations and probability snapshots immediately.

## Tests

`tests/test_narrative_cascade_layer.py` — impulses (bounds, velocity,
acceleration, reversal, duplicates, out-of-order, missing liquidity),
normalization + dedup (exact/URL/near-title, unicode, non-English),
linguistic features + inflection, narrative clustering/states (+ leakage:
future observations never count backwards), causal graph validation +
propagation (signs, depth decay, cycles, pruning, unknown nodes),
resolution ladder (exact/alias/curated/fuzzy/ambiguous/unresolved),
snapshot persistence bounds, runner normalizer fix, end-to-end cascade
with safety stamps, empty-DB honest zeros, API contract + cache.
