# Segment Role-Fit Scorecard

> Generated 2026-05-26T09:18:48+00:00 · advisory_status=`ADVISORY_ONLY` · execution_gate=`LOCKED` · broker_api_called=`False` · ai_execution_count=`0`.

> Two lenses, on purpose. **Absolute readiness** asks *'how close to production / private beta / public SaaS?'*. **Role-fit readiness** asks *'given this segment's role in this local-first MVP, is it performing that role at an elite level?'*. A refusal/safety segment that refuses perfectly is 10/10 even if it never scores a goal.

## Formulas

```
R_s        = 10 * Σ_i (w_i * p_i)   with Σ_i w_i = 1
E_s        = min(1, evidence_items_present / evidence_items_required)
R_adj_s    = R_s * (0.7 + 0.3 * E_s) * C_s
OverallAbsolute = Σ_s W_abs_s * A_s / Σ_s W_abs_s
OverallRoleFit  = Σ_s W_role_s * R_adj_s * T_s / Σ_s W_role_s * T_s   (NOT_TARGETED excluded)
```

**Calibration unlocked**: `False` (N_min=200).  When False, the *Scoring/model logic quality* segment cannot exceed its no-evidence ceiling of 5.8/10.

## Composite scores

| Lens | Score /10 |
|---|---:|
| Overall absolute readiness | 7.659 |
| Overall role-fit readiness | 8.588 |

**NOT_TARGETED (excluded from role-fit denominator):**
- Commercial SaaS readiness
- Public SaaS readiness

## Per-segment scorecard

