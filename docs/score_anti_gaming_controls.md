# Score Anti-Gaming Controls

RACR is designed so a higher rating must be **earned**, never manufactured. Below
is every anti-gaming control and the adversarial check that proves it holds. All
checks pass (11/11 in the RACR adversarial audit).

## The gaming attempts that are blocked

| Attempted gaming | Control | Where | Adversarial result |
|---|---|---|---|
| Produce more warnings / trigger more risk blocks / spam events | **Diminishing returns** on repeated event types **+ ±1.0 ledger nudge cap** in RACR | `contribution_ledger.score_events`, `racr.score_component` | 50× event volume → 6.3× points; RACR delta 0.27 |
| Add unreached / documentation-only code | **Runtime-reach cap 4.0** | `racr._NOT_RUNTIME_REACHED_CAP` | orphaned RACR = 4.0 |
| Claim a high score with no evidence | **UNSUPPORTED cap 5.0**, confidence ≤ 0.4 | `racr._UNSUPPORTED_CAP`, `_support_label` | unsupported RACR = 3.0 |
| Hide an integrity failure | **SEVERE-event cap 6.0** + penalty subtraction | `racr` severe path, `contribution_ledger` SEVERE types | clean 8.9 → severe 3.2 |
| Use one elite subsystem to inflate the product | **Five separate scores**; empirical firewall; whole-MVP capped by sample size | `racr.five_scores`, `whole_mvp_maturity` | empirical stays 1.0; whole-MVP 6.8 despite RACR 8.9 |
| Pick an easier role after seeing results | **Immutable, pre-declared role weights** (fresh copies) | `role_contracts._ROLE_WEIGHTS` | weight mutation has no effect |
| Reclassify simulated evidence as empirical | **No auto-promotion**; applied grade stays SIMULATED_ONLY | `calibration_harness.build_cohort` | applied = SIMULATED_ONLY even with 60 samples + human_approved |
| Sneak look-ahead outcomes into calibration | **LOOKAHEAD / FUTURE_UNRESOLVED / SAME_DAY guards** | `calibration_harness.resolve_prediction` | pre-cutoff bars → not resolved |
| Overfit to a small sample | **LOW_SAMPLE label**; status never CALIBRATED < 50 | `racr._support_label`, `calibration_harness` | zero-sample → LOW_SAMPLE |
| Avoid difficult cases | **Context-difficulty** scales credit; hard runs worth more (but only if handled) | `context_difficulty.score_context` | difficulty measured per run |
| Hide failures as graceful degradation | Fault injection asserts *survived AND safe*; silent failure is a SEVERE event | `reliability.run_fault_injection` | all faults survived safely |

## Score-quality labels (always attached)

- `UNSUPPORTED` — no evidence behind the score.
- `PROXY_HEAVY` — mostly proxy evidence, little measured.
- `LOW_SAMPLE` — sample too small to trust.
- `SUPPORTED` — evidence-linked, adequate sample.

## Independent recomputation

Scores are evidence-linked: every `DimensionScore` cites its source and every
`ContributionEvent` cites the run fact it was derived from, so a rating can be
recomputed and audited from the persisted events (`sil_contribution_events`) and
the stored run — not taken on trust.

## What is NOT rewarded

Increased code volume, more files, more tests with weak assertions, more model
complexity, repeated evidence, more warnings/blocks, or reclassifying simulated
evidence. None of these raise a score; several actively lower it.
