# Strategic Actor Map & Game Theory

## Purpose

Markets are strategic games. Costly, verifiable signals from incentive-aligned
actors outrank cheap talk; agency risk and adverse selection downgrade a
thesis; reflexivity loops amplify or unwind it. Lives in
`compute_strategic_actor_summary`, `compute_firm_incentive_summary`, and
`compute_reflexivity` in `scripts/bruce_lee_signal_discipline_report.py`;
related production logic is in `game_state_control_engine.py`.

## Inputs

0–1 factors.
* Signal credibility: costliness, verifiability, incentive_alignment,
  historical_accuracy.
* Firm quality: pricing_power, margins, demand_resilience, cost_structure,
  balance_sheet, competitive_position, management_incentives.
* Agency risk: compensation_misalignment, dilution_risk, debt_abuse,
  empire_building, insider_selling, governance_weakness.
* Adverse selection: insider_selling, opaque_accounting, weak_guidance,
  short_interest, liquidity_weakness, jurisdiction_opacity.
* Reflexivity: momentum, narrative_velocity, flow_confirmation (positive loop);
  drawdown, leverage, liquidity_stress, narrative_decay (negative loop).

## Formula

```
SignalCredibility = 0.35*Costliness + 0.25*Verifiability
                  + 0.20*IncentiveAlignment + 0.20*HistoricalAccuracy
FirmQuality       = weighted sum of the 7 firm factors
AgencyRisk        = weighted sum of the 6 agency factors
AdverseSelection  = weighted sum of the 6 adverse-selection factors
ReflexivityScore  = PositiveLoop - NegativeLoop
  PositiveLoop = Momentum * NarrativeVelocity * FlowConfirmation
  NegativeLoop = Drawdown * Leverage * LiquidityStress * (1 + NarrativeDecay)
```

## Outputs

`signal_credibility` + `cheap_talk`; `firm_quality`, `agency_risk`,
`adverse_selection_risk`, `downgrade_flag`; `reflexivity_score`,
`positive_loop`, `negative_loop`, `chaos_contribution`.

## State consequence

* `cheap_talk = true` when credibility < 0.35 — a cheap signal does not earn
  conviction.
* `downgrade_flag = true` when agency or adverse-selection risk ≥ 0.5.
* `chaos_contribution` (0–10) from the negative reflexivity loop is folded into
  JKD's chaos term — negative reflexivity raises chaos risk, which can force
  DIABLO_NO_NEW_RISK.

## Tests

`tests/test_bruce_lee_signal_discipline_report.py` — costly signals outrank
cheap talk; agency/adverse-selection downgrade; negative reflexivity raises
chaos contribution and lowers reflexivity score.

## Failure modes

* All-zero firm factors → quality 0 (no false confidence).
* Strong positive loop with no negative loop → high reflexivity, zero chaos
  contribution (clean trend, not chaos).

## Advisory-only safety note

Pure functions; no DB, network, or broker calls.

## How to verify locally

```powershell
python -m pytest tests\test_bruce_lee_signal_discipline_report.py -q -k "costly or agency or reflexivity"
```
