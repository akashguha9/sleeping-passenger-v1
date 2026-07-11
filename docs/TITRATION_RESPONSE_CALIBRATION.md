# Titration Response Measurement & Calibration

**Modules:** `scripts/titration_outcome_contract.py`,
`scripts/titration_response_pipeline.py`, `scripts/titration_susceptibility.py`,
`scripts/titration_recognition.py`, `scripts/titration_runtime_store.py`,
`scripts/titration_calibration_report.py`
**Config:** `config/titration_outcome_config.json`
**Tables:** `titration_response_observations`, `titration_susceptibility_estimates`,
`titration_state_transitions` (all additive, advisory record-keeping)
**API:** `GET /api/titration/calibration`, `GET /api/titration/stability`
**CLI:** `python scripts/titration_response_pipeline.py --json`,
`python scripts/titration_calibration_report.py --json`

This layer converts the heuristic titration engine (`titration_v1`) into a
**measurable** system (`titration_v2`): it observes what the market actually
did after each standardized evidence dose, and it replaces heuristic
susceptibility with a measured estimate wherever — and only wherever — the
sample supports it.

---

## What is MEASURED, SHRUNK, PROXY, PRIOR, CALIBRATED, UNPROVEN

| Quantity | Status |
|---|---|
| Forward returns, Z-responses, MFE/MAE, time-to-transition | **MEASURED** (from imported OHLCV, leakage-safe) |
| Transition labels (ABSOLUTE family) | **MEASURED** (versioned contract v1.0.0) |
| Susceptibility at TICKER level (n≥12, shrunk toward market/global) | **MEASURED/SHRUNK** when sample gates pass |
| Susceptibility at SECTOR/MARKET/GLOBAL (n≥30) | **SHRUNK/MEASURED (pooled)** |
| Susceptibility without sample | **HEURISTIC PROXY** (v1 formula, explicitly labelled, fallback level 5) |
| Buffer capacity with measured χ | **MEASURED/SHRUNK** (`barrier_invchi_stability_v1`) |
| Buffer capacity without | **PROXY** (`legacy_bounded_inverse_proxy_v1`) |
| Catalytic convexity | **EXPERIMENTAL** (quadratic LS, hard gates; never a state gate) |
| All engine weights/thresholds | **PRIOR** (configured, uncalibrated) |
| Transition hazard | **BLOCKED_INSUFFICIENT_OUTCOMES** below 40 matured outcomes; no fit exists yet |
| Any probability claim | **NONE** — nothing in this layer is calibrated; every score carries non-probability semantics |
| Predictive lift of PRIMED/PAG | **UNPROVEN** until matured outcomes accumulate |
| Critical-slowing indicators | **DEFERRED** — the repository currently holds zero OHLCV history in a fresh environment, so a CSD estimator could not be validated against any real series (data-reality audit) |

## Transition-outcome contract (v1.0.0)

Primary label (direction is unavailable on this evidence path, so the
primary falsifiable target is unsigned repricing):

    R_h = P_(entry+h) / P_entry − 1          (h = TRADING days, bar-indexed)
    Z_h = R_h / max(σ_pre · √h, σ_min)
    Y_abs = 1[|Z_h| ≥ κ],  κ = 1.0  (abs_z_1.0)

* Entry bar = first bar at/after the event timestamp (≤10 calendar days
  gap, else DATA_MISSING/stale).
* σ_pre = stdev of daily simple returns over ≤20 bars **strictly before**
  the entry bar (≥10 required, else EXCLUDED — never zero-filled).
* Retained alternatives: `dir_z_1.0` (directional; computed only when a
  real direction exists), `bench_rel_z_1.0` (vs SPY when benchmark bars are
  imported). A triple-barrier family is a candidate for a future version.
* Path features per horizon: `MFE = max_τ(P_τ/P_entry−1)`,
  `MAE = min_τ(...)`, `time_to_transition_days = min{τ: |Z_τ| ≥ κ}`.
* Maturation: MATURED / NOT_YET_MATURED / EXCLUDED / DATA_MISSING /
  INVALID. Labels exist only on MATURED rows.
* Synthetic-fixture bars are refused in runtime mode (`ohlcv_import_contract`
  convention); adjusted_close preferred with `price_field` recorded
  (corporate-action handling is only as good as the imported series).

## Leakage controls (test-enforced)

1. **As-of features**: the engine is re-evaluated at each event timestamp
   with the event list truncated to `≤ t` — proven by the two-database test
   (`test_leakage_future_events_do_not_change_past_features`).
2. **σ_pre boundary**: pre-entry bars only
   (`test_sigma_pre_uses_only_pre_entry_bars` — wild forward moves cannot
   inflate it).
3. **Forward prices are outcomes only**; entry bar ≥ event date asserted on
   every persisted observation.
4. **Maturity gate**: labels never exist on immature rows.
5. **Temporal evaluation**: 70/30 time-ordered split with an **overlap
   purge** — training rows whose forward window could cross the boundary
   (≈ horizon × 1.6 calendar days) are dropped.
6. `market_data` candle rows are excluded from evidence (they are outcome
   inputs, not evidence).

## Episode policy

