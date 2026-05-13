# Diagnostic Framework Roadmap

> **Status:** roadmap document. Not implementation. Not a commitment to ship.
>
> Companion to [REFLECTION_FRAMEWORKS.md](REFLECTION_FRAMEWORKS.md) and
> [FRAMEWORK_COMPONENT_MAP.md](FRAMEWORK_COMPONENT_MAP.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `execution_permission = false` · `can_execute = false`

## 0. Executive Decision

These frameworks should **not** all be implemented immediately. The current
MVP is showcase-grade local-first. Adding twelve diagnostics at once would
destabilize Day 1–35 hardening for marginal value.

Recommended sequence (each step is a discrete future PR, not a sprint):

1. Boundary / reaction invariants stay canonical. **No change.**
2. Add `signal_sensitivity_diagnostics` (perturbation harness, doc-only output).
3. Add `distribution_shift_diagnostics` (histogram diff against baseline).
4. Add `toxic_signal_quarantine` (state machine; UI tag).
5. Add `continuity_mode` (label first, then full mode logic).
6. Add `amplification_pathway_filter` (composite score).
7. Add `signal_rhythm_integrity` (rhythm score over refresh history).
8. Add `signal_metabolism_diagnostics` (only after enough historical data exists).

None of these unlock execution. Each is purely diagnostic or display.

---

## 1. P0 — Preserve Existing Safety

These already exist and **must not change** under this roadmap:

- **Advisory-only contract.** Every record carries `advisory_status =
  ADVISORY_ONLY`.
- **No broker execution.** No broker module imported. No
  `/execute|/buy|/sell|/order|/broker` route. AST-level test enforces this.
- **Human review required.** Every signal surface carries
  `HUMAN_REVIEW_REQUIRED`.
- **Reaction inhibition.** Perception ≠ permission. The transmission line
  between AI output and action is severed by design.
- **Boundary conditions.** Hard lines outrank opportunity in every code
  path.

No diagnostic in this roadmap may weaken any of these.

---

## 2. P1 — First Implementation Candidates

Each P1 candidate is documented with a formula and an implementation sketch.
The sketch is *advisory*; the actual PR will define the canonical interface.

### 2.1 Signal Sensitivity Diagnostic

**Formula:**

```
Chaos Sensitivity = Recommendation Variance / Input Perturbation Size
```

**Implementation sketch (deterministic, advisory-only):**

- Take a signal payload from `signal_events`.
- Perturb numeric fields by ±1%, ±3%, ±5% on a fixed grid.
- Rerun the deterministic scoring pipeline (no AI calls; no live data).
- Count classification flips across the grid.
- Output `chaos_sensitivity_score = flips / trials` and a
  `classification_stability_score = 1 - flips / trials`.
- Persist only as a derived field. Never execute. Never auto-suppress.

**Acceptance gates:** see §5.

### 2.2 Distribution Shift Diagnostic

**Formula:**

```
D_shift = | P_current(x) - P_baseline(x) |
```

**Implementation sketch:**

- Compare current source/theme distributions against a baseline window from
  `signal_events`.
- Use simple histogram counts; no ML.
- Below a configurable minimum sample size, output
  `distribution_shift_score = null` with reason `insufficient_evidence`.
- Never overclaim shift on small `n`.

### 2.3 Toxic Signal Quarantine

**Formula:**

```
Signal Safety  = Validation × Reliability × (1 - Contamination)
Toxic Signal  → Quarantine → Label → Study → Decay / Archive / Block
```

**Implementation sketch:**

- If: source reliability is low, **or** contradiction is high, **or** AI
  validation failed, **or** recycled-narrative score is high → enter
  `toxic_quarantine_state`.
- Preserve the signal in storage (do **not** delete).
- Block from inbox promotion; show under a distinct quarantine view.
- Allow manual review out of quarantine; log the override to Moltbook.

### 2.4 Continuity Mode

**Formula:**

```
if System Integrity < threshold:
    mode = SAFE_ADVISORY_CONTINUITY
```

**Implementation sketch:**

- Inputs: source outage count, DB degraded flag, AI validation pass rate,
  contradiction overload, mock-mode flag.
- Output: `continuity_mode_active` boolean and `continuity_mode_reason`.
- UI: surface a clear banner and reduce promotion-pulse intensity.
- Never grant any execution permission. Even in nominal mode the system
  cannot execute; continuity mode does not change that — it makes the
  reduced state legible.

---

## 3. P2 — Later Candidates

Implement only after the P1 set is stable and the UX implications of
quarantine + continuity have been observed live in a local showcase.

- `narrative_resonance_score`
- `paradigm_shift_audit`
- `operator_belief_lens`
- `signal_rhythm_integrity`
- `stale_signal_clearance`
- `signal_metabolism_diagnostics`

---

## 4. Do-Not-Build-Yet List

These will not be built under any reading of this roadmap.

- Full chaos simulator with stochastic engines.
- "Higgs" / resonance physics module.
- Occult-named modules (spells, rituals, sigils, magick).
- Large ML classifier for signal quality.
- Broker action layer.
- Automated trading driven by any of these diagnostics.
- Any module that would set `execution_permission = true` or
  `can_execute = true`.

---

## 5. Acceptance Criteria

A future diagnostic is accepted **only when all of these are true**:

- It has a plain-English name (no metaphors, no theatre).
- It has deterministic tests (input → expected output, no flakiness).
- It carries the canonical safety stamps on every output record:
  `advisory_status = ADVISORY_ONLY`, `execution_gate = LOCKED`,
  `broker_api_called = false`, `ai_execution_count = 0`,
  `execution_permission = false`, `can_execute = false`.
- It does not call broker APIs (AST-level enforcement).
- It does not produce execution permission anywhere in its output graph.
- It is documented in [REFLECTION_FRAMEWORKS.md](REFLECTION_FRAMEWORKS.md)
  and [FRAMEWORK_COMPONENT_MAP.md](FRAMEWORK_COMPONENT_MAP.md).
- Any UI surface labels degraded / quarantined / continuity states clearly,
  in plain English, without alarming theatre.

If any of these fail, the diagnostic is rejected, regardless of how
"sophisticated" it appears.
