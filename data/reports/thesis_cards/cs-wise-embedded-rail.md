# THESIS CARD — CASE STUDY: Wise — embedded rail / invisible infrastructure archetype

```
⚠️ CASE STUDY ONLY — NOT INVESTABLE
This card validates MVP architecture and scoring logic. It is not a buy candidate, not a recommendation, and not eligible for trading or portfolio selection.
```

**Entity:** Wise plc (WISE.L)

| governance field | value |
|---|---|
| DATA MODE (declared label) | `FIXTURE_DEMONSTRATION` |
| DERIVED DATA MODE (from verified evidence) | `FIXTURE` |
| AUTHENTICITY cap | `3.0` |
| LINEAGE | `n/a (root contract)` |
| CONTRACT PURPOSE | `CASE_STUDY` |
| BOARD SCOPE | `CASE_STUDY_BOARD` |
| INVESTMENT ELIGIBILITY | `NOT_ELIGIBLE` |
| TRADING STATUS | `DO_NOT_TRADE` |
| PROMOTION STATUS | `NOT_PROMOTABLE` |
| lifecycle status | `ACTIVE` |

DATA PURPOSE: CASE STUDY / MVP VALIDATION  
INVESTABILITY STATUS: NOT ELIGIBLE  
TRADING STATUS: DO NOT TRADE

> This contract validates MVP architecture only. It is not a buy candidate, not a recommendation, and cannot be used for trade selection unless separately promoted into a new INVESTABLE_CANDIDATE contract.

**Status:** ADVISORY_ONLY · real money: PROHIBITED

## VERDICT: CASE_STUDY_VALIDATION
Binding rule: `RP_PURPOSE_SCOPE_CASE_STUDY`

## FINAL SCORE: 1.422 / 10
Caps applied: EVIDENCE_QUALITY_CAP

## SCORE FAMILIES
- FRAMEWORK VALIDATION score: 10.0 / 10 (praise for the framework, never the trade)
- RESEARCH QUALITY score: 1.422 / 10
- INVESTABILITY SCORE: 0.0 / 10 (eligibility multiplier = 0.0)

## EVIDENCE QUALITY: 0.142 (cap = 1.42)
## CONTRADICTION: g_contra = 0.577 (for 2 / against 1 / neutral-ignored 0)
## EXPIRY: 90 days remaining (day 2464; as-of day 2374)

## NARRATIVE
Validates: embedded-infrastructure mapping, who-gets-paid graph, anecdote quarantine. Partner-routed volume compounds invisibly behind consumer front-ends (bunq pattern).

Trigger: MVP validation: infra_capture + beneficiary_map + anecdote quarantine  
Predicted direction: UP over 90d

## CAUSAL PATH
belief: cheap transfers -> neobanks embed rail -> partner volume -> take-rate revenue -> repricing

## WHO GETS PAID
- **house**: WISE.L (Platform)
- **losers**: incumbent FX desks, WU corridors
- **midstream**: neobanks (private)

## PREDICTION-MARKET LINK
- none (no liquid event market — gate is neutral, never a bonus)

## WOULD VALIDATE
- The framework modules exercised by this card behave per spec (validation target is the ARCHITECTURE, not the ticker).
## WOULD FALSIFY
- Framework check: embedded-rail archetype fails to render/score
- Forced null: *Consumer growth explains all volume; embedded routing is immaterial*

## SCORE BREAKDOWN
| component | value |
|---|---|
| demand D | 6.0 |
| moat M (top-2) | 7.5 |
| MERIT | 6.75 |
| g_txn | 0.9375 |
| g_contra | 0.5774 |
| g_stale | 0.9267 |
| g_pm | 1.0 |
| FINAL | 1.422 |
| eligibility multiplier | 0.0 |
| INVESTABILITY | 0.0 |

## PROVENANCE
- ANECDOTE: 1 item(s)
- MARKET: 2 item(s)

### Contradiction board
**FOR thesis:**
- [ANECDOTE] Operator field obs: bunq EUR->INR routed via Wise rail without Wise account (field observation, day 2350)
- [MARKET] Published corridor fees below bank wire pricing (pricing pages, day 2360)
**AGAINST (for null):**
- [MARKET] Provider cuts own take rate, offsetting volume (pricing history, day 2355)

### Anecdote quarantine
- Operator field obs: bunq EUR->INR routed via Wise rail without Wise account — weight 0.60 (corroborated)

## BINDING GATE
BindingGate = **EQS** (EQS = 0.142)

## NEXT EVIDENCE ACTIONS
- (none registered — add next_evidence_actions to the contract)

## NEXT ACTION
None for investment: case studies are not promotable in place. To pursue the idea, clone via promote_case_study_to_research() with new expiry, new falsification observable, and live/hard evidence.
