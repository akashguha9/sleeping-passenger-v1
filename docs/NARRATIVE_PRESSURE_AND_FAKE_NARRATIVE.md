# Narrative Pressure & Fake Narrative

## Purpose

Distinguish a real, fundamentally-transmitted narrative from a fragile or fake
one (loud emotion, no capital flow, no price confirmation). Lives in
`compute_news_quality` and `compute_narrative_quality` in
`scripts/bruce_lee_signal_discipline_report.py`; production engines are
`narrative_inflation_index.py`, `narrative_inertia_score.py`,
`narrative_drift_monitor.py`.

## Inputs

0–1 factors. News: freshness, source_credibility, materiality, novelty,
specificity, market_reaction, cross_verification. Narrative strength: velocity,
breadth, emotional_intensity, institutional_adoption, retail_adoption,
persistence, asset_specificity. Narrative fragility: crowding,
price_overextension, weak_fundamental_support, single_source_dependence,
meme_contamination, contradiction, time_decay.

## Formula

```
NewsQuality = 0.20*Freshness + 0.18*SourceCredibility + 0.16*Materiality
            + 0.14*Novelty + 0.12*Specificity + 0.10*MarketReaction
            + 0.10*CrossVerification
NarrativeStrength  = 0.22*Velocity + 0.18*Breadth + 0.16*EmotionalIntensity
            + 0.14*InstitutionalAdoption + 0.12*RetailAdoption
            + 0.10*Persistence + 0.08*AssetSpecificity
NarrativeFragility = 0.20*Crowding + 0.18*PriceOverextension
            + 0.16*WeakFundamentalSupport + 0.14*SingleSourceDependence
            + 0.12*MemeContamination + 0.10*Contradiction + 0.10*TimeDecay
NarrativeQuality   = NarrativeStrength - NarrativeFragility
```

(Freshness/age also drives the report's `staleness` term —
`AdjustedNewsSignal = RawNewsSignal * exp(-lambda*age_hours)` in the heavier
freshness-decay production logic.)

## Outputs

`news_quality` (0–1); `narrative_strength`, `narrative_fragility`,
`narrative_quality`.

## State consequence

High strength with high fragility (weak fundamentals, single-source, meme
contamination) yields low/negative `narrative_quality`, which lowers the
triangulated clean signal and raises the Diablo `narrative_virality` term.
`NarrativeStrength != FundamentalTruth` — a viral narrative without fundamental
support is a Diablo trigger.

## Tests

`tests/test_bruce_lee_signal_discipline_report.py` — stale news decays via
freshness; high narrative + weak fundamentals raises fragility and lowers
quality.

## Failure modes

* All-loud emotional narrative with zero fundamentals → fragility dominates;
  quality goes negative (correct fake-narrative behaviour).
* Stale news (freshness 0) scores far below fresh news with identical content.

## Advisory-only safety note

Pure functions; no DB, network, or broker calls.

## How to verify locally

```powershell
python -m pytest tests\test_bruce_lee_signal_discipline_report.py -q -k "news or narrative"
```
