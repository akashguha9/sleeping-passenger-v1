# OPERATIONAL TRUTH — how this MVP reports on itself

**Last verified: 2026-07-04 (Open-the-Gate sprint).**
This is the canonical reference for what the system's status words mean,
where truth lives, and what is still blocked. If code and this document
disagree, the code is the bug or this file is — fix one the same day.

Advisory-only by design: **no broker execution exists anywhere in this
repo.** `configs/no_execution_policy.yaml` + `tests/test_no_execution_guard_repowide.py`
machine-enforce it (repo-wide AST ban on order functions). A human makes
every trade decision and logs it manually.

---

## 1. The truth surface

One command answers "can I trust the system right now":

```powershell
python -m scripts.truth_surface_report          # or GET /truth-surface
```

It returns `overall_operational_state` ∈ `HEALTHY | DEGRADED | BLOCKED |
BROKEN` with per-axis evidence:

| Axis | Field(s) | Rule |
|---|---|---|
| Holdings truth | `holdings_truth_status`, `holdings_freshness_age_minutes` | run_date older than 3 days → DEGRADED; file missing → BROKEN |
| Stop discipline | `missing_stop_count`, `leveraged_without_stop_count` | any active holding without a stop → **BLOCKED** (leveraged: CRITICAL) |
| Evidence | `matured_real_outcome_count`, `calibration_status` | N=0 → can never be HEALTHY (“install healthy, operational evidence incomplete”) |
| Data persistence | `rows_persisted_status` | key source with no persisted rows >7 days → DEGRADED (`ZERO_PERSISTED_DEGRADED`) |
| Artifacts | `latest_artifact_age_minutes`, `artifacts.*` | operator artifact older than 26h → DEGRADED |
| Scheduler | `scheduler_status` | last-run record BROKEN/BROKEN_UNSAFE → BROKEN |

**Install health ≠ operational health.** A freshly installed scheduler that
has produced no outcomes reports DEGRADED, not HEALTHY 10/10.

## 2. Canonical holdings source (risk engine)

- **The only canonical open-position truth:** `data/daily_payload/verified_current_holdings.json`.
- **The only sanctioned loader:** `scripts/holdings_truth_gate.py`
  (freshness gate: fail-closed at run_date > 3 days; stop discipline:
  positions without `stop_loss` are `BLOCKED_MISSING_STOP`, leveraged ones
  `BLOCKED_MISSING_STOP_LEVERAGED`; prices only from ingested bars with
  `price_as_of`, stale price → `BLOCKED_STALE_PRICE`).
- `scripts/action_engine.py` reads positions through this gate by default.
  `moltbook/open_positions.json` is a **demoted historical ledger** — it is
  never a default risk source (regression-tested by
  `tests/test_action_engine_canonical_source.py`).
- The capacity gate (`max_open_positions`) counts the **max** of pipeline
  positions and canonical holdings, so a real 10-position book can never
  hide under a 6-position cap again.
- **Operator duty:** keep `verified_current_holdings.json` fresh (re-verify
  at least every 3 days) and record a `stop_loss` (and ideally
  `take_profit` / `invalidation_level`) per position. Until stops exist the
  risk engine stays BLOCKED **by design** — it will not pretend to protect
  what it cannot see.

## 3. What “probability” means today

`model_probability` is an **uncalibrated heuristic prior** — a clipped
linear blend of sub-scores (`src/scoring/net_signal_value.py`, whose own
docstring says "placeholder"). As of 2026-07-04 it is *measured* for the
first time:

- **N = 56** closed, real, timestamp-locked forward outcomes
  (2026-05-31 cohort, horizons closed 2026-06-05, matured 2026-07-04).
- **Brier 0.2794** vs 0.25 for always-predicting-0.5 and **0.1684** for the
  constant base-rate predictor. **The model currently has NO demonstrated
  edge** — it loses to both reference predictors on this corpus
  (`runtime/release/benchmark_comparison.json`, honest_verdict field).
- Mean realized return −3.41% vs SPY −1.33% (alpha −2.08%) on the same
  windows — post-hoc analytics, clearly labeled, never re-labeling locked
  outcomes.

**When may it be called calibrated?** Only when the repo gate passes:
N ≥ 200 real outcomes AND Brier ≤ 0.25 AND ECE ≤ 0.10
(`scripts/real_calibration_evidence.py`). Below N=50 every UI surface must
say "uncalibrated". `predictive_claim_allowed` stays `false` until the gate
passes; nothing in this sprint may loosen it.

## 4. Outcome maturation (the evidence flywheel)

```powershell
# read-only: what is due / pending / attached
python -m scripts.forward_outcome_maturity_scanner

# the daily close-the-loop command (dry-run by default)
python -m scripts.run_daily_outcome_maturation --write --benchmark-symbol SPY

# post-hoc benchmark analytics over the matured corpus
python -m scripts.benchmark_outcome_report --write
```

