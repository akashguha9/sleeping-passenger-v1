# Operator Emotional Content Gate

## Purpose

Bruce Lee's instruction was *emotional content* — focus and intent — not
*anger*. Translated to operating discipline: operator emotion is a measurable
risk variable that distorts sizing and timing. When it runs hot, the only safe
advisory output is **no new risk**. `scripts/operator_emotional_content_gate.py`
implements this as a decision-discipline variable **only** — not therapy, not a
diagnosis, no medical language.

## Inputs

0–1 levels: FOMO, Revenge, Overconfidence, Urgency, IdentityAttachment, plus an
optional `base_size`.

## Formula

```
OperatorHeat = 0.30*FOMO + 0.25*Revenge + 0.20*Overconfidence
             + 0.15*Urgency + 0.10*IdentityAttachment
EffectivePositionSize = BaseSize * (1 - OperatorHeat)
```

## Outputs

`operator_heat`, `heat_bucket` (COOL/WARM/ELEVATED/HOT), `dominant_emotion`,
`components`, `effective_position_size`, `size_adjustment`,
`diablo_no_new_risk`, `recommended_operator_action`, `human_review_required`,
`advisory_only`.

## State consequence

`OperatorHeat > 0.70` → `diablo_no_new_risk = true`. Effective size shrinks
linearly with heat. The recommended action is always a **non-trading** action:
reconcile open trades, review Moltbook, wait for a fresh signal, reduce size,
no new risk.

## Tests

`tests/test_operator_emotional_content_gate.py` — emotions raise heat, heat
reduces size, high heat triggers DIABLO, dominant emotion reported, actions are
non-trading, no medical language in the recommended action, advisory stamps.

## Failure modes

* All emotions maxed → heat 1.0, effective size 0 (full no-new-risk).
* Non-numeric inputs clamp to 0 (no crash, no spurious heat).

## Advisory-only safety note

Pure functions; no DB, network, or broker calls. This constrains sizing/new-
risk advice only; it makes no claim about the person and performs no broker
action. The disclaimer explicitly disclaims medical framing.

## How to verify locally

```powershell
python scripts\operator_emotional_content_gate.py --fomo 0.9 --revenge 0.8 --urgency 0.7
python -m pytest tests\test_operator_emotional_content_gate.py -q
```
