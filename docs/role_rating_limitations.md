# Role-Rating Limitations & Empirical Honesty

The RACR / Kanté Index measures **engineering and decision usefulness**, not
profit. This document states, plainly, what it does *not* establish — so a high
role score is never mistaken for evidence that a trade will make money.

## The firewall

> Role excellence never inflates empirical validation. A component can score 9+ on
> Role-Adjusted Performance while Empirical Validation stays near 1/10.

This is enforced in code (`racr.five_scores` / `whole_mvp_maturity`) and proven by
the adversarial audit: elite RACR (8.9) coexists with empirical 1.0 and whole-MVP
6.8. The five scores are separate by design.

## Hard honesty caps (this sprint)

- **Empirical Validation stays low.** There are no leakage-safe real outcomes
  wired into the SIL. The calibration harness computes Brier/ECE/tail-precision on
  *simulated defensiveness vs simulated/backtest outcomes*, and the applied
  evidence grade **never auto-promotes** above `SIMULATED_ONLY`.
- **No promotion above SIMULATED_ONLY without governance.** `EMPIRICALLY_CALIBRATED`
  and `MEASURED` are still never assigned automatically anywhere.
- **Whole-MVP maturity is capped by sample size** (≤ 8.0 below 20 real outcomes,
  ≤ 8.6 below 50). It is not inflated by one elite subsystem.

## What the scores are — and are not

| The scores DO measure | The scores do NOT measure |
|---|---|
| How well a component performs its declared role | Profit, returns, or realised P&L |
| Marginal contribution to decision quality (ablation) | Predictive accuracy of the council |
| Reliability, determinism, fault survival | Validated alpha |
| Honest evidence labelling & leakage resistance | That any recommendation will be correct |
| Operator clarity & explainability | A substitute for human judgement |

## Modelling caveats

- **Dimension evidence is partly proxy/derived.** Many dimensions are DERIVED from
  runtime facts (ablation Shapley, determinism, ledger events) rather than MEASURED
  from real outcomes. Support labels (`PROXY_HEAVY`, `LOW_SAMPLE`) and rating
  confidence surface this; a PROXY-heavy score is not a MEASURED one.
- **Context difficulty is a heuristic**, not ground truth. It scales credit but is
  bounded and never rewards a bad input on its own.
- **Ablation value `v(S)` is a constructed characteristic function**, not an
  economic value. Shapley values rank *relative* lens contribution to decision
  informativeness, not to returns.
- **The calibration target is defensiveness**, an advisory proxy — not a directional
  trading signal.

## What would raise Empirical Validation

Wire reconciled/forward outcomes through the existing leakage-safe path
(`outcome_evidence` → `calibration_map`), accumulate ≥ 20–50 leakage-safe
resolved outcomes, and have a human governance decision promote the evidence
grade. Until then, Empirical Validation stays low **and is reported low, on
purpose**. Role-adjusted excellence is real engineering value; it is not, and is
never presented as, financial performance.