One evidence event = one episode (per horizon), with the *cumulative* prior
state captured in `active_before` and the incremental dose
`= active_after − active_before` (saturating scale, so clustered events get
smaller marginal doses — double-counting of a single reaction across a
cluster is damped by construction rather than by an arbitrary cooldown).
Duplicate event IDs are impossible (PK); duplicate timestamps allowed and
recorded.

## Measured susceptibility

    χ_h = Theil–Sen slope of |Z_h| on dose, matured observations only

* Robust: median of pairwise slopes, clipped at ±25, deterministic pair
  thinning; approximate CI = central 90% band of pairwise slopes.
* Shrinkage: `(n·child + k·parent)/(n+k)`, k=10 (empirical-Bayes style).
* Gates: TICKER n≥12 (shrunk toward market/global), SECTOR×MARKET and
  MARKET and GLOBAL n≥30. Below every gate: **HEURISTIC_PROXY, level 5** —
  the proxy formula is unchanged from v1 and is retained inside every
  measured result for comparison (shadow mode).
* Normalization to the engine's [0,1]: `χ_norm = clip01(slope / 4.0)`
  (slope_scale=4 Z-units per dose unit is a configured prior; negative
  slopes → 0 = absorbing market).
* |Z| means the measured quantity is **response magnitude per dose**, not
  direction — stamped `measured_response_slope_not_probability`.
* Response acceleration: chronological half-split slope contrast →
  RESPONSE_ACCELERATING / STABLE / DECELERATING / INSUFFICIENT_DATA
  (≥8 obs per half). This is the operational dχ/dt approximation.

## Measured buffer capacity

With measured/shrunk χ:

    buffer = 0.5·barrier + 0.3·(1−χ_norm) + 0.2·stability
    stability: DECELERATING→1.0, STABLE/UNKNOWN→0.5, ACCELERATING→0.0

Status MEASURED (unshrunk ticker) / SHRUNK / PROXY / UNAVAILABLE; the v1
formula survives only as `legacy_buffer_proxy`.

## State activation (titration_v2)

* **ENDPOINT_CROSSING** (operational): activation threshold **newly**
  crossed this checkpoint step, measured/shrunk χ ≥ 0.20, recognition below
  the crowded gate, FTR below gate. Time-bounded by construction (the
  "newly crossed" flag lives one checkpoint step).
* **BUFFER_DEPLETING** (operational): measured/shrunk χ with
  RESPONSE_ACCELERATING, net accumulation positive, barrier still open,
  measured buffer ≤ 0.50, FTR below gate.
* Both are **impossible on proxy-only evidence** (test-enforced).
* **REPRICING remains RESERVED**: honest activation needs post-state
  realized-response attribution (outcome strictly after state timestamp,
  confident attribution), which the runtime read path cannot yet prove.
  The historical transition table (`titration_state_transitions`) is the
  data that will make it provable.

## Recognition (VMR v2) and PAG confidence

VMR components: PRICE + VOLUME (independent, from imported OHLCV via
`titration_recognition`) and ATTENTION + VELOCITY (evidence-derived,
overlapping with readiness inputs — flagged `overlap_warning`). Weights
renormalize over available components. PAG confidence:
`low_feature_overlap` (adjusted PAG = PAG × 0.5) when only evidence-derived
recognition exists; `moderate` with ≥1 independent component. Free energy
uses the **adjusted** PAG.

## Calibration report (refusal-first)

`GET /api/titration/calibration`: sample inventory, per-horizon temporal
out-of-sample comparator rankings (base rate / evidence dose / active
evidence / LRR / PAG — AUC + top-tercile transition rate with Wilson
intervals), per-state transition rates (n≥10 per state), experimental
convexity, hazard gate status, stability warnings. Refusals:
`INSUFFICIENT_EVIDENCE_FOR_PERFORMANCE_CLAIM` below 30 matured per horizon
or single-class; `BLOCKED_INSUFFICIENT_OUTCOMES` below 40 matured for
hazard. Sample-status ladder reuses `score_calibration`
(UNCALIBRATED/LOW_SAMPLE/CALIBRATING/CALIBRATED at 20/50) and the reactor
confidence bands (n<10 very_low, <30 low, <100 medium).

## Operational workflow

1. Import OHLCV (`scripts/import_ohlcv_csv.py`) and let live refresh
   accumulate `signal_events`.
2. Run `python scripts/titration_response_pipeline.py --json` (rebuilds
   observations + estimates deterministically; idempotent replace-all).
3. `/signals` decoration automatically starts using measured susceptibility
   (TTL-cached store; empty tables cost nothing and degrade to the labelled
   proxy).
4. Inspect `/api/titration/calibration` — it will refuse performance claims
   until matured outcomes accumulate. That refusal is the honest state.

## Known limitations

* This environment ships with **zero** market data (operator-local,
  gitignored); every runtime output here is the honest empty/proxy path.
  All measured-path behavior is proven by deterministic synthetic fixtures
  through the real DB schema and pipeline.
* Unsigned response mode: direction is never fabricated; directional labels
  await a typed evidence source that carries direction.
* Overlap purge is approximate (calendar-day proxy for trading days).
* Rolling beta is not implemented; benchmark-relative labels use z-score
  differences (β=1 equivalent, labelled).
* Hazard fitting deliberately does not exist below its sample gate.
* No component of this layer is a calibrated probability.
