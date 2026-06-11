# Customer Consent & Regulatory Fragility Engine

`src/consent/` stress-tests reported revenue against customer consent
quality, service fulfilment, exit fairness, and regulatory fragility.

**Core investment law:** reported revenue is not automatically good
revenue. A company may show strong recurring revenue while users are
trapped, confused, or unable to exit cleanly. Revenue earned through
friction, lock-in, failed cancellation, denied claims, or monetized delay
is lower quality and carries legal, reputational, and churn risk — it is
borrowing from future regulatory action.

**Everything here is ADVISORY_ONLY.** The engine detects *risk patterns*,
never legal guilt or intent. No orders are placed; there is no execution
path anywhere in this system.

## Doctrine

```text
Process without output is bureaucracy.
If collection is instant but correction is slow, revenue quality is suspect.
Digital payment without digital relief is a dark-pattern signal.
A premium price creates a premium accountability contract.
Internal fragmentation is not a customer's liability.
Delay becomes revenue when billing continues during processing.
Revenue from trapped users is lower quality than revenue from satisfied users.
A company that makes exit hard is borrowing from future regulatory risk.
Customer consent is a revenue-quality variable.
A system that tracks money better than outcomes is not efficient; it is extractive.
```

Exposed live at `GET /consent/doctrine`.

## Modules and formulas

All scores are 0–10. Quality scores (consent, segment fit, adjusted
revenue): higher = better. Risk scores (everything else): higher = worse.
Every score ships the full contract: `score`, `label`, `confidence`,
`evidence_terms`, `rationale`, `missing_data_warnings`, `raw_components`.

| Module | Formula |
|---|---|
| `customer_consent.py` | `consent = mean(clarity, predictability, cancellation clarity, refund access, dispute fairness, escalation) − mean(cancellation friction, hidden fees, billing-after-cancel, lock-in, language burden)` — complaint evidence can only worsen, praise cannot manufacture consent |
| `digital_asymmetry.py` | `relief_gap = collection_score − relief_score` over explicit action surfaces (5 collection, 7 relief actions); complaints override the claimed capability matrix |
| same, pause friction | `0.30·manual + 0.20·language + 0.25·delay + 0.25·continued_billing`; reports the monetized delay (`delay/7 × weekly charge`, the €7.50 case) |
| `friction_revenue.py` delay revenue | quantitative: `delay × complaint frequency` with per-user € cost; qualitative fallback from delay-phrase intensity |
| same, friction tax | mean of 8 burden channels (time, translation, proof, call queue, email, delay, payment, stress) |
| `subscription_extraction.py` | `√(recurring × exit_friction × ambiguity × escalation)` — extraction needs all four legs |
| `claims_non_payment.py` | `1 − (paid + formal_decisions)/submitted`; formal rejection counts (it enables appeal), silence does not; NLP evidence fallback |
| `premium_promise.py` | `premium × failure × (0.4 + 0.6·gap)`; Ryanair rule: low price + narrow promise stays coherent |
| `segment_fit.py` | fit components − misfit components ×1.3 for vulnerable segments (international students, migrants, elderly, non-native speakers) |
| `enforcement_asymmetry.py` | `mean(collection speed, penalty strength, debit precision) − mean(resolution speed, refund speed, human accountability)` |
| `narrative_gap.py` | promise-weighted mean contradiction; each promise tag maps to the evidence categories that refute it; no promises → no gap |
| `regulatory_fragility.py` | `severity × (0.4+0.6·vulnerable) × (0.5+0.5·ambiguity)`; weighted regulator-relevant evidence raises severity |
| `revenue_quality.py` | `adjusted = base × Π(0.3+0.7·multiplier) − friction − claims − gap penalties`, multipliers = consent, fulfilment, retention authenticity (1−extraction), regulatory safety (1−fragility) |

Labels: `clean ≥8`, `mostly_clean ≥6.5`, `mixed ≥4.5`, `fragile ≥2.5`,
else `extractive_risk`; plus the honest `insufficient_data` outcome when
the engine knows nothing — ignorance is evidence of neither harm nor
cleanliness.

## Evidence model

Complaint/review texts are scanned against 14 deterministic phrase
lexicons (charged-after-cancellation, cannot-cancel, email-only relief,
bot-only support, language burden, processing delay, hidden fees, claims
non-payment, premium failure, lock-in, pause friction, enforcement speed,
backend mismatch, positive relief). Extraction is counting, not
inference. Intensity uses a saturating denominator (a pattern in ~40% of
texts is established); sample size is reported separately through the
confidence channel and explicit warnings.

## Case studies (committed fixture)

