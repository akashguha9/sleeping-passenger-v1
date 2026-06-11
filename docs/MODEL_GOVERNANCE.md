# Model governance

Owner and sole change authority: **Akash Guha**. Companion documents:
[MODEL_CARD.md](../MODEL_CARD.md), [MODEL_PIPELINE_MAP.md](MODEL_PIPELINE_MAP.md),
[`model_registry.json`](../model_registry.json).

## Versioning

- Every model/signal lives in `model_registry.json` with a `version`;
  changing a formula, weight, or threshold bumps the version in the same
  commit (the registry test fails on missing fields, the config contract
  fails on undeclared env knobs).
- Repo-level provenance: `scripts/build_release_manifest.py` hashes the
  safety modules and lockfiles per release.

## Review cadence

- **Weekly:** review new decision memos vs outcomes due for review
  (`Post-decision review date` in each memo).
- **Monthly:** run `scripts/review_signal_outcomes.py` aggregate over
  resolved signals; regenerate the calibration report; check
  MAE/bias/stale-evidence-rate trends.
- **Quarterly:** regenerate the model scorecard; re-run sensitivity
  analysis on the live weight set; review the registry's `known_limits`
  for staleness; review the dependency advisory register (already
  CI-expiring).

## Scorecard threshold

A model change ships only if the regenerated scorecard total does not
drop, and no segment falls below 5/10 without a written gap + next-fix
entry. Scores are evidence-capped in code (no tests ≤8, no OOS ≤9, no
independent validation <10) — the caps cannot be argued with.

## Release checklist (model changes)

1. Full backend + frontend suites green; all policy gates PASS.
2. Registry entry updated (version, limits, tests).
3. Scorecard regenerated; total recorded in the commit message.
4. If a weight/threshold changed: sensitivity analysis re-run; if the
   change flips any historical decision, note it in the commit.
5. Backtest re-run on synthetic + available history; headline must be
   labeled with its basis (out-of-sample vs IN_SAMPLE_ONLY).
6. Advisory-only invariants re-verified (release gate + compliance
   preflight do this automatically).

## Deprecation rules

A model is deprecated by setting `"version": "<x>-deprecated"` and
moving its weight to zero — never by silent deletion; its outcome
history stays in the journal. Deprecated models keep their tests until
the code is removed in a separate, named commit.

## Minimum evidence before trusting a new signal

A new signal type earns scoring weight only after, in order:

1. registry entry + tests (synthetic, known answers);
2. ≥ 30 temporally-valid samples through the walk-forward backtester
   with the test split non-empty;
3. a calibration report where its confidence is not refuted
   (ECE path, small-sample warnings respected);
4. sensitivity analysis not recommending ABSTAIN on typical inputs;
5. explicit owner sign-off recorded in a decision memo.

Until all five: it is a note in the journal, not a feature in the score
— the same rule the grounding guard applies to LLM claims.

## Change approval

All changes are approved by the owner via commit on a reviewed branch.
No collaborator, no LLM, and no automated process can approve a model
change; CI can only refuse one.
