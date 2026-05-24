# Bruce Lee Signal Discipline

## Purpose

Bruce Lee is not a theme in this MVP — he is decision architecture. This
layer turns the Jeet Kune Do reflection into advisory **scores, gates,
diagnostics, a report, and tests**, never decorative branding, quotes, or a
"Bruce Lee mode". The unifying translation:

```
BruceLeeLayer = Discipline + Adaptation + Interception + NoiseRejection
              + EconomyOfMotion + RealityConfirmation + Survival

MVPQuality    = UsefulSignal + SurvivalValue + FeedbackValue
              - Noise - Ornamentation
```

The operator entry point is `scripts/bruce_lee_signal_discipline_report.py`,
which fuses the live runtime-truth state with the JKD decision layer into one
advisory read with a **final advisory constraint** that has consequence.

## Where each concept lives (consolidation map)

The reflection lists many sub-engines. Per the Economy-of-Motion principle the
reflection itself demands ("hack away the unessential"), the synthesis math is
**consolidated** into a focused, fully-tested set rather than dozens of thin
modules. Each concept is measurable and traceable:

| Concept | Lives in |
|---|---|
| JKD decision score / Interception (B2) / Directness (B3) | `scripts/jkd_decision_discipline.py` |
| Economy of motion / system sharpness (B4) | `scripts/economy_of_motion_audit.py` |
| Finger / moon reality confirmation (B5) | `scripts/finger_moon_reality_check.py` |
| Operator emotional content / heat (B6) | `scripts/operator_emotional_content_gate.py` |
| Diablo narrative veto (B10) | `scripts/diablo_narrative_veto.py` |
| BLDQI + SignalEfficiency / BrokenRhythm / AntiDogma / SurvivalUtility (B11) | `scripts/bruce_lee_decision_quality_index.py` |
| Polymarket belief / distortion (B7) | `compute_polymarket_distortion` in the report; production engines: `narrative_distortion_index.py`, `signal_distortion_index.py` |
| News / narrative / triangulation / contradiction (B8) | `compute_news_quality`, `compute_narrative_quality`, `compute_triangulation` in the report; production engines: `narrative_inflation_index.py`, `narrative_inertia_score.py`, `narrative_drift_monitor.py` |
| Strategic actor / firm incentive / reflexivity (B9) | `compute_strategic_actor_summary`, `compute_firm_incentive_summary`, `compute_reflexivity` in the report; related: `game_state_control_engine.py` |

## Inputs

* Runtime DB (read-only) for truth-purity and economy-of-motion state.
* A per-signal scenario dict (price/volume/news/narrative/PM/operator-emotion
  inputs). The CLI uses an explicitly *illustrative* neutral scenario; the
  operator supplies real inputs in practice (`build_report(scenario=...)`).

## Outputs

`truth_purity_status`, `economy_of_motion`, `jkd_decision_score`,
`interception`, `directness`, `adaptability`, `anti_dogma`,
`reality_confirmation`, `operator_heat`, `polymarket_distortion`,
`news_quality`, `narrative_quality`, `triangulated_signal`,
`contradiction_class`, `strategic_actor_summary`, `firm_incentive_summary`,
`reflexivity`, `diablo_veto`, `bldqi_score`, `final_advisory_constraint`, plus
the banners `ADVISORY_ONLY`, `HUMAN_EXECUTION_REQUIRED`,
`NO_BROKER_ACTION_PERFORMED`.

## State consequence

`final_advisory_constraint` is the **tightest** of the JKD constraint, the
BLDQI constraint, and the Diablo veto. Order, most → least restrictive:
`RECONCILE_OR_WAIT > NO_NEW_RISK_RECOMMENDED > MONITOR_ONLY > WATCHLIST_ONLY >
HUMAN_REVIEW_REQUIRED`. The strongest possible verdict is still
HUMAN_REVIEW_REQUIRED — no state authorises execution.

## Tests

`tests/test_bruce_lee_signal_discipline_report.py` — all required fields
present, the three banners printed, advisory invariants held, no execution
language, and each consolidated B7/B8/B9 helper behaves.

## Failure modes

* Missing DB → truth-purity fails closed (gate not passed); the report still
  renders with the safe banners.
* A scenario with loud pointers but no real anchor → low reality confirmation,
  WAIT/NO-NEW-RISK constraint (correct conservative behaviour).

## Advisory-only safety note

Read-only on the DB; pure compute for the synthesis. No broker calls, no order
placement, no execution endpoint. SQLite stays canonical; JSONL stays
audit-only. Every output carries the advisory-only stamps.

## How to verify locally

```powershell
python scripts\bruce_lee_signal_discipline_report.py
python scripts\bruce_lee_signal_discipline_report.py --json
python -m pytest tests\test_bruce_lee_signal_discipline_report.py -q
```
