# Narrative Branch Engine (nbi-v1.6)

## v1.6 — Session close: real install, real cases

Operated 2026-07-03: the Windows task `SleepingPassenger_NBI_DailyLoop` is
**actually installed** (schtasks-verified, daily 08:30, run-once HEALTHY
10/10 — a real nested-quoting bug in the generated PS1 was found by running
it and fixed).  **Two REAL calibration-eligible cases** were promoted
through the workshop with web-verified evidence: VW-emissions-2015
(EQS 10; −33% two-day move, EPA NOV citations) and Brexit-2016 (EQS 10;
GBP −8.1% day-one; the famous market-implied 0.88 'Remain' probability
recorded as a 0.88 prediction error — an honest anti-example seeded into
calibration).  CAA-2019 was **refused by the gate** (no defensible basket
price attribution) and holds as NOT_PROMOTABLE_YET with its evidence pack.
Calibration = CASE_ACCUMULATION (2/30); edge claim remains false.
`nbi_live_ops_cockpit session-close-report` writes
runtime/nbi_session_close_report.{json,md} with scheduler truth, corpus
counts, score, git hash, and the 7-day checklist.

---

## v1.5 — Live-Ops Cockpit + Corpus Acceleration

```powershell
# THE command (supervises everything; operator actions never automated):
python -m scripts.nbi_live_ops_cockpit autopilot        # or --dry-run
python -m scripts.nbi_live_ops_cockpit status | next-actions | score
# LiveOpsHealth = S x E x max(F,.7 fail-closed) x max(M,.75 no-match)
#               x R x C x K x Q x CorpusMaturity(.8 while eligible=0)
# S <= 0.82 helper-only. Labels: READY_RUNNING / DEGRADED_BUT_SAFE /
# BLOCKED_OPERATOR_ACTION / BROKEN_UNSAFE / BROKEN.
# Artifacts: runtime/nbi_live_ops_cockpit.{json,md}; API: GET /nbi/cockpit;
# frontend: cockpit panel on /nbi.

# Scheduler finisher
python -m scripts.nbi_scheduler doctor --fix-plan | verify-install
python -m scripts.nbi_scheduler print-install-command | generate-scripts
#  -> runtime/install_nbi_scheduler.ps1 (+ uninstall). Truth = schtasks only.

# Feed bridge (wire the real news chain into run-daily)
python -m scripts.nbi_feed_bridge discover | status | wire --source <path>
# FeedUsability = logRowCount x exp(-0.01*age_h) x SchemaScore; a source
# whose rows carry no URLs is REFUSED (cite-or-drop applies to feeds too).

# Prediction-market matching v1.5
python -m scripts.nbi_prediction_market_bridge search --event-id <id> --source kalshi
python -m scripts.nbi_prediction_market_bridge diagnose|explain-match --event-id <id>
# Deterministic QuerySet expansion (terms u countries u sectors u synonyms
# u entities), cursor pagination (5x200 markets), MatchScore = .35 Token
# + .25 Entity + .15 Sector + .15 BranchSpecificity + .10 Recency.
# Live finding (2026-07-03): 20 expanded queries over ~1000 open Kalshi
# markets -> 0 semiconductor-export contracts exist. Recorded, not padded.

# Template accelerator
python -m scripts.nbi_template_workshop make-evidence-pack --template-id <id>
python -m scripts.nbi_template_workshop validate-evidence-pack|batch-status
#  -> runtime/nbi_template_evidence_packs/<event>.json research contracts.

# First case
python -m scripts.nbi_evidence_factory first-case-readiness
```

**Operator checklist — next 7 days:**
Day 1: run `runtime/install_nbi_scheduler.ps1` (or `nbi_scheduler install
--time 08:30 --confirm`); `nbi_live_ops_cockpit autopilot` once by hand.
Day 1-2: `make-evidence-pack` for the top-3 first-case templates
(VW-emissions, CAA-2019, Brexit); source the dated URLs in the packs.
Day 3-4: attach evidence/outcome/price/probabilities; `promote --to-real
--operator-confirmed` — target 3 promotions (CASE_ACCUMULATION).
Day 5: refresh the active semiconductor event's query terms; wire the news
chain (`nbi_feed_bridge discover` -> `wire`) once its builder emits live rows.
Day 6-7: `corpus-status` daily; second batch of 3 packs; check `/nbi`.

**Why the score is not 10/10 yet** (all mechanically detected, none
code-fixable): (1) the OS task is generated-and-verified but not installed —
one operator command; (2) eligible real cases = 0 — the 30-case corpus can
only come from closed events and promoted templates; (3) live market
matching found zero listed contracts for the watched arena — a market
absence, not a code gap; (4) the feed builder currently emits an honest
empty file — live rows must come from the news-chain runners; (5) the edge
gate therefore stays false, which is the product working as designed.

