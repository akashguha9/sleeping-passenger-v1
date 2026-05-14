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

### 2.1 Signal Sensitivity Diagnostic — IMPLEMENTED

**Status:** Implemented in `scripts/signal_sensitivity_diagnostics.py`
during the Self-Test Hardening sprint. Tests in
`tests/test_signal_sensitivity_diagnostics.py` (16 cases).

**Formula:**

```
Chaos Sensitivity              = flip_count / perturbation_count
Classification Stability Score = 1 - Chaos Sensitivity
```

**Behaviour:**

- Takes a signal-like dict (no DB read; no live calls).
- Extracts numeric fields from `SENSITIVITY_NUMERIC_FIELDS` (confidence,
  reliability, freshness, narrative_intensity, market_confirmation,
  contradiction, durability, probability, price_change, priority,
  persistence, blocker_pressure, kill_rate).
- For each numeric field, perturbs by ±1%, ±3%, ±5% (configurable) and
  reruns a deterministic bucket classifier
  (`default_bucket_classifier`) — or a caller-supplied classifier.
- Counts classification flips relative to the baseline label.
- Returns `chaos_sensitivity_score`, `classification_stability_score`,
  `fragile` flag, `recommendation` in `{stable, fragile_watchlist,
  human_review_required}`, plus the canonical safety stamps.
- No DB writes. No live calls. Deterministic.

**Usage:**

```powershell
python scripts/signal_sensitivity_diagnostics.py --example
python scripts/signal_sensitivity_diagnostics.py --json path/to/signal.json
```

**Limitations:**

- The default classifier is a conservative bucket function, not the
  system's full scoring pipeline. Callers who want pipeline parity should
  pass their own `classifier=`.
- Fields not in `SENSITIVITY_NUMERIC_FIELDS` are ignored even if they are
  numerically significant.
- A signal with no numeric fields returns `not_applicable` rather than
  invalid — the operator should not treat absence of perturbation data as
  a signal of robustness.

**Acceptance gates:** see §5 — all satisfied.

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

### 2.3 Toxic Signal Quarantine — IMPLEMENTED

**Status:** Implemented in `scripts/toxic_signal_quarantine.py` during
the Self-Test Hardening sprint. Tests in
`tests/test_toxic_signal_quarantine.py` (13 cases).

**Formula:**

```
Contamination Score =
    w1 × Unreliability
  + w2 × Contradiction
  + w3 × Emotional_Manipulation
  + w4 × Recycled_Narrative
  + w5 × Hallucination_Risk
  + w6 × Fallback_or_Noncanonical_Risk
  + w7 × Operator_Desire_Distortion
  + w8 × AI_Invalidity

(score is clipped to [0, 1])

State buckets:
    contamination <  0.15  -> clean
    contamination <  0.35  -> monitor
    contamination <  0.65  -> quarantine
    contamination >= 0.65  -> block_from_promotion
```

**Behaviour:**

- Pure helper; no DB writes, no signal deletion.
- ``promotion_allowed`` is `True` only when state is `clean` or `monitor`.
- ``quarantine_reasons`` lists every component scoring ≥ 0.5 plus a
  banner reason if `fallback_used` is true or `ai_validation_status` is
  `invalid`.
- Caller can override weights and thresholds per call.
- Invalid input (non-dict) returns `block_from_promotion` with
  `validation_status="invalid"`.

**Integration:**

This sprint deliberately *does not* migrate the SQLite schema. The
helper accepts a signal-shaped dict so it can run alongside
`signal_inbox_api.list_inbox_items` output without a migration. A
future PR can attach `toxic_quarantine_state` to `signal_events` rows
as a derived field and surface it in the inbox UI.

**Limitations:**

- The default weights are tuned for "one dimension is enough to escape
  clean, two are enough to escalate". Operators with a different risk
  appetite should override.
- The helper does not detect toxicity *trends* over time. A signal that
  was clean yesterday and quarantine today is two independent records.

