# Signal Reactor Model

> Advisory-only doctrine document. The MVP is not an oracle, an
> execution engine, or a broker. It is a controlled signal reactor and
> adaptive routing model whose only outputs are observations, labels,
> warnings, and review prompts.

## 1. Purpose

This document translates the latest reflection
(Chaos Theory → Pendulums → Digital Signs → Psychedelic Perception →
Slime Mold Networks → Nuclear Fission/Fusion → MVP Signal Reactor)
into sober, deterministic, advisory-only engineering components.

The runtime never uses the metaphor vocabulary. It uses professional
engineering names that describe what the code actually measures.

## 2. Doctrine (one-line truths)

- Signal is not truth.
- A beautiful pattern is still only a hypothesis.
- Echo is not confirmation.
- Absence of expected confirmation is itself a signal.
- Timing order is evidence.
- Belief may generate hypotheses; evidence must validate them.
- Ritual is risk control.
- Fission maps consequences; fusion builds theses.
- Criticality means self-sustaining, not automatically actionable.
- Waste must decay, archive, or teach.
- Energy never outranks containment.
- The operator is one of the pendulums.
- No signal bypasses the veto layer.

## 3. Mental models

### 3.1 N'Golo Kanté (defensive intelligence)

The MVP does not need to "score". It earns its rating by reading the
signal field earlier than the operator's emotions do, intercepting
bad decisions, closing risky passing lanes, and turning chaos into
boring recoveries.

```
MVP_Defensive_Rating =
    Interception_Quality
  * Field_Geometry_Read
  * Transition_Prevention
  * Waste_Prune_Rate
  * Echo_Suppression
  * Operator_Heat_Control
  * Safety_Lock
  * Test_Reality
```

If any factor collapses to zero, the rating collapses.

### 3.2 Controlled signal reactor

Raw signals are unstable material. They pass through:

- field geometry classification
- echo risk and source independence
- signal decay / half-life / waste classification
- fission branch mapping (explosive events)
- fusion thesis synthesis (independent weak evidence)
- operator control rods (heat, containment, meltdown risk)
- adaptive routing (nutrient, terrain, reinforcement, pruning)

before they ever become a review candidate. None of this is an
execution path.

### 3.3 Slime-mold adaptive routing

The MVP forages like slime mold: explore broadly, reinforce evidence-
rich routes, prune weak routes, avoid hostile terrain, preserve useful
redundancy, punish duplicate echo.

```
New_Route_Weight =
    Old_Route_Weight
  + Reinforcement
  - Decay
  - Terrain_Penalty
  - Echo_Risk
  - Contradiction
```

### 3.4 Pendulum field geometry

One signal is a pendulum. Many signals are a field. The MVP detects
convergence, divergence, resonance, damping, spikes, echoes, fan-out,
compression, chaotic field, and hidden accumulation.

## 4. Master formula

```
Decision_Grade_Energy =
    Signal_Energy
  * Evidence_Density
  * Criticality_Control
  * Fusion_Validity
  * Fission_Branch_Clarity
  * Containment_Strength
  * Operator_Clearance
  - Waste_Load
  - Meltdown_Risk
  - Echo_Risk
```

Supporting equations:

```
Meltdown_Risk          = Reaction_Heat - Containment_Capacity
Reaction_After_Control = Raw_Reactivity * (1 - Control_Rod_Insertion)
Signal_Strength(t)     = Initial_Strength * exp(-lambda * t)
True_Confirmation      = Independent_Source_Count / max(Total_Mentions, 1)
Pattern_Overfit_Risk   = Pattern_Beauty * Conviction * Low_Evidence * Low_Diversity
Fusion_Thesis_Strength = Evidence_Density * Signal_Temperature
                       * Confinement_Quality * Time_Durability * Independence
```

## 5. Architecture

```
flowchart LR
    RawSignal --> SignalFieldGeometry
    SignalFieldGeometry --> EchoRiskEngine
    EchoRiskEngine --> SignalDecayWaste
    SignalDecayWaste --> FissionBranchMapper
    SignalDecayWaste --> FusionThesisEngine
    FissionBranchMapper --> SignalReactor
    FusionThesisEngine --> SignalReactor
    OperatorControlRods --> SignalReactor
    AdaptiveSignalRouter --> SignalReactor
    SignalReactor --> HumanReview
    SignalReactor --> Quarantine
    SignalReactor --> WasteArchive
    SafetyLock --> SignalReactor
```

The arrows are pure-function calls inside the orchestrator
`scripts/signal_reactor.py`. No arrow leaves the MVP. No arrow
calls a broker. No arrow runs a paid live API. No arrow writes a
trade execution payload.

## 6. Translation table (reflection → engineering)

