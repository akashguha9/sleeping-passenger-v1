# THESIS CARD — CASE STUDY: Adyen — enterprise payment orchestration archetype

```
⚠️ CASE STUDY ONLY — NOT INVESTABLE
This card validates MVP architecture and scoring logic. It is not a buy candidate, not a recommendation, and not eligible for trading or portfolio selection.
```

**Entity:** Adyen NV (ADYEN.AS)

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

## FINAL SCORE: 0.782 / 10
Caps applied: EVIDENCE_QUALITY_CAP

## SCORE FAMILIES
- FRAMEWORK VALIDATION score: 10.0 / 10 (praise for the framework, never the trade)
- RESEARCH QUALITY score: 0.782 / 10
- INVESTABILITY SCORE: 0.0 / 10 (eligibility multiplier = 0.0)

## EVIDENCE QUALITY: 0.078 (cap = 0.78)
## CONTRADICTION: g_contra = 0.680 (for 1 / against 1 / neutral-ignored 0)
## EXPIRY: 90 days remaining (day 2464; as-of day 2374)

## NARRATIVE
Validates: enterprise-orchestration archetype (single-platform full-stack vs bank/gateway patchwork) and merchant-migration causal path rendering.

Trigger: MVP validation: orchestration archetype + causal-path completeness  
Predicted direction: UP over 90d

## CAUSAL PATH
enterprise consolidation belief -> gateway patchwork pain -> single-platform migration -> net-revenue take-rate

## WHO GETS PAID
- **house**: ADYEN.AS
- **losers**: legacy gateways, bank acquiring patchworks
- **midstream**: enterprise merchants

## PREDICTION-MARKET LINK
- none (no liquid event market — gate is neutral, never a bonus)

## WOULD VALIDATE
- The framework modules exercised by this card behave per spec (validation target is the ARCHITECTURE, not the ticker).
## WOULD FALSIFY
- Framework check: orchestration archetype fails to render/score
- Forced null: *Orchestration is a commodity; take-rate competition erodes the premium*

## SCORE BREAKDOWN
| component | value |
|---|---|
| demand D | 4.0 |
| moat M (top-2) | 7.25 |
| MERIT | 5.625 |
| g_txn | 0.9375 |
| g_contra | 0.6798 |
| g_stale | 0.7391 |
| g_pm | 1.0 |
| FINAL | 0.782 |
| eligibility multiplier | 0.0 |
| INVESTABILITY | 0.0 |

## PROVENANCE
- ANALYST_PRIOR: 1 item(s)
- HARD_DATA: 1 item(s)

### Contradiction board
**FOR thesis:**
- [HARD_DATA] Net revenue / processed-volume take-rate disclosed (operator-classified) (annual report, day 2260)
**AGAINST (for null):**
- [ANALYST_PRIOR] Enterprise merchants multi-source processors to squeeze pricing; single-platform premium erodes (industry analysis, day 2320)

### Anecdote quarantine
- none

## BINDING GATE
BindingGate = **EQS** (EQS = 0.078)

## NEXT EVIDENCE ACTIONS
- (none registered — add next_evidence_actions to the contract)

## NEXT ACTION
None for investment: case studies are not promotable in place. To pursue the idea, clone via promote_case_study_to_research() with new expiry, new falsification observable, and live/hard evidence.