- Predictions are **locked at snapshot time** (timestamp, probability,
  entry price, horizon, target definition). Maturation only ever fills the
  outcome columns of horizon-elapsed rows; locked fields are immutable
  (verified byte-identical before/after the 2026-07-04 retro-maturation).
- Outcomes are attached append-only with provenance
  (`outcome_source=real_ohlcv_signal_events`, `outcome_kind=real_forward`).
- The daily scheduler (`scripts/nbi_scheduler.py run-once`) runs the
  maturation step every cycle and reports `outcomes_closed` /
  `n_real_forward` in its health record; a crashed maturation makes the run
  BROKEN, not silently green.
- Guard against re-stranding: `tests/test_branch_stranding_guard.py` fails
  the suite if the maturation entry points, table readers, or scheduler
  wiring disappear from the canonical branch.

## 5. Scheduler failure semantics

`python -m scripts.nbi_scheduler run-once` exit codes (regression-tested by
`tests/test_nbi_scheduler_exit_codes.py`):

| Status | Exit | Meaning |
|---|---|---|
| HEALTHY | 0 | full cycle incl. outcome maturation |
| DEGRADED_BUT_SAFE | 0 | designed non-blocking: fail-closed cycle, disclosed in record/log/cockpit |
| BROKEN / BROKEN_UNSAFE / FAILED / unknown | **1** | Task Scheduler Last Result goes nonzero; stderr says `NBI SCHEDULER RUN FAILED` |

The pre-sprint bug (BROKEN exited 0 because the CLI compared against a
legacy status the runner never emits) is fixed and pinned by tests.

## 6. Data-persistence honesty

`GET /source-health/summary` demotes any ok-classified source that has
persisted **zero rows beyond 7 days** to `ZERO_PERSISTED_DEGRADED`
(severity warning) with `last_persisted_at` / `persist_age_days` visible.
"Fetched 75, persisted 0, for 11 days" can no longer read as healthy.
The scheduled market-data refresh fetches the canonical holdings symbols in
addition to the index ETFs (`scripts/ingestion/market_data_loader.py`).

## 7. Real-money readiness — BLOCKED (explicit)

Real-money use is **blocked** until ALL of the following are true; the list
is enforced culturally by this doc and mechanically by the truth surface:

1. Calibration gate passes on real forward outcomes (N ≥ 200, Brier ≤ 0.25,
   ECE ≤ 0.10) — today: N=56, Brier 0.2794, **NO DEMONSTRATED EDGE**.
2. `verified_current_holdings.json` fresh (≤3 days) and broker-confirmed —
   today: stale until the operator re-verifies; `broker_confirmed:false`.
3. Every position carries an operator-set stop; leveraged positions
   (2×4x INR names) instrumented — today: **0/10 have stops → BLOCKED**.
4. A live drawdown monitor and push alerting exist — today: absent.
5. 30 days of unattended scheduled-loop evidence — today: first scheduled
   NBI run was 2026-07-04.

## 8. Investor-demo readiness — blockers

1. N is real but small (56) and unflattering (model loses to base rate) —
   presentable as honesty, not as performance.
2. No frontend-against-real-backend integration test.
3. Docs older than this sprint may still contain stale claims — the two
   pre-June self-audits are marked HISTORICAL; treat anything without a
   "Last verified" stamp with suspicion.
4. Sheets sync loop remains unproven end-to-end (audit segment H, 4.4/10).

## 9. Glossary (external-reader minimum)

| Term | Meaning |
|---|---|
| **NBI** | Narrative Branch Intelligence — event/rumor branch scoring lane (`scripts/nbi_*`, `/nbi` page) |
| **Chicken gate** | Demote-only freshness/asymmetry gate on daily candidates (`scripts/chicken_gate.py`) |
| **Moltbook** | Legacy trade journal — historical-only, demoted from truth |
| **Kanté** | Internal codename for defensive/invisible-work sprints (reliability, gates, hygiene) |
| **Mythos / Fable (signal_arbitrage)** | Interpretation/meaning-routing layers feeding multiplicative reality gating (`scripts/signal_arbitrage/`) |
| **Truth surface** | `scripts/truth_surface_report.py` / `GET /truth-surface` — the one honest status object |
| **Maturation** | Closing a locked forward prediction into a real outcome after its horizon elapses |

## 10. Feed-the-Loop additions (2026-07-04, same day)

**Stop confirmation loop (operator-in-the-loop, fail-closed):**

```powershell
python scripts/holdings_truth_gate.py --validate         # exit 1 while BLOCKED
python scripts/holdings_truth_gate.py --write-template   # suggestions only
# ... edit data/daily_payload/stop_loss_backfill_template.json:
#     set stop_loss_confirmed=true + stop_loss_confirmed_at per entry,
#     optionally holdings_confirmed_current=true (+timestamp) to refresh run_date
python scripts/holdings_truth_gate.py --apply-confirmed --write
```

