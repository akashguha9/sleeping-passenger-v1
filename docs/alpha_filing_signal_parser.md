# Alpha Filing Signal Parser

Advisory-only. Deterministic, offline keyword parsing — no SEC/EDGAR
network dependency, no model calls, replayable byte-for-byte.

## What it does

`src/alpha/filing_parser.py` converts a filing excerpt into:

1. **Evidence items with lineage** — category, claim, evidence text,
   source type, hardness weight, confidence, line number, source date.
2. **Risk disclosures** — scored separately into
   `filing_risk_disclosure_score` (they penalize opportunity; they never
   prove a theme).
3. **Proof summary** — `proof_density`, `embedded_proof_score`,
   `substrate_score`, and a classification:
   `simulated | embedded | substrate | insufficient_evidence`.
4. Optionally a `FilingSignal` (`to_filing_signal`) whose
   `verified_evidence` entries embed the line-number lineage.

## Evidence categories

Positive: revenue_segment, customer_contract, order_backlog,
capex_commitment, regulatory_approval, product_launch,
geographic_expansion, margin_improvement, free_cash_flow,
debt_reduction, partnership, patent_or_ip.

Risk: risk_disclosure, customer_concentration, supplier_dependency,
litigation_or_regulatory_risk, going_concern_or_liquidity_risk
(going-concern findings carry maximum severity).

## Hardness model

`hardness = EVIDENCE_HARDNESS_WEIGHTS[kind] × SOURCE_TYPE_MULTIPLIER[source]`

The same sentence is worth less on an investor slide (×0.45) than in a
10-K (×1.00); unknown source types are discounted to ×0.40 and reported
in `missing_inputs`. Marketing-cue lines ("world-class",
"market-leading", "revolutionary", …) are classified as claims — they
appear in the proof-density denominator, never the numerator.

```text
proof_density        = weighted_verified_evidence / max(1, narrative_claim_count)
embedded_proof_score = 100 × min(1, proof_density)
substrate_score      = 100 × min(1, recurring_revenue + segment_revenue
                                   + operating_dependency + capex_dependency)
```

## Known limits (honest)

- Keyword matching, not language understanding: novel phrasings are
  missed, and a sentence containing a cue is matched even when negated
  ("we did not enter into a contract" still matches). Treat scores as
  triage, then read the lineage lines yourself — that is what the
  line numbers are for.
- English-only cue lists, tuned on US filing conventions.
- No fraud detection: the parser scores what the document *says*, not
  whether it is true. Audited-source weighting is the only defense.
- TODO(filings): wire an offline-snapshot EDGAR ingestion that feeds
  excerpts into this parser with real source dates.

## API

`POST /alpha/filing/parse` (token-gated, read-only computation, text
capped at 100k characters). The dashboard's Alpha Framework section
includes a local parse box; text is processed in-process and never
stored or transmitted.
