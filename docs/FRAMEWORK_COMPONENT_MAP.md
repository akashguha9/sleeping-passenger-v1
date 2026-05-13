# Framework Component Map

> **Status:** mapping document. Not implementation.
>
> Companion to [REFLECTION_FRAMEWORKS.md](REFLECTION_FRAMEWORKS.md) and
> [DIAGNOSTIC_FRAMEWORK_ROADMAP.md](DIAGNOSTIC_FRAMEWORK_ROADMAP.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `execution_permission = false` · `can_execute = false`

## 0. Purpose

The reflection produces evocative metaphors. This document is the firebreak
between metaphor and code. It prevents metaphor sprawl by mapping each
concept to:

- the existing repo layer where it fits (if any)
- a sober, professional engineering name
- implementation status today
- priority for future work
- risk if implemented badly
- test strategy when (and if) it is implemented

Nothing in this document gives any code path execution permission. The
existing safety lock is canonical and outranks anything proposed here.

---

## 1. Existing MVP Layers

The current advisory MVP already has the following layers. Most of the
reflection's mechanisms map onto these — they are extensions, not new
products.

| Layer | Where it lives | What it does |
|---|---|---|
| Advisory safety lock | `scripts/api_server.py`, `scripts/persistence.py`, UI badges | Enforces ADVISORY_ONLY, EXECUTION_GATE=LOCKED, HUMAN_REVIEW_REQUIRED, AI_EXECUTION_COUNT=0, broker_api_called=false on every record and route. |
| DIABLO / chaos veto (historical) | `scripts/diablo_*` if present, board-control safety layer | Existing chaos/contradiction veto patterns in legacy diagnostics. |
| ISLERO / shock override (historical) | `scripts/islero_*` if present, extreme-state layers | Shock-mode override pattern in historical reference layers. |
| Signal inbox | `scripts/signal_inbox_api.py`, `scripts/signal_inbox_bridge.py` | Promotes ingested signal_events into reviewable inbox candidates. |
| Source health | `scripts/source_health_summary.py`, `source_health` table | Tracks per-source freshness, latency, error states. |
| Live-source refresh | `scripts/run_live_sources_phase1.py`, `scripts/run_live_sources_phase2.py`, `scripts/run_live_refresh.py` | Polls public sources, persists `signal_events`. |
| AI output validation | `scripts/ai_output_schema.py`, `docs/AI_OUTPUT_VALIDATION.md` | Validates AI payloads, blocks unsafe outputs. |
| Persistence truth | `scripts/persistence.py`, `runtime/mvp_local.db` | SQLite tables for journal streams. |
| Backup / restore | `scripts/backup_db.py`, `tests/test_db_backup_restore.py` | Local DB backup discipline. |
| Smoke check | `scripts/local_mvp_smoke_test.py` | End-to-end smoke flow. |
| Manual trade log | `manual_trades` table, `/manual-trades` route | Human-only trade records. |
| Reconciliation | `reconciliation_results` table | Match logged trades against actual outcomes. |
| Moltbook / reflection | `scripts/moltbook_api.py`, `moltbook_entries` table | Self-correction journal. |
| Frontend dashboard / sidebar / help | `frontend/src/app/`, `frontend/src/components/` | Next.js advisory cockpit, safety banners, badges. |

The reflection's frameworks mostly belong as **additions to existing layers**,
not as new top-level subsystems.

---

## 2. Framework-to-Repo Mapping Table

| Reflection concept | Professional engineering name | Existing repo overlap | Status | Priority | Implement now? | Notes |
|---|---|---|---|---|---|---|
| Chaos pendulum | `signal_sensitivity_diagnostics` | None explicit. Closest analog: durability + contradiction layers. | missing | P1 | No | Add deterministic perturbation harness; do not auto-act. |
| Higgs resonance | `narrative_resonance_score` | EMS narrative recycling, virality. | missing | P2 | No | Composite; flag only. |
| Chaos Magick | `paradigm_shift_audit` / `cross_frame_stability` | None. | missing | P2 | No | Doc-only at MVP stage. |
| Termite mound | `resilience_diagnostics` | `source_health_summary.py`. | partial | P2 | No | Roll up source-health into a single score. |
| Sinoatrial node | `signal_rhythm_integrity` | `LIVE_SIGNALS_REFRESH_MODEL`. | partial | P2 | No | Score over refresh cadence per signal/source. |
| Penguin / equator | `boundary_condition_gate` | Advisory-only safety lock. | **existing, canonical** | P0 | n/a — preserve | Do not weaken under any circumstance. |
| Galton board | `distribution_shift_diagnostics` | None explicit. | missing | P1 | No | Requires history depth. |
| Painkiller | `amplification_pathway_filter` | EMS / attention proxy. | missing | P1 | No | Decompose pain into event × pathway × sensitivity. |
| E-4B Nightwatch | `continuity_mode` | Partial: degraded source-health surfaced. | partial | P1 | No (label only) | Add explicit mode flag; clear UI label. |
| Mitochondria | `signal_metabolism_diagnostics` | None. | missing | P2 | No | Implement after history depth exists. |
| Sunflower | `toxic_signal_quarantine` | None as explicit state. | missing | P1 | No | Quarantine state machine; never auto-delete. |
| Botox | `reaction_inhibition_gate` | Advisory-only safety lock (action side). | **existing, canonical** | P0 | n/a — preserve | Same lock as boundary, viewed from the action side. |

---

## 3. Implementation Priority

### P0 — Safety-critical, must remain locked

These are not "future work". They are canonical and outrank every framework
in this document.

- `boundary_condition_gate` — the advisory-only safety lock
- `reaction_inhibition_gate` — perception ≠ permission
- Advisory-only safety invariant (every record, every route, every test)
- Continuity safe mode (existing degraded-state behavior, even before
  formal labeling)

### P1 — High-value diagnostics for future implementation

These add real signal quality, deterministically, without any execution
risk. They are the *first* candidates if implementation is ever undertaken.

- `signal_sensitivity_diagnostics`
- `distribution_shift_diagnostics`
- `signal_rhythm_integrity`
- `toxic_signal_quarantine`
- `amplification_pathway_filter`
- `continuity_mode` (label/flag now; full mode logic later)

### P2 — Useful but easy to overengineer

These should not be implemented until the P1 set is stable. Each carries
a risk of bloating the MVP with theatrical sophistication.

- `paradigm_shift_audit`
- `narrative_resonance_score`
- `signal_metabolism_diagnostics`
- `colony_resilience_score`
- `cross_source_rescue`

### P3 — Document only, never as code names

- Theatrical names (Higgs, Botox, penguin, sunflower as filenames)
- Occult branding (spell, ritual, magick)
- Pseudo-physics labels (turbulent resonance, dark field)
- Animal/biology metaphor filenames

---

## 4. Field Naming Proposal

When (and only when) the corresponding diagnostic is implemented, fields
should use these canonical names. Existing fields keep their existing names.

```
chaos_sensitivity_score
classification_stability_score
narrative_resonance_score
amplification_risk_score
cross_frame_stability_score
operator_desire_distortion_score
source_failure_resilience_score
signal_path_redundancy_count
signal_rhythm_integrity_score
arrhythmia_risk_score
boundary_violation
distribution_shift_score
pattern_emergence_score
amplification_pathway_score
continuity_mode_active
last_known_good_drift_score
signal_metabolism_score
stale_signal_decay_score
cross_source_rescue_score
contamination_score
toxic_quarantine_state
reaction_inhibition_active
perception_not_permission
```

Plus the canonical safety stamps on every new surface:

```
advisory_status = ADVISORY_ONLY
execution_gate = LOCKED
broker_api_called = false
ai_execution_count = 0
broker_order_id = NONE
execution_permission = false
can_execute = false
```

---

## 5. Anti-Theatre Naming Rules

The following names are **banned from the codebase** as module names, class
names, or filenames:

- `higgs_turbulent_resonance.py` / `Higgs*` classes
- `chaos_magick.py`, `spell_engine.py`, `occult_signal_layer.py`,
  `ritual_*.py`, `sigil_*.py`
- `botox_gate.py`, `neurotoxin_*`
- `penguin_gate.py`, `equator_*`
- `termite_engine.py`, `colony_mound_*`
- `sunflower_radioactivity.py`, `phytoremediation_*`
- `mitochondria.py`, `atp_engine.py`
- `painkiller.py`, `nsaid_*`
- `sinoatrial_pacemaker.py`, `e4b_nightwatch.py`

The rule that produced each banned name:

> **Professional_Name = measurable_mechanism + testable_output + plain-English meaning.**

If a proposed name does not describe what is measured, what is output, and
what it means in English, it is theatrical and must be rewritten.

Concretely:

- `sunflower_radioactivity.py` describes nothing measurable → rewrite as
  `toxic_signal_quarantine`.
- `botox_gate.py` mentions a drug → rewrite as `reaction_inhibition_gate`.
- `chaos_magick.py` invokes a tradition → rewrite as
  `cross_frame_stability` or `paradigm_shift_audit`.

---

## 6. Future Test Strategy

When a diagnostic is implemented, these tests are required *before* it is
exposed in the UI or API. The same patterns apply to any new diagnostic in
this family.

### Sensitivity / chaos
- A tiny input perturbation should not flip a robust signal's classification.
- A high `chaos_sensitivity_score` must reduce, not increase, confidence.
- Sensitivity output must never set `execution_permission = true`.

### Distribution
- A single-source signal must score low on `signal_path_redundancy`.
- A distribution shift under a small `n` must report `insufficient_evidence`,
  not a confident shift.

### Continuity / degraded mode
- Crisis mode must reduce confidence, not increase it.
- `continuity_mode_active = true` must not unlock any normally-locked surface.

### Boundary
- A boundary violation must force `execution_permission = false` regardless
  of signal strength.
- No code path may grant execution permission outside the existing lock.

### Quarantine / contamination
- A toxic signal must end up in quarantine state, not promoted.
- A quarantined signal must remain in storage for learning, not deleted.

### Rhythm
- High `arrhythmia_risk_score` must block a promotion pulse, not amplify it.

### Amplification pathway
- High amplification with low real-event severity must flag pathway
  distortion, not auto-suppress the signal.

### Universal invariants on any new diagnostic
- `advisory_status = ADVISORY_ONLY` on every output record.
- `broker_api_called = false` proven by AST-level test (no broker import).
- `ai_execution_count = 0` immutable.
- No new HTTP route named `/execute|/buy|/sell|/order|/broker`.
- No new live API call without an explicit env-gated, advisory-only adapter.
