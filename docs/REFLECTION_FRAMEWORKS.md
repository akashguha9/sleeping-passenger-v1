# Reflection Frameworks: Nonlinear Signal Systems, Resilience, and Reaction Control

> **Status:** internal framework document. Not implementation. Not a feature
> announcement. The MVP remains advisory-only.
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `broker_order_id = NONE` · `execution_permission = false` ·
> `can_execute = false`

## 0. Executive Summary

This document distills a forensic reflection (biological, physical, military,
probabilistic, and symbolic metaphors) into sober engineering principles for
the MVP. The core lesson is:

> The MVP should behave like a resilient nonlinear advisory organism, not a
> simple signal engine.

In operational terms, the MVP should:

- detect input fragility (small perturbations should not flip a signal)
- avoid single-signal overconfidence (rhythm and distribution beat spikes)
- separate observation from action (perception is not permission)
- quarantine toxic signals (absorb, label, decay — never just delete)
- survive degraded source conditions (continuity mode over heroics)
- preserve hard advisory-only boundaries (some lines are survival lines)
- regulate reaction rather than chase noise (see the signal, block the reflex)

**Doctrine — one line:**

> Observe everything, execute nothing, promote only what survives perturbation,
> distribution, boundary, and contamination checks.

Nothing in this document grants execution permission to any code path. The
existing safety invariants are canonical and outrank any framework here.

---

## 1. Core Insights

The reflection produces 13 mechanism-level insights. Each is rewritten in
engineering language, given a candidate professional name, a measurable
formula, a status against the current MVP, and a recommended action.

### Insight 1 — Chaos sensitivity belongs inside the MVP

- **Engineering translation:** A signal whose downstream classification flips
  under a ±1–5% perturbation of its numeric inputs is fragile and must not be
  trusted as a high-conviction recommendation.
- **Candidate field/module:** `chaos_sensitivity_score` /
  `signal_sensitivity_diagnostics`
- **Formula:** `Chaos Sensitivity = Recommendation Variance / Input Perturbation Size`
- **Status:** missing (durability and contradiction layers exist, but no
  explicit perturbation diagnostic).
- **Recommended action:** P1 — document now, implement later as a deterministic
  perturbation runner on the deterministic scoring path.

### Insight 2 — Existing chaos logic without perturbation diagnostics is incomplete

- **Engineering translation:** Durability scoring, contradiction checks, and
  operator-state filters are necessary but not sufficient. They guard against
  some failure modes, not against classification fragility.
- **Candidate field/module:** `signal_sensitivity_diagnostics`
- **Formula:** Same as Insight 1, applied across the existing scoring chain.
- **Status:** partly present — coverage is real but uneven.
- **Recommended action:** P1 — add a single perturbation harness rather than
  retrofitting each scorer.

### Insight 3 — Narrative resonance, not "Higgs turbulent resonance"

- **Engineering translation:** When narrative intensity, attention velocity,
  crowded positioning, and macro stress align, a single marginal signal can
  produce outsized response. Measure the amplification surface, not the
  metaphor.
- **Candidate field/module:** `narrative_resonance_score` /
  `amplification_risk_score`
- **Formula:** `Amplification Risk = Narrative Intensity × Attention Velocity × Crowded Positioning × Macro Stress`
- **Status:** missing as a labeled score; pieces exist across EMS/EQS.
- **Recommended action:** P2 — document the math; do not ship a "resonance
  module" with theatrical naming.

### Insight 4 — Chaos Magick as epistemology only

- **Engineering translation:** Useful idea: hold multiple incompatible frames
  and discount any decision whose outcome depends on choice of frame. Useless
  idea: occult branding on a journal product.
- **Candidate field/module:** `paradigm_shift_audit` /
  `cross_frame_stability` / `operator_belief_lens`
- **Formula:** `Decision Confidence = Signal Strength × Cross-Frame Stability × (1 - Operator Desire Distortion)`
- **Status:** missing.
- **Recommended action:** P2 — documentation only. No module named after an
  esoteric tradition is allowed in the repo.

