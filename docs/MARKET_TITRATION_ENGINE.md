# Market Titration Engine

**Module:** `scripts/market_titration_engine.py`
**Config:** `config/market_titration_config.json`
**Wired into:** Signal Inbox decoration (`scripts/signal_inbox_api.py`), `GET /signals`,
`GET /signals/{event_id}`, `GET /api/titration/summary`, and the manual-trade
journal (`titration_state_at_decision` snapshot columns via
`scripts/titration_snapshot_attach.py`).
**Versions:** `schema_version=1.0.0`, `scoring_version=titration_v1`.

---

## Doctrine

> The final drop is not the signal. The signal is that the system has lost
> the ability to absorb one more drop.

The engine does not hunt visible alpha (price already moving). It estimates
**transition readiness**: is coherent evidence accumulating faster than it
decays, how much activation barrier remains, and has the market already
recognized the thesis? The core ranking quantity is the **Pre-Alpha Gap**
(latent readiness minus visible recognition).

Advisory-only. The engine never produces a Buy/Sell, never authorizes
execution, and stamps the full safety contract
(`advisory_status=ADVISORY_ONLY`, `execution_gate=LOCKED`,
`broker_api_called=False`, `ai_execution_count=0`) on every payload.

## Honesty contract

* **Every score is a bounded heuristic, not a probability.** Payloads carry
  `score_semantics="heuristic_bounded_score_not_probability"`. Nothing here
  passes through `score_output_contract` as calibrated.
* **Proxies are labelled.** Susceptibility, buffer capacity, MCD, VMR,
  coherence and free energy carry `is_proxy=True` plus an `estimator` name.
* **Missing data is exposed, never zero-filled.** Temperature and VMR list
  `inputs_missing`; `INSUFFICIENT_DATA` is a first-class state; the
  `data_sufficiency` block reports level, observation count, span and limits.
* **No directional claims.** Per-event direction/magnitude is not available
  on the inbox path, so active evidence is *unsigned readiness mass*
  (`directional_evidence_available=False`) and coherence is a structural
  proxy, not directional agreement.
* **Half-lives are configured priors** (`half_life_source="configured_prior"`),
  deliberately aligned with `scripts/signal_decay_waste.DEFAULT_HALF_LIFE_HOURS`.
  They are not fitted from outcomes yet.

## Mathematics (conceptual form → production estimator)

### Active evidence
Conceptual: `a_i(t) = d·m·q·r·c · 2^(-(t-t_i)/h_i)`.
Production: direction `d`, magnitude `m` and per-event confidence `c` are
unavailable on this path, so `a_i(t) = q_f · r_f · 2^(-(t-t_i)/h_f)` with
family-level quality/reliability priors `q_f, r_f` and family half-life
`h_f` from config. Aggregate: raw mass `A_raw = Σ a_i`, normalized with a
saturation transform `A = A_raw / (A_raw + k)` (k = `evidence_saturation_mass`,
default 3.0) instead of a weighted mean — the doctrine's quantity is
accumulated dose, so mass should grow with corroborating events, bounded to
[0,1). Invalid timestamps are dropped and recorded; future timestamps are
clamped to now; negative/zero half-lives are rejected at config validation.

### Accumulation vs decay (flow)
`A_now − A_prev_step` on the normalized scale (step = `series_checkpoint_hours`),
with the two components separated: `inflow_fresh_mass` (decayed mass of events
inside `fresh_inflow_window_hours`) and `decay_outflow_mass` (evaporation of
the previous stock). `loading = net_accumulation > eps` and additionally
requires `min_events_for_loading` (default 2) before the LOADING state can be
claimed.

### Geometry
The evidence series is evaluated at K fixed checkpoints (default 5 × 6h).
Velocity = mean first difference, acceleration = mean second difference.
Labels: `CONVEX` (accelerating accumulation — pre-alpha loading shape),
`CONCAVE` (decelerating), `APPROX_LINEAR`, `FLAT`, `INSUFFICIENT_DATA`
(fewer than `min_events_for_geometry`=3 events). Series are never forced
into a named shape. Hyperbolic / logistic classification requires denser
history than the inbox path provides and is deliberately not claimed.

