# Role-Fit Scoring Model

> Internal scoring doc. Not customer-facing. The football analogy here
> is a deliberate mental model, not product copy: nothing in this file
> should leak into a UI label, a marketing surface, or a public README.

The previous scorecard tried to grade every segment as if each one had
to "score goals" — public-SaaS reach, predictive validity, multi-tenant
auth, billing — and was therefore unfair to segments whose actual job
is *not* to score goals. A defensive midfielder who breaks up play and
recycles possession can rate 10/10 without scoring or assisting. We
apply the same framing here.

This document defines the two scorecards we use side by side, the
formulas behind them, and the conventions for ceilings, NOT_TARGETED
segments, and calibration honesty.

---

## 1. Why two scorecards

Two distinct questions deserve two distinct answers.

| Lens | Question it answers | Allowed to be low when … |
|---|---|---|
| **Absolute readiness** `A_s` | How close is the segment to production / private beta / public SaaS / true predictive validity? | … the role is not yet shipped; this is brutally honest. |
| **Role-fit readiness** `R_s` | Given this segment's role in *this* local-first MVP, is it performing that role at an elite level? | … the role itself is not yet performed elite-well; not when the segment plays a different role from "ship public SaaS". |

We refuse to let one score answer both questions, because that is what
produced the "inflate-or-deflate" pressure the previous sprint hit.

- A **safety / refusal** segment performs its role perfectly when it
  refuses, denies, and stamps. That is a 10/10 role-fit, even though
  it never produces a signal.
- A **calibration gate** segment performs its role perfectly when it
  blocks false predictive claims. It is allowed 10/10 role-fit even
  while `N_real = 0`, because *blocking* is the role.
- A **scoring/model logic** segment cannot reach a high absolute score
  without `N_real ≥ 200`, regardless of how clean its code is. Role-fit
  is bounded by the same evidence — if there is no labelled outcome
  evidence, the predictive role is not yet being performed.
- A **public-SaaS** segment scores low on absolute readiness *and* is
  marked `NOT_TARGETED_THIS_YEAR` for role-fit. We do not grade an MVP
  that has chosen local-first as if it were trying to be a striker.

---

## 2. Formulas

For each segment `s`:

```
A_s ∈ [0, 10]     absolute readiness, brutally honest
R_s ∈ [0, 10]     role-fit readiness, evaluated against role-specific criteria
E_s ∈ [0, 1]      evidence completeness (paths-on-disk per criterion)
C_s ∈ [0, 1]      confidence in the score
T_s ∈ [0, 1]      target relevance — 0 means NOT_TARGETED this year
W_abs_s, W_role_s composite weights (default 1 for the MVP)
```

Role-fit score:

```
R_s = 10 * Σ_i (w_i * p_i)        with    Σ_i w_i = 1
```

Evidence completeness:

```
E_s = min(1, evidence_items_present / evidence_items_required)
```

Confidence-adjusted role-fit:

```
R_adj_s = R_s * (0.7 + 0.3 * E_s) * C_s
```

- The `(0.7 + 0.3 * E_s)` factor lets us start a segment at 70 % of its
  nominal role-fit when no evidence has been verified, then graduate
  toward 100 % as evidence paths are present on disk.
- `C_s` discounts the score by our confidence in the underlying signal
  — high for safety/contract segments where 3000+ tests pin the
  invariant, lower for forward-looking segments where judgment is
  doing more of the work.

Dashboard score (the value shown in the role-fit column):

```
D_s = "NOT_TARGETED_THIS_YEAR"     if T_s == 0
    = R_adj_s                       otherwise
```

Composite scores:

```
OverallAbsolute = Σ_s W_abs_s * A_s / Σ_s W_abs_s

OverallRoleFit  = Σ_s W_role_s * R_adj_s * T_s
                  ─────────────────────────────
                  Σ_s W_role_s * T_s
                  (NOT_TARGETED segments excluded from both sums)
```

Deltas:

```
ΔA_s = A_after_s - A_before_s
ΔR_s = R_after_s - R_before_s
```

