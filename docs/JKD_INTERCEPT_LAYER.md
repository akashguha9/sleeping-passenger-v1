# JKD Intercept Layer

## Purpose

Operationalise Jeet Kune Do as a single advisory decision-discipline score
(`scripts/jkd_decision_discipline.py`), with the **intercepting fist** (early
belief-shift detection) and **directness** (thesis clarity) as first-class
component scores. A state without consequence is decorative complexity, so
every JKD band maps to a concrete advisory action constraint.

## Inputs

Nine 0–10 inputs: Interception (I), Directness (D), Adaptability (A), Economy
(E), Reality confirmation (R), Noise (N), Greed/ego/operator-heat (G), Chaos
risk (C). I and D have their own sub-formulas (0–1 inputs):

```
I = 10*(0.35*price_structure_shift + 0.25*narrative_acceleration
        + 0.20*volume_confirmation + 0.20*consensus_delay)
D = 10*(0.30*invalidation_clarity + 0.25*thesis_specificity
        + 0.20*source_specificity + 0.15*time_horizon_clarity
        + 0.10*risk_reward_clarity)
```

## Formula

```
JKD = 0.22*I + 0.16*D + 0.16*A + 0.14*E + 0.18*R - 0.10*N - 0.12*G - 0.18*C
```

Clamped to 0–10. The positive ceiling is 8.6 by construction — perfection is
deliberately unclaimable.

## Outputs

`jkd_score`, all component scores, `noise_penalty`,
`operator_greed_ego_penalty`, `chaos_risk_penalty`, `invalidation_capped`,
`dominant_weakness`, `advisory_state`, `action_constraint`,
`human_review_required`, `advisory_only`. Interception also returns
`false_positive_warning`.

## State consequence

| Condition | State | Constraint |
|---|---|---|
| jkd ≥ 8.0, chaos & heat low | AVENTADOR_CANDIDATE | HUMAN_REVIEW_REQUIRED |
| 6.5 ≤ jkd < 8.0 | MURCIELAGO_WATCH | WATCHLIST_ONLY |
| 5.0 ≤ jkd < 6.5 | MIURA_MONITOR | MONITOR_ONLY |
| jkd < 5.0 | WAIT_OR_AVOID | NO_NEW_RISK_RECOMMENDED |
| chaos high OR heat high | DIABLO_NO_NEW_RISK | RECONCILE_OR_WAIT |

Plus: a thesis that cannot be invalidated (low directness) caps the JKD score
at 6.0 and can never reach AVENTADOR — "a signal that cannot be invalidated is
useless."

## Tests

`tests/test_jkd_decision_discipline.py` — score from weights, interception
raises, noise lowers, chaos/heat force DIABLO, band→constraint mapping,
uninvalidatable cap, interception false-positive warning, directness dominated
by invalidation.

## Failure modes

* High narrative acceleration with no volume → `false_positive_warning` (head
  fake), and interception does not over-credit it.
* Non-numeric inputs clamp to the safe floor (0) rather than raising.

## Advisory-only safety note

Pure functions; no DB, network, or broker calls. Strongest verdict is
HUMAN_REVIEW_REQUIRED.

## How to verify locally

```powershell
python scripts\jkd_decision_discipline.py --demo
python scripts\jkd_decision_discipline.py --interception 8 --directness 7 --chaos 9 --json
python -m pytest tests\test_jkd_decision_discipline.py -q
```
