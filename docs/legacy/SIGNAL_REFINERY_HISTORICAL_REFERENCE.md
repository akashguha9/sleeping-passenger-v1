# Signal Refinery MVP_1 — Historical Reference (legacy, non-canonical)

> **This document is preserved for historical context only.**  The
> Signal-Refinery subsystem (`src/`, the EMS/EQS/DS/LS/EFS/APS scoring
> stack, the Streamlit dashboard scaffold, the IGNORE/WATCH/VALIDATE/
> PAPER_TRADE classifier) was an additive research path.  It is **not** the
> canonical advisory journal workflow described in the main `README.md`.
>
> The advisory-only safety contract still applies:
> `advisory_status="ADVISORY_ONLY"`, `execution_gate="LOCKED"`,
> `broker_api_called=false`, `ai_execution_count=0`.
>
> The current calibration posture for the scoring stack is documented in
> `docs/SCORING_STACK_VALIDATION.md` — scores are **uncalibrated** until
> the calibration gate reports `MEASURED` with Brier ≤ 0.25 and ECE ≤ 0.10.

---

## Signal Refinery MVP_1

This repo now includes an additive read-only public-data subsystem under `src/` for a geopolitical / narrative / prediction-market signal refinery MVP.

### Doctrine

- Detect widely.
- Classify intent early.
- Reject aggressively.
- Validate durable signals.
- Paper-trade before capital.
- Execute only after proof.

The edge is disciplined refusal, not speed.

### What It Does

- fetches public Polymarket market data through a read-only client with deterministic mock fallback
- scores markets for engineered attention versus durable evidence
- classifies each market into `IGNORE`, `WATCH`, `VALIDATE`, or `PAPER_TRADE`
- stores raw snapshots, processed scores, attention clusters, rejected signals, and paper trades in SQLite
- supports a paper-only dashboard and explanatory output layer

### What It Does Not Do

- live trading
- wallet or private-key handling
- authenticated order placement
- signed Polymarket orders
- broker integration
- capital deployment logic

This is a read-only signal-refinery MVP.
It does not provide financial advice.
It does not execute trades.
It does not handle wallets or private keys.
It uses public data to test signal classification and paper-trading logic.
Real capital should not be connected until the paper system is validated.

### Governing Formulas

`Signal Problem ≠ Truth vs Falsehood`

`Signal Problem = Durable Evidence vs Engineered Attention`

`Detected Signal ≠ Valid Signal ≠ Actionable Signal`

`AI Output = Explanation Layer`

`Pipeline Score = Decision Layer`

`MVP_1 = Public Data + Scoring + Dashboard + Paper Trade`

`Alpha = Refusal Quality + Validation Discipline + Execution Patience`

`False Claim ≠ Zero Value`

`False Claim = Low Truth Value + Possible Attention Value`

`Good MVP = Signal Refinery`

`Bad MVP = Premature Trading Bot`

`NetSignalValue = MarketMispricing × EvidenceQuality × Durability × Liquidity - EngagementManipulation - ExecutionFriction`

`ReadyForLive = PaperAccuracy > θa AND Drawdown < θd AND APIStability = True AND WalletSecurity = True`

`ReadyForLive` is roadmap only and is not implemented.

### Scoring Stack

- `EMS = 0.20*EmotionalIntensity + 0.15*HeadlineExtremity + 0.15*NarrativeRecycling + 0.15*ViralitySpike + 0.15*CuriosityGap - 0.10*EvidenceDensity - 0.10*SourceCredibility`
- `EQS = 0.25*PrimarySourceWeight + 0.20*SourceCredibility + 0.20*ConfirmationCountNorm + 0.15*RecencyScore + 0.10*CrossSourceDiversity - 0.10*ContradictionPenalty`
- `DS = 0.25*Persistence + 0.25*StressSurvival + 0.20*CrossSourceConfirmation + 0.15*TimeStability + 0.15*ContradictionResistance`
- `LS = 0.35*LiquidityNorm + 0.30*VolumeNorm + 0.20*OrderBookDepthNorm - 0.15*SpreadPenalty`
- `EFS = 0.25*SpreadPenalty + 0.25*LowLiquidityPenalty + 0.20*VolatilityPenalty + 0.20*TimingRisk + 0.10*APIUncertaintyPenalty`
- `ModelProbability = clip(0.50 + 0.25*(EQS-0.50) + 0.20*(DS-0.50) - 0.15*EMS - 0.10*EFS, 0.01, 0.99)`
- `APS = 0.30*EQS + 0.25*DS + 0.20*LS + 0.15*MarketMispricingEstimate - 0.20*EMS - 0.15*EFS`

