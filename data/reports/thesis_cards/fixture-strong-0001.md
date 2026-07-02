# THESIS CARD — Embedded rail volume compounding

```
⚠️ CASE STUDY ONLY — NOT INVESTABLE
This card validates MVP architecture and scoring logic. It is not a buy candidate, not a recommendation, and not eligible for trading or portfolio selection.
```

**Entity:** FixtureRail Plc (FIXR)

| governance field | value |
|---|---|
| DATA MODE | `FIXTURE_DEMONSTRATION` |
| CONTRACT PURPOSE | `FIXTURE_TEST` |
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

## VERDICT: FRAMEWORK_TEST_PASS
Binding rule: `RP_PURPOSE_SCOPE_FIXTURE_TEST`

## FINAL SCORE: 5.196 / 10
Caps applied: none

## SCORE FAMILIES
- FRAMEWORK VALIDATION score: 10.0 / 10 (praise for the framework, never the trade)
- RESEARCH QUALITY score: 5.196 / 10
- INVESTABILITY SCORE: 0.0 / 10 (eligibility multiplier = 0.0)

## EVIDENCE QUALITY: 0.574 (cap = 5.74)
## CONTRADICTION: g_contra = 0.900 (for 5 / against 0 / neutral-ignored 0)
## EXPIRY: 90 days remaining (day 2464; as-of day 2374)

## NARRATIVE
Partner-routed volume grows without CAC while market prices the consumer brand only.

Trigger: ΔP shock on payments-adoption event market  
Predicted direction: UP over 120d

## CAUSAL PATH
belief: cheap transfers -> neobanks embed rail -> partner volume -> take-rate revenue -> repricing

## WHO GETS PAID
- **house**: FIXR
- **losers**: INCB
- **midstream**: NEOB

## PREDICTION-MARKET LINK
- market: `FIX-PAY-ADOPT` · edge: 0.42 · alignment: 8.0 · category validated: True

## WOULD VALIDATE
- The framework modules exercised by this card behave per spec (validation target is the ARCHITECTURE, not the ticker).
## WOULD FALSIFY
- Two consecutive reports without partner-volume growth, or a top-3 partner insourcing the rail
- Forced null: *Consumer growth explains all volume; partner-routed volume is flat*

## SCORE BREAKDOWN
| component | value |
|---|---|
| demand D | 6.0 |
| moat M (top-2) | 7.75 |
| MERIT | 6.875 |
| g_txn | 0.9375 |
| g_contra | 0.9004 |
| g_stale | 0.9525 |
| g_pm | 0.94 |
| FINAL | 5.196 |
| eligibility multiplier | 0.0 |
| INVESTABILITY | 0.0 |

## PROVENANCE
- ANECDOTE: 1 item(s)
- HARD_DATA: 2 item(s)
- MARKET: 2 item(s)

### Contradiction board
**FOR thesis:**
- [HARD_DATA] 10-K discloses take-rate revenue share 62% (EDGAR 10-K, day 2354)
- [MARKET] Event market ΔP +0.14 persisted 5 days (prediction market, day 2371)
- [MARKET] Partner-corridor fee page cut 30bps (pricing page diff, day 2364)
- [HARD_DATA] Counterparty 10-K names provider as vendor (EDGAR FTS, day 2334)
- [ANECDOTE] Operator field obs: transfer routed via rail (field observation, day 2359)
**AGAINST (for null):**
- (empty — the null has not been tested)

### Anecdote quarantine
- Operator field obs: transfer routed via rail — weight 0.60 (corroborated)

## NEXT ACTION
None for investment: case studies are not promotable in place. To pursue the idea, clone via promote_case_study_to_research() with new expiry, new falsification observable, and live/hard evidence.