### Insight 5 — Termite mound resilience

- **Engineering translation:** Distributed redundancy, compartmentalization,
  drainage paths, and local self-repair beat heroic single-point recovery. The
  MVP's source mesh should fail gracefully when any single source dies.
- **Candidate field/module:** `colony_resilience_score` /
  `resilience_diagnostics` / `signal_path_redundancy`
- **Formula:** `Shock Survival = Redundancy + Compartmentalization + Drainage + Local Repair + Command Continuity`
- **Status:** partly present (`source_health`, multi-source fanout).
- **Recommended action:** P2 — document; implement only as a small score on
  top of existing source-health data.

### Insight 6 — Sinoatrial node / signal pacemaker

- **Engineering translation:** Rhythm of confirmation matters more than any
  single spike. A signal that arrives clean but stays clean across a few
  refresh cycles is worth more than a single dramatic hit.
- **Candidate field/module:** `signal_rhythm_integrity` / `arrhythmia_risk_score`
- **Formula:** `Rhythm Integrity = Pulse Consistency × Source Synchrony × Temporal Durability × (1 - Noise Arrhythmia)`
- **Status:** partly present in `LIVE_SIGNALS_REFRESH_MODEL`.
- **Recommended action:** P2 — turn the refresh-cadence data into an actual
  rhythm score before adding new spike detectors.

### Insight 7 — Penguins / equator hard boundary

- **Engineering translation:** Some lines are not crossed even when the
  opportunity case is overwhelming. Boundary violations void permission
  regardless of signal strength.
- **Candidate field/module:** `boundary_condition_gate` / `policy_veto` /
  `execution_permission_gate`
- **Formula:** `If Signal Strength > 0.95 AND Boundary Violation = 1 THEN NO ACTION`
- **Status:** **existing, canonical.** The advisory-only safety lock is
  precisely this.
- **Recommended action:** P0 — preserve unchanged. Never weaken.

### Insight 8 — Galton board / distribution emergence

- **Engineering translation:** One observation is noise. A distribution of
  observations across sources, time, and frames reveals structure. Decisions
  should be based on emerging shape, not single balls.
- **Candidate field/module:** `distribution_shift_score` /
  `pattern_emergence_score`
- **Formula:** `Pattern Confidence = Sample Size × Source Diversity × Directional Consistency × Temporal Persistence × (1 - Correlation Illusion)`
- **Status:** missing.
- **Recommended action:** P1 — implement later as a deterministic histogram
  comparison against a baseline window.

### Insight 9 — Painkiller / amplification pathway

- **Engineering translation:** Loud pain (a screaming signal) is rarely the
  root cause. Treat the pathway that amplifies it: positioning, narrative,
  perception sensitivity — not the symptom.
- **Candidate field/module:** `amplification_pathway_filter`
- **Formula:** `Signal Pain = Real Event × Amplification Pathway × Perception Sensitivity`
- **Status:** missing.
- **Recommended action:** P1 — document; flag, do not auto-suppress.

### Insight 10 — E-4B Nightwatch / continuity-of-command

- **Engineering translation:** When the world degrades, the system should not
  attempt heroic full functionality. It should switch to a smaller, safer,
  legible mode that still gives the human something to work with.
- **Candidate field/module:** `continuity_mode` / `safe_advisory_mode` /
  `last_known_good_snapshot`
- **Formula:** `If System Integrity < threshold THEN Mode = SAFE_ADVISORY_CONTINUITY`
- **Status:** partly present (advisory lock; source-health degradation
  surfaced; no explicit "continuity mode" label).
- **Recommended action:** P1 — add an explicit mode indicator; UI should
  label degraded state clearly.

### Insight 11 — Mitochondria / signal metabolism

- **Engineering translation:** Signals are not free. Each one consumes attention
  and time. Apply stress-test, repair, quality control, and fate logic so weak
  signals decay and don't linger.
- **Candidate field/module:** `signal_metabolism_diagnostics` /
  `stale_signal_clearance`
