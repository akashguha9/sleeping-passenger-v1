# Eureka Limitations & Empirical Honesty

## What this sprint did and did NOT do
It built the **machine that can generate, freeze, resolve and learn from evidence
without leakage**. It did **not** fabricate outcomes. Therefore:

- **Empirical Readiness ≈ 9.0/10** — the loop closes: falsifiable predictions are
  frozen, outcome windows are registered, resolution is leakage-safe and wired.
- **Empirical Score ≈ 1.0/10** — there are still no validated real outcomes. It
  will rise only as real forward windows elapse and resolve, and only a human
  governance decision may promote an evidence grade above SIMULATED_ONLY.

These two are reported **separately** (`GET /api/intelligence/eureka-health`) and
never merged. A high readiness score is not, and is never presented as, financial
performance.

## The surprise: how it was discovered and why it is non-obvious
While wiring the Value-of-Information engine, the naive formulation recommended
acquiring information the system already effectively had (many correlated sources,
or a robust council consensus). The non-obvious fix couples VoI to **two** signals
most engines ignore:
1. **Redundancy** — discount value for information that duplicates existing
   (concentrated) evidence or merely confirms a robust consensus.
2. **Calibration** — amplify VoI where the system is *poorly calibrated* in this
   regime (its beliefs are untrustworthy) and damp it where well-calibrated.

Why non-obvious: standard VoI ranks by uncertainty reduction alone. Coupling it to
the system's *own historical trustworthiness* and to *evidence independence* means
research spending self-regulates — it stops when the system already knows enough,
and intensifies exactly where its beliefs cannot be trusted. Measured marginal
value: it flips the verdict to NO_RESEARCH_WORTHWHILE for robust candidates and
changes net VoI by ~40× between well- and poorly-calibrated regimes. It is not
score inflation — it *reduces* recommended research, protecting operator attention.

## Modelling caveats
- The falsifiable predictions are `MODEL_INFERRED` at best; they are honest but
  not yet validated.
- The VoI catalogue is fixed and its cost/reliability priors are heuristics.
- Regime cohorts are small early on; low-sample labels apply and metrics are not
  presented as reliable until sample minimums are met.
- The calibration reliability that feeds the VoI amplifier is a conservative prior
  (0.5) until enough resolved outcomes exist per regime.
- Belief revisions require an evidence-arrival source; the loop registers the
  machinery but real evidence-arrival ingestion is a next step.

## Remaining blockers
1. Auto-populate the daily candidate list from the live discovery pipeline (the
   signal bridge is wired to the API, not yet to the daily cron).
2. Schedule automatic outcome resolution as windows elapse (the due-queue exists;
   a resolver cron does not yet run).
3. Accumulate enough leakage-safe resolved outcomes to lift Empirical Score with a
   human governance decision.
