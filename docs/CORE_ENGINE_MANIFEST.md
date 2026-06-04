# Core Engine Manifest

Honest, audit-driven inventory of the **production-core** engines — the small
set that can actually influence what the operator sees and decides. The repo
has ~400 scripts; most are experimental, diagnostic, or report generators.
This manifest names the ones that matter, states what each one *actually*
decides (not its codename mythology), and records whether it has behavioural
test coverage.

Hard invariant for every engine below: **none can execute a trade.** They are
advisory-only, `broker_api_called=False`, `ai_execution_count=0`,
`execution_gate=LOCKED`. The repo-wide guard
(`tests/test_no_execution_guard_repowide.py`) enforces this across all of
`scripts/` and `src/`.

Status legend: **production-core** (wired into the operator path) ·
**experimental** (present, not load-bearing) · **archived** (kept for history,
excluded from the pipeline).

---

## Production-core engines

### `scripts/leverage_governance.py` — Leverage doctrine
- **Purpose:** enforce the leverage doctrine on logged manual trades.
- **Decision function:** `validate_leverage_policy(ticker, leverage, jurisdiction, exchange, country)`. Resolves a jurisdiction group (INDIA / REST_OF_WORLD / UNKNOWN), applies the ceiling (India 4.0x, ROW 1.0x, unknown fails closed to 1.0x), returns `breach` + `severity` (NONE / WARNING / POLICY_BREACH).
- **Inputs:** ticker, numeric leverage, optional jurisdiction/exchange/country hints.
- **Outputs:** structured policy result; stamped onto the manual-trade row and surfaced in the API response.
- **Influences operator recommendation:** yes — flags breaches visibly.
- **Can execute trades:** no.
- **Behavioural tests:** `tests/test_leverage_governance.py`, `tests/test_leverage_governance_api.py`, `tests/test_core_engine_behavior.py`.

### `scripts/diablo_narrative_veto.py` — DIABLO hard advisory veto
- **Purpose:** veto dangerous risk *combinations* down to a safe non-trading action and force human review.
- **Decision function:** `evaluate_veto(...)`. Threshold combinations on 0–1 inputs (HIGH=0.70, LOW=0.30): weak-signal+strong-emotion+leverage; viral-narrative+no-fundamentals; old-news+high-conviction; high-heat+unclear-invalidation; high-crowding+low-liquidity → `DIABLO`; thin-polymarket+high-impact → `DIABLO_REVIEW`; else `CLEAR`.
- **Outputs:** veto state, firing combinations, recommended safe action (wait / reconcile / reduce / review Moltbook / no-new-risk).
- **Influences operator recommendation:** yes.
- **Can execute trades:** no (recommends only non-trading actions).
- **Behavioural tests:** `tests/test_diablo_narrative_veto.py`, `tests/test_core_engine_behavior.py` (fires on chaos; stays CLEAR on benign).

### `scripts/event_prior_detector.py` — Temporal clustering detector
- **Purpose:** detect windows of clustered observations in the chronology store (prior-event evidence).
- **Decision function:** `detect_prior_windows(conn, source, window_minutes, min_count, since, until)`. Maximal contiguous run within `window_minutes` containing `>= min_count` rows.
- **Inputs:** read-only chronology DB (`observations` table).
- **Outputs:** list of windows (start/end/count/source). Empty input → empty result; **never invents rows**; skips unparseable timestamps.
- **Influences operator recommendation:** yes (prior-event context).
- **Can execute trades:** no (read-only).
- **Behavioural tests:** `tests/test_event_prior_detector.py`, `tests/test_core_engine_behavior.py` (insufficient data → no window; threshold met → window; spread-out → no cluster).

### `scripts/calibration_recommendations.py` — Guarded feedback loop
- **Purpose:** turn reconciled outcomes + Moltbook into a threshold-shift recommendation, never auto-applied.
- **Decision function:** `build_recommendation(reconciliations, bucket_key=...)` → `OBSERVE_MORE_DATA` / `LOW_SAMPLE_DO_NOT_ADJUST` / `RECOMMEND_TIGHTEN` / `RECOMMEND_MAINTAIN` / `RECOMMEND_LOOSEN_SLIGHTLY` with `recommended_threshold_shift`, `confidence`, `applied=False`.
- **Influences operator recommendation:** advisory only; `auto_apply=False` always.
- **Can execute trades:** no. Surfaced at `/api/calibration-recommendations`.
- **Behavioural tests:** `tests/test_calibration_recommendations.py`.

### `scripts/score_output_contract.py` — Score honesty contract
- **Purpose:** ensure no score travels without calibration metadata.
- **Decision function:** `build_score_contract(raw_score, summary, human_sizing_approved=...)`; `should_drive_sizing` True only when CALIBRATED **and** human-approved; `calibrated_score` never fabricated.
- **Can execute trades:** no. Attached to `/signals` (`score_contract`).
- **Behavioural tests:** `tests/test_score_output_contract.py`.

### `scripts/pre_real_money_preflight.py` — Real-money readiness gate
- **Purpose:** score honest manual real-money readiness and pick an allowed mode.
- **Decision function:** `assess_real_money_readiness(...)` → mode (`SCALE_BLOCKED` / `PAPER_ONLY` / `TINY_MANUAL_PROBE_ONLY` / `MANUAL_REAL_MONEY_READY`); hard caps (exec surface=0, leverage missing≤5, uncalibrated≤6.5, tests/preflight fail≤6, clean≤7). Capped at 7.0 — never scaling.
- **Can execute trades:** no (read-only). Surfaced at `/api/readiness/real-money`.
- **Behavioural tests:** `tests/test_real_money_readiness.py`.