### Temperature and Goldilocks
`T = sigmoid(bias + Σ w_j·x_j)` over the inputs actually available:
event-arrival velocity (saturating events/day), chaos-sensitivity
diagnostic, contamination. Missing classic inputs (implied vol, cross-asset
correlation, liquidity stress, macro stress) are listed in `inputs_missing`.
Anchors used to set the weights (documented calibration-by-scenario, not
fitted): no activity → ≈0.10 (COLD); reference-rate clean flow → ≈0.50
(WARM); dense burst → ≈0.77 (HOT); dense noisy burst → ≈0.92 (OVERHEATED).
Goldilocks quality `G = exp(−(T−T*)²/2σ²)` with `T*=0.55`, `σ=0.18`
(configurable). Maximum temperature is never treated as maximum opportunity.

### Titration core
* **Activation barrier** `B = max(0, θ − A)/θ`, θ = `activation_threshold`
  (0.55, configured prior — not calibrated per sector/regime yet).
* **Susceptibility (proxy)** `χ = 0.5·accel⁺ + 0.3·coherence + 0.2·freshness`,
  `estimator="heuristic_proxy_v1"`. The true quantity is `∂R/∂E`
  (market response per evidence unit), which requires evidence→response
  observations the platform does not collect yet. Returns `None`
  (insufficient) when geometry is unestablished.
* **Buffer capacity (proxy)** `β = 1 − χ` — a bounded monotone inverse used
  instead of the conceptual `1/χ` to avoid singularities. Documented
  deviation; inherits proxy status.
* **Minimum catalytic dose (proxy)** `MCD = B/(ε+χ)`, capped at `mcd_cap`,
  reported both raw and normalized (`MCD/(MCD+1)`).

### Readiness, recognition, gap
* **LRR** = sigmoid of weighted components (active evidence, coherence,
  susceptibility, persistence, barrier openness, Goldilocks quality, minus
  source-concentration and false-transition penalties). Weights are
  configurable priors (`weights_source="configured_prior_uncalibrated"`);
  every contribution is exposed.
* **VMR (proxy)** = weighted reporting breadth + arrival velocity
  (`breadth_velocity_proxy_v1`, confidence `low`). Missing inputs (price
  extension, valuation repricing, analyst/social attention, options
  crowding) are listed, so "low recognition" is distinguishable from
  "missing recognition data".
* **Pre-Alpha Gap** `PAG = LRR − VMR ∈ [−1, 1]`. Positive gap is necessary
  but not sufficient for PRIMED.
* Known limitation: VMR's velocity input and evidence inflow share the same
  underlying arrivals, so PAG is partially mechanically coupled until
  external recognition feeds exist.

### False-transition risk and free energy
`FTR` = weighted overheat excess, single-source dependence, low persistence,
contamination, low sufficiency — with a `reasons` list, and a gate
(`ftr_gate`=0.6) that forces the FALSE_TRANSITION_RISK state.
`FE = LRR·max(PAG,0)·G·Q − friction_prior − uncertainty_penalty` — a
composite proxy ("free energy" is a modelling metaphor); `Q` is the data
sufficiency score; friction is a configured prior because no live
spread/liquidity feed exists on this path. `FE ≤ 0` with real evidence mass
drives NO_EDGE.

### Source-concentration entropy
Shannon entropy of decayed mass across source families, normalized by
`ln(n)`. This measures evidence-base concentration (single-source dependence
feeds FTR); it is **not** directional disagreement, which would need signed
evidence. Directional/model disagreement remains the job of
`scripts/model_disagreement.py`.

## State machine

Precedence (first match wins), all thresholds configurable:

1. `INSUFFICIENT_DATA` — no parseable events / below minimum.
2. `FALSE_TRANSITION_RISK` — FTR ≥ gate (heat/noise/persistence veto).
3. `CROWDED` — VMR ≥ 0.65 and PAG ≤ 0.05 (recognition ate the gap).
4. `EXHAUSTING` — CONCAVE geometry with recognition ≥ 0.40.
5. `PRIMED` — LRR ≥ 0.65, PAG ≥ 0.15, barrier ≤ 0.45, Goldilocks ≥ 0.5, FTR below gate.
6. `PRE_ALPHA_WATCH` — LRR ≥ 0.45 and PAG ≥ 0.05.
7. `LOADING` — net accumulation > eps with ≥ 2 events.
8. `NO_EDGE` — evidence above floor but free energy ≤ 0.
9. `INERT` — default low-energy state.