| # | Segment | Role | T_s | A_s | R_s | C_s | E_s | R_adj_s | Dashboard |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Product clarity / customer understandability | Local-first advisory copilot pitch | 1.00 | 8.50 | 9.84 | 0.90 | 1.00 | 8.85 | 8.85 |
| 2 | Advisory-only safety integrity | Ball-winning defensive midfielder | 1.00 | 9.80 | 10.00 | 0.97 | 1.00 | 9.70 | 9.70 |
| 3 | Execution-lock integrity | Goal-line clearance defender | 1.00 | 9.70 | 10.00 | 0.97 | 1.00 | 9.70 | 9.70 |
| 4 | Backend architecture | Modular FastAPI advisory backend | 1.00 | 7.50 | 9.00 | 0.85 | 1.00 | 7.65 | 7.65 |
| 5 | Frontend architecture | Strict React/TS operator surface | 1.00 | 8.00 | 9.40 | 0.90 | 1.00 | 8.46 | 8.46 |
| 6 | Frontend UX truthfulness | Honest-state painter | 1.00 | 9.30 | 10.00 | 0.95 | 1.00 | 9.50 | 9.50 |
| 7 | Mock/fallback transparency | Truth-surface marker | 1.00 | 9.60 | 10.00 | 0.95 | 1.00 | 9.50 | 9.50 |
| 8 | Data-source realism | Realistic-but-bounded data layer | 1.00 | 7.50 | 9.00 | 0.85 | 1.00 | 7.65 | 7.65 |
| 9 | Live-source integration quality | Live-feed contract enforcer | 0.80 | 6.50 | 9.00 | 0.80 | 1.00 | 7.20 | 7.20 |
| 10 | Source-health observability | Freshness/degraded-state truth surface | 1.00 | 9.00 | 10.00 | 0.95 | 1.00 | 9.50 | 9.50 |
| 11 | Scoring/model logic quality | Predictive engine | 1.00 | 5.80 | 1.50 | 0.75 | 1.00 | 1.12 | 1.12 |
| 12 | Calibration gate honesty | False-confidence blocker | 1.00 | 9.70 | 10.00 | 0.97 | 1.00 | 9.70 | 9.70 |
| 13 | Calibration corpus evidence | Outcome-labelled evidence ledger | 1.00 | 4.50 | 10.00 | 0.90 | 1.00 | 9.00 | 9.00 |
| 14 | State-machine / archetype clarity | Regime-aware state machine | 1.00 | 7.00 | 9.00 | 0.85 | 1.00 | 7.65 | 7.65 |
| 15 | Signal explainability | Why-this-signal narrator | 1.00 | 7.50 | 9.00 | 0.85 | 1.00 | 7.65 | 7.65 |
| 16 | Portfolio/trade recommendation safety | Advisory recommendation guard | 1.00 | 9.00 | 10.00 | 0.92 | 1.00 | 9.20 | 9.20 |
| 17 | Risk / chaos / veto logic | Veto-and-recover layer | 1.00 | 7.80 | 9.00 | 0.85 | 1.00 | 7.65 | 7.65 |
| 18 | Testing depth | Truth-gate test ladder | 1.00 | 9.20 | 10.00 | 0.95 | 1.00 | 9.50 | 9.50 |
| 19 | Frontend tests | Component truth tests | 1.00 | 8.00 | 10.00 | 0.90 | 1.00 | 9.00 | 9.00 |
| 20 | Backend tests | Backend contract suite | 1.00 | 9.00 | 10.00 | 0.95 | 1.00 | 9.50 | 9.50 |
| 21 | Integration tests | End-to-end advisory loop test | 1.00 | 7.50 | 9.00 | 0.85 | 1.00 | 7.65 | 7.65 |
| 22 | Runtime hygiene | Artefact coherence enforcer | 1.00 | 8.70 | 10.00 | 0.92 | 1.00 | 9.20 | 9.20 |
| 23 | Logging / auditability | Audit-trail keeper | 1.00 | 8.50 | 10.00 | 0.90 | 1.00 | 9.00 | 9.00 |
| 24 | Persistence model / database truth | Canonical-store discipline | 1.00 | 8.50 | 10.00 | 0.92 | 1.00 | 9.20 | 9.20 |
| 25 | JSONL vs SQLite truth discipline | Canonical/audit boundary keeper | 1.00 | 9.50 | 10.00 | 0.95 | 1.00 | 9.50 | 9.50 |
| 26 | Deployment readiness | Local-first deploy | 0.50 | 6.00 | 9.50 | 0.80 | 1.00 | 7.60 | 7.60 |
| 27 | Local developer experience | First-day operator concierge | 1.00 | 8.50 | 10.00 | 0.90 | 1.00 | 9.00 | 9.00 |
| 28 | Security posture | Local-first security baseline | 1.00 | 7.30 | 10.00 | 0.85 | 1.00 | 8.50 | 8.50 |
| 29 | Secret-handling posture | Secret-redaction enforcer | 1.00 | 9.30 | 10.00 | 0.95 | 1.00 | 9.50 | 9.50 |
| 30 | Documentation quality | Operator-first doc set | 1.00 | 9.00 | 10.00 | 0.92 | 1.00 | 9.20 | 9.20 |
| 31 | Operator workflow usability | 13-step workflow conductor | 1.00 | 8.20 | 10.00 | 0.90 | 1.00 | 9.00 | 9.00 |
| 32 | Commercial SaaS readiness | Out-of-scope striker | 0.00 | 1.50 | 10.00 | 0.95 | 1.00 | 9.50 | NOT_TARGETED |
| 33 | Feedback-loop / Moltbook readiness | Closed-loop learning ledger | 1.00 | 8.00 | 10.00 | 0.88 | 1.00 | 8.80 | 8.80 |
| 34 | Maintainability | Future-operator readability | 1.00 | 7.50 | 9.50 | 0.85 | 1.00 | 8.07 | 8.07 |
| 35 | Performance / scalability | Local-machine performance | 0.50 | 5.00 | 9.00 | 0.75 | 1.00 | 6.75 | 6.75 |
| 36 | Failure-mode handling | Graceful-degradation conductor | 1.00 | 8.00 | 10.00 | 0.90 | 1.00 | 9.00 | 9.00 |
| 37 | Real-user readiness | Single-operator readiness | 0.60 | 6.50 | 10.00 | 0.85 | 1.00 | 8.50 | 8.50 |
| 38 | Overall MVP readiness | Local-first showcase composite | 1.00 | 8.20 | 10.00 | 0.92 | 1.00 | 9.20 | 9.20 |
| 39 | Local-first showcase | Local-first showcase | 1.00 | 8.90 | 10.00 | 0.93 | 1.00 | 9.30 | 9.30 |
| 40 | Private beta readiness | Design-stage candidate | 0.50 | 5.00 | 10.00 | 0.85 | 1.00 | 8.50 | 8.50 |
| 41 | Public SaaS readiness | Out-of-scope striker | 0.00 | 1.50 | 10.00 | 0.95 | 1.00 | 9.50 | NOT_TARGETED |

## Per-segment criteria

### Product clarity / customer understandability — *Local-first advisory copilot pitch*

> Make the local-first, advisory-only nature obvious to anyone reading the README or first-run UI.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.50  (ceiling: Recorded demo + screenshots still missing.)
- role_fit_score `R_s` = 9.84
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 8.85**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| README states ADVISORY_ONLY and local-first up front | 0.34 | 1.00 | `README.md`, `docs/ADVISORY_DISCLOSURE.md` | — |
| UI banner / badges reinforce no-execution posture | 0.33 | 1.00 | `frontend/src/components/NoExecutionBanner.tsx`, `frontend/src/components/AdvisoryOnlyBadge.tsx` | — |
| Final scorecard documents lens differences honestly | 0.33 | 0.95 | `docs/FINAL_SCORECARD.md` | — |

**Blockers**:
- No recorded 5-minute demo or screenshot pack.

**Next action**: Record a 5-minute demo and pin it from README.