Suggested stops use the named policy (5% hard stop 1x / 2.5% leveraged) and
are NEVER active until confirmed: an unconfirmed stop is
`BLOCKED_UNCONFIRMED_STOP`, exactly like a missing one.  Confirmed stops
unlock `loss_at_stop`, `portfolio_stop_exposure`, and the
`portfolio_stop_exposure_fraction` (computed against cost-basis equity,
labeled as such).

**The daily loop now compounds** (`python -m scripts.nbi_scheduler run-once`):
discovery refresh (canary-gated) -> snapshot producer (25 locked/day max,
same-day idempotent) -> Kalshi settlement harvest (append-only) -> NBI
ingest/cards -> outcome maturation -> alert dispatch.  Health axes:
`producer_ok`/`maturation_ok` multiply into SchedulerHealth;
`discovery_status`/`settlement_provider_state`/`alerts_dispatched` are
recorded per run.

**Velocities** (truth surface): `evidence_velocity_7d` = locked forward
predictions/day, `maturation_velocity_7d` = matured outcomes/day.  Zero
evidence velocity with a scheduled producer, or any due-unmatured
prediction, degrades the overall state.

**Provider canary** (`scripts/refresh_fresh_discovery_live.py`): PASS when
the newest SPY bar is fresh (<=26h) OR inside the 4-day weekend/holiday
window WITH a successful provider run <=26h old (mode
`MARKET_CLOSED_WINDOW`) — distinguishing "markets closed" from "provider
dead".  Discovery payloads carry `artifact_created_at` + the canary; the
truth surface age-gates them (>26h DEGRADED, >50h BLOCKED).

**Alert channel** (`scripts/operator_alert_bridge.py`): append-only JSONL
queue (`runtime/alerts/operator_alerts.jsonl`) + latest snapshot + console.
SHA-256 dedupe per condition per day.  Dispatched by every daily cycle;
rendered in the cockpit truth panel.

**Kalshi settlement loop**
(`scripts/kalshi_settlement_reconciliation.py --poll --write`): resolves the
846-row live probability ledger against the public market endpoint,
append-only settlements with per-row Brier/logloss; unknown settlements stay
UNKNOWN — never faked.  As of 2026-07-04 all polled markets are honestly
UNSETTLED (they resolve months out).

**Cockpit copy rules (pinned by tests):** N<50 -> "UNCALIBRATED SCORE — not
a calibrated probability"; 50<=N<200 -> "MEASURED BUT NOT DECISION-GRADE
CALIBRATED"; the phrase "CALIBRATION GATE PASSED" is only reachable when the
backend gate (N>=200, Brier<=0.25, ECE<=0.10) actually passes.

## 11. Open-the-Gate additions (2026-07-04, same day)

**Strict stop-confirmation contract.** A stop only becomes active when the
template entry carries ALL of: `stop_loss_confirmed: true`,
`stop_loss_confirmed_at`, `operator_confirmation_id`,
`risk_acknowledgement: true`, `operator_confirmation_text` equal to the
EXACT string `I_CONFIRM_THESE_STOPS_ARE_MY_OPERATOR_RISK_LIMITS`, and — on
leveraged positions — `leverage_risk_acknowledged: true`.  Anything less is
rejected by `--apply-confirmed` and the risk gate stays BLOCKED.  Pending
confirmations are documented in `STOP_LOSS_CONFIRMATION_REQUIRED.md` +
`data/daily_payload/stop_loss_operator_confirmation_required.json`.
Workflow: `--write-template` -> edit/confirm -> `--validate-template` ->
`--apply-confirmed --dry-run` -> `--apply-confirmed --write` (archives the
prior holdings file to `data/daily_payload/archive/` first).

**Freshness is three-tier:** holdings age <=1 day FRESH, <=3 days DEGRADED,
>3 days BLOCKED (`freshness_state` on the gate; HEALTHY requires FRESH).

**Drawdown/stop-breach monitor** (`scripts/drawdown_stop_monitor.py`, in the
daily loop): distance-to-stop, breach detection, leveraged unrealized
return, portfolio drawdown fraction; CRITICAL at breach or <=1% distance or
<=-10% drawdown; WARNING at <=3% / <=-5%.  Positions without a usable
confirmed stop are UNMONITORABLE — surfaced, never skipped.

**Escalation:** a CRITICAL condition still firing after 24h escalates to
level 2, after 72h to level 3 (persistent-blocker alert for a non-HEALTHY
truth surface).  `OPERATOR_ACTION_CHECKLIST.md` is regenerated from the
truth surface every daily cycle.

**Proof commands:** `scripts/sheets_roundtrip_probe.py --fixture|--live-safe`
(round-trip hash + idempotency + schema-drift; DEGRADED without
credentials), `scripts/smoke_cockpit_truth.py` (real-app honesty smoke),
`scripts/evidence_calendar.py --next 14` (when N grows; projections never
touch real N).
