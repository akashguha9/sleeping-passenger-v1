# The Kanté Index — Role-Adjusted Contribution Rating (RACR) Methodology

> **Disclaimers (read first).**
> - The "Kanté Index" is a **conceptual analogy only**. It is inspired by the
>   general, widely-understood idea that an elite defensive midfielder can earn a
>   top match rating through positioning, interception, recovery and error
>   prevention — *without* scoring or assisting.
> - It is **not affiliated with, endorsed by, or connected to N'Golo Kanté** in
>   any way. The name is used purely as a memorable label for "role-aware
>   evaluation".
> - It is **not affiliated with SofaScore** and **does not reproduce, reverse-
>   engineer, or approximate SofaScore's proprietary rating algorithm**. RACR is
>   an original, auditable formula built from first principles.
> - It **does not transform engineering quality into claimed investment
>   performance**. A high role score is a statement about *how well a component
>   does its job*, never a prediction of profit. Empirical validation is scored
>   separately and stays low until leakage-safe real outcomes exist.
> - The football nickname appears only in technical documentation like this. The
>   investor-facing UI uses plain role-rating language.

---

## 1. Why role-aware scoring

Sleeping Passenger's Simulation Intelligence Layer must **not** be judged as if it
were a broker, a portfolio manager, or an alpha generator — it is none of those,
by design and by hard safety controls. Its job is to make the system *harder to
fool, harder to break, harder to overfit, and better at reasoning under
uncertainty*. A component can be elite at that job while never touching the final
financial outcome — exactly like a defensive midfielder.

So each component is scored against **the responsibilities in its declared role
contract**, with role-specific weights. A risk engine is rewarded for
interception and error prevention, not for producing opportunities; a frontend is
rewarded for operator clarity, not for search depth.

## 2. The 20 RACR dimensions

Every component is scored on all twenty dimensions; its role decides which ones
carry weight (`scripts/simulation_intelligence/role_contracts.py`,
`RoleDimension`):

`role_fidelity, coverage, risk_interception, error_prevention, decision_influence,
reliability, consistency, context_difficulty, recovery_ability, collaboration,
information_efficiency, uncertainty_handling, explainability, operator_usefulness,
resource_efficiency, evidence_quality, calibration_integrity,
adversarial_resilience, runtime_reach, regression_resistance`.

Each dimension measurement (`racr.DimensionEvidence`) carries: a value in [0,10],
an **evidence grade** (MEASURED/DERIVED/PROXY/SIMULATED/NONE), a **confidence**, a
**sample size**, an **evidence source**, and a **reason**. Missing evidence is not
neutral — see the caps below.

## 3. Not a simple average

The role-adjusted performance is a confidence- and weight-weighted combination
over *measured* dimensions:

```
RACR_raw = Σ_d  W_role[d] · value[d] · confidence[d]
           ────────────────────────────────────────
           Σ_d  W_role[d] · confidence[d]
```

Weights `W_role` come from the component's immutable role template. A role-critical
dimension (weight ≥ 1.0) with **no** evidence is not skipped — it is inserted as a
low, low-confidence placeholder that drags the score, so silence on a core
responsibility costs you.

## 4. Anti-gaming caps (applied after the weighted score)

RACR is designed so that a higher rating must be *earned*, never manufactured
(`racr.score_component`):

| Cap | Rule |
|---|---|
| **Not runtime-reached** | capped at **4.0** — orphaned/documentation-only code cannot be elite |
| **Unsupported evidence** | capped at **5.0** with rating confidence ≤ 0.4 |
| **SEVERE integrity event** | capped at **6.0** and reduced by the severe penalty (up to −3.0) |
| **Honest ceiling** | never exceeds the role contract's declared ceiling |
| **Ledger nudge** | the contribution ledger can only move the score by ±1.0, so event *volume* cannot inflate |

Support labels — `SUPPORTED`, `LOW_SAMPLE`, `PROXY_HEAVY`, `UNSUPPORTED` — are
attached from the evidence's aggregate grade and total sample size.

## 5. Five separate scores — never one number

RACR reports **five distinct scores** (`racr.five_scores`) that are never averaged
into one misleading figure:

| Score | Question | Can be high? |
|---|---|---|
| **A. Role-Adjusted Performance** | How exceptionally does it do its job? | yes, >9 possible |
| **B. Engineering Quality** | How well built/tested/reliable is it? | yes |
| **C. Decision Utility** | Does it materially improve decisions? | yes |
| **D. Empirical Validation** | Backed by leakage-safe real outcomes? | **firewalled low** |
| **E. Whole-MVP Maturity** | How mature is the full product? | capped by (D) |

This is why it is honest — not contradictory — to report, e.g., *Simulation
Intelligence RACR 9.3 / Engineering 9.0 / Decision Utility 8.7 / Empirical
Validation 2.0 / Whole-MVP 7.8*. The component is elite in its role while the full
product still lacks outcome evidence.

## 6. Context-difficulty adjustment

A 9/10 on an easy, complete-data run is not a 9/10 on an adversarial, stale,
contradictory run. `context_difficulty.score_context` scores the run's difficulty
from twelve factors (data completeness/freshness, contradiction, volatility,
regime instability, actor interaction, source concentration, model disagreement,
scenario complexity, engine availability, runtime degradation, tail severity).
Difficulty scales *positive* contribution credit up (handling a hard input is
worth more) but **never** rewards the system merely because the input was bad — the
contribution event must have actually fired.

## 7. What RACR is not

RACR does not measure, imply, or predict profit, returns, or alpha. It is an
engineering- and decision-usefulness instrument. See
`docs/role_rating_limitations.md`.
