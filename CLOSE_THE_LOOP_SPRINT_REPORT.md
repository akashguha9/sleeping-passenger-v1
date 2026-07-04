# CLOSE THE LOOP — Sprint Report

**Date:** 2026-07-04
**Baseline:** `FORENSIC_AUDIT_SLEEPING_PASSENGER.md` (2026-07-03/04) — overall **4.96/10**, near-term ceiling 6.50, ultimate ceiling 8.01.
**Sprint mandate:** execute the audit's "Close the Loop" sprint — evidence, truth, and risk repointing — without faking a single number.

---

## 1. Headline results

| Metric | Before | After |
|---|---|---|
| Matured real forward outcomes (N) | **0** | **56** (2026-05-31 cohort, timestamp-locked, horizons closed 2026-06-05, matured 2026-07-04) |
| Calibration status | NO_REAL_OUTCOME_EVIDENCE (honest but empty) | **MEASURED_NOT_CALIBRATED**: Brier 0.2794, logloss 0.7522, ECE 0.3316 on real outcomes; `predictive_claim_allowed` remains **false** |
| Benchmark comparison | none anywhere in the live outcome path | per-row SPY alpha + Brier-vs-baselines report: mean realized −3.41% vs SPY −1.33% (alpha −2.08%); **verdict: NO DEMONSTRATED EDGE** (model loses to both the coin and base-rate predictors) |
| Risk engine position source | `moltbook/open_positions.json` (demoted phantom ledger; emitted EXIT_NOW on positions that don't exist) | `data/daily_payload/verified_current_holdings.json` via fail-closed `scripts/holdings_truth_gate.py`; moltbook is never a default source (regression-tested) |
| Scheduler failure semantics | BROKEN runs exited 0 (silent death; schtasks Last Result always 0) | BROKEN/BROKEN_UNSAFE/FAILED/unknown → **exit 1** + stderr `NBI SCHEDULER RUN FAILED`; DEGRADED_BUT_SAFE exits 0 by documented design |
| Daily loop closes outcomes | never (no maturation step; loop was ingest-only) | maturation runs every scheduled cycle; `outcomes_closed` / `n_real_forward` / `maturation_ok` in the health record; crashed maturation ⇒ BROKEN |
| Operational health | fragmented, artifact-served, no staleness checks; "HEALTHY 10/10" possible with N=0 and stale everything | `GET /truth-surface` + `python -m scripts.truth_surface_report`: HEALTHY/DEGRADED/BLOCKED/BROKEN with per-axis evidence; N=0, missing stops, stale holdings/artifacts, zero-persist sources each cap the state |
| /nbi page | orphan route (no nav link); ageless health panel | in sidebar ("Narrative Branches"); cockpit + cards render artifact age with amber >26h / red >50h; sub-50-N pages say "uncalibrated model output" |
| Sources persisting nothing | `ok_filtered` = "Source healthy" for 11 silent days | `ZERO_PERSISTED_DEGRADED` (warning) after 7 silent days, `last_persisted_at`/`persist_age_days` visible in `/source-health/summary` |
| Test pollution of served artifacts | tests wrote fixture cards (MACRO1) into the exact files `GET /nbi/cards` serves (live for ~14h on 2026-07-03/04) | conftest redirects `NBI_ARTIFACT_DIR` + `HOLDINGS_TRUTH_PATH` per-test; exporters honor the redirect only for canonical runtime/ paths |
| Branch stranding | two flagship sprints stranded on unmerged branches, undetected for a month | 25 modules (~7,900 lines) + 22 test files ported to the canonical branch; `tests/test_branch_stranding_guard.py` fails the suite if entry points / table readers / scheduler wiring / doc claims go missing again (it already caught one real case during the sprint) |

## 2. What was implemented

### P0 — Outcome maturation on the canonical branch (audit SP-001/002 core)
Ported from `chore/real-forward-outcome-maturation` (a 468-file divergent
branch — merged surgically, not wholesale): `probability_snapshot`,
`decision_probability_snapshot`, `forward_snapshot_contract`,
`outcome_labeling_flow`, `calibration_report`, `snapshot_calibration_bridge`,
`real_calibration_evidence`, `real_price_outcome_evidence`,
`attach_due_outcomes`, `forward_outcome_maturity_scanner`,
`run_daily_outcome_maturation`, `real_evidence_bundle`,
`forward_eligibility_diagnostics`, `real_evidence_canary`,
`real_signal_score_vector`, `score_real_signal_events`,
`source_freshness_contract`, `ensure_ohlcv_for_scored_tickers`,
`ticker_resolution`, `refresh_real_evidence`, plus the snapshot-producer
stack (`run_daily_live_advisory_decisions`, `live_decision_path`,
`admission_gates`, `capital_rotation_guard`, `moltbook_adjustment`,
`portfolio_correlation_guard`, `leverage_policy`) and 22 test files
(230 ported tests pass). All registered in `core_module_boundary` /
`private_scope_guard`.

**Retro-maturation of the 56 locked predictions** (real data, no fabrication):
1. DB backed up (`backup_local_state/pre_close_the_loop_sprint/`).
2. 92 real June OHLCV bars appended for AAPL/MSFT/NVDA/TSLA via the ported
   `ensure_ohlcv_for_scored_tickers --write` (SPY/QQQ/GLD/TLT bars already
   in the canonical DB); zero fetch failures.
3. `run_daily_outcome_maturation --write --benchmark-symbol SPY` attached
   all 56 outcomes (`outcome_source=real_ohlcv_signal_events`,
   `outcome_kind=real_forward`).
4. **Immutability verified**: SHA-256 fingerprint over all locked prediction
   fields (snapshot_id, timestamp, ticker, probability, entry price,
   horizon close, target threshold) byte-identical before/after the write.
5. Outcome reality: 12/56 hit (base rate 0.214) — SPY and TLT rose over the
   5-day window; AAPL/NVDA/MSFT/TSLA/GLD/QQQ missed. The model's ~0.55-flat
   probabilities score Brier 0.2794: worse than both reference predictors.
   **This unflattering number is the sprint's proudest artifact — it is the
   system's first real measurement.**

New: `scripts/benchmark_outcome_report.py` — post-hoc, read-only,
clearly-labeled analytics (per-row realized return, SPY same-window return,
alpha, Brier vs coin/base-rate, `honest_verdict`); it can never re-label
outcomes or unlock claims (tested).

### P0 — Loud failures (audit SP: scheduler exit-code bug, orphan route, ageless health)
- `scripts/nbi_scheduler.py`: explicit exit-code mapping (see table in
  `docs/OPERATIONAL_TRUTH.md` §5) + maturation step in `run_once()` folded
  into `SchedulerHealth`.
- `scripts/api_server.py /nbi/cockpit`: server-computed
  `artifact_age_minutes` + `artifact_stale`.
- Frontend: `/nbi` added to sidebar; `FreshnessBadge` (amber >26h, red >50h,
  "AGE UNKNOWN — treat as stale"); red `CARDS ARTIFACT STALE` banner;
  uncalibrated-scores note when closed real cases < 50.

### P0 — Risk engine repointed at reality (audit SP-001/005/009/010/011/012)
- New `scripts/holdings_truth_gate.py`: the only sanctioned position feed.
  Freshness fail-closed (>3 days ⇒ `HOLDINGS_TRUTH_STALE`, zero monitorable
  positions), stop discipline fail-closed (`BLOCKED_MISSING_STOP`, leveraged
  ⇒ `BLOCKED_MISSING_STOP_LEVERAGED` + CRITICAL), price honesty (only
  ingested bars with `price_as_of`; stale/missing price blocks), leverage
  explicit on every row, env-overridable for tests.
- `scripts/action_engine.py`: default source is the gate; explicit fixture
  paths are stamped `EXPLICIT_PATH`; blocked positions surface as
  `position_risk_alerts` with operator actions; report carries
  `position_source` provenance. Two legacy tests that had encoded the
  phantom behavior (EXIT_NOW on nonexistent UNG) were corrected to pin the
  fail-closed truth.
- `scripts/signal_refinery.py` thermal battery: effective open-position
  count = max(pipeline count, canonical count) — the real 10-vs-6 breach can
  no longer hide; both counts reported.
- **Not faked:** stops for the operator's 10 real positions cannot be
  invented by an agent. The system now BLOCKS loudly (truth surface, action
  engine alerts, cockpit) until the operator records them.

### P1 — Silent data death killed (audit SP-016/017)
- `scripts/source_health_summary.py`: `ZERO_PERSISTED_DEGRADED` demotion
  axis (pure-function param; API supplies per-source `last_persisted_at`).
- `scripts/ingestion/market_data_loader.py`: default ticker universe =
  index ETFs + canonical holdings symbols (fail-soft).

### Eureka add-ons
- **2.1 Truth Surface Unification**: `scripts/truth_surface_report.py` +
  `GET /truth-surface` — every field the sprint spec required
  (`canonical_holding_count` … `overall_operational_state`), computed live,
  fail-closed to BROKEN on any computation error. 11 rule-pinning tests.
- **2.2 Confidence demotion**: truth surface emits
  `calibration_display_note` ("uncalibrated model score — do not read model
  probabilities as calibrated frequencies"); NBI page renders the
  uncalibrated note below 50 cases; CALIBRATED is unreachable below the
  repo gate (tested: N=199 with perfect Brier still refuses).
- **2.3 Branch-stranding guard**: `tests/test_branch_stranding_guard.py` —
  entry-point imports, table-reader presence, scheduler/action-engine
  wiring, and docs-claim-vs-code checks. During the sprint it caught
  `docs/REAL_FORWARD_DAILY_RUNBOOK.md` referencing a script absent from the
  branch (`refresh_real_evidence.py`) — which was then ported. The guard
  works.

### Docs truth-sync (audit segment L)
- `TESTING.md`: "~100 test files" → real counts; the false "no
  Vitest/Playwright installed" claim corrected with a dated note; lint
  blocker documented.
- `README.md`: route table 9 → all 16 routes (dated); new "Current state
  (last verified 2026-07-04)" section with the honest N/Brier/blocked-risk
  summary.
- `AUDIT_BRUTAL_MVP_ASSESSMENT.md` + `docs/FINAL_SCORECARD.md`: HISTORICAL
  banners (the dueling 4.8 vs 8.2 self-audits no longer masquerade as
  current truth).
- New `docs/OPERATIONAL_TRUTH.md`: canonical holdings source, truth-surface
  axes, what "probability" means today, when it may be called calibrated,
  maturation commands, scheduler exit semantics, real-money and
  investor-demo blockers, codename glossary.
- `docs/REAL_FORWARD_DAILY_RUNBOOK.md` ported.
- `frontend/package.json` lint script now prints the exact ESLint-CLI
  migration required and exits 1 (Next 16 removed `next lint`; eslint deps
  are not installed, so migration is documented rather than half-done).

## 3. What was NOT implemented (and why)

1. **Stops on the 10 real positions** — operator-only knowledge; the system
   now fails loudly (BLOCKED) instead of silently. This is the top operator
   action item.
2. **Holdings truth refresh** — same: only the operator can re-verify their
   real book. The gate demotes everything until `run_date` is ≤3 days old.
3. **Fresh-discovery live wiring (audit SP-006)** — deliberately out of
   sprint scope (audit sequenced it separately); `today_*` payloads remain
   static-fallback and fresh discovery still fail-closes honestly.
4. **Sheets sync overhaul (segment H)** — audit sequenced for Sprint 2; the
   loop has never run in production so it blocks nothing this sprint.
5. **Push alerting / lock files / venv-pinned task actions (segment I
   residue)** — exit codes + truth surface shrink the silent-death window;
   real notification remains open.
6. **ESLint CLI migration** — dependencies not installed; blocker documented
   in the lint script itself and TESTING.md rather than introducing an
   unvetted dependency change at sprint close.
7. **Anti-staleness wall-clock gate on `today_*` payloads (SP-019)** — the
   holdings member of that family is gated via `holdings_truth_gate`; the
   general payload gate goes with the fresh-discovery sprint.
8. **New forward-snapshot production scheduling** — the producer
   (`run_daily_live_advisory_decisions`) is ported and tested but not yet in
   the scheduled loop; N grows only via `refresh_real_evidence` manual runs
   until Sprint 2 wires it (listed as the top next-sprint item).

## 4. Files changed (summary)

- **Ported from branch (26 modules + 22 test files):** listed in §2-P0.
- **Modified:** `scripts/nbi_scheduler.py` (exit codes, maturation step,
  artifact redirect), `scripts/action_engine.py` (canonical source),
  `scripts/signal_refinery.py` (canonical capacity count),
  `scripts/source_health_summary.py` (zero-persist axis),
  `scripts/api_server.py` (truth-surface endpoint, cockpit age,
  last-persisted supply), `scripts/ingestion/market_data_loader.py`
  (holdings-driven tickers), `scripts/nbi_evidence_factory.py` +
  `scripts/nbi_live_ops_cockpit.py` (artifact redirect),
  `scripts/private_scope_guard.py` + `scripts/core_module_boundary.py`
  (registrations), `conftest.py` (holdings + artifact isolation),
  `frontend/src/components/layout/Sidebar.tsx`,
  `frontend/src/app/nbi/page.tsx`, `frontend/package.json`,
  `tests/test_action_engine.py` (phantom expectations corrected),
  `TESTING.md`, `README.md`, `AUDIT_BRUTAL_MVP_ASSESSMENT.md`,
  `docs/FINAL_SCORECARD.md`.
- **New:** `scripts/holdings_truth_gate.py`,
  `scripts/truth_surface_report.py`, `scripts/benchmark_outcome_report.py`,
  `docs/OPERATIONAL_TRUTH.md`, `docs/REAL_FORWARD_DAILY_RUNBOOK.md`,
  `tests/test_holdings_truth_gate.py`,
  `tests/test_action_engine_canonical_source.py`,
  `tests/test_truth_surface_report.py`,
  `tests/test_nbi_scheduler_exit_codes.py`,
  `tests/test_benchmark_outcome_report.py`,
  `tests/test_zero_persisted_health_axis.py`,
  `tests/test_branch_stranding_guard.py`,
  `frontend/src/app/__tests__/nbi.spec.tsx`.

## 5. Commands run (evidence)

| Command | Result |
|---|---|
| `python -m pytest tests -q` (pre-sprint baseline, 2026-07-03) | 7,567 passed / 3 skipped, 14m14s |
| `ensure_ohlcv_for_scored_tickers --symbols AAPL,MSFT,NVDA,TSLA --as-of 2026-06-09 --write` | 92 bars added, 0 failures |
| `run_daily_outcome_maturation` (dry-run) | 56 DUE_FORWARD, 0 pending, write_mode=false |
| `run_daily_outcome_maturation --write --benchmark-symbol SPY` | 56 outcomes attached; N 0→56; Brier 0.2794; predictive_claim_allowed=false |
| SHA-256 locked-field fingerprint before/after | identical (`15bb0fae…3503`) |
| `benchmark_outcome_report --write` | 56/56 benchmark-matched; alpha −2.08%; NO DEMONSTRATED EDGE |
| `python -m pytest tests -q` (post-sprint) | see §6 — full-suite result recorded at sprint close |
| `npm test` / `npm run build` (post-sprint) | see §6 |

## 6. Validation results (filled at sprint close)

- Backend full suite: **7,893 passed, 3 skipped, 0 failed** (16m04s; baseline 7,567 — net +326 tests).
- Targeted sprint tests (`-k "maturation or scheduler or holdings or risk or health or branch_stranding or calibration or benchmark"`): **586 passed, 0 failed** (1m42s).
- Frontend vitest: **36 files / 207 tests passed** (incl. new nbi.spec.tsx; one timing flake under full-parallel load, green on isolated rerun).
- `next build`: **16 routes compiled** (unchanged route set, /nbi now navigable).
- `npm run lint`: intentionally exits 1 with the documented migration
  blocker (Next 16 removed `next lint`; see TESTING.md).

## 7. Updated segmented scores (honest, evidence-anchored)

| Seg | Segment | W | Audit | Now | Δ | Why (evidence) |
|---|---|---|---|---|---|---|
| A | Product / Operator Value | 10% | 4.7 | 5.2 | +0.5 | /nbi navigable; truth surface; artifact ages; fixture pollution fixed. Fresh discovery still empty → capped |
| B | Signal Quality / Model Logic | 12% | 4.8 | 5.1 | +0.3 | model quality now *measured* on real outcomes (unflattering but real); scorer sprawl and placeholder semantics unchanged |
| C | Risk Engine / Portfolio Discipline | 12% | 3.8 | 5.4 | +1.6 | phantom ledger cut; canonical fail-closed gate; leverage explicit; capacity counts real book; BUT stops still unrecorded (BLOCKED) and no drawdown monitor |
| D | Calibration / Outcome Evidence | 12% | 3.6 | 5.6 | +2.0 | N=0→56 locked real outcomes; Brier/logloss/ECE + benchmark on real data; loop scheduled daily; immutability verified; guard against re-stranding. One cohort only; producer not yet scheduled |
| E | Data Integrity / Provider Reliability | 9% | 4.8 | 5.6 | +0.8 | zero-persist DEGRADED axis; holdings-driven prices; persist ages visible. News fallback chain + payload wall-clock gate still open |
| F | Backend Architecture | 8% | 4.7 | 4.8 | +0.1 | +26 modules cleanly registered, truth surface consolidates status logic; the flat-scripts architecture itself unchanged |
| G | Frontend / UX / Operator Workflow | 7% | 6.7 | 7.2 | +0.5 | orphan route fixed; staleness badges; uncalibrated copy; new spec file |
| H | Google Sheets / External Sync | 7% | 4.4 | 4.4 | 0 | untouched (sequenced Sprint 2) |
| I | Scheduler / Runtime / Automation | 6% | 4.4 | 5.8 | +1.4 | exit-code bug fixed+tested; maturation in daily loop; health includes closure axis; first scheduled run succeeded. No push alerting yet |
| J | Testing / CI / Regression Defense | 7% | 7.4 | 7.7 | +0.3 | ~300 real new tests; hermeticity hardened (holdings/artifact isolation); stranding guard. Coverage instrumentation still absent |
| K | Security / Secrets / Privacy | 5% | 7.8 | 7.8 | 0 | untouched |
| L | Documentation / Investor Readiness | 5% | 5.4 | 7.0 | +1.6 | TESTING/README truth-synced; HISTORICAL banners; OPERATIONAL_TRUTH.md + glossary; runbook ported |

```text
Overall_Current_Score = 0.10·5.2 + 0.12·5.1 + 0.12·5.4 + 0.12·5.6 + 0.09·5.6
                      + 0.08·4.8 + 0.07·7.2 + 0.07·4.4 + 0.06·5.8 + 0.07·7.7
                      + 0.05·7.8 + 0.05·7.0
                      = 0.520+0.612+0.648+0.672+0.504+0.384+0.504+0.308+0.348+0.539+0.390+0.350
                      = 5.78
```

- **New estimated current score: 5.78 / 10** (audit baseline 4.96; +0.82).
  The audit projected ~5.9 for this sprint; we land slightly under because
  fresh-discovery wiring and the sheets loop were explicitly out of scope,
  and because we refuse to score the risk engine higher while the real
  positions carry no stops. The classification band is unchanged
  ("functional MVP but fragile", 4.1–6.0) — now at its top edge instead of
  its middle.
- **New near-term ceiling: ~6.70** (was 6.50) — one excellent sprint
  (stops + producer scheduling + fresh discovery + alerting) now reaches
  C≈6.5, D≈6.3, I≈6.8 because the substrate they need exists.
- **New ultimate ceiling: ~8.11** (was 8.01) — the two structural caps the
  audit priced in (dead evidence loop, documented-vs-running divergence)
  are removed: D_ult 7.5→8.0, C_ult 7.5→7.8, L_ult 8.7→8.8. The remaining
  cap is architectural (flat 184k-LOC scripts/) and single-machine ops.

## 8. Remaining blockers

**To real-money readiness** (see `docs/OPERATIONAL_TRUTH.md` §7): calibration
gate unmet (N=56 <200, Brier 0.2794 >0.25 — currently NO demonstrated edge);
stops unrecorded (0/10) → risk BLOCKED; holdings truth stale + unconfirmed;
no drawdown monitor; no push alerting; <30 days unattended loop evidence.

**To investor-demo readiness:** small unflattering N (presentable as
honesty); no frontend-vs-real-backend integration test; sheets loop
unproven; older docs beyond the synced set may still contain stale claims.

## 9. Next Best Sprint recommendation

**"Feed the Loop":** (1) operator records stops + refreshes holdings (1
day, human) → risk engine unblocks on real positions; (2) schedule
`run_daily_live_advisory_decisions` into the daily loop so new forward
snapshots lock daily and N compounds past 56 toward the 200 gate; (3) wire
fresh discovery to the proven Yahoo canary so `today_*` payloads go
`is_live=true` (audit SP-006); (4) add one push-alert channel (Windows
toast or a red /truth-surface banner polled by the frontend shell) for
BROKEN/BLOCKED states; (5) Kalshi settlement poller for the 846-row live
probability ledger (audit SP-053) — a second, larger calibration corpus for
free. Projected: 5.78 → ~6.5.
