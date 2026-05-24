# Triangulated Signal & Contradiction Alpha

## Purpose

No single source is truth. Triangulate price, news, Polymarket, and narrative,
then classify *why* they disagree — because some contradictions are alpha and
others are danger. Lives in `compute_triangulation` /
`_classify_contradiction` in `scripts/bruce_lee_signal_discipline_report.py`.

## Inputs

0–1 signals: price_signal, news_signal, polymarket_signal, narrative_signal,
filing_signal. Plus penalties: pm_distortion, fake_narrative_risk, staleness;
and context: source_credibility, reality_confirmation_01.

## Formula

```
TriangulatedSignal = 0.30*Price + 0.25*News + 0.25*PM + 0.20*Narrative
ContradictionScore = variance(News, Price, PM, Narrative, Filing)
CleanSignal = TriangulatedSignal - PMDistortion - FakeNarrativeRisk - Staleness
```

## Outputs

`triangulated_signal`, `contradiction_score`, `clean_signal`,
`contradiction_class`.

## State consequence — contradiction classes

Priority-ordered classifier:

| Class | When |
|---|---|
| `NO_MATERIAL_CONTRADICTION` | variance < 0.05 |
| `DATA_RELIABILITY_CONTRADICTION` | source credibility < 0.35 |
| `POLYMARKET_DISTORTION_CONTRADICTION` | pm_distortion ≥ 0.45 |
| `FAKE_NARRATIVE_CONTRADICTION` | fake_narrative_risk ≥ 0.45, or loud narrative with dead price/news |
| `HEALTHY_ALPHA_CONTRADICTION` | news/PM ahead of price, reality confirmed |
| `LAGGING_PRICE_CONTRADICTION` | signals ahead of price, weaker confirmation |
| `DANGEROUS_CONTRADICTION` | signals disagree AND reality weak (< 0.4) |

A disagreement with a *confirmed* reality anchor is **not** flagged dangerous —
that would be ornamental alarm, which economy of motion forbids.

## Tests

`tests/test_bruce_lee_signal_discipline_report.py::test_contradiction_classifier_classes`
— fake-narrative, data-reliability, and aligned (no-contradiction) cases.

## Failure modes

* Borderline variance with anchored reality → `NO_MATERIAL_CONTRADICTION`
  rather than a false DANGEROUS flag.
* Low source credibility short-circuits to DATA_RELIABILITY before any alpha
  classification.

## Advisory-only safety note

Pure functions; no DB, network, or broker calls. A contradiction class is a
diagnostic label, never a trade instruction.

## How to verify locally

```powershell
python -m pytest tests\test_bruce_lee_signal_discipline_report.py -q -k contradiction
```
