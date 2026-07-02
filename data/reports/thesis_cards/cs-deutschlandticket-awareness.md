# THESIS CARD — CASE STUDY: Deutschlandticket — awareness arbitrage / transaction certainty / state integrity

```
⚠️ CASE STUDY ONLY — NOT INVESTABLE
This card validates MVP architecture and scoring logic. It is not a buy candidate, not a recommendation, and not eligible for trading or portfolio selection.
```

**Entity:** Deutschlandticket ecosystem (NONE)

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

## FINAL SCORE: 0.097 / 10
Caps applied: EVIDENCE_QUALITY_CAP

## SCORE FAMILIES
- FRAMEWORK VALIDATION score: 9.333 / 10 (praise for the framework, never the trade)
- RESEARCH QUALITY score: 0.097 / 10
- INVESTABILITY SCORE: 0.0 / 10 (eligibility multiplier = 0.0)

## EVIDENCE QUALITY: 0.010 (cap = 0.10)
## CONTRADICTION: g_contra = 0.551 (for 2 / against 0 / neutral-ignored 0)
## EXPIRY: 90 days remaining (day 2464; as-of day 2374)

## NARRATIVE
Validates: awareness-gap scoring, transaction-certainty gate, state-integrity risk flag, and the non-tradable-insight path (mechanism with no listed pure-play).

Trigger: MVP validation: awareness_gap + g_txn + state_integrity flag  
Predicted direction: UP over 90d

## CAUSAL PATH
street observation -> awareness gap hypothesis -> needs listed-proxy mapping -> no tradable node

## WHO GETS PAID
- **candidate_winners**: ticketing aggregators (unmapped)
- **observed_losers**: confused consumers

## PREDICTION-MARKET LINK
- none (no liquid event market — gate is neutral, never a bonus)

## WOULD VALIDATE
- The framework modules exercised by this card behave per spec (validation target is the ARCHITECTURE, not the ticker).
## WOULD FALSIFY
- Framework check: non-tradable mechanism gets a ticker anyway
- Forced null: *The confusion was idiosyncratic; no systematic demand leakage*

## SCORE BREAKDOWN
| component | value |
|---|---|
| demand D | 5.5 |
| moat M (top-2) | 0.0 |
| MERIT | 2.75 |
| g_txn | 0.375 |
| g_contra | 0.5513 |
| g_stale | 0.6176 |
| g_pm | 1.0 |
| FINAL | 0.097 |
| eligibility multiplier | 0.0 |
| INVESTABILITY | 0.0 |

## PROVENANCE
- ANECDOTE: 2 item(s)

### Contradiction board
**FOR thesis:**
- [ANECDOTE] Tourist bought pricier 7-day ticket with less coverage (travel observation, day 2280)
- [ANECDOTE] App cancellation not registered by billing; collection letter issued (operator experience, day 2300)
**AGAINST (for null):**
- (empty — the null has not been tested)

### Anecdote quarantine
- Tourist bought pricier 7-day ticket with less coverage — weight 0.15 (quarantined)
- App cancellation not registered by billing; collection letter issued — weight 0.15 (quarantined)

## NEXT ACTION
None for investment: case studies are not promotable in place. To pursue the idea, clone via promote_case_study_to_research() with new expiry, new falsification observable, and live/hard evidence.
