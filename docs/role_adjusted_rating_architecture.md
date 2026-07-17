# Role-Adjusted Rating (RACR) — Architecture

**Status:** Implemented, runtime-reached, tested.
**Package:** `scripts/simulation_intelligence/` (extends the SIL from the prior sprint).

The RACR sprint adds a **role-aware evaluation layer** on top of the six-lens
simulation council: it scores every major component against the job assigned to
it (not against trade execution or returns), measures each lens's *invisible*
marginal contribution via ablation, records evidence-linked contribution events,
bridges live signal state into the council, and reports honest leakage-safe
calibration. Five separate scores are produced and never averaged.

Everything is advisory-only, record-only, fail-closed. `execution_gate=LOCKED`,
`broker_api_called=false`, `ai_execution_count=0` on every surface.

## Module map (new this sprint)

```
scripts/simulation_intelligence/
  role_contracts.py        # 18 versioned, immutable ComponentRoleContracts + 20 dims
  racr.py                  # RACR engine: role weights, anti-gaming caps, 5 scores
  contribution_ledger.py   # positive/negative/prevention/recovery/enabling events
  context_difficulty.py    # 12-factor context-difficulty score
  ablation.py              # leave-one-out + EXACT Shapley (2^6) + interactions
  signal_bridge.py         # Priority 1: live OHLCV/signal state → MarketObservation
  calibration_harness.py   # Priority 2: leakage-safe SIL prediction/outcome cohorts
  reliability.py           # reliability metrics + fault injection + scenario mutation
  engine_validation.py     # Priority 3: Stockfish/COPASI verification profiles
  champion_challenger.py   # bounded champion–challenger (no auto-promotion)
  role_rating_service.py   # runtime glue: council→ablation→ledger→RACR→5 scores
```

Persistence (`scripts/persistence.py`, additive tables):
`sil_contribution_events`, `sil_role_ratings` (+ accessors), advisory-stamped rows.

API (`scripts/api_server.py`): `/api/simulation/role-contracts`, `/ratings`
(POST+GET), `/contribution-events`, `/observation/{ticker}`, `/reliability`,
`/engine-validation`.

Frontend: the Simulation Lab gains a role-ratings view (five scores, the quiet-
but-valuable "Kanté" lens, per-component RACR with support/grade/ceiling, and a
contribution-event drill-down).

## Data flow (runtime-reached)

```
POST /api/simulation/ratings (or role_rating_service.build_ratings)
   │
   ├─ run_council(request)                     → SimulationCouncilResult
   ├─ ablation.run_ablation(request)           → Shapley marginal contributions
   ├─ context_difficulty.score_context(...)    → context difficulty
   ├─ reliability.measure_reliability([...])   → determinism/safe rates (measured)
   ├─ contribution_ledger.derive_events_from_run(council, ablation)
   │        → evidence-linked ContributionEvents  (persisted)
   ├─ per component: assemble DimensionEvidence from the above facts
   ├─ racr.score_component(...)  ×18            → RoleAdjustedRating (persisted)
   └─ racr.five_scores(...)                     → the five separate headline scores
```

## Design decisions

1. **Role weights are immutable and declared first.** A component cannot pick an
   easier role after seeing results (`role_contracts._ROLE_WEIGHTS`, returned as
   fresh copies; tested).
2. **Evidence-linked, not asserted.** Every dimension score cites a source; every
   contribution event points at a concrete run fact. Prevented-failure claims are
   grounded in *executable* ablation counterfactuals, never imagination.
3. **Five scores stay separate.** The empirical-validation score is firewalled: it
   rises only with leakage-safe real outcomes, never from simulated sophistication;
   whole-MVP maturity is pulled toward it and capped by sample size.
4. **Anti-gaming is structural.** Runtime-reach cap, unsupported cap, severe-event
   cap, honest ceiling, capped ledger nudge, diminishing returns, support labels.
5. **Bounded + deterministic.** Ablation is exact only for ≤6 lenses (64 coalition
   evals, stress disabled); above that it is labelled *approximate*. Reliability
   batches are tiny and bounded. Same seed + cutoff → identical results.
6. **Fail-closed everywhere.** SIL disabled → structured refusal; missing data →
   INSUFFICIENT_DATA; optional engine absent → graceful degradation; a broken lens
   is isolated and the council still returns.

## Integration with existing systems

- Reuses `advisory_contract` stamps, `persistence` conventions, `api_server`
  route/auth/rate-limit style, and the frontend design system.
- The **signal bridge** reads canonical `ohlcv_bars` (fallback: live
  `market_data` events) and resolves market via `leverage_governance` — see
  `docs/signal_to_simulation_integration.md`.
- The **calibration harness** reuses `outcome_evidence.build_outcome` and
  `calibration_map.fit_from_outcomes` (its OOS split is the look-ahead guard) —
  see `docs/sil_calibration_methodology.md`.
- Architecture-fitness stays PASS at score 1.0 (new modules live in the
  subpackage, import no broker/frontend/sqlite in the pure layers).