### 2.4 Continuity Mode — IMPLEMENTED

**Status:** Implemented in `scripts/continuity_mode.py` during the
Self-Test Hardening sprint. Tests in `tests/test_continuity_mode.py`
(14 cases).

**Formula:**

```
System_Integrity =
      Backend
    × DB
    × Safety_Invariant
    × Source_Health
    × Freshness
    × Backup_Recency
    × AI_Validation_Health

(score is multiplicative — a single broken factor pulls the whole thing
down sharply. Hard floor at 0.40 when the safety invariant is broken.)

State buckets:
    System_Integrity >= 0.85 -> NORMAL
    System_Integrity >= 0.55 -> DEGRADED_ADVISORY
    System_Integrity <  0.55 -> CONTINUITY_SAFE_ADVISORY
```

**Behaviour:**

- Pure helper; no DB writes, no live calls, deterministic.
- Missing fields are treated as healthy by design — operators must
  pass `False` explicitly when something is known broken. This avoids
  alarmist defaults.
- ``allowed_actions["execute_broker_order"]`` is **always** `False`,
  regardless of mode. Continuity mode does not gate execution because
  there is no execution path; it labels the reduced state for the
  operator.
- ``allowed_actions["log_manual_trade"]`` and ``["reconcile"]`` flip to
  `False` only when the DB is unavailable, because we cannot guarantee
  persistence of a manual decision without it.
- Surfaces `fallback_used` and `mock_used` in the `informational` block
  so callers can render banners.

**Integration:**

The helper accepts a flat dict so it can be assembled from existing
health surfaces without a schema migration. Future PRs may wire it into
`/health` and `scripts/smoke_check.py`. This sprint adds the diagnostic
itself; UI surfaces remain optional.

**Limitations:**

- The mapping from `stale_source_count` / `failed_source_count` to the
  source-health factor is linear and capped. It is a *rough* signal —
  one stale source costs 0.10, one failed costs 0.20. Operators tuning
  the threshold can override the entire factor by passing
  `source_health_ok` directly.
- The hard floor of 0.40 when the safety invariant breaks is
  intentional: the MVP's identity depends on advisory-only safety, so
  any failure there must surface as continuity-safe-or-worse.

---

### 2.5 Signal Reactor + Adaptive Routing Model — IMPLEMENTED

**Status:** Implemented in the Signal Reactor + Adaptive Routing Model
Upgrade sprint. See `docs/SIGNAL_REACTOR_MODEL.md` for the doctrine and
`docs/SIGNAL_REACTOR_USAGE.md` for runtime usage.

Implemented modules (all pure, deterministic, advisory-only — no DB
writes, no live APIs, no broker imports):

- `scripts/signal_field_geometry.py` — direction/phase/resonance/damping.
- `scripts/echo_risk_engine.py` — echo risk, source independence, AI echo guard.
- `scripts/signal_decay_waste.py` — half-life decay, waste-load summary.
- `scripts/fission_branch_mapper.py` — branch energies, branch clarity.
- `scripts/fusion_thesis_engine.py` — evidence density, fusion validity.
- `scripts/operator_control_rods.py` — operator heat, containment, meltdown
  risk, gallardo block.
- `scripts/adaptive_signal_router.py` — nutrient value, terrain penalty,
  route weight, route state.
- `scripts/signal_reactor.py` — pure orchestrator producing one advisory
  payload, exposing CLI `python scripts/signal_reactor.py --example --json`.

Tests live under `tests/test_signal_*` and
`tests/test_signal_reactor_safety_invariants.py`. The safety invariants
test walks every public function's output recursively and asserts that
no nested record claims execution permission.

This raises the Signal Reactor / Adaptive Routing entry from *future*
to *implemented (advisory-only)*. The reactor is not wired into the
inbox API or the frontend yet — that is a follow-up sprint.

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
- Reactor UI badges (state, decision-grade energy, gallardo block).
- Reactor threshold calibration once self-test outcomes are labeled.

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