---

## v1.4 — Operate and Close the Real Loop

```powershell
# Scheduler: doctor verifies the whole chain before you install
python -m scripts.nbi_scheduler doctor          # preflight (14 checks)
python -m scripts.nbi_scheduler install --time 08:30   # real schtasks task
# Health v1.4: SchedulerHealth = Run x Persisted x Cards x ScoreReport x
# Safety; feeds-missing with clean fail-closed = DEGRADED_BUT_SAFE.
# BROKEN_UNSAFE fires if the scheduled action ever contains execution tokens.

# Activation flow (WATCH_ONLY -> ACTIVE is an explicit operator act)
python -m scripts.nbi_evidence_factory activate-event --event-id <id>
python -m scripts.nbi_evidence_factory deactivate-event|event-status --event-id <id>
# Gates: EventReadiness10 >= 5, query terms, country_scope, not fixture.
# Readiness v1.4 = Query x max(Source,.25) x max(Bench,.5) x max(Chain,.5)
#                x max(Official,.5); no official sources -> confidence cap 0.7.

# Prediction markets: REAL public read-only Kalshi fetcher (no key, no
# secrets, GET /markets only; client-side title filter):
python -m scripts.nbi_prediction_market_bridge fetch --event-id <id> --source kalshi
python -m scripts.nbi_prediction_market_bridge refresh-all --source kalshi
python -m scripts.nbi_prediction_market_bridge status
# alpha now includes RecencyScore = exp(-0.01*age_h); non-LIVE adapter
# status -> alpha 0; unknown fetched_at -> RECENCY_UNKNOWN note.

# Template worklist (the 10-case retro-fill queue)
python -m scripts.nbi_template_workshop export-worklist   # runtime/nbi_template_worklist.json
python -m scripts.nbi_template_workshop next | batch-validate
python -m scripts.nbi_template_workshop batch-promote --ids ... --operator-confirmed

# Calibration bands: 0 INSUFFICIENT | 1-9 CASE_ACCUMULATION (metrics
# withheld) | 10-29 DESCRIPTIVE_ONLY | >=30 CALIBRATION_POSSIBLE.

# Operating board (main daily view)
python -m scripts.nbi_evidence_factory corpus-status
# LiveOpsReadiness = Scheduler x ActiveEvents x Feed x Cards (0.7 cap
# helper-only); includes next_required_operator_actions.

# Frontend: real Next.js app route /nbi (frontend/src/app/nbi/page.tsx,
# build-verified) consuming GET /nbi/cards; advisory banner, edge gate,
# fixture labels, zero execution controls.
```

**14-day operating loop** (the whole point):
Day 0: `nbi_scheduler doctor` → `install --time 08:30`; `activate-event` on
1-2 watch events after refreshing their query terms.  Daily (automatic):
run-daily → cards → score-report; skim `/nbi` or `corpus-status`.  Every
2-3 days: `template_workshop next` → attach evidence/outcome/price/
probabilities → `promote --to-real --operator-confirmed` (one template ≈
30-45 min of sourcing).  When a live event resolves: `close-event` with
branch outcomes and returns.  Day 14 target: scheduler HEALTHY streak,
5-10 eligible cases (CASE_ACCUMULATION), first honest look at prediction
errors.  Edge claims stay false throughout — that is the design.

---

## v1.3 — the Operational Alpha Loop

The factory becomes schedulable, monitored, market-matched, and corpus-building:

```powershell
# Scheduler (Windows Task Scheduler; helper is honest: INSTALLED only when
# the task actually exists — module presence claims nothing)
python -m scripts.nbi_scheduler install --time 08:30     # or --dry-run
python -m scripts.nbi_scheduler status | uninstall | run-once | cron
# Health: SchedulerHealth = RunSuccess x FeedAvailable x ReportPersisted x
# CardsExported; missing feeds -> DEGRADED_BUT_SAFE, never a crash.

# Active event definitions (configuration, never evidence)
python -m scripts.nbi_evidence_factory list-events | validate-events
python -m scripts.nbi_evidence_factory add-event --event-id X --name "..." `
    --query-terms "summit,tariff" --status WATCH_ONLY
# EventReadiness = Query x Source x Benchmark x ValueChain (x10).
# 3 operator-ready WATCH_ONLY packs: data/nbi_watch_event_definitions.json

# Prediction markets
python -m scripts.nbi_prediction_market_bridge fetch|match|refresh-all
# alpha = min(1, logVolume x Liquidity x Phrasing); illiquid cap 0.15,
# weak-phrasing cap 0.30, uncited alpha 0, official-evidence cap 0.25.
# Live auto-fetch reports ADAPTER_UNAVAILABLE honestly in this environment;
# inject a fetcher or refresh runtime/nbi_market_contracts.json.

