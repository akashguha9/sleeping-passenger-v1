# Market-Physics Simulator

The simulator layer (`src/simulator/`) upgrades the MVP from a screener to a
**failure-mode simulator first, opportunity engine second**. It converts
upstream narrative / prediction-market signals into downstream stock
candidates and stress-tests every candidate through fifteen gates before any
review state is granted.

**Everything here is ADVISORY_ONLY.** The simulator scores and explains; it
never places, sizes, or routes an order. The advisory contract
(`advisory_status=ADVISORY_ONLY`, `execution_gate=LOCKED`,
`broker_api_called=false`, `ai_execution_count=0`) is stamped on every
response, and there is no execution path anywhere in this system.

## Doctrine

```text
No signal is immortal.
No score is naked.
No stale soft signal can support hard conviction.
No fire extinguisher, no trade.
No high opportunity score can override high crash density.
No candidate is promoted without telemetry.
No user action is allowed if driver discipline is dangerous.
Prediction markets are radar, not the trade.
Narratives are weather. Signals are tyres.
Evidence is downforce. Noise is drag.
The MVP is the chassis. Crash cases are the wall.
Telemetry is truth.
```

Exposed live at `GET /simulator/doctrine`.

## Pipeline

`src/simulator/pipeline.py::evaluate_candidate_payload` runs the full chain
on one JSON payload:

```text
prediction-market radar -> narrative tracker -> theme/track condition
-> company exposure -> circuit classifier -> signal tyres -> inflection
-> aero package -> crash permutations -> triple-blind review -> meal box
-> driver license -> cherry-pick decision -> decision telemetry
```

Missing payload sections fall back to conservative defaults, so the
pipeline is **stingy by construction**: an empty payload dies on the ladder
(`reject`). Most candidates should die before the cherry-pick board.

## Modules and formulas

| Module | Formula(s) implemented |
|---|---|
| `signal_tyres.py` | `grip% = 100 × 0.5^(age / adjusted_half_life)` · `freshness = max(0, 1 − lag/window)` · `effective = raw × grip × freshness × source_quality × confirmation` · compounds soft/medium/hard/intermediate/wet with per-compound half-lives · stale-soft conviction block |
| `narrative_radar.py` | `shock = |Δp| × velocity × importance × liquidity × confirmation` |
| `narrative_tracker.py` | `dirty_air = 1 − origins/mentions` · 8 lifecycle states (`ignored … broken`) |
| `theme_mapper.py` | `track = macro + sector + policy + liquidity + risk_appetite − friction − crowding − heat` |
| `exposure_resolver.py` | `exposure = revenue + margin + backlog + customer + geo + policy + chain − weak_evidence` · 5 exposure classes |
| `circuit_classifier.py` | `difficulty = volatility + liquidity + data + manipulation + crash_baseline` · 9 circuits with threshold multipliers, size caps, allowed compounds, required license |
| `aero_engine.py` | `efficiency = downforce / drag` · dirty air, slipstream, ground effect, DRS, stall, porpoising, aero balance |
| `crash_simulator.py` | `risk = ΣRᵢ + Σβᵢⱼ RᵢRⱼ + Σβᵢⱼₖ RᵢRⱼRₖ` · `density = severe/total` over all pairwise + triple-wise permutations · synergy betas for known deadly combos |
| `triple_blind.py` | identity-blind score from anonymized metrics; model thesis written **before** user thesis; topic-overlap agreement; reality review pending until resolved |
| `meal_box.py` | `complete = thesis ∧ evidence ∧ catalyst ∧ invalidation` — no fire extinguisher, no trade |
| `driver_license.py` | `points(t) = points₀ × 0.5^(days/30)` · bands clean/caution/warning/probation/suspended/black_flag → permission multiplier 1.0 … 0.0 · 7 license levels matched to circuit requirements |
| `threshold_ladder.py` | state ladder `reject … high_conviction_candidate` + `pit_stop`/`black_flag` interrupts · 3-point hysteresis (anti-porpoising) · `inflection = Δvelocity + Δdiversity + Δvolume + Δestimates + Δfilings − Δcontradiction` |
| `cherry_pick.py` | `final = Σ positive weights − crash − drag − heat − dirty_air − driver_penalty` on 0–100 · all gates · never a naked Buy/No-Buy |
| `telemetry.py` | full decision snapshot · 8 outcome classes (good/bad process × result, timing, luck, false ±) · `calibration_error = predicted − actual` · JSONL replay log |

