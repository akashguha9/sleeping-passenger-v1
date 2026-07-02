# THESIS CARD — CASE STUDY: Visa — payment network / stablecoin coexistence archetype

```
⚠️ CASE STUDY ONLY — NOT INVESTABLE
This card validates MVP architecture and scoring logic. It is not a buy candidate, not a recommendation, and not eligible for trading or portfolio selection.
```

**Entity:** Visa Inc (V)

| governance field | value |
|---|---|
| DATA MODE | `FIXTURE_DEMONSTRATION` |
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

## FINAL SCORE: 0.795 / 10
Caps applied: EVIDENCE_QUALITY_CAP

## SCORE FAMILIES
- FRAMEWORK VALIDATION score: 10.0 / 10 (praise for the framework, never the trade)
- RESEARCH QUALITY score: 0.795 / 10
- INVESTABILITY SCORE: 0.0 / 10 (eligibility multiplier = 0.0)

## EVIDENCE QUALITY: 0.080 (cap = 0.80)
## CONTRADICTION: g_contra = 0.667 (for 1 / against 1 / neutral-ignored 0)
## EXPIRY: 90 days remaining (day 2464; as-of day 2374)

## NARRATIVE
Validates: payment-rail logic and the substitution-vs-coexistence forced null (stablecoin rails as threat or as routed volume).

Trigger: MVP validation: payment-rail logic + contradiction board  
Predicted direction: UP over 90d

## CAUSAL PATH
stablecoin adoption belief -> rail substitution question -> network take-rate -> volume mix shift

## WHO GETS PAID
- **house**: V
- **losers**: cash networks
- **midstream**: issuers, acquirers

## PREDICTION-MARKET LINK
- none (no liquid event market — gate is neutral, never a bonus)

## WOULD VALIDATE
- The framework modules exercised by this card behave per spec (validation target is the ARCHITECTURE, not the ticker).
## WOULD FALSIFY
- Framework check: rail-coexistence null fails to construct
- Forced null: *Stablecoins substitute rather than route through the network; take-rate compresses*

## SCORE BREAKDOWN
| component | value |
|---|---|
| demand D | 2.5 |
| moat M (top-2) | 7.5 |
| MERIT | 5.0 |
| g_txn | 1.0 |
| g_contra | 0.6668 |
| g_stale | 0.7589 |
| g_pm | 1.0 |
| FINAL | 0.795 |
| eligibility multiplier | 0.0 |
| INVESTABILITY | 0.0 |

## PROVENANCE
- ANALYST_PRIOR: 1 item(s)
- HARD_DATA: 1 item(s)

### Contradiction board
**FOR thesis:**
- [HARD_DATA] Network take-rate disclosed in filings (operator-classified) (EDGAR 10-K, day 2250)
**AGAINST (for null):**
- [ANALYST_PRIOR] Stablecoin rails bypass the network entirely for cross-border settlement (industry analysis, day 2330)

### Anecdote quarantine
- none

## NEXT ACTION
None for investment: case studies are not promotable in place. To pursue the idea, clone via promote_case_study_to_research() with new expiry, new falsification observable, and live/hard evidence.