`tests/fixtures/consent_case_studies.json` — anonymized composites of the
operator reflection, labeled SIMULATED RESEARCH DATA:

| Case | What it proves | Verdict |
|---|---|---|
| `premium_gym` | €250 upfront + €15/2wk premium positioning, German-email pause (~1wk, €7.50 monetized delay), stolen property ignored, trainer lock-in | `extractive_risk`; premium failure ≥6, pause friction ≥6 |
| `deutschland_ticket` | app/store cancellation mismatch, German-only fine letters, fast enforcement vs slow resolution | extraction ≥5, enforcement asymmetry ≥6, narrative gap ≥4 |
| `insurer_claims` | 6 claims submitted, 0 paid, 0 formal decisions, bot-loop support | claims non-payment = 10/10 |
| `asymmetric_app` | one-click signup, email-only cancellation | relief gap ≥7 |
| `clean_saas` | in-app cancel/pause/refund, human escalation | `mostly_clean`; the control case |

## End-to-end pipeline bridge (added after `fae6800`)

The consent layer is now an **automatic decision modifier**, not a parked
scorer. Inside `evaluate_candidate_payload`:

```text
complaint evidence (raw text / JSON / CSV / structured records)
  → normalized evidence bundle (dedup, language, categories)
  → evidence reliability (source-weighted, anti-inflation)
  → consent/regulatory profile + jurisdiction map + dark-pattern chain
  → crash-wall risk factors (scaled by reliability)
  → multipliers / penalties / severity caps on the final verdict
  → Buy/Watch/Avoid effect, recorded in a deterministic decision ledger
```

Candidate payload evidence fields (any may be present):
`consent_profile`, `complaint_texts`, `consumer_evidence`,
`complaint_evidence`, `regulatory_evidence` (defaults to regulator-action
source weight), `customer_reviews`.

Adjustment contract (`src/consent/pipeline_bridge.py`):

```text
score_after =
  score_before
  × gate(clamp(adjusted_revenue_quality/10, 0.25, 1.05))
  × gate(clamp(consent_quality/10,          0.35, 1.05))
  × gate(clamp(1 − regulatory_fragility/10, 0.30, 1.00))
  − friction_penalty − claims_penalty − narrative_gap_penalty

gate(m) = 1 − (1 − m) × reliability_factor   # reliability gates impact
```

Fairness rules (tested): clean/specific positive evidence → neutral
multipliers (no punishment); **zero harm-category evidence → multipliers
floored at 0.97** (ignorance from missing structured inputs is never
treated as harm); missing evidence → full neutrality + `insufficient_data`
warning. Severity caps by reliability band: severe + high reliability caps
the ladder at watchlist; severe + medium at active_watch; severe + low is
a warning with a mild cap — one angry anecdote is never a verdict.

## Evidence reliability (`evidence_reliability.py`)

```text
reliability = 0.35·source_quality + 0.25·corroboration + 0.10·recency
            + 0.20·specificity + 0.10·severity
            − anecdote_penalty − duplicate_penalty − vague_language_penalty
```

Source weights: regulator action (1.0) > lawsuit (0.95) > official
disclosure (0.85) > verified review (0.70) > app-store review (0.55) >
forum post (0.40) > anonymous (0.25). Near-duplicates (Jaccard ≥ 0.75
after normalization) are collapsed — copied text does not corroborate
itself. Bands: high ≥ 6.5, medium ≥ 3.5, low below.

## German-English lexicon

Matching is umlaut-safe and digraph-tolerant (`Kündigung` ≡ `Kuendigung` ≡
`kundigung`) and hyphen-tolerant (`Handy-Ticket` ≡ `handy ticket`). Harm
phrases map to categories ("trotz kundigung abgebucht" →
charged-after-cancellation, "mahngebuhr"/"inkasso" → hidden fees,
"stilllegung" → pause friction, "erstattungsantrag abgelehnt" → claims
non-payment). Bare topic words (`Vertrag`, `SEPA`, `Abo`, `Beitrag`…) are
deliberately **not** harm evidence — they map to topics for language
detection and term surfacing only, so a neutral German contract text
scores zero harm.

## Offline ingestion (`ingestion.py`)

`ingest_raw_texts`, `ingest_json_file`, `ingest_csv_file` →
`EvidenceBundle` (deduplicated records, language guesses, categories,
topics, reliability, warnings). Strictly offline; fixtures live in
`tests/fixtures/consent_evidence/`. Offline ingestion is not live
monitoring — sourcing and source-ToS compliance stay with the operator.

## Jurisdiction risk map (`jurisdiction.py`)