- **Formula:** `Signal Value = Energy Worthiness × Stress Safety × Repairability × (1 - Toxicity)`
- **Status:** missing.
- **Recommended action:** P2 — implement only after enough longitudinal
  signal history exists to make decay measurable.

### Insight 12 — Sunflower phytoremediation / toxic-signal quarantine

- **Engineering translation:** Toxic signals (recycled narratives, low-source
  reliability, AI-invalid payloads, high contradiction) should not be deleted.
  They should be quarantined, labeled, studied, decayed, archived, or blocked.
- **Candidate field/module:** `toxic_signal_quarantine` / `contamination_score`
- **Formula:** `Signal Safety = Validation × Reliability × (1 - Contamination)` →
  `Toxic Signal → Quarantine → Label → Study → Decay / Archive / Block`
- **Status:** missing as an explicit state.
- **Recommended action:** P1 — add a `quarantine_state` column or derived
  field, then a UI tag.

### Insight 13 — Botox / targeted reaction inhibition

- **Engineering translation:** Seeing the signal does not authorize action.
  The transmission line between perception and action must be inhibitable on
  purpose, by policy, not by accident.
- **Candidate field/module:** `reaction_inhibition_gate` /
  `action_transmission_gate`
- **Formula:** `If Signal Seen AND Action Transmission Allowed = 0 THEN Observe, Do Not Act`
- **Status:** **existing, canonical.** Same safety lock as Insight 7, viewed
  from the action side.
- **Recommended action:** P0 — preserve unchanged.

---

## 2. Mental Models

Each model below is restated as something the codebase could plausibly
implement, with status against the current MVP.

| Model | Definition | MVP Use | Formula (sketch) | Status | Risk if implemented badly |
|---|---|---|---|---|---|
| Sensitive Dependence | Tiny input changes can flip outputs. | Pre-promotion stability check. | `dy/dx` over perturbation budget. | missing | False stability claims if perturbation grid is too coarse. |
| Signal Fragility | A signal's classification stability under noise. | Score, not a gate. | 1 − flip rate. | missing | Over-blocking real signals if threshold is reactive. |
| Narrative Resonance | Amplification surface around a story. | Caution flag. | See Insight 3. | missing | Suppressing legitimate stories that happen to be loud. |
| Belief-as-Tool | Multiple frames evaluated in parallel. | Decision discount. | Frame-agreement ratio. | missing | Endless frame proliferation; analysis paralysis. |
| Paradigm Shift Audit | Detect when the base frame has changed. | Flag, not act. | Frame-distribution drift. | future | Confusing regime change with noise. |
| Colony Resilience | Source mesh fails gracefully. | Source-health roll-up. | See Insight 5. | partial | Overrating redundancy when sources are correlated. |
| Flood-Resistant Architecture | Compartmentalization survives shock. | DB / API isolation. | Blast-radius score. | partial | Premature microservice cost on a local MVP. |
| Signal Pacemaker | Rhythm of confirmation matters. | Score promotions. | See Insight 6. | partial | Penalizing rare-but-real signals. |
| Arrhythmia Detection | Identify rhythm breakage. | Flag. | Pulse variance. | missing | Noisy alerts during low-volume windows. |
| Hold-the-Line Boundary | Hard policy line. | Veto. | Boolean. | existing | Weakening for "obvious" cases. |
| Distribution Emergence | Many balls beat one ball. | Score. | See Insight 8. | missing | Overclaiming structure on small n. |
| Pathway Intervention | Treat amplifier, not symptom. | Diagnostic, not act. | See Insight 9. | missing | Hiding real pain. |
| Continuity-of-Command | Safer when degraded. | Mode switch. | See Insight 10. | partial | "Continuity" becoming the only mode. |
| Signal Metabolism | Energy, repair, fate. | Decay model. | See Insight 11. | missing | Killing slow-burn signals too early. |
| Stale Signal Clearance | Decay over time. | Sweeping job. | TTL × confirmation factor. | missing | Confusing slow-arriving truth with staleness. |
| Phytoremediation | Toxic signals are quarantined. | State, not delete. | See Insight 12. | missing | Quarantine becomes a graveyard. |
| Targeted Inhibition | Perception ≠ permission. | Gate. | See Insight 13. | existing | Cannot be implemented "badly"; only weakened. |

