# Chicken Gate v1.2 — Daily Synthesis Integration

**ADVISORY-ONLY.** The chicken gate scores and gates; it never executes,
never calls a broker, never places orders. Every output carries the
canonical advisory stamp and requires human review.

## Where it is wired

`scripts/daily_synthesis_pipeline.py :: run_daily_synthesis()` — after
`build_candidate_executable_split` (the existing decision) and before the
result object is returned:

    CQS/EQS scoring -> candidate_executable_split (EXISTING decision)
        -> scripts/chicken_gate_daily_bridge.build_chicken_gate_integration
        -> chicken_gate.evaluate_chicken_gate per buy-side candidate
        -> demote-only integrated gate
        -> result["chicken_gate_integration"] + audit lines + artifacts

`SELL / EXIT REVIEW` rows are not buy decisions and are excluded (listed
under `excluded_rows`). The split object itself is never mutated.

## How the final gate is computed

Gate ranks: BUY_BLOCKED=0, WATCHLIST=1, BUY_LIMITED=2, BUY_ALLOWED=3.

    EXISTING_ACTION_GATE  = classification mapping
        (EXECUTABLE-PAPER-BUY -> BUY_ALLOWED,
         BUY-CANDIDATE / NOT-EXECUTABLE -> BUY_LIMITED,
         WATCHLIST/WATCHLIST-UPGRADE/WAIT -> WATCHLIST,
         AVOID / STALE-REMOVE -> BUY_BLOCKED)
    CHICKEN_ACTION_GATE   = chicken_gate FINAL_ACTION_GATE
    FINAL_ACTION_GATE     = rank_to_gate(min(existing_rank, chicken_rank))

    EXISTING_SCORE          = CQS x 10
    CHICKEN_FINAL_SCORE     <= RAW_VALIDATED_SCORE   (gate invariant)
    INTEGRATED_FINAL_SCORE  = min(EXISTING_SCORE, CHICKEN_FINAL_SCORE)

The chicken gate can only confirm or demote. It can never upgrade an
existing decision, and the integrated score can never exceed either input.

## Field mapping (daily candidate -> chicken thesis)

Only real pipeline data becomes evidence:

| Chicken input | Source | Missing behaviour |
|---|---|---|
| house_edge_score / confidence | CQS x 10 / mover source_health | neutral, confidence 0 |
| input_quality_score / confidence | data_quality x 10 / source_health | neutral, confidence 0 |
| information_access_premium | max(crowding_risk x 10, (1 - why_today) x 10) | IAP evidence-slot notes + silence floor |
| price_move_since_signal_pct | mover move_pct | slot note |
| channel_premium_score | provider/source classification (FILING 1.0 .. SOCIAL 8.0, STATIC 6.0) | slot note + neutral 5 |
| thesis_age_days | 0.0 if live/fresh today, 1.0 if carried from yesterday | first-signal haircut x0.85 |
| operator fit | payload verified_holdings positions (deterministic) | fit 5 + x0.90 haircut |
| model / market probability | not available at this layer | NET_EDGE INSUFFICIENT_EVIDENCE -> cap BUY_LIMITED |
| process integrity, label, bone | no daily evidence | documented conservative neutrals (conf 0.5) |
| load-bearing node | **deliberately unmapped** | fail-closed cap at BUY_LIMITED |

**Consequence (by design):** an auto-mapped daily candidate cannot exceed
BUY_LIMITED, and with today's degraded providers most rows gate BLOCKED.
The gate's `evidence_notes` list exactly what evidence would unlock a
higher gate. Operators supply it per ticker via
`runtime/chicken_gate_thesis_overrides.json` (or the
`chicken_thesis_overrides` argument) — e.g. `load_bearing_node`,
`thesis_touches_node`, `model_probability`, component confidences.

## Fields added

Per integrated row (top level, UPPERCASE): `EXISTING_ACTION_GATE`,
`CHICKEN_ACTION_GATE`, `FINAL_ACTION_GATE`, `EXISTING_SCORE`,
`CHICKEN_FINAL_SCORE`, `CHICKEN_RAW_VALIDATED_SCORE`,
`INTEGRATED_FINAL_SCORE`, `CHICKEN_HARD_FLAG_TRIGGERED`,
`CHICKEN_CAP_RULES_TRIGGERED`, `CHICKEN_ONE_LINE_REASON`,
`FINAL_EXECUTABLE`, `AUDIT_LINE`, plus the nested `chicken_gate` audit
block (scoring version, raw/validated scores, multipliers, ledger,
evidence notes, advisory stamp) and `chicken_gate_thesis_inputs` (stored
for daily decay re-evaluation).

Runtime artifact `runtime/daily_synthesis_context.json` gains a
`chicken_gate` summary (mode, version, final_gate_counts, demotions,
audit_lines). All pre-v1.2 keys are preserved. No Google Sheets sync
exists in this repo; if one is added, migrate from this JSON block.

## Daily decay

`chicken_gate_daily_bridge.reevaluate_daily_decay(integration, now=...)`
re-runs stored thesis inputs at a later date. With fixed non-time inputs,
the freshness multiplier and final score are monotonically non-increasing
(tested).

## Configuration

Defaults: `CHICKEN_GATE_ENABLED_DEFAULT = True`,
`CHICKEN_GATE_DEBUG_BYPASS_DEFAULT = False` (constants in the bridge;
`run_daily_synthesis` exposes matching keyword arguments). When bypassed,
every row is stamped `CHICKEN_GATE_DISABLED_DEBUG_ONLY` and the final gate
falls back to the existing decision — the bypass discloses itself and is
never the default path.

## How to run

    python -m pytest tests/test_chicken_gate.py tests/test_chicken_gate_daily_bridge.py -v
    python scripts/daily_synthesis_pipeline.py          # context block incl. audit lines
    python scripts/daily_synthesis_pipeline.py --write  # persist runtime artifacts
    python -m scripts.chicken_gate --demo               # standalone gate card