Every assignment carries a `state_rule_trace` (the exact comparisons that
fired) and an `explanation` block (`supporting_factors`, `penalties`,
`invalidation_conditions`).

**Reserved, designed but NOT operational:** `BUFFER_DEPLETING`,
`ENDPOINT_CROSSING`, `REPRICING`. They require true evidence→response
susceptibility (price-reaction observations) that the data layer does not
collect yet. They are exported as `RESERVED_STATES` and asserted
unreachable in tests, so designed-vs-operational stays honest.

## Runtime wiring

```
signal_events (SQLite)
  → signal_inbox_bridge._aggregate_group          (+ event_timestamps/event_sources)
  → signal_inbox_api._decorate_inbox_diagnostics  (sensitivity, quarantine)
  → signal_inbox_api._decorate_with_reactor_diagnostics
  → signal_inbox_api._decorate_with_titration_state   ← NEW
  → GET /signals (items carry titration_state + compact titration block;
                  response carries titration_state_counts)
  → GET /api/titration/summary (state counts + top pre-alpha-gap candidates)
  → POST /manual-trades → titration_snapshot_attach auto-fills
      titration_state_at_decision / titration_pre_alpha_gap_at_decision /
      titration_lrr_at_decision on the journal row
```

Single horizon in v1: `swing_multi_day` (the inbox path's native cadence).
Intraday/positional horizons need per-horizon half-life and threshold sets —
deferred and stamped on the payload (`horizon` field).

## Outcome feedback and calibration path

The manual-trade journal now records the titration state at decision time
(same contract as the reactor snapshot: explicit values win, absence is
never fabricated, nothing grants execution). Once enough reconciled
outcomes accumulate, `titration_state_at_decision` /
`titration_pre_alpha_gap_at_decision` can be joined against
`reconciliation_results` exactly as `reactor_state_at_decision` is today,
and PAG can be registered as a calibratable series in
`scripts/calibration_map.py`. **No such calibration exists yet** — the
titration layer is uncalibrated and says so on every payload.

## Configuration reference

See `config/market_titration_config.json`. All parameters validated with
range bounds; invalid files degrade to internal defaults with
`config_status="invalid_file_fallback_defaults"` and per-key
`config_problems`. Key groups: half-lives per source family, source
quality/reliability priors, saturation mass, checkpoint grid, geometry
epsilons, temperature weights/bias/bands, Goldilocks center/width, LRR/VMR/FTR
weights, state thresholds, friction prior, epsilon, MCD cap.

## Known limitations (unproven / heuristic)

* All weights and thresholds are operator priors — zero outcome calibration.
* Susceptibility/buffer/MCD are heuristic proxies until evidence→response
  observations exist (that is also what blocks the three reserved states).
* VMR lacks external recognition feeds (attention, valuation, options) and
  is mechanically coupled to evidence velocity.
* Unit evidence mass: event magnitude/direction/quality per event are not
  yet modelled (needs a typed evidence schema on `signal_events.raw_payload`).
* Single horizon; no per-sector thresholds; half-lives not fitted.
* Geometry uses mean differences over a fixed grid — robust-fit residual
  checks and S-curve/hyperbolic detection are future work.

## Tests

* `tests/test_market_titration_engine.py` — decay identities, timezone and
  hostile-input safety, geometry, temperature regimes, entropy, synthetic
  Cases A–F (INERT, LOADING, PRIMED, CROWDED, FALSE_TRANSITION, NO_EDGE),
  numerical safety, config fallback, versioning, safety-invariant walker,
  CLI.
* `tests/test_titration_inbox_integration.py` — bridge provenance,
  decoration, list aggregates, `/api/titration/summary` contract, snapshot
  persistence and bounds.

CLI smoke: `python scripts/market_titration_engine.py --example --json`.
