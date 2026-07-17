# Lens Ablation & Marginal-Contribution Methodology

`scripts/simulation_intelligence/ablation.py` measures the *invisible work* of
each lens: how much worse, more fragile, or less informed does the council become
when a lens is absent? This is the core mechanism for crediting Kanté-like
contribution — a lens that rarely changes the headline vote can still be elite if
it consistently reduces uncertainty, preserves tail warnings, or adds orthogonal
coverage.

## Method (deterministic, bounded)

1. **Run the full council** on the observation.
2. **Leave-one-out:** for each lens, re-run aggregation without it and measure
   concrete deltas — vote change, confidence/robustness/fragility/uncertainty
   deltas, tail-warnings lost, risk-block lost, coverage loss (unique evidence),
   evidence-diversity loss (distinct source keys), decision-stability delta.
3. **Characteristic value** `v(S)` over lens coalitions — a bounded [0,1] blend of
   coverage (unique evidence), robustness, tail-awareness, and certainty.
4. **Shapley value** — the average marginal contribution of a lens across all
   coalitions:
   - **EXACT** for ≤ 6 lenses: all `2^n` subsets are evaluated (64 for six lenses),
     `shapley_exact=true`. Reported as exact.
   - **APPROXIMATE** above six: deterministic permutation Monte-Carlo
     (`shapley_exact=false`). Never presented as exact.
5. **Pairwise interactions** (≤ 6 lenses): `v(AB) − v(A) − v(B) + v(∅)` →
   SYNERGY / REDUNDANCY / INDEPENDENT.

Stress is disabled during the coalition sweep so 64 council evaluations stay cheap
(~0.3–0.5 s total). Randomness in the approximate path comes from a seeded LCG,
so replay is exact.

## Outputs

`CouncilAblationResult`: per-lens `LensMarginalContribution` (with the deltas and
Shapley value above), `InteractionContribution` list, `most_valuable_lens`
(highest Shapley), and `quietest_valuable_lens` — the **Kanté lens**: high Shapley
*without* changing the headline vote. This is exactly the contribution ordinary
scorecards miss.

## Grounding prevented-failure claims

Prevented-failure and quiet-contribution events in the ledger are derived from
these ablations, so every such claim is backed by an **executable counterfactual**
(re-running the council without the lens), never an imagined one. If removing lens
L loses a tail warning, that is a measured fact about this run, not a guess.

## Determinism

Identical (observation, seed) → identical Shapley values and deltas (tested,
`test_ablation_deterministic`). Shapley values are bounded to [−1, 1] by
construction (tested).