Evidence categories map onto eight named domains
(consumer_subscription_risk, insurance_claims_risk,
direct_debit_billing_risk, language_accessibility_risk, dark_pattern_risk,
vulnerable_user_risk, claims_handling_risk, refund_friction_risk), with
DE/EU consumer-subscription and SEPA context weighted fully and
vulnerable segments held at full intensity. Pattern classification only —
not legal advice, no guilt, no intent.

## Anti-gaming rules (`anti_gaming.py`)

1. Generic praise ("friendly staff") refutes nothing.
2. Marketing language ("award-winning", "we pride ourselves") is flagged,
   never counted as customer proof.
3. Positive evidence helps only in the category it directly refutes
   ("refund received within 24 hours" reduces refund friction — it does
   not unsay "claim never reimbursed").
4. Resolution evidence ("refunded after I complained") grants bounded
   severity relief across layers.
5. Maximum refutation relief is capped at 50% — proof reduces, never
   erases, contrary evidence.

## Dark-pattern chain detector — the eureka move (`dark_pattern_chain.py`)

"Fraud is sometimes a system design, not one illegal act." The detector
reconstructs the extraction journey as an ordered six-stage chain —
easy signup/recurring billing → hard pause/cancel → slow processing →
continued billing → fees/interest → collections — and scores the longest
**consecutive** run superlinearly:

```text
chain = (longest_run / 6)² × mean_stage_severity
        × reliability_factor × vulnerable_multiplier(1.25)
```

Scattered frictions barely register; an unbroken chain is the system
design itself. Each stage cites its evidence terms; an unreliable chain is
explicitly labeled a hypothesis, not a finding. The chain feeds the crash
wall as the `dark_pattern_chain` risk factor.

## Decision ledger schema (`ConsentDecisionLedger`)

Deterministic and machine-readable: `input_summary`, `evidence_sources`,
`deduplication_summary`, `detected_terms`, `layer_scores`,
`evidence_reliability_score`, `reliability_band`, `multipliers_applied`,
`penalties_applied`, `risk_caps_applied`, `simulator_factors_added`,
`jurisdiction_domains`, `dark_pattern_chain`, `anti_gaming`,
`recommendation_before_consent`, `recommendation_after_consent`,
`score_before_consent`, `score_after_consent`, `warnings`, `rationale`,
`advisory_only_notice`. Same input → byte-identical ledger (tested). No
secrets, no raw file paths.

## Simulator integration

`to_simulator_risk_factors(profile)` bridges the consent profile into the
crash-case simulator as first-class crash vectors (`extractive_revenue`,
`regulatory_fragility`, `claims_non_payment`, `customer_churn_pressure`,
`narrative_experience_gap`), with amplified synergy betas for the classic
blow-up pairs (extractive revenue × regulatory fragility, extractive
revenue × high valuation). Business-model fragility now interacts with
valuation and macro risks inside the cherry-pick pipeline's crash wall.

## How this affects Buy / Watch / Avoid

The engine never emits trade instructions. In journal terms:

* `clean` / `mostly_clean` — consent layer adds no objection; the thesis
  stands or falls on the simulator's other gates.
* `mixed` — log the specific risk layers in the thesis's invalidation
  section; complaint-density worsening is a thesis-damage trigger.
* `fragile` / `extractive_risk` — feed the bridge factors into the crash
  simulator; expect the crash gate to cap promotion at watchlist. Growth
  built on trapped users is treated as a crash vector, not a moat.
* `insufficient_data` — gather evidence before forming any view.

## API

* `GET /consent/doctrine` — doctrine + limitations.
* `POST /consent/evaluate` — full profile from structured inputs +
  complaint texts; stateless; bounded (200 texts × 2000 chars); response
  includes `simulator_risk_factors` and full advisory stamps.

## Limitations (read before using)

* **Complaint data can be biased** — angry users write more than happy
  ones; volume is reported through the confidence channel, not hidden.
* **Personal anecdotes are not statistical proof** — fixtures derived
  from one operator's experience are labeled SIMULATED and prove the
  machinery, not any real company.
* **Intent cannot be inferred without evidence** — the engine scores
  structural asymmetry (e.g., delay that happens to be revenue), never
  purpose.
* **The model detects risk patterns, not legal guilt.**
* Lexicons now cover German + English harm phrases, but they remain
  hand-built keyword lists, not language models; coverage gaps exist.
* No scraping is built in: ingestion is offline (raw text/JSON/CSV); data
  sourcing (reviews, regulator databases) is a separate, ToS-respecting
  concern. Offline ingestion is not live monitoring.
* All thresholds, weights, source weights, and the chain exponent are
  doctrine-derived, **not empirically calibrated** — no labeled outcome
  data exists yet.