### `scripts/calibration_map.py` — OOS-validated recalibration
- **Purpose:** learn `calibrated_p = f(raw_score)` (isotonic PAV + Platt) and keep it only if it beats raw Brier out of sample.
- **Decision function:** `fit_calibration_map(scores, ys)` → `CalibrationMap{method, apply()}`; `fit_from_outcomes(outcomes)`.
- **Can execute trades:** no. Recalibrated probabilities are advisory; never enable sizing. Surfaced at `/api/calibration-map`.
- **Behavioural tests:** `tests/test_calibration_map.py` (OOS ECE reduction proven).

### `scripts/backtest_calibration.py` — Backtest evidence (IMPORTED_BACKTEST)
- **Purpose:** walk-forward over historical OHLCV → outcomes with real forward returns, zero lookahead, explicit provenance.
- **Decision function:** `backtest_symbol(...)`, `run_backtest(...)`.
- **Can execute trades:** no. Calibrates the scores, never lifts real-money readiness (keys on real_n).
- **Behavioural tests:** `tests/test_backtest_calibration.py` (no-lookahead, provenance, readiness-not-lifted).

### `scripts/score_calibration.py` — Honest score calibration
- **Purpose:** prevent false confidence by labelling every score with its calibration status computed from reconciled outcomes.
- **Decision function:** `compute_score_calibration(reconciliations)` → win_rate / false_positive_rate / avg return / sample_size / `calibration_status` (UNCALIBRATED / LOW_SAMPLE / CALIBRATING / CALIBRATED). `score_calibration_envelope(...)` sets `score_should_drive_sizing` (True only when CALIBRATED).
- **Inputs:** reconciliation rows (read-only).
- **Outputs:** calibration summary + per-score envelope; surfaced via `/api/score-calibration`, attached to `/signals`, rendered by `ScoreCalibrationBadge`.
- **Influences operator recommendation:** yes — gates whether a score may drive sizing.
- **Can execute trades:** no.
- **Behavioural tests:** `tests/test_score_calibration.py`, `tests/test_score_calibration_api.py`, `tests/test_core_engine_behavior.py`.

### `scripts/moltbook_feedback.py` — Outcome feedback classification
- **Purpose:** classify reconciled paper/real outcomes into the feedback vocabulary (SUCCESS_VALID_SIGNAL / FAIL_* / INCONCLUSIVE / FAIL_DATA_QUALITY) and summarise patterns.
- **Decision function:** `_classify_case(...)` via `build_feedback_case_from_reconciliation_row(row)`; `build_feedback_summary(cases)`.
- **Inputs:** reconciliation rows / paper outcomes.
- **Outputs:** classified feedback cases + summary; explicitly refuses to over-claim when outcome evidence is missing.
- **Influences operator recommendation:** yes (Moltbook learning) — advisory only.
- **Can execute trades:** no.
- **Behavioural tests:** `tests/test_moltbook_feedback.py`, `tests/test_core_engine_behavior.py`.

### `scripts/signal_inbox_api.py` — Manual trade log / reconciliation contract
- **Purpose:** the operator-facing backend contract (inbox, reflections, manual-trade LOG, reconciliation).
- **Decision function:** `log_manual_trade(...)`, `reconcile_trade(...)`. The manual-trade log is **record-keeping of a human-executed trade** — it never places an order; it now validates leverage governance at log time.
- **Can execute trades:** no (`broker_api_called=False`, `execution_permission=False` on every response).
- **Behavioural tests:** `tests/test_manual_trade_journal_api.py`, `tests/test_api_server.py`, `tests/test_leverage_governance_api.py`.

### `scripts/persistence.py` — Canonical SQLite store
- **Purpose:** canonical runtime state. JSONL is audit/fallback only.
- **Can execute trades:** no. Every write stamps the advisory invariants.
- **Behavioural tests:** `tests/test_data_model_persistence_v2.py`, `tests/test_db_integrity_check.py`, and the broader persistence suite.

### `scripts/calibration_gate.py` — Calibration readiness gate
- **Purpose:** conservative readiness status (NOT_READY / *_CONFIDENCE / REVIEWABLE) based on row counts. Complements `score_calibration.py`.
- **Can execute trades:** no (read-only).
- **Behavioural tests:** `tests/test_calibration_gate.py`.

---

## Experimental / non-core (NOT load-bearing)

These exist but do not gate the operator path. They are excluded from the
production-core set and should not be trusted as analysis until promoted with
behavioural tests of their own.

- Archetype theater: `chess_archetype_decision_layer.py`, `tennis_archetype_execution.py`, `football_portfolio_archetype_engine.py`, `bruce_lee_*`, `jkd_decision_discipline.py`, `optical_operating_system.py`, `structural_admission_layer.py` (Lamborghini-codename states). The codenames are labels over threshold logic; treat as experimental until each has a documented decision function + adversarial test.
- Many `*_report.py`, `*_diagnostics.py`, `*_index.py` modules are report/diagnostic generators, not decision engines.

## Archived / vendored (excluded from runtime)

- `scripts/external/tribev2/` — vendored neuroscience/fMRI library, **not wired into the pipeline** (`TribeV2Adapter.healthcheck()` reports `wired_into_pipeline: False`). See Phase 5 isolation.
- `scripts/_quarantine/` — known-broken files kept out of import (`*.py.broken`).

---

## Maintenance rule

A module may only move into **production-core** when it has (a) a documented
decision function in this manifest and (b) at least one behavioural/adversarial
test that drives a real decision boundary — not a label check. The no-execution
invariant is non-negotiable for every entry.
