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

## Scrutineering bay (anti-fooling layer)

`src/simulator/scrutineering.py` cross-examines every payload against the
simulator's own physics invariants before a verdict is published — like
post-race technical inspection. Conservation laws checked:

1. **Confirmation without origins** — claimed confirmation must be carried
   by absolute independent origin count, not echo volume.
2. **Hard evidence without hard tyres** — a 0.9 hard-evidence claim with
   only soft-compound signals supplied is a contradiction.
3. **Clean crash on a dirty circuit** — claimed total risk cannot undercut
   the circuit's own crash baseline.
4. **Downforce without filings** — high aero evidence with an empty
   meal-box evidence text is downforce with no wing.
5. **Shock without narrative** — a large prediction-market delta with no
   mentions on the wire is radar contact with an empty sky.
6. **Uniform optimism** — many extreme favorable inputs with near-zero
   variance; honest research is never that smooth.
7. **Humility index** — confidence claims above the volume-supported
   ceiling get dampened in the final score.

A failed inspection caps the ladder at watchlist
(`DISQUALIFIED_PENDING_EVIDENCE`) — the verdict survives, provisionally,
until the evidence is real. This makes the simulator structurally hard to
fool with self-consistent optimistic inputs.

## Calibration bridge (recommendation-only)

`src/simulator/calibration_bridge.py` reuses the journal's canonical
Brier/ECE implementations (`scripts/calibration_map.py`) over decision
telemetry, computes per-segment drift (circuit, compound, exposure class,
crash-density bucket, license, narrative state), and proposes — never
applies — parameter adjustments:

```text
D_s   = mean(error_s) - mean(error_global)
h_new = clamp(h_old · exp(-λ·D_s), 0.25·h_old, 4·h_old)
β_new = clamp(β_old + η·residual, 0.1, 1.5)
```

Calibration modes are never conflated: `insufficient_data`,
`fixture_replay` (seeded data proves the machinery, not the market), and
`empirical` (only real resolved decisions). `unsafe_to_autotune` defaults
to True and clears only through a strict gate (empirical mode, n ≥ 50,
ECE ≤ 0.10) — and even then nothing is applied without a human.
A deterministic 48-row fixture lives at
`tests/fixtures/simulator_replay_fixture.jsonl` (SIMULATED, labeled as such).

## Reality replay (triple-blind stage 3)

`src/simulator/reality_replay.py` replays resolved decisions against
outcome and classifies them: `right_for_right_reason`,
`right_for_wrong_reason`, `wrong_but_process_clean`,
`wrong_due_to_stale_signal` / `missing_invalidation` /
`exposure_mismatch` / `driver_violation`, `insufficient_data`. A failure
is *knowable* when the decision-time snapshot already contained the
warning. Knowable process failures convert into driver violations.

## Derived driver state

`src/simulator/driver_derivation.py` derives violations from the actual
journal (manual trades + reconciliations) instead of self-report: missing
thesis/invalidation, ignored block flags, leverage breaches, tailgating
confidence, and revenge re-entry within 48h of a reconciled loss — all
with the standard 30-day penalty decay.

## Live adapter & exposure graph

`src/simulator/live_adapter.py` transforms stored ingestion shapes
(Polymarket/Kalshi snapshot pairs, source mention clusters, security
metadata) into pipeline payload sections — fixture-tested, no network.
`src/simulator/exposure_graph.py` resolves theme→ticker exposure through
provenance-carrying edges (`1 - Π(1-c_i)`, fragility and lag decay); the
pipeline falls back to the seed graph when the caller supplies no
exposure section. The seed graph is illustrative, not a real
supply-chain dataset.

## API

* `GET /simulator/doctrine` — doctrine, compound half-lives, circuit table.
* `POST /simulator/evaluate` — full evaluation of one candidate payload.
  Stateless and read-only; the response includes `decision`, `telemetry`,
  and per-engine `breakdown`, all stamped with the advisory contract.
* `POST /simulator/evaluate-and-record` — evaluate and persist the verdict
  (local SQLite) so threshold hysteresis survives across sessions.
* `GET /simulator/history` — read-only persisted evaluation history.
* `GET /simulator/calibration/report` — recommendation-only calibration
  report over persisted telemetry (honest mode labeling, autotune locked).

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

* The live adapter is a tested boundary, but the 6-hour refresh job does
  not yet call it automatically — assembling payloads from stored
  ingestion is still operator-initiated.
* Half-lives, betas, weights, and thresholds remain doctrine-derived
  defaults. The calibration bridge can now measure drift and propose
  adjustments, but **no empirical fitting has occurred** (no resolved
  real-decision sample exists yet) and autotune is locked.
* The exposure graph is a seeded v0 structure, not a real supply-chain
  dataset.
* Driver derivation reads the journal but the simulator does not yet
  auto-inject derived violations into every evaluation; callers opt in.
* UI: the simulator page runs fixtures against the live backend; free-form
  payload editing is not built.