### State Classification

- `IGNORE`: high manipulation / low evidence, or friction too high
- `WATCH`: early but incomplete
- `VALIDATE`: promising and durable enough for deeper review
- `PAPER_TRADE`: strongest paper-only candidates with sufficient evidence, durability, liquidity, and manageable friction

### Storage and Dashboard

- SQLite path: `data/processed/signal_refinery.sqlite`
- Streamlit app: `src/dashboard/streamlit_app.py`
- Run ingestion: `python scripts\run_ingestion.py --summary`
- Run scoring: `python scripts\run_scoring.py --summary`
- Run paper trading: `python scripts\run_paper_trading.py --summary`
- Run dashboard helper: `python scripts\run_dashboard.py`
- `unavailable`: external mode was requested, but zero valid observations survived provider/data-quality checks; the system fails closed.

All bridge modes remain advisory and paper-safe. They do not enable capital deployment or broker execution.

## Grok Intelligence Limits

- Grok is an intelligence-extraction layer, not an execution layer.
- It can interpret payloads and rank current candidates, but it does not approve trades or alter governance.
- It requires explicit `XAI_API_KEY`, `XAI_API_BASE_URL`, and `XAI_MODEL` configuration.
- If the API call fails or the returned payload is not valid structured JSON, the repo persists that failure state explicitly in `runtime/grok_xai_report.json`.

## Reconciliation Layer

The repo now writes a cumulative paper reconciliation history and summary.

- `logs/paper_reconciliation_history.jsonl` accumulates one reconciled row per closed paper trade.
- `runtime/paper_reconciliation_summary.json` tracks cumulative expectancy, win/loss, and data-gap metrics.
- `runtime/paper_reconciliation_report.json` reports the latest reconciliation pass and merge counts.
- This measures paper lineage quality and paper expectancy. It is still not economic proof of a live system.

## Experience Ladder

The repo now has a first additive experience/readiness report for trainer/utility/jet-style surfaces.

- `runtime/experience_mode_report.json` summarizes trainer-mode metadata, visibility/lineage legibility, readiness scaffolding, degraded-mode flags, and premium-surface eligibility.
- `runtime/complexity_ladder_controller.json` interprets that report into advisory surface exposure flags for trainer, utility, and premium operator views.
- `runtime/environment_fit_report.json` adds advisory environment-fit, robustness-vs-precision, locality, dependency-fragility, and anti-overcustomization summaries.
- That report now also includes a `truth_boundary_summary` block separating observed repo evidence, heuristic inference, placeholders, and items that still need real data or live APIs for full validation.
- The current tree should still be interpreted as trainer / early-utility phase.
- These experience/complexity reports are advisory only. They do not change decisioning or execution behavior.

## Manual Operator Control Commands

Examples:

```powershell
python scripts\operator_control.py state --active-objective "ship operator control MVP" --active-task "wire phase report" --operator-mode focused --baseline-score 0.42 --current-score 0.58 --peak-score 0.73 --note "manual-only input"
python scripts\operator_control.py start-block --objective "ship operator control MVP" --success-metric "tests green" --time-boundary "90m" --active-task "wire gate" --non-goal "rewrite paper flow" --block-type coding
python scripts\operator_control.py log-event --event-type execution_started
python scripts\operator_control.py log-event --event-type context_switch --reason "checked adjacent module before closing"
python scripts\operator_control.py close-block --output-exists
python scripts\operator_control.py report --summary
```

## Known Coherence Gap

- `runtime/signal_vocoder_report.json` is a legacy unmanaged artifact in the current tree.
- It does not carry the repo's current runtime metadata contract.
- Do not treat it as proof that all runtime outputs are coherent until its producer is either patched or retired.

## Environment Template

Copy `.env.example` into your local environment management flow if you want to test paper/live-prepared mode flags later. The checked-in verified path does not require secrets.