# Template retro-fill workshop (audited TEMPLATE -> REAL, the only path)
python -m scripts.nbi_template_workshop list | show | validate
python -m scripts.nbi_template_workshop attach-evidence|attach-outcome|`
    attach-price|attach-probabilities --template-id ...
python -m scripts.nbi_template_workshop promote --template-id ... `
    --to-real --operator-confirmed
# PromoteToReal = 1[EQS10>=7] x 1[outcomes complete] x 1[refs valid]
#               x 1[explicit operator flag] x 1[not fixture]
# attach-probabilities REQUIRES --basis (reconstructions must cite sources).
# Every mutation lands in nbi_template_audit.

# Closeout quality (v1.3): CloseoutQuality = Outcome x Evidence x Price x
# DecisionHistory; < 0.5 refuses unless --force-noncalibration, which marks
# NON_CALIBRATION_CLOSE and caps label confidence at 0.3 (never eligible).
# Per-branch squared errors + case Brier persist on every close.

# Corpus dashboard
python -m scripts.nbi_evidence_factory corpus-status
# CasesRemaining = max(0, 30 - N_eligible); Progress10 = 10 x N/30.

# Score report v1.3: Overall = min(sum(w_i*s_i)/sum(w_i), honesty caps).
# Caps: no eligible cases -> <=8.8; edge false -> <=9.0; scheduler not
# installed -> <=8.8; markets not live-auto-fetched -> <=8.8; plus per-
# segment caps (LiveData/Frontend/Calibration/PM/TrackRecord <= 8).

# Operator surface: token-gated GET /nbi/cards (api_server) serves the
# runtime/nbi_operator_cards.json artifact written by export-cards; plus
# static HTML/MD. Advisory-only banner, edge_claim_allowed=false until
# earned, fixtures labeled, no execution controls (tested against
# FORBIDDEN_EXECUTION_TOKENS).
```

---

## v1.2 — the Evidence Factory (closed loop)

```
feeds -> run-daily ingestion -> event reports -> operator cards
      -> operator decision -> close-event -> outcome/price measurement
      -> backtest case -> calibration readiness -> edge-claim gate
      -> score-report deltas
```

**Commands** (`scripts/nbi_evidence_factory.py` — a CLI runner, NOT a
scheduler; wire it into your existing scheduled task to make it periodic):

```powershell
python -m scripts.nbi_evidence_factory run-daily        # one factory cycle
python -m scripts.nbi_evidence_factory status           # loop-state census
python -m scripts.nbi_evidence_factory close-event --event-id X `
    --core-outcome 1 --venue-outcome 0 --realized-return 0.04 `
    --benchmark-return 0.01 --initial-risk 0.02 --notes "venue shifted"
python -m scripts.nbi_evidence_factory import-templates # 20 retro-label seeds
python -m scripts.nbi_evidence_factory export-cards     # HTML+MD surface
python -m scripts.nbi_evidence_factory score-report     # segmented ceiling census
python -m scripts.nbi_evidence_factory init-event-template
```

Operator inputs: `runtime/nbi_active_events.json` (event definitions:
keywords, priors, exposures or value-chain graph) and optional
`runtime/nbi_market_contracts.json` (per-event prediction-market rows).

**Closeout math** (`close_event`): branch outcomes `y_b ∈ {0,1}`;
`PredictionError_b = P_b − y_b`; `ReturnVsBenchmark = R_i − R_bench`;
`RMultiple = RealizedReturn / (|InitialRisk| + ε)`.  `is_fixture` is
inherited from the event row — a fixture event can never create a REAL case.

**Case kinds:** `REAL` (only kind that can ever count) / `FIXTURE` /
`TEMPLATE` (retro-label seeds from `data/nbi_historical_event_templates.json`
— 20 public events awaiting verified outcomes + price evidence).

**Evidence Quality Score** (`nbi_track_record_ledger`):
`EQS = Citation × OutcomeClarity × PriceCompleteness × BranchLabels ×
OperatorDecisions`; calibration-eligible ⇔ `EQS10 ≥ 7 ∧ kind=REAL ∧ closed`.

**Edge-claim gate** (false until earned, shown on every surface):
`N_eligible ≥ 30 ∧ Brier < Brier_baseline ∧ ECE ≤ 0.10 ∧ MeanR > 0 ∧
MaxDD ≤ 5R` — and even then a human calibration review is still required.

**Prediction markets** (`nbi_prediction_market_bridge`): contracts map to
*branches* (a Guwahati-venue contract blends venue, never core);
`α = min(1, Volume × Liquidity × PhrasingMatch)`;
`P_blend = α·P_market + (1−α)·P_model`; uncited contracts get α=0; branches
with official evidence cap α at 0.25; venue_blend ≤ core_blend holds.

**Track record ledger:** open/close/summarize advisory recommendations;
below 10 closed non-fixture entries the summary is
`TRACK_RECORD_INSUFFICIENT` and refuses all performance numbers.

---

> v1.1 (live-wiring sprint) adds: claim ingestion from raw provider rows
> (`nbi_claim_ingestion`), automatic source-cluster derivation + rule-based
> layer classification, canonical SQLite persistence (`nbi_store`),
> backtest-corpus accumulation + honest calibration report
> (`nbi_calibration_report` — Brier/logloss/ECE, refuses N<10), value-chain
> graph exposure (`nbi_value_chain_mapper`), pure price validation
> (`nbi_price_validation_adapter`), and the demote-only daily bridge
> (`nbi_daily_bridge`, wired into `daily_synthesis_pipeline`).  New engine
> invariants: `P(deals) <= P(delegation) <= P(core)` (unless deals has
> direct evidence), event confidence decay `C_t = e^(-0.05*days)`, price
> bonus `min(1 + 0.5*PD, 1.25)` min()-guarded by merit, emotion scoring v2
> (lexicon + exclamation density + caps ratio), ACT requires OAS >= 7.5 and
> rumor < 5.

Advisory-only pipeline that stops the system treating events as binary
on/off headlines:

```
Claim -> Source Cluster -> Narrative Layer -> Rumor / Causal-Leap Score
      -> Event Branch Probabilities -> Surviving Narrative Layer
      -> Value-Chain Exposure Rotation -> Price-Dislocation Validation
      -> Demote-Only Gates -> Advisory Event Card -> Operator
