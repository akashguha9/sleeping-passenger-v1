# Simulation Intelligence Layer — Operator Guide

The **Simulation Lab** (`/simulation-lab` in the frontend) runs an advisory-only
six-lens *what-if* council for one candidate. It answers the questions a decision
needs — *what changed, why, which assumption matters, what could invalidate this,
how robust is it, what is the cost of waiting, what is the worst plausible outcome,
and is this measured or simulated* — **without ever placing an order**.

Everything the Lab produces is `SIMULATED_ONLY` unless explicitly labelled
otherwise. It is a rehearsal tool, not a prediction of profit.

---

## 1. Enabling it

All defaults are safe. In `.env` (see `.env.example`):

```bash
SIL_ENABLED=true            # master switch; false → the layer refuses (fail-closed)
SIL_STOCKFISH_ENABLED=false # optional EXTERNAL_PROCESS engine, off by default
SIL_COPASI_ENABLED=false    # optional NATIVE_LIBRARY engine, off by default
SIL_MAX_RUNS=512            # Monte-Carlo cap per scenario (bounded workload)
SIL_MAX_SCENARIOS=24        # scenarios applied per run
SIL_TIMEOUT_MS=2000         # per-run soft budget
```

The council runs fully with both optional engines off — they only widen breadth,
never gate the result.

## 2. API surface (advisory-only, bounded, typed)

| Method & path | Purpose |
|---|---|
| `GET /api/simulation/health` | SIL availability + feature flags. Never blocks. |
| `GET /api/simulation/engines` | The verified 18-engine manifest + honest live availability. |
| `GET /api/simulation/scenarios` | The 32 India/US stress + operational scenarios. |
| `POST /api/simulation/run` | Run the six-lens council for a candidate; persist a `SIMULATED_ONLY` run. |
| `GET /api/simulation/runs` | Recent runs (newest first). |
| `GET /api/simulation/runs/{run_id}` | One stored run (full council result). |
| `GET /api/simulation/runs/{run_id}/replay` | Deterministic replay from the stored seed + data cutoff. |
| `GET /api/simulation/council/{ticker}` | Latest stored council result for a ticker. |
| `GET /api/simulation/stress-summary` | Aggregate stress-scenario summary. |

`POST /api/simulation/run` body (all bounded and validated):

```json
{
  "ticker": "RELIANCE.NS",
  "market": "IN",
  "seed": 42,
  "max_runs": 512,
  "parent_signal_id": "SIG_123",
  "scenarios": ["broad_market_crash", "earnings_miss", "liquidity_evaporation"],
  "requested_lenses": [],
  "observation": {
    "ticker": "RELIANCE.NS", "market": "IN", "data_cutoff": "2026-07-15",
    "returns": [0.01, -0.02, 0.015, "…recent daily returns…"],
    "volatility": 0.025, "spread_bps": 8, "adv_usd": 8000000,
    "sector": "Energy", "narrative_sources": ["reuters", "et"], "source_count": 2,
    "freshness_status": "FRESH",
    "catalysts": [{"id": "earnings", "magnitude": 0.3}]
  }
}
```

Missing numeric fields are recorded in `missing_fields` and the lenses **fail
closed** (label `INSUFFICIENT_DATA`) rather than inventing values.

## 3. Reading a council result

- **`aggregate_vote`** — one of `WATCH / OUTCOME_REVIEW / WAIT / AVOID / RISK_BLOCK`.
  These are **attention/timing stances a human interprets**, never execution
  instructions.
- **`evidence_label`** — the *weakest binding* label across contributing lenses
  (the honesty floor). If it says `SIMULATED_ONLY`, the conclusion rests on
  simulation, not measured outcomes.
- **`simulation_only`** (boolean) — a *finer* signal than the label: `true` when
  **every** contributing lens is simulation-grade. It can be `false` (some lens is
  `MODEL_INFERRED` from real-ish inputs) even while `evidence_label` is
  `SIMULATED_ONLY` — read both.
- **`disagreement_class`** — how the six lenses relate:
  `CONSENSUS_ROBUST`, `CONSENSUS_FRAGILE`, `SPLIT_DECISION`,
  `MINORITY_TAIL_WARNING`, `SHARED_EVIDENCE_ILLUSION`,
  `INSUFFICIENT_INDEPENDENCE`, `SIMULATION_ONLY_CONSENSUS`.
- **`risk_block_engaged`** + **`risk_block_reason`** — a defensive override fired.
- **`lens_weights`** — every weight with its `reasons` (base × evidence × penalties).
- **`minority_warnings` / `tail_warnings`** — never buried by the aggregate.
- **`usefulness_score`** (0–10) — **engineering/decision usefulness, NOT alpha**.
- **`robustness` / `fragility`** — stability to assumption perturbation.

## 4. Frontend — the Simulation Lab

`/simulation-lab` (registered in the sidebar) shows: engine & capability registry,
scenario catalog, the six-lens council with per-lens votes and evidence tones,
the aggregate stance with its explanation, robustness-vs-fragility, tail/minority
warnings, recent runs, and a clear **measured-vs-simulated** distinction. It uses
the existing design system (`AdvisoryOnlyBadge`, `NoExecutionBanner`) and always
displays the no-execution banner.

## 5. CLI / machine-readable report

```bash
python -m scripts.simulation_intelligence.report --write   # writes runtime/release/simulation_intelligence_summary.json
python -m scripts.simulation_intelligence.report --json    # prints to stdout
```

The artifact follows the repo's `*_summary.json` convention and prints the standard
`[safety] broker_api_called=False ai_execution_count=0 execution_gate=LOCKED` line.
Its `simulation_usefulness_score` measures engineering/decision usefulness only;
`empirical_validation_score` is `0.0` until leakage-safe real outcomes exist.

## 6. What it will not do

It cannot place, route, or simulate a broker order; cannot raise
`ai_execution_count` above 0; cannot unlock `execution_gate`; cannot feed
calibration or sizing; and cannot claim profitability or validated alpha. If data
is stale, missing, or the layer is disabled, it degrades or refuses — it never
guesses.
