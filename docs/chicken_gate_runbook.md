# Chicken Gate Runbook (v1.3)

**ADVISORY-ONLY.** Sleeping Passenger does not trade and does not execute.
It blocks weak evidence, teaches what evidence is missing, and keeps the
final score at or below validated merit. A human makes every decision.

## What ships where

| Piece | Path |
|---|---|
| Canonical gate (the ONLY BUY gate) | `scripts/chicken_gate.py` |
| Daily-synthesis integration bridge | `scripts/chicken_gate_daily_bridge.py` |
| Evidence repair loop / unlock sim / payload health | `scripts/chicken_gate_repair_engine.py` |
| Wiring point | `scripts/daily_synthesis_pipeline.py :: run_daily_synthesis()` |
| Docs | `docs/chicken_gate_consolidation_map.md`, `docs/chicken_gate_v1_2_daily_integration.md`, `docs/chicken_gate_v1_3_evidence_repair_loop.md` |
| Runtime artifacts (gitignored, regenerated) | `runtime/daily_synthesis_context.json`, `runtime/chicken_gate_thesis_overrides.template.json` |
| Operator evidence input | `runtime/chicken_gate_thesis_overrides.json` |

## Reproduce from a fresh checkout

```powershell
# 1. Gate + integration + repair-loop tests (fast, ~5s)
python -m pytest tests/test_chicken_gate.py tests/test_chicken_gate_daily_bridge.py tests/test_chicken_gate_repair_engine.py tests/test_chicken_gate_session_smoke.py -q

# 2. Guard suites (registration, boundaries, advisory contract)
python -m pytest tests/test_private_scope_guard.py tests/test_core_module_boundary.py tests/test_architecture_fitness.py tests/test_advisory_contract.py -q

# 3. Full suite — run in chunks (a single run exceeds 10 minutes)
python -m pytest -q tests/test_[a-k]*.py
python -m pytest -q tests/test_[l-r]*.py
python -m pytest -q tests/test_[s-z]*.py tests/chronology
```

## Daily operator loop

```powershell
# Score one thesis standalone (trade card + who-ate-the-value ledger)
python -m scripts.chicken_gate --demo
python -m scripts.chicken_gate --thesis-json my_thesis.json
python -m scripts.chicken_gate --thesis-json my_thesis.json --holdings   # fit from verified holdings

# Run the daily synthesis with the gate + evidence repair loop
python scripts/daily_synthesis_pipeline.py            # print context incl. audit lines + repair summary
python scripts/daily_synthesis_pipeline.py --write    # persist runtime artifacts + override template
python scripts/daily_synthesis_pipeline.py --json     # machine-readable summary
```

Then:

1. Read `runtime/daily_synthesis_context.json` → `chicken_gate_v1_3_summary`.
   Check `payload_health_score` FIRST: below 5 means a bad-data day — do
   not read mass BUY_BLOCKED as bearishness.
2. Open `runtime/chicken_gate_thesis_overrides.template.json`. Each
   sub-ALLOWED ticker has `_priority_repairs` (do these first),
   `_max_simulated_repairable_gate` (what the fix is worth), and
   `do_not_override_if` / `_non_repairable_do_not_touch` (never bypass).
3. Fill only what you can EVIDENCE into
   `runtime/chicken_gate_thesis_overrides.json` (copy blocks from the
   template). Confidence without citations is still haircut.
4. Re-run the pipeline. Overrides change the NEXT run's gate — repair
   plans never change the current one.
5. Five-model roundtrip: run `scripts/run_five_model_synthesis.ps1` so the
   report exists for today's run_date; otherwise every candidate is capped
   at BUY_LIMITED (`FIVE_MODEL_SYNTHESIS_NOT_AUDITED`) by design.

## Invariants you can rely on (all test-enforced)

- `FINAL_SCORE <= RAW_VALIDATED_SCORE <= RAW_TRADE_SCORE`; every stage
  multiplier is in [0, 1] (demote-only).
- `rank(FINAL_GATE) = min(rank(existing), rank(candidate), rank(synth))`,
  with the synth-unaudited cap only ever lowering further.
- `INTEGRATED_FINAL_SCORE <= min(available scores)`.
- `0 <= payload_health_score <= 10`; `< 5` always carries the
  DAILY_PAYLOAD_DEGRADED warning.
- Non-repairable hard blocks (spoilage, time-spoiled freshness, process
  integrity < 3) pin the unlock simulation at BUY_BLOCKED.
- `THEORETICAL_COMPONENTS == ()` — no scoreboard claim without shipped code.
- Advisory-only stamp on every output; no broker imports anywhere in the
  gate path (token-scanned in tests).