---

## 3. Case Studies as Engineering Analogies

> Each case study is a metaphor source. The *mechanism* is portable. The
> *naming* is not. Repo-safe names are deliberate.

### 3.1 Ten pendulums separated by 1 degree
- **Metaphor:** chaotic divergence from near-identical initial conditions.
- **Usable mechanism:** small perturbation → classification variance.
- **Repo-safe name:** `signal_sensitivity_diagnostics`.
- **Do NOT name:** `chaos_pendulum.py`, `lorenz_engine.py`.
- **Implication:** add a perturbation harness on the deterministic scorer.

### 3.2 "Higgs turbulent resonance"
- **Metaphor:** field that amplifies surrounding mass.
- **Usable mechanism:** amplification model with measurable factors.
- **Repo-safe name:** `narrative_resonance_score` / `amplification_risk_score`.
- **Do NOT name:** `higgs_turbulent_resonance.py`.
- **Implication:** compute a single composite amplification factor; flag, do
  not block.

### 3.3 Chaos Magick
- **Metaphor:** belief as a swappable lens.
- **Usable mechanism:** frame-pluralism penalty against frame-dependent
  conviction.
- **Repo-safe name:** `paradigm_shift_audit` / `cross_frame_stability`.
- **Do NOT name:** `chaos_magick.py`, `spell_engine.py`, `occult_signal_layer.py`.
- **Implication:** documentation-only at MVP stage.

### 3.4 Termite mounds
- **Metaphor:** distributed resilient architecture.
- **Usable mechanism:** redundancy, compartmentalization, drainage, repair.
- **Repo-safe name:** `resilience_diagnostics`.
- **Do NOT name:** `termite_engine.py`, `colony_mound.py`.
- **Implication:** roll up existing source-health into a resilience score.

### 3.5 Sinoatrial node
- **Metaphor:** small node sets macro rhythm.
- **Usable mechanism:** rhythm-of-confirmation measurement.
- **Repo-safe name:** `signal_rhythm_integrity`.
- **Do NOT name:** `sinoatrial_pacemaker.py`.
- **Implication:** rhythm score over the refresh-cadence history.

### 3.6 Penguins / equator
- **Metaphor:** a hard line that is never crossed.
- **Usable mechanism:** policy veto regardless of opportunity.
- **Repo-safe name:** `boundary_condition_gate`.
- **Do NOT name:** `penguin_gate.py`, `equator_lock.py`.
- **Implication:** the existing advisory-only lock IS this. Preserve.

### 3.7 Galton board
- **Metaphor:** distribution emerges from many trials.
- **Usable mechanism:** histogram comparison against baseline.
- **Repo-safe name:** `distribution_shift_diagnostics`.
- **Do NOT name:** `galton_board.py`.
- **Implication:** later phase; requires history depth.

### 3.8 Painkillers
- **Metaphor:** block the amplification pathway, not the symptom.
- **Usable mechanism:** pathway filter score.
- **Repo-safe name:** `amplification_pathway_filter`.
- **Do NOT name:** `painkiller.py`, `nsaid_engine.py`.
- **Implication:** scoring component; never a suppressor.

### 3.9 E-4B Nightwatch
- **Metaphor:** continuity of command under degradation.
- **Usable mechanism:** explicit degraded-safe operating mode.
- **Repo-safe name:** `continuity_mode`.
- **Do NOT name:** `nightwatch.py`, `e4b_command.py`.
- **Implication:** add a mode flag and clear UI label.

### 3.10 Mitochondria
- **Metaphor:** energy, repair, quality control, fate.
- **Usable mechanism:** decay and fate logic for signals.
- **Repo-safe name:** `signal_metabolism`.
- **Do NOT name:** `mitochondria.py`, `atp_engine.py`.
- **Implication:** later; needs history depth.