## Gates (in force at every evaluation)

| Gate | Rule | Cap |
|---|---|---|
| Crash gate | risk ≤ 0.60 and density ≤ 0.50 | watchlist |
| Grip gate | blended grip ≥ 35% | watchlist |
| Data/stall gate | data quality ≥ 0.30, no aero stall | watchlist |
| Stability gate | no porpoising | watchlist |
| Meal box | all four items present | active_watch |
| Hard conviction | no stale-soft-only thesis; hard evidence ≥ 0.60 | buy_candidate |
| Driver license | license rank ≥ circuit requirement | buy_candidate |
| Driver black flag | revenge flags / 80+ danger points | black_flag interrupt |
| Thesis damage | damaged thesis | pit_stop interrupt |

Circuit threshold multipliers (0.95 defensive → 1.6 biotech-event) scale
every ladder rung, so the same score promotes on large-cap and dies on
micro-cap. Hostile circuits also shorten signal half-lives.

## API

* `GET /simulator/doctrine` — doctrine, compound half-lives, circuit table.
* `POST /simulator/evaluate` — full evaluation of one candidate payload.
  Stateless and read-only; the response includes `decision`, `telemetry`,
  and per-engine `breakdown`, all stamped with the advisory contract.

A committed example request/response lives at
[`docs/examples/simulator_example_output.json`](examples/simulator_example_output.json)
(generated from the strong-candidate fixture in
`tests/test_simulator_cherry_pick_pipeline.py` — note it lands at
`active_watch`, not buy: the simulator is deliberately stingy).

## UI

`frontend/src/components/SimulatorVerdictCard.tsx` renders the breakdown —
ladder state, grip, crash risk/density, downforce/drag/efficiency, dirty
air, meal box, driver permission, failed gates — with conservative copy:
even `high_conviction_candidate` renders as "HIGH CONVICTION (REVIEW)" and
the card always carries "Advisory only · Execution gate locked · No orders
placed · Human decision required".

## Tests

```bash
pytest tests/test_simulator_signal_tyres.py \
       tests/test_simulator_narrative.py \
       tests/test_simulator_theme_exposure_circuit.py \
       tests/test_simulator_aero_crash.py \
       tests/test_simulator_driver_mealbox.py \
       tests/test_simulator_ladder_blind_telemetry.py \
       tests/test_simulator_cherry_pick_pipeline.py \
       tests/test_simulator_api.py
cd frontend && npx vitest run src/components/__tests__/SimulatorVerdictCard.spec.tsx
```

Covered doctrine cases: half-life decay; stale soft blocked from hard
conviction; dirty-air penalty (37 articles / 2 origins → 0.946); aero
efficiency; crash density and interaction terms; missing fire extinguisher
blocks promotion; danger points cap permission; circuit difficulty changes
thresholds; reaction lag reduces effective strength; triple-blind review is
serializable; final state is never a naked score; advisory language is
preserved end to end.

## Known limits (honest)

* All inputs are caller-supplied normalized scores; there is **no live
  ingestion** wiring narratives/prediction markets into the pipeline yet.
* Half-lives, interaction betas, weights, and thresholds are doctrine-derived
  defaults, **not calibrated from historical outcomes**.
* Theme→company exposure is scored, not resolved from a real supply-chain
  graph.
* Telemetry persists to local JSONL; replay/calibration analysis on top of
  it is manual.
