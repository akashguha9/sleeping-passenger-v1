# Bruce Lee Decision Quality Index (BLDQI)

## Purpose

The single synthesis score that fuses the JKD virtues, the survival calculus,
and the operator/distortion penalties into one advisory decision-quality number
with a state that has consequence. Lives in
`scripts/bruce_lee_decision_quality_index.py`.

## Inputs

Eleven 0–10 components: Interception, Directness, Adaptability, Economy,
RealityConfirmation, SignalEfficiency, BrokenRhythm, AntiDogma, SurvivalUtility
(virtues) and OperatorHeat, DiabloRisk (penalties). Four have sub-formulas:

```
SignalEfficiency = saturating( (EV*Confidence*SurvivalQuality)
                   / (Assumptions + DataFragility + OpComplexity + eps) )
BrokenRhythm = 10*(0.30*Dislocation + 0.25*DelayedConsensus + 0.20*Asymmetric
               + 0.15*VolCompression + 0.10*NarrativeMismatch)
AntiDogma = 10*(0.40*Adaptability + 0.30*InvalidationClarity
            + 0.30*(1 - SingleSourceDependence))
SurvivalUtility = 10*(0.20*ReturnPotential + 0.30*SurvivalQuality
                  + 0.25*FeedbackValue + 0.15*InvalidationClarity
                  + 0.10*Liquidity - 0.20*ChaosRisk)
```

## Formula

```
BLDQI = 0.12*Interception + 0.10*Directness + 0.10*Adaptability + 0.10*Economy
      + 0.12*RealityConfirmation + 0.10*SignalEfficiency + 0.08*BrokenRhythm
      + 0.08*AntiDogma + 0.10*SurvivalUtility - 0.10*OperatorHeat - 0.10*DiabloRisk
```

Clamped to 0–10.

## Outputs

`bldqi_score`, `component_scores`, `operator_heat_penalty`,
`diablo_risk_penalty`, `dominant_weakness`, `state_recommendation`,
`action_constraint`, `moltbook_feedback_required`, `human_review_required`,
`advisory_only`.

## State consequence

Mirrors JKD bands (AVENTADOR/MURCIELAGO/MIURA/WAIT). High operator heat (≥ 7)
or high diablo risk (≥ 7) overrides into `DIABLO_NO_NEW_RISK` /
`RECONCILE_OR_WAIT`. AVENTADOR and DIABLO states set
`moltbook_feedback_required = true` — a high-stakes decision must produce a
logged lesson, closing the learning loop.

## Tests

`tests/test_bruce_lee_decision_quality_index.py` — survival/reality raise the
score, heat/diablo cap into DIABLO, signal efficiency rewards low assumptions,
survival utility weights survival over return, anti-dogma penalises
single-source dependence.

## Failure modes

* Every virtue maxed but heat high → DIABLO regardless of raw score (the
  override is intentional and uncapped by virtue).
* Assumption-stacked thesis → low signal efficiency drags BLDQI down even with
  high EV.

## Advisory-only safety note

Pure functions; no DB, network, or broker calls. Strongest verdict is
HUMAN_REVIEW_REQUIRED.

## How to verify locally

```powershell
python scripts\bruce_lee_decision_quality_index.py --json
python -m pytest tests\test_bruce_lee_decision_quality_index.py -q
```
