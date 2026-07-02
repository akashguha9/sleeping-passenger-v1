# Chicken Gate Consolidation Map

**Canonical owner of the freshness + asymmetry + node-evidence gate:**
`scripts/chicken_gate.py` (SCORING_PROFILE_VERSION `chicken-gate-v1.1`).

Rule: any module below that overlaps a chicken-gate concept is either a
**source** the gate imports, an **adapter target**, or a **future port**.
Do not add a second gate. Do not re-implement decay, crowding, or lateness
math outside the sources named here.

Actions: `KEEP_AS_SOURCE` (gate imports it), `WRAP_WITH_ADAPTER` (gate
consumes its output shape), `FUTURE_PORT` (useful, lives on another branch
or not yet wired), `DEPRECATE` (superseded; do not extend), `IGNORE`
(name-overlap only, different concern).

## On this branch (live-data-config-sprint)

| Module | Concept | Canonical owner | Used by chicken_gate? | Action |
|---|---|---|---|---|
| `scripts/signal_decay_waste.py` | exponential decay engine, half-life math, waste classes | signal_decay_waste | **YES** — `compute_decay_factor` is the freshness engine | KEEP_AS_SOURCE |
| `scripts/crowding_detector.py` | crowding score, full-moon trap flag | crowding_detector | **YES** — derives IAP from crowding inputs | KEEP_AS_SOURCE |
| `scripts/late_adoption_lockout.py` | LALO parrot-ceiling, late-entry states | late_adoption_lockout | **YES** — LALO score maps to IAP; LOCKED_OUT escalates to hard block | KEEP_AS_SOURCE |
| `scripts/advisory_contract.py` | safety stamp vocabulary | advisory_contract | **YES** — the only safety stamp source | KEEP_AS_SOURCE |
| `data/daily_payload/verified_current_holdings.json` | canonical OPEN-position truth | daily_payload | **YES** — operator-fit adapter (`load_verified_holdings`) | KEEP_AS_SOURCE |
| `scripts/candidate_memory_decay_v2.py` | exp(-lambda*d) candidate decay | chicken_gate (for gate-path decay) | no — same math, candidate-board scope | IGNORE (different consumer; do not extend for gating) |
| `scripts/narrative_inflation_index.py` | conclusion-scope vs evidence-scope inflation | narrative_inflation_index | no — label-premium *estimation* input, upstream of the gate | WRAP_WITH_ADAPTER (feed its NII into `label_premium`) |
| `scripts/narrative_distortion_index.py` | circulating-narrative distortion | narrative_distortion_index | no | WRAP_WITH_ADAPTER (candidate `spoilage_risk` input) |
| `scripts/signal_lifecycle_tracker.py` | IGNITION..CLOSURE stage labels | signal_lifecycle_tracker | indirectly (stage feeds LALO) | KEEP_AS_SOURCE (via LALO) |
| `scripts/composite_edge_score.py` | CE weighted synthesis of pipeline scores | composite_edge_score | no — parallel scorer for the S-pipeline | IGNORE (different pipeline; chicken_gate does NOT replace CE) |
| `scripts/milk_test_uso_removal.py`, `scripts/milk_test_polymarket_history.py` | ground-truth (Milk Test) probes | milk_test_* scripts | no — evidence generators, not gate math | KEEP_AS_SOURCE (their findings justify component confidences) |
| `scripts/fresh_discovery_contract.py` | provenance gate for fresh candidates | fresh_discovery_contract | no — upstream discovery gate | IGNORE (runs before chicken_gate, different question) |
| `scripts/signal_arbitrage/` (ceiling, mythos, strategist) | multiplicative reality gating, `final <= merit` | signal_arbitrage | no direct import — chicken_gate carries the same invariant | IGNORE (doctrine sibling; keep invariants aligned) |
| `scripts/asymmetry_survival_scorer.py` | asymmetry survival scoring | asymmetry_survival_scorer | no | FUTURE_PORT (candidate extra IAP evidence slot) |
| `scripts/anti_staleness.py` | freshness labels / novelty enforcement (daily payload) | anti_staleness | no — payload freshness, not thesis freshness | IGNORE |
| `scripts/execution_quality_scorer.py` | execution-rail quality | execution_quality_scorer | no — payment-rail axis carries zero gate weight by doctrine | IGNORE |
| `scripts/contextual_interpretation_engine.py` | interpretation quality | contextual_interpretation_engine | no | IGNORE (interpretation front-end, not gating) |

## Stranded on `feature/p2-interpretation-defense-expansion`

| Module (branch path) | Concept | Overlap with chicken_gate | Action |
|---|---|---|---|
| `scripts/signal_half_life_estimator.py` | SNACK/SIGNAL/DURABLE edge durability, half-life priors | **Word lists + 3/21/90d priors PORTED** into `chicken_gate.derive_half_life_from_catalyst_text` (v1.1). Full candidate-level estimator (structural/fundamental/falsifiability weighting) still on branch | FUTURE_PORT (full module); ported subset is canonical in chicken_gate |
| `scripts/signal_payoff_capture_estimator.py` | "gross is not net" value capture, WEAK_CAPTURE cap | chicken_gate's NET_EDGE + friction covers the gate-level slice | FUTURE_PORT (richer capture decomposition) |
| `scripts/wrapper_premium_value_scorer.py` | wrapper-premium pre/post/delta company scorer | overlaps `label_premium` estimation (can move scores up — NOT gate-compatible; gate is demote-only) | FUTURE_PORT as *input estimator only*; its outputs may set `label_premium`/`label_authenticity_score`, never gate multipliers |
| `scripts/interpretation_defense_engine.py` + `interpretation_quality_score.py` (IDS P2 stack) | narrative-substance gap, incentive, audience misread — demote-only | overlaps `label_authenticity_score` estimation | FUTURE_PORT (feed IDS narrative-substance gap into `label_authenticity_confidence`) |

**Why not try/except adapter imports now:** those modules do not exist on
this branch, so a guarded import would be permanently-dead code here. The
one piece with immediate gate value (catalyst-text durability word lists)
was ported directly instead. When the branch merges, wire the full modules
as *input estimators* per the table — they compute evidence, chicken_gate
stays the only gate.

## Ownership summary

- **Decay math:** `signal_decay_waste` owns it; chicken_gate consumes.
- **Crowding/lateness evidence:** `crowding_detector` + `late_adoption_lockout` own it; chicken_gate maps to IAP.
- **Gate arithmetic, hard flags, caps, ledger:** `chicken_gate` owns it, exclusively.
- **Safety stamps:** `advisory_contract` owns them.
- **Holdings truth:** `data/daily_payload/verified_current_holdings.json` owns it; chicken_gate reads via `load_verified_holdings` (opt-in `use_verified_holdings` for determinism).
- Nothing in this repo may implement a second BUY_ALLOWED/BUY_LIMITED/WATCHLIST/BUY_BLOCKED gate.
