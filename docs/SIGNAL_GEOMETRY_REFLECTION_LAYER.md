# Signal Geometry Reflection Layer

> Advisory-only diagnostic architecture, translated from the
> "mathematical reflection" into disciplined MVP code.
> Beautiful math may *structure* the system. It must never become
> false trade confidence.

This document describes the eighteen reflection concepts integrated
into the MVP as a single deterministic diagnostic layer
(`scripts/signal_geometry_reflection.py`) and how that layer is wired
into the signal reactor, the local self-test report, and the
pre-real-money preflight.

## Doctrine

This layer is **diagnostic**, not predictive. It exists to:

- structure raw events before interpretation (spatial index, BSP),
- filter recycled/stale narratives cheaply (Bloom-style hint only,
  never canonical),
- expose where signal is strengthening, spreading, or contradicting
  itself (gradient/divergence/curl),
- reveal hidden macro drivers from pairwise asset relationships,
- surface chaotic regimes that should shrink the forecast horizon,
- detect Möbius-style risk/opportunity inversions (crowded → fragile,
  AI consensus → echo chamber),
- and route through risk weights to a *lowest-risk advisory route* —
  never to a buy/sell.

The strongest positive recommendation the layer can produce is
`review_candidate`. There is no path to `buy`, `sell`, `execute`,
`place_order`, or `broker_*`.

## The Eighteen Modules

Every module is exposed as a pure Python function in
`scripts/signal_geometry_reflection.py` and is exercised by
`tests/test_signal_geometry_reflection.py`. Every output carries the
canonical safety stamps:

```
advisory_status        = "ADVISORY_ONLY"
execution_gate         = "LOCKED"
broker_api_called      = false
ai_execution_count     = 0
execution_permission   = false
can_execute            = false
broker_order_id        = "NONE"
human_review_required  = true
```

| # | Reflection concept | Function | What it actually does |
|---|---|---|---|
| 1 | Signal Spatial Index (H3/R-tree/BSP/Hilbert) | `build_signal_cell` | Maps each signal to a coarse, searchable `SignalCell` keyed by source/jurisdiction/sector/event/cluster/time-bucket. Pure structuring; no prediction. |
| 2 | Duplicate / Stale Pre-Veto (Bloom) | `classify_duplicate_stale_pre_veto` | Cheap probabilistic hint (`probably_seen` / `definitely_new` / `probably_stale`). **Never canonical.** Declares `canonical_source = "sqlite"` and `verification_required = true`. |
| 3 | Narrative Feature Extractor (CNN) | `extract_narrative_features` | Deterministic 13-feature vector in `[0,1]` plus `feature_extraction_quality` so downstream consumers can see when input was sparse. |
| 4 | Decision BSP Tree | `classify_decision_partition` | Routes a signal into one of 11 partitions (`macro`, `micro_company`, `geopolitical`, `regulatory`, `earnings_filings`, `flow_market_structure`, `prediction_market`, `ai_report`, `on_chain`, `manual_trade_reconciliation`, `unclassified`). |
| 5 | Dijkstra Risk Router | `compute_risk_route` | Sums weighted risk edges (source uncertainty, freshness decay, liquidity risk, leverage risk, contradiction risk, crowding risk, chaos risk, operator heat, invalidation weakness, missing-data penalty). Emits `route_cost`, `route_penalties`, `dominant_risks`, `lowest_risk_route`, `advisory_decision`. |
| 6 | Constrained-First Queue (Warnsdorf) | `compute_constrained_first_priority` | Score for "handle the most fragile signals first" — short freshness, ambiguity, chaos, few exits, leverage pressure, breached stops/TPs, reconciliation mismatch. |
| 7 | Invariant Ratio Monitor (Marion/Viviani) | `compute_invariant_ratio` | Checks balance between narrative, capital flow, and risk-control strengths. Flags imbalances like "narrative_without_capital" or "leverage_without_survival_quality". |
| 8 | Signal Derivative Engine (Taylor) | `compute_signal_derivatives` | First/second-order derivatives — `momentum`, `curvature`, `chaos_acceleration`, `forecast_horizon_decay`, and `history_completeness`. |
| 9 | Phase Alignment (Lissajous) | `compute_phase_alignment_state` | Classifies narrative vs liquidity phase relationship — `aligned_confirming`, `narrative_leads_capital`, `capital_leads_narrative`, `out_of_phase`, `dangerous_desync`, or `insufficient_data`. |
| 10 | Regime Composition (Riemann/Lebesgue) | `compute_regime_composition` | Daily intensity-state occupancy fractions (durable, noisy, contradictory, actionable, stale, diablo, moltbook-feedback-value), plus a dominant `regime_state`. |
| 11 | Monte Carlo Survival Stub | `monte_carlo_survival_stub` | **Diagnostic stub only.** Deterministic pseudo-random walk derived from the signal fingerprint, declared `is_real_monte_carlo = false` and `method = "deterministic_diagnostic_stub"`. On missing inputs it returns `method = "insufficient_data"` rather than guessing. |
| 12 | Signal Field Diagnostics (vector calculus) | `compute_field_diagnostics` | Gradient / divergence / curl proxies. High curl = contradiction chaos risk; high divergence = attention spreading thin; high gradient + low divergence = strengthening/concentrating. |
| 13 | Thermodynamic Exposure | `classify_thermodynamic_exposure` | Mode classifier (`isothermal`, `isobaric`, `isochoric`, `adiabatic`, `insufficient_data`) using `portfolio_heat`, `exposure_volume`, `market_pressure`, `external_confirmation`. |
| 14 | Hidden Macro Driver (Monge) | `detect_hidden_macro_driver` | Pairwise asset/sector/jurisdiction links + inferred shared driver with `driver_confidence` and `driver_contradictions`. |
| 15 | Recursive Moltbook Engine | `summarize_moltbook_recursive_state` | Computes `learning_radius = sqrt(validated_events)` and a *candidate* `recursive_weight_adjustment_candidate`, with `not_auto_applied_without_human_review = true`. |
| 16 | Noise Taxonomy | `classify_noise_taxonomy` | Classifies dominant noise (`normal_noise`, `fat_tail_shock_risk`, `oscillatory_cancellation`, `stale_echo_noise`, `ai_echo_noise`, `source_repetition_noise`). |
| 17 | Chaos Attractor Detector | `classify_chaos_attractor` | `sensitivity_score`, `regime_instability`, `forecast_decay_rate`, `max_safe_forecast_horizon_hours`, `chaos_attractor_flag`. |
| 18 | Möbius Inversion Detector | `classify_mobius_inversion` | Flags `bullish_crowded_fragile`, `bearish_narrative_no_capital`, `ai_consensus_echo_chamber`, `strong_narrative_false_confidence`. Outputs `mobius_inversion_risk`, `crowding_penalty`, `false_confidence_penalty`. |

