# Alpha Framework — Final Boss Pass: Self-Auditing Advisory Intelligence

Advisory-only. Not financial advice. No trade execution, ever. The
system classifies, explains, and audits itself; humans decide.

This pass closes the loop the first two phases left open: outcomes from
the operator's own journal now feed calibration, calibration gates
verdicts, every layer of evidence is triangulated, and the system can
write its own autopsy for a hostile auditor.

## What was added

| Upgrade | Module |
|---|---|
| A | `src/alpha/journal_replay_bridge.py` + `scripts/build_alpha_replay_from_journal.py` + `POST /alpha/replay/from-journal` |
| B | `apply_calibration_gate` in `src/alpha/opportunity.py` |
| C | `score_residual_utility_v2` (JTBD / failure-cost / substitution) |
| D | Negation & risk guard in `src/alpha/filing_parser.py` |
| E | `src/alpha/adapters/narrative_snapshot_adapter.py` |
| F | `src/alpha/triangulation.py`, integrated into opportunity v2 |
| G | `src/alpha/autopsy.py` + `POST /alpha/autopsy` |
| H | `build_plumbing_case_study_v3` (full-stack node profiles) |
| Surprise | `src/alpha/blind_test.py` — measured blind-test differential |

## A/B. Journal → replay → calibration → verdicts

The repo's existing `outcome_evidence_extractor` (manual trades +
reconciliations + Moltbook, read-only) feeds the bridge. Resolved
WIN/LOSS/BREAKEVEN outcomes become replay records with full lineage;
open/unknown outcomes and synthetic fixtures are skipped with counted
reasons. Probabilities are score proxies on calibration-eligible records
only, stamped `probability_derivation: score_proxy` — the same
score→outcome treatment `scripts/calibration_map.py` already applies.

```text
Brier = (p − y)^2
precision@k = true_positive_top_k / k
calibration_support = 100 × min(1, resolved_probability_records / 50)
outcome_coverage = usable_replay_records / max(1, discovered_records)
calibrated_confidence =
  base_confidence × (0.5 + 0.5 × calibration_support/100) × outcome_coverage
```

The calibration gate (tiers, all advisory-only):

```text
support < 10   : verdicts cap at deep_research
10 ≤ s < 30    : small_position_candidate only with score ≥ 45,
                 confidence ≥ 60, evidence ≥ 60, no severe trap flags
30 ≤ s < 60    : full ladder + explicit calibration-limited warning
s ≥ 60         : full advisory ladder
severe traps   : override every tier, cap at watchlist
```

No tier produces execution language; the gate's explanation says so in
every response.

## C. Residual utility v2

```text
Residual Utility = normalize(
  Necessity × FailureCost × Frequency × SwitchingCost
  × WillingnessToPay × BoringButEssential
  / (1 + SubstitutionRisk + NarrativeDependency)
)
```

Necessity types map survival 100 → speculation 10. Classes:
`apex_necessity` (plumbing), `durable_utility` (Ryanair-style transport,
sticky SaaS), `convenience_utility`, `status_utility` (a well-formed
logo collab), `speculative_utility` (memecoin), `weak_utility` (an ugly
logo collab). One dead factor collapses the job — geometric mean.

## D. Filing negation & risk guard

Token-window rules (8 tokens before the cue): negators (`not, no,
never, without, …`) reject evidence and record the line under
`negated_statements`; modals (`may, could, might, …`) reclassify
positive cues as `forward_looking_claims` (claims, not proof); negated
risk cues ("no material customer concentration") become
`risk_mitigations`, each offsetting 0.25 of risk load. "We may face
supplier dependency" stays a risk disclosure. Line-number lineage is
preserved for every category including rejections.

## E. Narrative snapshots

```text
mention_velocity = (mentions_current − mentions_previous) / max(1, previous)
source_diversity_score = 100 × min(1, unique_sources / 8)
```

Velocity saturates via x/(1+|x|) so a 10× spike stays bounded.
Confidence is diversity-led: a single-source spike of any size is
low-confidence by construction.

## F. Triangulation

```text
Triangulation = 100 × weighted_mean(source_independence,
  cross_source_agreement, evidence_hardness, value_chain_alignment,
  replay_support) − contradiction_penalty
```

Classes: `single_source_hype`, `weakly_supported`, `mixed_evidence`,
`quiet_food_chain_candidate` (weak narrative + strong filings + value
chain — the residual-utility hunting ground), `strongly_triangulated`,
`contradicted`. Integrated into opportunity v2: contradiction shrinks
the score; agreement boosts confidence **only when sources are
independent (≥2)**; the weakest link lands in `why_not_higher`.

## Surprise: the blind-test differential

The original reflection's Module 4 ("hide ticker, brand, narrative
before scoring") was never built — Phase 3 builds it as a *measurement*:
score the same evidence twice, labelled vs narrative-neutralized, and
report `Narrative Contribution = Labelled − Blind` with survival against
a 25-point floor. Classes: `story_carried` (the story is the only thing
keeping it alive), `narrative_supported`, `narrative_independent`,
`narrative_understated` (blind scores HIGHER — quiet reality).

A structural property this made testable: the v2 geometric mean bounds
any single loud factor, so the engine is *near-blind by construction* —
a hype-only signal gains under 15 points from its story, and the
differential proves it in tests rather than asserting it in prose.

## G/H. Autopsy and plumbing v3

`build_alpha_autopsy` produces the hostile-auditor view: what survives
blind testing (measured), what was only casino, proof with line-level
lineage, explicitly negated claims, calibration state, verdict
explanation, and the exact next evidence to collect. The plumbing v3
case study runs the entire stack (narrative snapshot → prediction-market
stub → filing excerpt → triangulation → journal calibration →
opportunity v2 → autopsy) over three node profiles: plumbers/contractors
(`apex_necessity`, food-chain-heavy), valves (`apex_necessity`,
bottleneck), smart leak sensors (`durable_utility`, higher casino energy
and proof risk). Under the isolated test journal all verdicts honestly
cap at research grade.

## Why the system still does not execute trades

Execution is not a missing feature; it is a refused capability. Every
route is advisory-stamped and token-gated, the AST/route-table tests
forbid execution surfaces, the calibration gate's ceiling is an advisory
container, and the compliance preflight verifies no broker route exists.
A score is a research classification, not an instruction.

## What remains before scores can go above 9

1. Real reconciled outcomes flowing through the bridge (the machinery is
   live; the journal history is not yet large enough to matter).
2. Live narrative and filing ingestion (adapters are offline-snapshot).
3. Multiple full replay cycles with out-of-sample verification.
4. Language-aware filing parsing beyond token-window rules.
5. Independent review of every threshold against observed outcomes.
