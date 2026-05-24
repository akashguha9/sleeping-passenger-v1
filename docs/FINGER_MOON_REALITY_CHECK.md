# Finger / Moon Reality Check

## Purpose

"It is like a finger pointing away to the moon. Don't concentrate on the
finger or you will miss all that heavenly glory." AI output, news, narrative,
and Polymarket odds are **pointers**; price, volume, filings, and realised
outcomes are the **moon**. `scripts/finger_moon_reality_check.py` measures how
much of a read is reality-anchored versus pointer-worship.

## Inputs

0–1 confirmations: price, volume, source credibility, liquidity, filing/
official, outcome/Moltbook. Plus pointer strengths: `ai_consensus`,
`polymarket_odds`, `narrative_strength`.

## Formula

```
RC = 0.22*PriceConfirmation + 0.18*VolumeConfirmation + 0.18*SourceCredibility
   + 0.16*LiquidityConfirmation + 0.14*FilingOrOfficialConfirmation
   + 0.12*OutcomeOrMoltbookConfirmation
```

Returned on a 0–10 scale to feed JKD's R term.

## Outputs

`reality_confirmation_score`, `components`, `pointers`,
`pointer_dominance_warning`, `missing_reality_anchor`,
`source_truth_hierarchy`, `human_review_required`, `advisory_only`.

## State consequence

`pointer_dominance_warning = true` when at least one loud pointer (≥ 0.60)
coincides with weak real anchoring (RC fraction < 0.40). Downstream this drags
JKD's reality term down and tightens the advisory constraint. Enforced rules:
`AIConsensus != RealityConfirmation`, `PolymarketOdds != Truth`,
`NarrativeStrength != FundamentalTruth`.

## Tests

`tests/test_finger_moon_reality_check.py` — pointers alone cannot be truth
(warning fires, low score), real anchors raise RC, hierarchy orders filings
above AI, advisory stamps.

## Failure modes

* All inputs zero → RC 0, all anchors reported missing (honest "no reality
  signal").
* Loud narrative with zero price/volume/filings → pointer-dominance warning
  (the classic narrative trap).

## Advisory-only safety note

Pure functions; no DB, network, or broker calls.

## How to verify locally

```powershell
python scripts\finger_moon_reality_check.py --ai-consensus 1 --narrative-strength 1
python scripts\finger_moon_reality_check.py --price 0.9 --volume 0.9 --filing 0.9 --json
python -m pytest tests\test_finger_moon_reality_check.py -q
```