A small **Leverage Policy** helper (`summarize_leverage_policy`) caps
Indian-equity leverage at 4.0x as a ceiling (not a default) and forces
rest-of-world to spot-only (1.0x).

## Top-level orchestrator

`build_signal_geometry_diagnostics(signal_or_cluster, *, context=None,
operator_state=None, moltbook_state=None, leverage_hint=None,
seen_fingerprints=None, history=None)` runs every module, never raises
on bad input, and produces a single payload:

```
{
  "signal_geometry_diagnostics": {
    "signal_cell_index": {...},
    "duplicate_stale_pre_veto": {...},
    "feature_extraction": {...},
    "decision_partition": {...},
    "risk_route": {...},
    "constrained_first_priority": {...},
    "invariant_ratio": {...},
    "signal_derivatives": {...},
    "phase_alignment": {...},
    "regime_composition": {...},
    "monte_carlo_survival": {...},
    "field_diagnostics": {...},
    "thermodynamic_exposure": {...},
    "hidden_macro_driver": {...},
    "moltbook_recursive_state": {...},
    "noise_taxonomy": {...},
    "chaos_attractor": {...},
    "mobius_inversion": {...},
    "leverage_policy": {...}
  },
  "signal_count": <int>,
  "vetoes": [...],
  "recommendation": "observe" | "watch" | "review_later"
                    | "review_candidate" | "decay_archive"
                    | "human_review_only" | "wait_insufficient_data",
  "operator_action": <same>,
  "human_review_required": true,
  "canonical_truth_source": "sqlite",
  "jsonl_role": "audit_fallback_only",
  "safety": { ... canonical stamps ... }
}
```

## Wiring

- **Signal reactor** (`scripts/signal_reactor.py`): adds
  `components["geometry_reflection"]` and a top-level
  `geometry_reflection_summary` field. Geometry vetoes can only
  *downgrade* the reactor (e.g. `WARM_WATCH` → `HOT_CONTAINMENT_REQUIRED`
  when chaos/curl/Möbius/leverage are out of policy); they **cannot
  promote** any state. Existing precedence (operator block, echo, waste,
  fission, fusion, meltdown) is preserved.
- **Pre-real-money preflight** (`scripts/pre_real_money_preflight.py`):
  adds a seventh subcheck `signal_geometry_reflection` that imports the
  module on an empty cluster, verifies the safety contract, and emits a
  blocking issue (`signal_geometry_reflection_safety_invariant_failed`)
  on any breach. The geometry layer cannot unlock execution; it can
  only *fail* the safety contract.
- **Self-test report** (`scripts/self_test_report.py`): adds
  `geometry_reflection_self_check` to the full report, the summary
  payload, and the Markdown rendering.

## Safety contract test surface

`tests/test_signal_geometry_reflection.py` covers:

- safety stamps on every sub-component and on the orchestrator,
- forbidden-execution-language scan over the full payload,
- missing-data must degrade to `wait_insufficient_data` / `watch` /
  `decay_archive`, never `review_candidate` or stronger,
- high Möbius inversion adds a veto and downgrades,
- chaos-attractor flag adds a veto,
- high field curl adds a veto,
- AI echo noise classification,
- probable-duplicate adds a veto,
- India leverage **ceiling** at 4.0x — and the ceiling is **not a
  default** (bare signals default to 1.0x),
- ROW jurisdictions (US/UK/EU/JP/DE/SG …) are vetoed for any leverage
  above 1.0,
- duplicate/stale pre-veto declares `canonical_source = "sqlite"` and
  `verification_required = true`,
- orchestrator declares `canonical_truth_source = "sqlite"` and
  `jsonl_role = "audit_fallback_only"`,
- recursive Moltbook engine never auto-applies its weight-adjustment
  candidate,
- Monte Carlo survival stub honestly declares
  `is_real_monte_carlo = false`.

## Non-goals

This layer:

- does **not** call brokers,
- does **not** place orders,
- does **not** write to the database,
- does **not** call the network,
- does **not** drive AI execution,
- does **not** replace SQLite truth,
- does **not** treat JSONL as canonical,
- does **not** infer a price target,
- does **not** issue a buy/sell.

When the math is beautiful but the input is sparse, the layer returns
`wait_insufficient_data` and explains why.