---

## 3. NOT_TARGETED handling

We mark a segment NOT_TARGETED when the product strategy says we are
*not* trying to play that role this year. Today that includes:

- **Public SaaS readiness** — `T_s = 0`.
- **Commercial SaaS readiness** — `T_s = 0`.

Both keep an *absolute* score (1.5/10) because absolute readiness is
about the world's grading, not ours. But role-fit-wise they are
excluded from the denominator of `OverallRoleFit`, so they cannot drag
the local-first showcase score down. The dashboard renders them as
the literal string `"NOT_TARGETED_THIS_YEAR"` so no reader can mistake
it for a numeric score.

For partially-targeted segments (private beta, performance/scalability,
deployment readiness, real-user readiness) we use `T_s` in (0, 1) so
they contribute proportionally to `OverallRoleFit` without being
treated as full-weight goals.

---

## 4. Calibration honesty ≠ predictive scoring quality

The single most important separation in this model:

- **Calibration gate honesty** (segment 12). Its role is to *refuse*
  predictive claims until thresholds pass. It earns 10/10 role-fit when:
  - `N_real` is reported,
  - `predictive_claim_allowed = false` while `N_real < N_min`,
  - Brier / ECE / MCE formulas are unit-tested,
  - the docs / report warn explicitly,
  - fixture/mock data is excluded from `N_real`.

  This segment *can* be 10/10 today.

- **Scoring/model logic quality** (segment 11). Its role is to *be a
  predictive engine*. Until we have `N_real ≥ 200` with usable
  `model_probability` snapshots, it cannot earn that role's score.
  The script enforces this by reading the live
  `runtime/release/calibration_report.json` and:
  - if `predictive_claim_allowed = true` AND `n_real ≥ N_min`,
    `calibration_unlocked = True`;
  - otherwise the segment's `A_s` is capped at
    `SCORING_MODEL_CEILING_NO_EVIDENCE = 5.8`, and the predictive
    criteria are scored `p_i = 0`.

A 10/10 calibration *gate* sitting next to a capped predictive *model*
is not a contradiction — it is the whole point of the gate.

---

## 5. Why local-first should not be punished for not being public SaaS

If we evaluate every segment on `OverallAbsolute` alone, "Public SaaS
readiness = 1.5" pulls the average down toward a number that does not
describe anything we are trying to build. `OverallRoleFit` answers a
different question: *"is this MVP performing the roles it has chosen
to perform?"* — and Public SaaS, by being NOT_TARGETED, simply does
not appear in the denominator.

So a healthy state looks like this:

| Lens | Reasonable target | Why |
|---|---:|---|
| `OverallAbsolute` | 7.5 – 8.3 | Bounded by per-segment ceilings (auth, hosted DB, predictive validity). |
| `OverallRoleFit` | 8.5 – 9.3 | Local-first showcase, safety, mock truth, source health, calibration honesty all elite at their role. |

The two numbers should not converge. If `OverallRoleFit` ever falls to
`OverallAbsolute` we have probably let role-fit re-absorb absolute
readiness; if `OverallRoleFit` ever races to 10, we have probably
inflated.

---

## 6. Where the model lives in code

- Engine: `scripts/segment_role_scorecard.py`
- Tests: `tests/test_segment_role_scorecard.py`
- Generated JSON: `runtime/release/segment_role_scorecard.json`
- Generated Markdown: `docs/scorecards/SEGMENT_ROLE_SCORECARD.md`
- Role map (this doc + the human map): `docs/scorecards/SEGMENT_ROLE_MAP.md`

The script is read-only, advisory-only, and never touches secrets.
Stamps come from `scripts.advisory_contract`, the single source of
truth.

---

## 7. The Kanté line, kept here on purpose

> A 10/10 defensive midfielder does not score. A 10/10 calibration
> gate does not predict. They are 10/10 because they prevent the exact
> failure their role exists to prevent.

That is the bar. If a segment cannot earn 10/10 by preventing the
failure mode it owns, it should not be in this scorecard.
