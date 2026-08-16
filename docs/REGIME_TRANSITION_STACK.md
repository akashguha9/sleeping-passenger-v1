# Regime-Transition Stack (sprint 2026-08-16)

Implements the Dzhanibekov/wave/titration/inertia reflection as seven
non-overlapping, measurable modules. Each answers ONE question; each is
pure/deterministic, UNKNOWN-honest, cite-or-drop on evidence, and
advisory-only (no broker, no execution, real money PROHIBITED).

Causal spine:

```
History → Inertia → Titration → Buffer → Threshold → Instability →
Flip → Wave → Wavefront → Propagation Gap → HalfLife → Research Triage
```

## Modules

| Module | Question | Classification |
|---|---|---|
| `regime_transition_contract_equivalence_score.py` | Are two contracts resolving the same proposition? (CES 0–100 + gate) | CORE gate (wraps existing `prediction_market_semantic_pairing`) |
| `regime_transition_market_state_engine.py` | Venue quality, dP/dt, d²P/dt², divergence + dD/dt, momentum state, PMDS | SUPPORTING (PMDS itself EXPERIMENTAL) |
| `regime_transition_inertia_engine.py` | PIS / CIS / SIS / policy genealogy / IIR | SUPPORTING (evidence-gated) |
| `regime_transition_titration_engine.py` | Accumulated evidence, buffers, Threshold Pressure | SUPPORTING; sensitivity monitor DIAGNOSTIC ONLY |
| `regime_transition_flip_engine.py` | Instability (fragility) vs flip probability (transition) — kept distinct | Instability SUPPORTING; flip probability EXPERIMENTAL |
| `regime_transition_wave_engine.py` | Temporal graph, bidirectional propagation, wavefront, backwash | SUPPORTING; backwash DIAGNOSTIC ONLY |
| `regime_transition_propagation_gap_engine.py` | PEG: has price absorbed the probability move? | CORE discovery trigger |
| `regime_transition_report.py` | Auditable per-ticker card + gated research triage | Reporting surface |

## Relation to existing modules (no duplication)

- `prediction_market_semantic_pairing` / `prediction_market_disagreement_scanner`
  — event matching + alerting; CES adds the numeric gate on top.
- `prediction_market_shock_engine` — conviction-weighted ΔP + frozen
  event→equity maps; PEG consumes ΔP-style inputs, does not recompute them.
- `narrative_inertia_score` (narrative momentum) vs the inertia engine
  (physical/institutional resistance) — different phenomena, both kept.
- `tension_accumulation_tracker` (prediction-market entry timing) vs the
  titration engine (heterogeneous evidence accumulation) — different inputs.
- `narrative_structure_divergence` (NSD) feeds the flip engine as the
  narrative-vs-fundamentals input; it is not re-derived.
- `nbi_value_chain_mapper` / `fission_branch_mapper` — static exposure /
  branch maps; the wave engine adds TIME (edge lags) and direction.

## Honesty invariants (tested)

- Missing data → `UNKNOWN` / `INSUFFICIENT_*`, never a silent zero.
- Uncited evidence (no `evidence_ref`) contributes nothing, anywhere.
- Duplicate/syndicated evidence accumulates zero extra pressure.
- Future-dated evidence is ignored (leakage guard).
- Volatility alone is never a threshold signal (`UNCONFIRMED_NOISE`).
- Blocked CES ⇒ blocked PMDS; low metadata coverage fails closed.
- Instability ≠ flip probability; flip requires corroborating pressure,
  is stamped EXPERIMENTAL with a wide uncertainty band.
- All ranked output is `RESEARCH_TRIAGE_ONLY`; hard gates
  (uncited exposure, stale price) cannot be outscored.

All numeric thresholds are `UNCALIBRATED_DEFAULTS` documented in-code;
calibration against `data/calibration_corpus/` is the next experiment.