### 3.11 Sunflowers absorbing contaminants
- **Metaphor:** bad signals are absorbed, not erased.
- **Usable mechanism:** quarantine state with explicit lifecycle.
- **Repo-safe name:** `toxic_signal_quarantine`.
- **Do NOT name:** `sunflower_radioactivity.py`, `phytoremediation.py`.
- **Implication:** add a `quarantine_state` derived field; never auto-delete.

### 3.12 Botox
- **Metaphor:** block the action transmission, leave perception intact.
- **Usable mechanism:** explicit reaction inhibition.
- **Repo-safe name:** `reaction_inhibition_gate`.
- **Do NOT name:** `botox_gate.py`, `neurotoxin_layer.py`.
- **Implication:** the advisory-only lock IS this, on the action side. Preserve.

---

## 4. Errors / Failure Modes

These are the failure modes the reflection itself warns against — treat them
as anti-patterns when reading this document and any future PR.

1. **Literal pseudo-scientific naming creates fake sophistication.**
   `higgs_turbulent_resonance.py` is impressive-looking and tells you nothing
   measurable. Reject on sight.
2. **Occult branding makes the repo unserious.** The product is an advisory
   journal. Naming code after spells, rituals, or esoteric traditions
   undermines every safety claim the repo has earned.
3. **Single-signal overconfidence.** A loud signal is not a true signal.
4. **Loud pain is not root cause.** The visible spike is rarely the place to
   intervene.
5. **Crisis should not increase confidence.** Under degradation, conviction
   should *fall*, not rise.
6. **Toxic signals should not simply be erased.** Erasure destroys learning
   data; quarantine preserves it.
7. **Blocking all signals is not discipline.** Discipline is selective
   refusal, not generalized refusal.
8. **Urgency is not authorization.** Speed pressure is not a green light.

---

## 5. Signals vs Noise

The reflection contains both high-value insights and theatrical residue. The
table separates them so future readers can extract value without inheriting
the noise.

| Category | Examples | What to do |
|---|---|---|
| High-value insights | Sensitivity, distribution emergence, hard boundary, quarantine, continuity mode, reaction inhibition. | Translate into diagnostics; preserve safety invariants. |
| Repeatable frameworks | Perturbation runner, histogram diff, quarantine state machine, mode flag. | Implement deterministically; add tests. |
| Structural patterns | Resilient mesh, rhythm score, pathway filter. | Document; implement after foundations are stable. |
| Theatrical residue to avoid | Higgs, Chaos Magick, Botox, penguins, termites, sunflowers as filenames. | Never as module/file names. Translate into measurable names. |

> Rule: **Metaphors are inputs to engineering translation, not code names.**

---

## 6. Strategic Principles

The 13 principles, restated in operational form:

1. **Small shocks can create macro divergence.** Assume sensitivity until
   proven otherwise.
2. **Do not trust signals that flip under small perturbations.** Stability
   under noise is a feature.
3. **Extract mechanism, discard theatrical naming.** Always.
4. **Belief is a lens, not a fact.** Conviction must survive frame-swap.
5. **A resilient system has many tunnels.** Source diversity is structural.
6. **Rhythm matters more than spikes.** Confirmation cadence > single hit.
7. **Some lines are survival boundaries.** The advisory-only lock is one.
8. **One ball is random; many balls reveal distribution.** Score on shape.
9. **Treat amplification pathways, not symptoms.** Where the volume comes
   from matters more than the volume.
10. **When the world breaks, simplify command.** Continuity > completeness.
11. **Signals require metabolism.** They cost attention; they should decay.
12. **Toxic signals must be quarantined.** Never deleted; never promoted.
13. **See the signal, block the reflex.** Perception is not permission.

---

## 7. Candidate Framework Components

Twenty candidate components, each evaluated for whether it belongs in the
MVP **now**, **later**, or **only as documentation**. None of these grant
execution permission; all are diagnostics or display states.

