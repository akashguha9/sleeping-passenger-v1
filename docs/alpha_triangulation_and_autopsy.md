# Triangulation, Blind Testing, and the Alpha Autopsy

Advisory-only. These are diagnostic layers: they classify and explain;
they never instruct.

## Triangulation (`src/alpha/triangulation.py`)

A signal is only as credible as the independence of its supports.

```text
Triangulation =
  100 × weighted_mean(
    source_independence,      # how many independent layers exist (of 4)
    cross_source_agreement,   # 100 − mean pairwise support gap
    evidence_hardness,        # filing proof level
    value_chain_alignment,    # node attractiveness
    replay_support            # calibration_support (meta-layer)
  )
  − contradiction_penalty     # 0.5 × contradiction_score
```

Independent layers: narrative, prediction market, filings, value chain.
Replay calibration is meta-support, not a source. Contradictions are
explicit and named: loud narrative vs weak filings (+40), loud narrative
vs heavy risk disclosures (+30), prediction market pricing against the
narrative (+20), hard proof shadowed by severe disclosures (+20).

Classes: `single_source_hype`, `weakly_supported`, `mixed_evidence`,
`quiet_food_chain_candidate`, `strongly_triangulated`, `contradicted`.

Integration into opportunity v2:
- contradiction shrinks the opportunity score (×(1 − 0.3·c/100));
- agreement boosts confidence **only when ≥2 independent layers exist**
  — one loud source agreeing with itself moves nothing;
- the weakest link is appended to `why_not_higher`.

## Blind-test differential (`src/alpha/blind_test.py`)

```text
Narrative Contribution = Labelled Score − Blind Score
```

The blind pass neutralizes only the story's positive channel
(`narrative_velocity` → 50); casino distortion stays because the market
environment does not vanish when the auditor is blindfolded. Survival is
a 25-point floor on the blind score. Classes:

```text
story_carried          story props it up AND it fails blind
narrative_supported    story helps, signal survives without it
narrative_independent  the story barely moves the score
narrative_understated  blind scores HIGHER — quiet reality
```

Measured structural property (test-enforced): the v2 geometric mean
bounds single-factor influence, so even a 95-velocity narrative
contributes under 15 points — the engine is near-blind by construction.

## Alpha autopsy (`src/alpha/autopsy.py`)

The system explaining itself to a hostile auditor, with every claim
traceable:

- **what_survives_blind_test** — from the measured differential, not a
  heuristic;
- **what_was_only_casino** — story contribution, casino distortion,
  attention-ahead-of-proof;
- **embedded_proof / missing_proof** — filing lineage lines, explicitly
  negated claims, absent inputs;
- **calibration_state** — which gate tier the verdict sat behind;
- **verdict_explanation** — the top `why_not_higher` drivers;
- **next_evidence_to_collect** — deterministic gap-driven list (resolve
  journal outcomes, segment-revenue disclosure, weakest triangulation
  layer, narrative snapshots, prediction-market quote).

Surfaces: `POST /alpha/autopsy` (token-gated) and the "Alpha Autopsy"
dashboard panel, populated by the plumbing v3 case study.
