# Syndication detector (Pass 5 surprise upgrade)

**The failure it kills:** one wire story republished by twenty outlets
looks like twenty independent confirmations to any naive evidence
counter. Confirmation count drives the evidence-quality and grounding
layers, so syndication silently turns one data point into twenty — which
is exactly how crowded narratives masquerade as well-confirmed theses.
This is among the most common real-world ways retail research fools
itself, and no other control in the stack addressed it.

## Method (`scripts/syndication_detector.py`, stdlib, deterministic)

1. Normalize claim text (casefold, strip punctuation).
2. Word 3-shingles → Jaccard similarity.
3. Greedy single-link clustering at τ = 0.55 (light editorial rewrites of
   one wire story measure ≈ 0.58; genuinely distinct stories ≈ 0.0–0.1).
4. **Effective sources = number of clusters.** Outlets inside a cluster
   are listed but contribute zero extra confirmations.
5. Non-text evidence (empty claims) stays independent — we can't prove
   duplication, and there is no wire-copy phenomenon for price bars.

## Integration point

`llm_grounding_guard.ground_claim` now counts support and contradiction
by **effective clusters** (`representatives()`), so:

```
weight = base × source_confidence × freshness × n_eff_support/(n_eff_support + 2·n_eff_contra)
```

## Evidence it works (test-pinned, `tests/test_syndication_and_tournament.py`)

- 20 near-identical wire copies → `effective_count = 1` (19 collapsed).
- Grounding weight with 20 syndicated copies **equals** the single-source
  weight to 1e-9.
- Three genuinely independent stories vs one contradiction keep penalty
  3/5; twenty syndicated copies vs the same contradiction now get 1/3 —
  **syndication can no longer outvote contradiction** (previously: 20/22 ≈ 0.91).
- Distinct stories and structured evidence remain fully independent.
- Red-team case 9 exercises the same property end-to-end.

## Score impact

Grounding-layer confirmation inflation from syndicated news: eliminated
by construction for the wired LLM path (worst case demonstrated above:
a contested syndicated thesis dropped from penalty 0.91 to 0.33 — a ~64%
confidence haircut exactly where overconfidence lived).

## Remaining limitation

Same-story detection is lexical (Jaccard). Two outlets paraphrasing one
press release in genuinely different words can evade collapse; a
semantic-similarity upgrade would need embeddings (a heavier dependency,
deliberately not added). The clusters list in `effective_sources()`
keeps the human able to spot this in review.