| # | Component | Purpose | Operationalization | Formula (sketch) | Input fields | Output fields | When |
|---|---|---|---|---|---|---|---|
| 1 | Chaos Sensitivity Diagnostic | Detect classification fragility. | Perturb numerics ±1/3/5%; rerun deterministic scorer; count flips. | `flips / trials` | numeric signal payload, classifier | `chaos_sensitivity_score`, `classification_stability_score` | later |
| 2 | Narrative Resonance Score | Flag amplification surface. | Composite of intensity × velocity × crowding × stress. | See Insight 3. | EMS components, attention proxy, regime tags | `narrative_resonance_score` | later |
| 3 | Paradigm Shift Audit | Detect base-frame change. | Frame-distribution drift over windows. | KL-style frame drift. | frame tags over time | `paradigm_shift_flag` | doc only |
| 4 | Operator Belief Lens | Discount frame-dependent conviction. | Compute per-frame score, take min/median. | `min(frame_scores)` | per-frame scores | `operator_desire_distortion_score` | doc only |
| 5 | Colony Resilience Diagnostics | Score source mesh resilience. | Roll up source-health into redundancy / compartmentalization. | See Insight 5. | source_health rows | `colony_resilience_score`, `source_failure_resilience_score` | later |
| 6 | Signal Path Redundancy Map | Detect single-source signals. | Count distinct sources confirming a theme. | `n_distinct(source)` | signal_events | `signal_path_redundancy_count` | later |
| 7 | Signal Pacemaker | Rhythm score. | Pulse consistency × synchrony × durability. | See Insight 6. | refresh history per signal | `signal_rhythm_integrity_score` | later |
| 8 | Arrhythmia Detector | Rhythm-break flag. | Pulse variance over window. | `var(intervals)` | refresh history | `arrhythmia_risk_score` | later |
| 9 | Boundary Condition Gate | Hard policy veto. | Boolean policy check. | See Insight 7. | policy state, signal | `boundary_violation`, `execution_permission` (always false at MVP) | **now** (already canonical) |
| 10 | Distribution Shift Diagnostic | Detect distribution drift. | Histogram diff vs baseline. | See Insight 8. | source/theme distributions | `distribution_shift_score` | later |
| 11 | Pattern Emergence Score | Confidence from distribution shape. | Composite over sample × diversity × consistency × persistence. | See Insight 8. | aggregated signal stream | `pattern_emergence_score` | later |
| 12 | Amplification Pathway Filter | Distinguish event from amplifier. | Decompose pain into event × pathway × sensitivity. | See Insight 9. | event metadata, attention proxy, regime | `amplification_pathway_score` | later |
| 13 | Continuity Command Layer | Degraded-safe mode. | Mode switch on integrity threshold. | See Insight 10. | source_health, AI validation, DB status | `continuity_mode_active` | **now** (label existing degraded state) |
| 14 | Last-Known-Good Snapshot | Stable fallback view. | Periodic snapshot of "all green" state. | n/a | full inbox view | `last_known_good_drift_score` | later |
| 15 | Signal Metabolism Diagnostics | Energy/repair/fate. | Decay model with fate tags. | See Insight 11. | signal lifecycle events | `signal_metabolism_score` | later |
| 16 | Stale Signal Clearance | Decay action. | TTL × confirmation factor. | `decay = age / (1 + confirmation_count)` | signal age, confirmations | `stale_signal_decay_score` | later |
| 17 | Cross-Source Rescue | Resurrect a degraded signal via another source. | Cross-source confirmation lookup. | n/a | source mesh | `cross_source_rescue_score` | later |
| 18 | Toxic Signal Quarantine | Quarantine state machine. | State: detected → quarantined → labeled → decayed/archived/blocked. | See Insight 12. | validation, reliability, contamination | `toxic_quarantine_state`, `contamination_score` | later |
| 19 | Contamination Score | Quantify toxicity. | `1 − Validation × Reliability`. | See Insight 12. | AI validation, source reliability | `contamination_score` | later |
| 20 | Reaction Inhibition Gate | Perception ≠ permission. | Boolean gate. | See Insight 13. | any signal state | `reaction_inhibition_active` (always true at MVP), `perception_not_permission` | **now** (already canonical) |

