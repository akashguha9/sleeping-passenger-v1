# Shadow-Policy Evaluation

`shadow_policies.py` records how alternative advisory policies would have classified
each candidate — advisory-only, historically immutable, never executed.

## Policies
`council, risk_first, wait_for_confirmation, highest_confidence_only, no_action
(baseline), racr_weighted`. Each maps a council result deterministically to one
advisory state with a rationale.

## No hindsight
Each `ShadowPolicyDecision` is a frozen dataclass with a content hash over
(policy, twin, cutoff, candidate, state). `verify_decision` detects any rewrite
(tested: `test_shadow_policies_immutable_and_no_action_baseline`). A policy can
never rewrite its own history.

## Comparison without trading
Once outcomes resolve, `compare_on_outcome` scores each policy per case
(correct / false-risk-block / missed-risk-block / tail-caught). Aggregating across
many resolved cases yields calibration / false-escalation / tail-recall per policy —
empirical policy comparison **without placing a single trade**. Promotion is never
automatic (see champion–challenger).
