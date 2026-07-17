# Eureka Experiment Results

## Minimum breakthrough experiment (current vs current + Decision Twin)

Ran the four-candidate cohort through the current system (council only) and the
breakthrough (closed loop). Evidence: `scratchpad/eureka_probe.py` Part A.

| Metric | Current system | + Breakthrough |
|---|--:|--:|
| Falsifiable predictions frozen | 0 | 15 |
| Outcomes resolvable (registered) | 0 | 15 |
| Missing-info decisions produced | 0 | 3 |
| Weak candidates cheaply rejected | 0 | 1 |

**Counterfactual gate:** with the twin a candidate yields 5 frozen, resolvable
falsifiable predictions; without it, 0 (a council result is not resolvable). The
breakthrough produces evidence the current system structurally cannot.

## Adversarial audit matrix (14/14 PASS)

| Attack | Result |
|---|---|
| Prediction mutation | PASS — twin hash detects any content change |
| Frozen prediction edit | PASS — FalsifiablePrediction is frozen |
| Outcome leakage (pre-cutoff bars) | PASS — → NO_DATA, not resolved |
| Future window peeking | PASS — → FUTURE_UNRESOLVED |
| Same-day entry ambiguity | PASS — entry strictly after cutoff |
| Value-of-information spam | PASS — ranked list bounded to ≤8 |
| Endless research loop | PASS — robust+calibrated → NO_RESEARCH_WORTHWHILE |
| Shadow-policy hindsight | PASS — decision hash prevents rewrite |
| Lucky-outcome inflation | PASS — bad-process/good-outcome → flag_lucky_process |
| Process-score inflation | PASS — no-execution violation caps process at 3.0 |
| Compute theatre on weak candidate | PASS — REJECT_CHEAP, no council |
| Unbounded computation | PASS — candidate list capped at 50 |
| No-execution invariants | PASS — loop never executes |
| Hidden execution language | PASS — summary free of execution-shaped advice |

## Eureka quality gates

- **Novelty:** not an existing module renamed — twins/VoI/shadow-policies/outcome-resolution are new.
- **Runtime:** reached via `POST /api/intelligence/daily-shadow-run` and the `/intelligence` page.
- **Counterfactual:** removing the twin loses all falsifiability (measured above).
- **Evidence:** 34 backend tests + 3 frontend tests + 14 adversarial checks.
- **Safety:** advisory-only controls intact everywhere.
- **Simplicity:** ~10 bounded modules; each small and single-purpose.
- **Reliability:** fails closed; leakage guards tested.
- **Empirical honesty:** Empirical Readiness ≠ Empirical Score, reported separately.
- **Operator value:** attention queue + single most-valuable research action + cheap rejects.
- **Anti-gaming:** VoI bounded, research terminates, no hindsight, no lucky-outcome credit.