For each, the safety invariants hold:

- `advisory_status = ADVISORY_ONLY`
- `execution_gate = LOCKED`
- `broker_api_called = false`
- `ai_execution_count = 0`
- `execution_permission = false`
- `can_execute = false`

---

## 8. Unresolved Questions

Grouped by category. These are *real* open questions, not theatre.

### Sensitivity / chaos
- What is the right perturbation budget for numeric signal inputs?
- Should the perturbation harness be deterministic (grid) or stochastic
  (sampled)?
- How do we detect a classifier that is artificially stable because it
  rounds aggressively?

### Distribution / source independence
- What baseline window is appropriate per source category?
- How do we account for correlated sources (e.g., NewsAPI and Event Registry
  both indexing the same wire story)?
- Below what `n` does distribution shift become unreliable?

### Boundary / safety
- Are there any future feature requests where the boundary is *implicitly*
  loosened? (Answer must remain "no" for execution.)
- Is the boundary surface in the UI as visible as it is in code?

### Quarantine / contamination
- Where does quarantined signal data live, and for how long?
- How does a quarantined signal exit quarantine (decay, archive, block)?
- Does the user see quarantined items in a separate view, or filtered out?

### Degraded mode
- What is the integrity threshold below which continuity mode engages?
- Which UI surfaces must change in continuity mode, and which must not?
- Does continuity mode reduce refresh frequency, scope, or both?

### Frontend communication
- How does the UI distinguish "quarantined" from "rejected" from "stale"?
- What is the visual language for fragility (low chaos stability)?
- How do we communicate continuity mode without alarming the user?

### Implementation overlap
- How much of the framework can be folded into the existing inbox-bridge
  vs. requiring new tables?
- Which framework concepts already exist under a different name (avoid
  duplication)?

---

## 9. One-Line Truths

Reference quotes that should appear in design reviews of any future
diagnostic addition.

- Perception is not permission.
- Urgency is not authorization.
- Survival boundaries outrank opportunity.
- See the signal. Do not twitch.
- A good advisory system is not brave; it is survivable.
- The MVP's job is not to react; it is to regulate reaction.

---

## 10. Final Knowledge Inventory

Compressed inventory, grouped by domain. Each line is a pointer, not a
restatement.

### Nonlinear dynamics
- Sensitivity to perturbation (§1.1, §1.2)
- Classification fragility as a measurable quantity

### Narrative / amplification
- Resonance/amplification factor (§1.3)
- Amplification pathway vs symptom (§1.9)

### Frame / belief discipline
- Multi-frame stability (§1.4)
- Operator desire distortion (§7.4)

### Resilience architecture
- Source mesh redundancy (§1.5)
- Compartmentalization, drainage, repair (§2)

### Rhythm / timing
- Pacemaker / rhythm integrity (§1.6)
- Arrhythmia detection (§2)

### Hard boundaries
- Boundary condition gate (§1.7) — canonical, preserved
- Reaction inhibition gate (§1.13) — canonical, preserved

### Distribution logic
- Emergence from many trials (§1.8)
- Histogram diff vs baseline (§7.10)

### Pathway diagnostics
- Pain = event × pathway × sensitivity (§1.9)

### Continuity / degraded mode
- E-4B continuity model (§1.10)
- Last-known-good snapshot (§7.14)

### Metabolism / quality control
- Signal metabolism (§1.11)
- Stale signal clearance (§7.16)

### Quarantine / contamination
- Toxic signal quarantine (§1.12)
- Contamination score (§7.19)

### Reaction inhibition
- Perception ≠ permission (§1.13, §6.13, §9)

---

## Closing line

> Observe everything, execute nothing, promote only what survives perturbation,
> distribution, boundary, and contamination checks.
