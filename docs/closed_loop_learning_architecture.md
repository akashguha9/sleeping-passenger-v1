# Closed-Loop Learning Architecture

The runtime flow that makes discovery→learning a closed loop
(`daily_shadow_run.py`, `POST /api/intelligence/daily-shadow-run`):

```
DAILY CANDIDATES
  → build MarketObservation (fail-closed, provenance preserved)
  → INTELLIGENCE BUDGET (cheap-reject weak; deep-allocate high-value uncertainty)
  → SIX-LENS COUNCIL (at allocated depth)
  → VALUE OF INFORMATION (ranked agenda or "no research worthwhile")
  → DECISION TWIN (freeze falsifiable predictions + refusals + regime + uncertainty)
  → SHADOW POLICIES (immutable counterfactual advisory decisions)
  → PROCESS QUALITY (outcome-independent)
  → OUTCOME-RESOLUTION JOBS (registered with a resolve-on-or-after date)
  → [time passes]
  → LEAKAGE-SAFE RESOLUTION (entry strictly after cutoff; unelapsed window skipped)
  → PREDICTION OUTCOMES (Brier/hit; job → RESOLVED; prediction untouched)
  → PROCESS×OUTCOME quadrant → RACR ledger credit/blame
  → EUREKA HEALTH (Empirical Readiness vs Empirical Score, reported separately)
  → NEXT DAILY RUN
```

Shadow mode (default): all predictions recorded, no human action required, no
broker interaction, outcomes resolve later. This is the safe evidence-accumulation
path. Every stage is advisory-only; `execution_gate=LOCKED` throughout.