### Advisory-only safety integrity — *Ball-winning defensive midfielder*

> Prevent execution drift: no broker SDKs, no order routes, advisory stamps everywhere, AI never granted execution.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.80  (ceiling: Capped at 9.8 until an external red-team confirms no drift.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.97, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.70**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Advisory stamp property test passes on safe GETs | 0.30 | 1.00 | `tests/test_advisory_stamp_property.py` | — |
| Forbidden execution-route test pins zero broker routes | 0.25 | 1.00 | `tests/test_api_server.py` | — |
| advisory_contract.py is the single stamp source | 0.25 | 1.00 | `scripts/advisory_contract.py` | — |
| ai_execution_count=0 and broker_api_called=false stamps | 0.20 | 1.00 | `runtime/release/release_gate_proof.json` | — |

**Next action**: Schedule an external red-team review of advisory routes.

### Execution-lock integrity — *Goal-line clearance defender*

> Keep execution_gate=LOCKED everywhere; no live trading path.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.70  (ceiling: Capped pending a documented annual rotation drill of the lock.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.97, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.70**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| execution_gate=LOCKED in advisory contract module | 0.40 | 1.00 | `scripts/advisory_contract.py` | — |
| Release gate proof shows LOCKED stamps | 0.30 | 1.00 | `runtime/release/release_gate_proof.json` | — |
| No broker SDK import in repo (negative-evidence test) | 0.30 | 1.00 | `tests/test_api_server.py` | — |

**Next action**: Run an annual lock-rotation drill and document it.

### Backend architecture — *Modular FastAPI advisory backend*

> Routes/scripts cleanly separated; SQLite canonical; routers modularised; no business logic in route handlers.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.50  (ceiling: Script pile still large; no Postgres adapter.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.65**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| api_server.py composes modular routers | 0.35 | 0.90 | `scripts/api_server.py`, `scripts/api/routers` | — |
| Architecture boundaries doc exists and is current | 0.30 | 0.90 | `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE_BOUNDARIES.md` | — |
| Architecture fitness checker enforces shape | 0.35 | 0.90 | `scripts/architecture_fitness.py` | — |

**Blockers**:
- No Postgres adapter; script pile not yet collapsed.

**Next action**: Land Postgres adapter behind a feature flag.

### Frontend architecture — *Strict React/TS operator surface*

> Strict TypeScript; small, composable components; no any/ts-ignore.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.00  (ceiling: No Storybook / visual regression yet.)
- role_fit_score `R_s` = 9.40
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 8.46**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| frontend npx tsc --noEmit passes on strict | 0.40 | 1.00 | `frontend/tsconfig.json` | — |
| Small, named components in src/components | 0.30 | 0.90 | `frontend/src/components` | — |
| Component unit tests exist alongside components | 0.30 | 0.90 | `frontend/src/components/__tests__` | — |

**Blockers**:
- No visual regression coverage.

**Next action**: Add Storybook or Playwright visual snapshots for top panels.

### Frontend UX truthfulness — *Honest-state painter*

> Never claim live/fresh when source is mock, stale, or degraded.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.30  (ceiling: No full e2e suite asserting truth markers under load.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| TopTruthBar renders mock/fallback when source is mock | 0.35 | 1.00 | `frontend/src/components/TopTruthBar.tsx`, `frontend/src/components/__tests__/TopTruthBar.spec.tsx` | — |
| SourceConfigurationSnapshot surfaces degraded counts | 0.35 | 1.00 | `frontend/src/components/SourceConfigurationSnapshot.tsx`, `frontend/src/components/__tests__/SourceConfigurationSnapshot.spec.tsx` | — |
| AdvisoryEmptyState communicates absence, not synthetic data | 0.30 | 1.00 | `frontend/src/components/AdvisoryEmptyState.tsx`, `frontend/src/components/__tests__/AdvisoryEmptyState.spec.tsx` | — |

**Blockers**:
- No e2e suite asserts truth markers under live load.

**Next action**: Add a Playwright e2e covering mock + degraded toggles.

### Mock/fallback transparency — *Truth-surface marker*

> Mock or fallback data can never be mistaken for live truth: global mock chip, panel-level fallback labels, source-snapshot unavailable copy, no mock contamination in canonical store.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.60  (ceiling: Capped at 9.6 until row-level mock chip lands on every signal card.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Global mock chip via TopTruthBar | 0.25 | 1.00 | `frontend/src/components/TopTruthBar.tsx`, `frontend/src/components/__tests__/TopTruthBar.spec.tsx` | — |
| Panel-level fallback labels in SourceHealthPanel | 0.25 | 1.00 | `frontend/src/components/SourceHealthPanel.tsx` | — |
| Snapshot 'unavailable' copy when backend down | 0.25 | 1.00 | `frontend/src/components/SourceConfigurationSnapshot.tsx` | — |
| No mock contamination in canonical SQLite | 0.25 | 1.00 | `docs/CALIBRATION_CORPUS.md` | — |

**Blockers**:
- Row-level mock chip on every signal card pending.

**Next action**: Add a row-level mock chip to SignalCard.

### Data-source realism — *Realistic-but-bounded data layer*

> Where live, we say live; where mock, we say mock; never blur.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.50  (ceiling: Several sources still rely on bounded mocks.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.65**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Source registry distinguishes live vs mock | 0.50 | 0.90 | `docs/DATA_SOURCE_LICENSE_REGISTER.md` | — |
| Kalshi operator truth panel reflects real watchdog state | 0.50 | 0.90 | `frontend/src/components/KalshiOperatorTruthPanel.tsx`, `runtime/release/kalshi_watchdog_summary.json` | — |

**Blockers**:
- Several sources rely on bounded mocks.

**Next action**: Promote one bounded-mock source to a live adapter.

### Live-source integration quality — *Live-feed contract enforcer*

> When a source is wired live, contract tests / canaries gate it; no silent stale or partial reads pass as truth.

- target_relevance `T_s` = 0.80
- absolute_score `A_s` = 6.50  (ceiling: Most sources remain bounded mocks; canary live-only.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.80, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.20**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Hosted canary workflow asserts live contract | 0.50 | 0.90 | `docs/HOSTED_CANARY.md` | — |
| Live provider evidence file present and stamped | 0.50 | 0.90 | `runtime/release/live_provider_evidence.json` | — |

**Blockers**:
- Only Kalshi has the full live-canary contract today.

**Next action**: Extend the live canary to one additional provider.

### Source-health observability — *Freshness/degraded-state truth surface*

> Freshness, last_success_at, degraded, never_run all visible without an operator having to read logs.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.00  (ceiling: No external alerting wired (Slack/email).)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| SourceHealthPanel renders per-source freshness state | 0.30 | 1.00 | `frontend/src/components/SourceHealthPanel.tsx` | — |
| Source-config snapshot counts fresh/stale/degraded | 0.30 | 1.00 | `frontend/src/components/SourceConfigurationSnapshot.tsx` | — |
| Watchdog status panel + tests cover degraded states | 0.20 | 1.00 | `frontend/src/components/WatchdogStatusPanel.tsx`, `frontend/src/components/__tests__/WatchdogStatusPanel.spec.tsx` | — |
| Kalshi source-health JSON written under runtime/release | 0.20 | 1.00 | `runtime/release/kalshi_source_health.json` | — |

**Blockers**:
- No external alerting (Slack/email) wired.

**Next action**: Wire one external alert sink for degraded states.

### Scoring/model logic quality — *Predictive engine*

> Real predictive validity: N_real >= 200, Brier ≤ 0.25, ECE ≤ 0.10, MCE ≤ 0.25, reliability diagram generated.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 5.80  (ceiling: Hard cap at 5.8 until N_real ≥ 200 with usable model_probability.)
- role_fit_score `R_s` = 1.50
- confidence `C_s` = 0.75, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 1.12**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| N_real ≥ 200 with usable model_probability | 0.40 | 0.00 | `runtime/release/calibration_report.json` | N_real=0 with usable p — no predictive claim allowed. |
| Brier / ECE / MCE measured and within thresholds | 0.30 | 0.00 | `scripts/calibration_report.py` | — |
| Score axes EMS/EQS/DS/LS/EFS/APS documented | 0.15 | 1.00 | `docs/CALIBRATION_CORPUS.md` | — |
| Reliability diagram artefact generated | 0.15 | 0.00 | `runtime/release/calibration_report.json` | — |

**Blockers**:
- N_real=0 with usable model_probability — predictive validity not yet earnable.

**Next action**: Begin labelling outcomes against stored model_probability snapshots.

### Calibration gate honesty — *False-confidence blocker*

> Refuse to claim predictive validity until thresholds pass; report N_real, N_min, BS, ECE, MCE, and predictive_claim_allowed honestly.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.70  (ceiling: External calibration audit not yet performed.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.97, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.70**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| N_real and N_min explicit in calibration_report.json | 0.25 | 1.00 | `runtime/release/calibration_report.json` | — |
| predictive_claim_allowed=false when N_real < N_min | 0.25 | 1.00 | `scripts/calibration_report.py`, `tests/test_calibration_report.py` | — |
| Brier / ECE / MCE formulas covered by unit tests | 0.25 | 1.00 | `tests/test_calibration_report.py` | — |
| Calibration corpus excludes fixture/mock from N_real | 0.25 | 1.00 | `tests/test_calibration_corpus.py`, `docs/CALIBRATION_CORPUS.md` | — |

**Next action**: Commission an external calibration audit when N_real ≥ 200.

### Calibration corpus evidence — *Outcome-labelled evidence ledger*

> Curate a corpus of (model_probability, outcome) pairs drawn from canonical SQLite, fixture/mock-excluded.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 4.50  (ceiling: N_real with usable model_probability is currently 0.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.00**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Corpus path published with provenance | 0.40 | 1.00 | `runtime/release/calibration_corpus.json` | — |
| Corpus curator script enforces fixture/mock exclusion | 0.30 | 1.00 | `scripts/calibration_report.py`, `tests/test_calibration_corpus.py` | — |
| Records carry advisory/execution stamps | 0.30 | 1.00 | `runtime/release/calibration_corpus.json` | — |

**Blockers**:
- No usable model_probability snapshots in corpus yet.

**Next action**: Persist model_probability with every signal advisory.

### State-machine / archetype clarity — *Regime-aware state machine*

> Bull / non-bull / collapse / archetype transitions are explicit and audited.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.00  (ceiling: Transitions audited but evolving.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.65**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Archetype profile + registry modules and tests | 0.50 | 0.90 | `scripts/archetype_profile.py`, `scripts/archetype_registry.py`, `tests/test_archetype_profile.py` | — |
| Bull state report exists and is stamped | 0.50 | 0.90 | `runtime/bull_state_report.json` | — |

**Blockers**:
- Some archetypes lack reliability evidence.

**Next action**: Tie each archetype to a Brier-style outcome stat.

### Signal explainability — *Why-this-signal narrator*

> Every advisory signal explains the axes that drove it.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.50  (ceiling: Narratives are static; no per-signal LM rationale.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.65**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| SignalScorePanel exposes per-axis scores in UI | 0.50 | 0.90 | `frontend/src/components/SignalScorePanel.tsx` | — |
| Why-today summary written under runtime/release | 0.50 | 0.90 | `runtime/release/why_today_summary.json` | — |

**Blockers**:
- No per-signal natural-language rationale yet.

**Next action**: Add an explainability section to SignalCard.

### Portfolio/trade recommendation safety — *Advisory recommendation guard*

> Recommendations never imply execution; manual-log workflow is the only mutation path.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.00  (ceiling: No external review of recommendation surface.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.92, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.20**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Manual trade log form is the only mutation entrypoint | 0.50 | 1.00 | `frontend/src/components/ManualTradeLogForm.tsx`, `frontend/src/components/__tests__/ManualTradeLogForm.aiModel.spec.tsx` | — |
| Portfolio truth summary written and stamped | 0.50 | 1.00 | `runtime/release/portfolio_truth_summary.json` | — |

**Next action**: Schedule a UX review of advisory recommendation copy.

### Risk / chaos / veto logic — *Veto-and-recover layer*

> Every fragile branch can be vetoed safely; chaos paths fall back to advisory degraded states.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.80  (ceiling: No fault-injection harness yet.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.65**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Board-control safety layer present and tested | 0.50 | 0.90 | `scripts/board_control_safety_layer.py`, `tests/test_board_control_safety_layer.py` | — |
| Failure-mode handling documented | 0.50 | 0.90 | `docs/E2E_TEST_PLAN.md` | — |

**Blockers**:
- No automated fault-injection harness.

**Next action**: Add a chaos-style test harness for the refresh loop.

### Testing depth — *Truth-gate test ladder*

> Property tests + contract tests + runtime artefact coherence.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.20  (ceiling: No mutation testing yet.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Advisory stamp property test covers ≥90% safe GETs | 0.25 | 1.00 | `tests/test_advisory_stamp_property.py` | — |
| Runtime artefact coherence strict suite passes | 0.25 | 1.00 | `tests/test_runtime_artifact_coherence_strict.py` | — |
| Calibration math is unit-tested | 0.25 | 1.00 | `tests/test_calibration_report.py` | — |
| Credential hygiene test present and green | 0.25 | 1.00 | `tests/test_credential_hygiene.py` | — |

**Blockers**:
- No mutation testing.

**Next action**: Add a small mutmut sweep for the safety modules.

### Frontend tests — *Component truth tests*

> Component-level spec coverage of the top truth-surface panels.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.00  (ceiling: No CI integration of frontend tests.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.00**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Top-truth panels have component specs | 0.50 | 1.00 | `frontend/src/components/__tests__/TopTruthBar.spec.tsx`, `frontend/src/components/__tests__/SourceConfigurationSnapshot.spec.tsx` | — |
| Watchdog + reconciliation panels have specs | 0.50 | 1.00 | `frontend/src/components/__tests__/WatchdogStatusPanel.spec.tsx`, `frontend/src/components/__tests__/ReconciliationCard.currency.spec.tsx` | — |

**Blockers**:
- Frontend tests not yet wired into CI.

**Next action**: Wire vitest into CI on the frontend workspace.

### Backend tests — *Backend contract suite*

> Stamps, routes, calibration, persistence, watchdog covered.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.00  (ceiling: No long-running soak tests.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| api_server tests cover safe + forbidden routes | 0.50 | 1.00 | `tests/test_api_server.py` | — |
| Advisory contract test pins stamp invariants | 0.50 | 1.00 | `tests/test_advisory_contract.py` | — |

**Blockers**:
- No soak test.

**Next action**: Add a 10-minute soak test for the refresh orchestrator.

### Integration tests — *End-to-end advisory loop test*

> Spanning fetch → score → moltbook → refresh, advisory-only.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.50  (ceiling: No Playwright e2e yet.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.65**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Cross-module integration tests exist | 0.50 | 0.90 | `tests/test_ai_schema_integration.py` | — |
| Real-API canary workflow is gated and stamped | 0.50 | 0.90 | `tests/test_real_api_canary_workflow.py` | — |

**Blockers**:
- No Playwright workflow e2e.

**Next action**: Add a 13-step Playwright e2e once a stable demo dataset exists.

### Runtime hygiene — *Artefact coherence enforcer*

> All runtime/* JSON artefacts are coherent, stamped, and honest about provenance.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.70  (ceiling: No JSON-schema validation per artefact.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.92, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.20**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Runtime artefact coherence strict suite | 0.50 | 1.00 | `tests/test_runtime_artifact_coherence_strict.py` | — |
| Release-gate proof present and stamped | 0.50 | 1.00 | `runtime/release/release_gate_proof.json` | — |

**Blockers**:
- No per-artefact JSON schema validation.

**Next action**: Generate JSON schemas for top 5 runtime artefacts.

### Logging / auditability — *Audit-trail keeper*

> JSONL audit mirror for every canonical SQLite mutation.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.50  (ceiling: No external SIEM sink wired.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.00**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| JSONL is audit-only, SQLite canonical | 0.50 | 1.00 | `scripts/advisory_contract.py` | — |
| Moltbook feedback JSONL written audit-only | 0.50 | 1.00 | `runtime/moltbook_feedback_cases.jsonl` | — |

**Blockers**:
- No external SIEM.

**Next action**: Document a SIEM sink option for future deployments.

### Persistence model / database truth — *Canonical-store discipline*

> SQLite canonical, demo rows quarantined, holdings truth centralised.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.50  (ceiling: Single-tenant SQLite; no Postgres parity yet.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.92, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.20**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Canonical SQLite present | 0.40 | 1.00 | `runtime/mvp_local.db` | — |
| Persistence integrity summary written | 0.30 | 1.00 | `runtime/release/persistence_integrity_summary.json` | — |
| Daily payload truth file present | 0.30 | 1.00 | `data/daily_payload` | — |

**Blockers**:
- No Postgres parity.

**Next action**: Ship a Postgres adapter behind a flag.

### JSONL vs SQLite truth discipline — *Canonical/audit boundary keeper*

> Never let JSONL be canonical; tests pin the invariant.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.50  (ceiling: Pinned by tests; cap pending external review.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| jsonl_is_canonical = False stamp everywhere | 0.50 | 1.00 | `scripts/advisory_contract.py` | — |
| Calibration corpus declares canonical='sqlite' | 0.50 | 1.00 | `runtime/release/calibration_corpus.json` | — |

**Next action**: Add an explicit test that scans for jsonl_is_canonical=True.

### Deployment readiness — *Local-first deploy*

> Local-first; hosted single-VPS plan documented but unvalidated.

- target_relevance `T_s` = 0.50
- absolute_score `A_s` = 6.00  (ceiling: Hosted deploy not yet validated.)
- role_fit_score `R_s` = 9.50
- confidence `C_s` = 0.80, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 7.60**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Local deployment checklist present | 0.50 | 1.00 | `docs/LOCAL_DEPLOYMENT_CHECKLIST.md` | — |
| Hosted deployment plan present | 0.50 | 0.90 | `docs/HOSTED_DEPLOYMENT_PLAN.md` | — |

**Blockers**:
- Hosted deploy never executed.

**Next action**: Run a one-shot hosted deploy on a throwaway VPS.

### Local developer experience — *First-day operator concierge*

> An operator can run, refresh, and read the scorecard locally in under an hour.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.50  (ceiling: No one-line bootstrap script yet.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.00**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Local deployment checklist + README present | 0.40 | 1.00 | `docs/LOCAL_DEPLOYMENT_CHECKLIST.md`, `README.md` | — |
| Scorecard generator runnable from CLI | 0.30 | 1.00 | `scripts/segment_role_scorecard.py` | — |
| Backup + restore docs present | 0.30 | 1.00 | `scripts/backup_db.py`, `scripts/backup_local_state.py` | — |

**Blockers**:
- No single-command bootstrap.

**Next action**: Add a `make bootstrap` / pwsh `bootstrap.ps1`.

### Security posture — *Local-first security baseline*

> Local token auth, rate-limit, security headers, advisory-only.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.30  (ceiling: No hosted secrets manager; no third-party audit.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 8.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Local API token panel + tests | 0.50 | 1.00 | `frontend/src/components/LocalApiTokenPanel.tsx`, `frontend/src/components/__tests__/LocalApiTokenPanel.spec.tsx` | — |
| API token gate contract test passes | 0.50 | 1.00 | `tests/test_api_token_gate_contract.py` | — |

**Blockers**:
- No third-party audit; no hosted secrets manager.

**Next action**: Schedule a lightweight security review.

### Secret-handling posture — *Secret-redaction enforcer*

> Secrets never serialised, never printed; redaction tests pin it.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.30  (ceiling: No external red-team on secrets paths.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Credential hygiene test passes | 0.50 | 1.00 | `tests/test_credential_hygiene.py` | — |
| Credential hygiene report written and stamped | 0.50 | 1.00 | `runtime/release/credential_hygiene_report.json` | — |

**Blockers**:
- No external red-team.

**Next action**: Add a secrets-pattern grep to CI.

### Documentation quality — *Operator-first doc set*

> Every contract has a doc, every doc cites the test that pins it.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 9.00  (ceiling: Some docs duplicate; need consolidation.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.92, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.20**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Architecture + boundaries docs present | 0.25 | 1.00 | `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE_BOUNDARIES.md` | — |
| Advisory disclosure + safety model docs present | 0.25 | 1.00 | `docs/ADVISORY_DISCLOSURE.md`, `docs/ADVISORY_ONLY_SAFETY_MODEL.md` | — |
| Calibration corpus + hosted canary docs present | 0.25 | 1.00 | `docs/CALIBRATION_CORPUS.md`, `docs/HOSTED_CANARY.md` | — |
| Final + role-fit scorecard docs both reachable | 0.25 | 1.00 | `docs/FINAL_SCORECARD.md`, `docs/scorecards/ROLE_FIT_SCORING_MODEL.md` | — |

**Blockers**:
- Some duplication across older docs.

**Next action**: Prune duplicate sections from the legacy docs.

### Operator workflow usability — *13-step workflow conductor*

> The first-day operator can complete the canonical workflow without reading source.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.20  (ceiling: No recorded walk-through.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.00**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Demo case studies + rehearsal notes present | 0.50 | 1.00 | `docs/DEMO_CASE_STUDIES.md`, `docs/DEMO_REHEARSAL_NOTES.md` | — |
| E2E test plan documents the workflow | 0.50 | 1.00 | `docs/E2E_TEST_PLAN.md` | — |

**Blockers**:
- No recorded walk-through.

**Next action**: Record a 5-minute walkthrough video.

### Commercial SaaS readiness — *Out-of-scope striker*

> Not the role this MVP plays this year; flagged NOT_TARGETED.

- target_relevance `T_s` = 0.00
- absolute_score `A_s` = 1.50  (ceiling: Hard capped at 1.5 — multi-tenant auth, hosted DB, billing all absent.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| NOT_TARGETED documented in FINAL_SCORECARD | 1.00 | 1.00 | `docs/FINAL_SCORECARD.md` | — |

**Blockers**:
- Out of scope this year.

**Next action**: Revisit only after local-first showcase ships.

### Feedback-loop / Moltbook readiness — *Closed-loop learning ledger*

> Moltbook captures advisory outcomes for later calibration.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.00  (ceiling: No labelled outcome corpus yet.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.88, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 8.80**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Moltbook entry card + feedback ledger present | 0.50 | 1.00 | `frontend/src/components/MoltbookEntryCard.tsx`, `runtime/moltbook_feedback_summary.json` | — |
| Feedback cases JSONL written audit-only | 0.50 | 1.00 | `runtime/moltbook_feedback_cases.jsonl` | — |

**Blockers**:
- No outcome-labelled corpus yet.

**Next action**: Begin labelling moltbook outcomes against signal probability.

### Maintainability — *Future-operator readability*

> Tests + docs + advisory contract make changes safe to land.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 7.50  (ceiling: Script pile still large.)
- role_fit_score `R_s` = 9.50
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 8.07**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Architecture fitness checker pins boundaries | 0.50 | 0.90 | `scripts/architecture_fitness.py` | — |
| Advisory contract module is the single safety source | 0.50 | 1.00 | `scripts/advisory_contract.py` | — |

**Blockers**:
- Script directory not yet collapsed.

**Next action**: Group scripts into named subpackages.

### Performance / scalability — *Local-machine performance*

> Acceptable latency for a single-operator local workflow.

- target_relevance `T_s` = 0.50
- absolute_score `A_s` = 5.00  (ceiling: No concurrency or scaling work.)
- role_fit_score `R_s` = 9.00
- confidence `C_s` = 0.75, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 6.75**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Cockpit hot-path indexes applied | 1.00 | 0.90 | `scripts/apply_cockpit_hot_path_indexes.py` | — |

**Blockers**:
- No load test.

**Next action**: Add a 5-minute Locust scenario for the API.

### Failure-mode handling — *Graceful-degradation conductor*

> When a source fails, the UI degrades to advisory empty/stale states truthfully rather than fabricating data.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.00  (ceiling: No chaos harness.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.90, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.00**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| AdvisoryEmptyState handles absent data truthfully | 0.40 | 1.00 | `frontend/src/components/AdvisoryEmptyState.tsx`, `frontend/src/components/__tests__/AdvisoryEmptyState.spec.tsx` | — |
| Watchdog status panel surfaces failures | 0.30 | 1.00 | `frontend/src/components/WatchdogStatusPanel.tsx`, `frontend/src/components/__tests__/WatchdogStatusPanel.spec.tsx` | — |
| Anti-staleness rules tested | 0.30 | 1.00 | `tests/test_anti_staleness_rules.py` | — |

**Blockers**:
- No chaos harness.

**Next action**: Add a chaos test for the refresh orchestrator.

### Real-user readiness — *Single-operator readiness*

> Ready for the *local* operator role; not for multi-user beta.

- target_relevance `T_s` = 0.60
- absolute_score `A_s` = 6.50  (ceiling: No multi-user auth, no hosted DB.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 8.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Local API token gate works end-to-end | 0.50 | 1.00 | `tests/test_api_token_gate.py` | — |
| First-day operator surface documented | 0.50 | 1.00 | `docs/LOCAL_DEPLOYMENT_CHECKLIST.md` | — |

**Blockers**:
- No multi-user identity layer.

**Next action**: Design a multi-user identity layer behind a flag.

### Overall MVP readiness — *Local-first showcase composite*

> Composite — weighted average of the segments that matter to this MVP's role today.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.20  (ceiling: Composite ceiling tied to per-segment ceilings.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.92, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.20**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Per-segment composite agrees with FINAL_SCORECARD | 1.00 | 1.00 | `docs/FINAL_SCORECARD.md` | — |

**Blockers**:
- Bound by per-segment ceilings.

**Next action**: Unlock per-segment ceilings to lift the composite.

### Local-first showcase — *Local-first showcase*

> End-to-end local demo: safe, honest, observable, reproducible.

- target_relevance `T_s` = 1.00
- absolute_score `A_s` = 8.90  (ceiling: No recorded demo yet; e2e partial.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.93, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.30**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Local deployment checklist + README present | 0.30 | 1.00 | `docs/LOCAL_DEPLOYMENT_CHECKLIST.md`, `README.md` | — |
| Top-truth panels render honest state | 0.30 | 1.00 | `frontend/src/components/TopTruthBar.tsx`, `frontend/src/components/SourceConfigurationSnapshot.tsx` | — |
| Calibration honesty + advisory safety stamped | 0.40 | 1.00 | `runtime/release/calibration_report.json`, `runtime/release/release_gate_proof.json` | — |

**Blockers**:
- No recorded demo.

**Next action**: Record the demo and pin it from README.

### Private beta readiness — *Design-stage candidate*

> Design exists for auth + hosted DB; nothing shipped yet.

- target_relevance `T_s` = 0.50
- absolute_score `A_s` = 5.00  (ceiling: Hard capped at 5.0 without real multi-user auth + hosted DB.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.85, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 8.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| Hosted deployment plan documented | 0.50 | 1.00 | `docs/HOSTED_DEPLOYMENT_PLAN.md` | — |
| Legal/privacy compliance notes present | 0.50 | 1.00 | `docs/LEGAL_PRIVACY_NOTES.md`, `docs/LEGAL_PRIVACY_COMPLIANCE_MODEL.md` | — |

**Blockers**:
- No multi-user auth, no hosted DB.

**Next action**: Implement the documented auth design behind a flag.

### Public SaaS readiness — *Out-of-scope striker*

> Not a target role for this MVP this year; intentionally low.

- target_relevance `T_s` = 0.00
- absolute_score `A_s` = 1.50  (ceiling: Out of scope: no multi-tenant, no billing, no legal audit, no SaaS deploy.)
- role_fit_score `R_s` = 10.00
- confidence `C_s` = 0.95, evidence_completeness `E_s` = 1.00
- **confidence-adjusted role-fit `R_adj_s` = 9.50**

| Criterion | w_i | p_i | Evidence | Blocker |
|---|---:|---:|---|---|
| FINAL_SCORECARD declares public-prod 'do not pursue' | 1.00 | 1.00 | `docs/FINAL_SCORECARD.md` | — |

**Blockers**:
- Out of scope this year.

**Next action**: Revisit only after private-beta ships.