```

Module: `scripts/narrative_branch_engine.py`
Tests:  `tests/test_narrative_branch_engine.py`

## Run it

```powershell
python -m scripts.narrative_branch_engine --demo          # Guwahati->Delhi card
python -m scripts.narrative_branch_engine --demo --json   # raw report
python -m scripts.narrative_branch_engine --event-json path\to\event.json
```

## Doctrine (all tested)

1. **Sub-branch <= core.** `P(venue_specific)`, `P(delegation_intact)`,
   `P(deals_or_mous)`, `P(sector_impact)` are hard-capped at `P(core_event)`.
2. **DEAD only when core collapses.** A collapsed venue with a surviving core
   is `TRANSFORMED` -> `ROTATE`, never `FOLD`.
3. **Truth(Event) != Truth(CausalClaim).** A verified trigger (traffic jam)
   plus an unsupported macro claim (visit cancelled) yields verdict
   `TRUE_MICRO_EVENT_UNSUPPORTED_MACRO_CLAIM` and a HIGH rumor risk — the
   true kernel makes the rumor more dangerous, not less.
4. **Social media is velocity, not truth.** SOCIAL/LLM claims never move
   branch probabilities; they feed RumorRisk only.
5. **Repetition is not independence.** One best claim per source *cluster*
   per branch; five articles from one root source count once.
6. **Cite-or-drop.** No `evidence_refs` -> claim UNVERIFIED (excluded from
   truth), exposure scores 0 (`NO_VERIFIED_EVIDENCE`).
7. **No price validation -> WATCH_ONLY.** Narrative scores never float in
   the air; `model_probability`, `market_implied_probability`, and
   `realized_move_zscore` are all required to leave watch state.
8. **Rumor can only demote** (multiplier `1 - 0.05*RumorRisk`) **or flag**
   (`DISLOCATION_WATCH` when model/market divergence + real price move +
   surviving core coexist). RumorRisk >= 7 makes `ACT` impossible.
9. **Demote-only chain:** `FINAL <= VALIDATED <= BASE`; every multiplier in
   `[0, 1]`.

## Wired existing modules (reuse, not duplication)

| Module | Role in NBI |
|---|---|
| `narrative_drift_monitor` | NDM epistemic drift over the event's claim corpus |
| `consensus_formation_detector` | CS/CFD amplification context (optional inputs) |
| `hedge_ratio_engine` | classifies the rotate-basket hedge ratio |
| `advisory_contract` | canonical safety stamps |
| `chicken_gate` | `integrate_with_chicken_gate()` — min() score + min-rank gate; NBI can only lower an existing decision |

## Scores (0-10)

`RUMOR_RISK`, `NARRATIVE_CONFIDENCE`, `EVENT_BRANCH` (core p x10),
`SOURCE_DISAGREEMENT` (normalized Bernoulli variance across clusters),
`HEDGE_NEED`, `OPERATOR_ACTION`.

## Calibration honesty

`CLASS_LLR`, thresholds, and multipliers are documented heuristics until the
backtest corpus reaches ~30 closed cases. `build_backtest_case()` freezes a
report + resolution into the `BACKTEST_CASE_FIELDS` schema (false-positive /
false-negative labels included) precisely so those constants can eventually
be fitted from evidence instead of judgment.

Advisory-only. No broker execution, no order surface, no real-money sizing.
