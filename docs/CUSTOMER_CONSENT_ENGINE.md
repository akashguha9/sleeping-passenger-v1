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
* Phrase lexicons are English-language v1; multilingual complaint
  handling (German Mahnung/Kündigung vocabularies, etc.) is future work.
* No scraping is built in: the engine scores caller-supplied texts; data
  sourcing (reviews, regulator databases) is a separate, ToS-respecting
  concern.