| Reflection concept            | Engineering component (runtime)    | Status | Risk if literal name leaked into runtime                                |
| ----------------------------- | ---------------------------------- | ------ | ----------------------------------------------------------------------- |
| Pendulum field                | `signal_field_geometry`            | P0     | Implies physics-level prediction; we only measure direction/timing fit. |
| Digital signs                 | `signal_field_geometry` traces     | P0     | Implies omens; we only label spikes, echoes, gaps.                      |
| Echo / repetition             | `echo_risk_engine`                 | P0     | Implies confirmation; we measure dependency, not truth.                 |
| Source independence           | `echo_risk_engine`                 | P0     | Implies certainty; we measure diversity, not validity.                  |
| Absence is a signal           | `absence_confirmation_gap` field   | P0     | Implies prophecy; we measure expected-vs-observed counts.               |
| Psychedelic perception        | `operator_control_rods`            | P0     | Implies altered-state reasoning; we measure operator heat only.         |
| Ritual                        | `process_compliance_score`         | P0     | Implies superstition; we measure checklist completion.                  |
| Slime-mold network            | `adaptive_signal_router`           | P1     | Implies biological optimality; we update simple route weights.          |
| Nutrient node                 | `nutrient_value`                   | P1     | Implies food; we measure evidence value.                                |
| Hostile terrain               | `terrain_penalty`                  | P1     | Implies geography; we measure source/legal/operator risk.               |
| Fission shock                 | `fission_branch_mapper`            | P0     | Implies blast permission; we only map consequences.                     |
| Fusion thesis                 | `fusion_thesis_engine`             | P0     | Implies certainty; we only score independence + density.                |
| Criticality                   | `decision_grade_energy` formula    | P0     | Implies actionability; criticality means self-sustaining, not allowed.  |
| Control rods                  | `operator_control_rods`            | P0     | Implies physical safety; we only block promotions, not the operator.   |
| Nuclear waste                 | `signal_decay_waste` waste manager | P0     | Implies hazardous material; we only flag stale/duplicate signals.       |
| Signal reactor (composite)    | `signal_reactor`                   | P0     | Implies live energy; we only produce an advisory diagnostic payload.    |

## 7. Naming discipline

### 7.1 Banned in runtime (module names, class names, function names)

`magic`, `magick`, `spell`, `sigil`, `occult`, `psychedelic`, `lsd`,
`dmt`, `mushroom`, `ayahuasca`, `oracle`, `prophecy`, `divine`,
`supernatural`, `cosmic`, `reactor_meltdown_button`.

These may appear in documentation only when explaining metaphor
translation. They must not appear in importable module paths,
class names, or function names. The existing
`scripts/reflection_frameworks.py` already enforces a banned-term
list; this sprint's safety-invariants test extends that discipline
to the new modules.

### 7.2 Required runtime field categories

Every new module output carries:

- a `safety` block with the canonical advisory stamps
- an `operator_action` string with one of:
  `observe`, `watch`, `review_candidate`, `review_later`,
  `map_branches`, `quarantine`, `decay_archive`, `cool_down`,
  `human_review_only`, `do_not_promote`
- a structured score (clamped to `0..1` unless a count)
- `reasons` (a list of short codes) when relevant

No new module emits a `buy`, `sell`, `execute`, `place_order`, or
`broker_payload` field. None.

## 8. Safety invariants (non-negotiable)

For every output dict from every new module:

```
output.advisory_status     == "ADVISORY_ONLY"
output.execution_gate      == "LOCKED"
output.broker_api_called   is False
output.ai_execution_count  == 0
output.execution_permission is False
output.can_execute         is False
```

Three downstream consequences:

1. The reactor may say `human_review_candidate`. It may never say
   `actionable`.
2. The reactor may produce a `decision_grade_energy` score above 0.9.
   That score remains advisory-only.
3. Observation is not permission. Hypothesis is not trade. Review
   candidate is not execution.

## 9. Runtime components

| Module                                 | Phase | Status this sprint |
| -------------------------------------- | ----- | ------------------ |
| `scripts/signal_field_geometry.py`     | P2    | implemented        |
| `scripts/echo_risk_engine.py`          | P3    | implemented        |
| `scripts/signal_decay_waste.py`        | P4    | implemented        |
| `scripts/fission_branch_mapper.py`     | P5    | implemented        |
| `scripts/fusion_thesis_engine.py`      | P6    | implemented        |
| `scripts/operator_control_rods.py`     | P7    | implemented        |
| `scripts/adaptive_signal_router.py`    | P8    | implemented        |
| `scripts/signal_reactor.py`            | P9    | implemented        |
| Reactor integration into reports / API | P10   | optional, deferred unless safe |

Each module is pure: no DB writes, no live APIs, no broker calls, no
filesystem writes except those owned by the existing safe writers.
The orchestrator `signal_reactor.py` is the only module that imports
the others, and it does so by name; failures in any subcomponent fall
back to `insufficient_data` rather than crashing.

## 10. Future work (out of this sprint)

- UI badges for `reactor_state`, `echo_risk_score`, `decision_grade_energy`.
- Calibration of thresholds on real historical data (only after a real
  self-test period has produced labeled outcomes).
- A `source_independence` graph that traces canonical-URL lineage across
  feeds.
- Persistence of stale/quarantine waste counts in a read-only diagnostic
  table — only if a clean migration path is available.

Nothing here implies broker execution, AI execution, or hosting.

## 11. One-line truth

The MVP is a signal reactor that can read the field, label the trace,
mark the echo, decay the waste, map the shock, fuse only what is
independent, insert control rods when the operator is hot — and it
still does not execute a trade.
