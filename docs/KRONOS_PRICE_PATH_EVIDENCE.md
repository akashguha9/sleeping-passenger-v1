# Kronos Price-Path Evidence (advisory-only)

`KRONOS_PRICE_PATH_EVIDENCE` integrates the [Kronos](https://github.com/shiyu-coder/Kronos)
financial K-line / candlestick foundation model into the Sleeping
Passenger advisory signal-refinery as a **read-only price-path evidence
layer**. Kronos is a *technical witness, not the judge*.

It answers exactly one question:

> "Does the recent OHLCV / candlestick price path **agree** with an
> already-existing candidate signal thesis?"

It never answers "should we buy / sell / enter / execute".

---

## 0. Component status (the truth, as wired today)

Kronos enters the pipeline through exactly one runtime path:

```
config/external_adapters.yaml (kronos: enabled:false)
  → ExternalAdapterRegistry
  → scripts/external_adapters/kronos_adapter.py  (KronosAdapter)   ← canonical
  → scripts/kronos_price_path_evidence.py        (internal math helper)
  → ExternalEvidence(CANDLESTICK_FORECAST, WATCH_ONLY)
  → scripts/core/external_evidence_router.py     (caps at WATCH, Apollo/DIABLO veto)
```

| Component | Status |
| --- | --- |
| `external_adapters/kronos_adapter.py` (`KronosAdapter`) | **canonical runtime integration** (registered + routed) |
| `kronos_price_path_evidence.py` (math + `apply_kronos_to_signal`) | **internal helper, used by the adapter** |
| Persistence (`signal_events` `KRONOS_*` columns) | **not wired / removed** — external evidence does not persist to `signal_events`; future work |
| Moltbook outcome learning / calibration | **not wired / removed** — needs an entry-snapshot + close-event pipeline first; future work. `calibration_multiplier` defaults to the `0.50` cold-start haircut |
| Source health | **folded into `KronosAdapter.healthcheck()`** (no parallel health module) |
| Frontend card (`KronosEvidenceCard.tsx`) | **not mounted** — implemented + unit-tested, not imported by any page |
| Real-money sizing | **prohibited** before 50–100 paper-trade outcomes (and ≥30 per calibration bucket) |

Kronos is **disabled by default** (`config/external_adapters.yaml` → `kronos.enabled: false`).
With the adapter disabled, `collect()` returns `[]` and there is **no live decision
impact** whatsoever. Even enabled, candlestick-forecast evidence is capped at
`WATCH` by the router and can never (alone) produce a paper trade.

The standalone `kronos_persistence.py`, `kronos_moltbook_learning.py`, and
`kronos_source_health.py` modules that previously existed were **removed** to
avoid a second, orphaned Kronos system. Their designs are described below as
*future work*, not shipped behavior.

---

## 1. What Kronos does

Kronos takes a window of recent OHLCV bars for a ticker that **already has
a candidate advisory signal**, produces a short-horizon price-path
forecast, and turns that forecast into a small set of *evidence fields*
plus one advisory *classification*. That classification can only nudge the
existing advisory score within hard caps. It is one more witness alongside
news, filings, regulatory data, prediction markets, market data,
multi-model reasoning, chaos vetoes, Moltbook learning, and human review.

## 2. Why it is evidence-only

This repo is an advisory-only signal refinery. Execution is **manual
only** — no broker API orders, no autonomous trading, no AI execution.
Kronos is integrated under the same contract as every other layer:

- `ADVISORY_ONLY` stays true.
- `HUMAN_EXECUTION_REQUIRED` stays true.
- `execution_gate` stays `LOCKED`.
- `broker_api_called` stays `false`.
- `ai_execution_count` stays `0`.

A price-path model is *helpful context*, not authority. A model with no
local track record is even less trustworthy — so Kronos confidence is
haircut until Moltbook accumulates real post-trade outcomes (Section 6).

## 3. What it is forbidden from doing

Kronos in this MVP **cannot**:

- create a trade by itself;
- increase leverage by itself;
- override DIABLO, ISLERO, or any chaos / safety veto;
- unlock the execution gate or call a broker;
- emit execution wording (order placement, trade execution, auto-trading,
  broker-connection language);
- emit any of the forbidden output labels: `BUY`, `SELL`, `ENTER`,
  `EXIT_NOW`, `EXECUTE`, `PLACE_ORDER`, `AUTO_TRADE`.

Allowed output labels only: `SUPPORTIVE`, `CONTRADICTORY`, `UNSTABLE`,
`NOISY`, `INSUFFICIENT_DATA`, `DISABLED`, `ERROR_SAFE`.

## 4. Mathematical scoring definitions

Observed closes `C_t` for `t = 1..T`; Kronos forecast closes `F_{T+h}` for
`h = 1..H` with `F_T = C_T`.

```
R_f                     = (F_{T+H} - C_T) / C_T              # forecast return (fraction)
forecast_return_pct     = 100 * R_f

r_h                     = (F_{T+h} - F_{T+h-1}) / F_{T+h-1}  # per-step return, F_T = C_T
sigma_f                 = sqrt( (1 / max(H-1, 1)) * Σ_{h=1..H} (r_h - mean(r))^2 )
forecast_volatility_pct = 100 * sigma_f

peak_h                  = max(F_T, F_{T+1}, ..., F_{T+h})
drawdown_h              = (F_{T+h} - peak_h) / peak_h
MDD_f                   = min_h drawdown_h
downside_path_risk      = clip( |min(MDD_f, 0)| / D_ref, 0, 1 )

upside_path_score       = clip( max(R_f, 0) / U_ref, 0, 1 )

noise_ratio             = forecast_volatility_pct / max(|forecast_return_pct|, eps)   # eps = 0.25
noise_penalty           = MAX_NOISE_PENALTY * clip( (noise_ratio - 1.5) / 3.0, 0, 1 )

sign_forecast           = +1 if forecast_return_pct >= +theta_return       # theta_return = 0.50%
                          -1 if forecast_return_pct <= -theta_return
                           0 otherwise
sign_signal             = +1                                  # long-only advisory candidates
directional_agreement   = (sign_forecast == sign_signal)

confidence_raw          = clip( 0.40*|R_f|/U_ref + 0.30*upside_path_score
                                + 0.30*(1 - downside_path_risk), 0, 1 )
confidence_calibrated   = clip( confidence_raw * calibration_multiplier, 0, 1 )

alignment_bonus         = I(directional_agreement) * MAX_ALIGNMENT_BONUS
                          * confidence_calibrated * (1 - downside_path_risk)
                          * (1 - min(noise_penalty / MAX_NOISE_PENALTY, 1))
downside_penalty        = MAX_DOWNSIDE_PENALTY * downside_path_risk
                          * max(confidence_calibrated, 0.25)

final_score_delta       = clip( alignment_bonus - downside_penalty - noise_penalty,
                                -1.00, +0.50 )
```

Reference scales (`D_ref` / `U_ref`) default by asset class and are
overridable via `KRONOS_D_REF` / `KRONOS_U_REF`:

| Asset class | `D_ref` | `U_ref` |
| ----------- | ------- | ------- |
| daily equities (default) | 0.08 | 0.10 |
| crypto      | 0.12 | 0.15 |

**Hard rule:** Kronos can help by at most **+0.50** and hurt by up to
**−1.00**. It is a stronger risk-reducer than hype-booster, by design.

## 5. Safety gates

`apply_kronos_to_signal(base_signal, kronos_evidence)` applies the
evidence under hard gates:

```
S_base       = existing advisory signal score
ΔK           = kronos final_score_delta
S_candidate  = clip(S_base + ΔK, 0, 10)
```

- **Rule 1** — Kronos as the *only* positive evidence ⇒ class capped at
  `WATCHLIST` (never `BUY-CANDIDATE`).
- **Rule 2** — base class in `{DIABLO, NO_NEW_RISK, CHAOS_VETO}` ⇒ Kronos
  cannot upgrade it; `S_final = min(S_candidate, S_base)`.
- **Rule 3** — `status == UNSTABLE` ⇒ add / preserve a `NO_NEW_RISK`
  warning.
- **Rule 4** — `status == CONTRADICTORY` ⇒ `human_review_required = True`.
- **Rule 5** — `status == SUPPORTIVE` ⇒ small score delta only; the
  execution gate stays `LOCKED`.
- **Rule 6** — Kronos failure ⇒ `S_final = S_base` and
  `proof_status = ERROR_SAFE_NO_DECISION_IMPACT`.

For `status in {ERROR_SAFE, DISABLED, INSUFFICIENT_DATA}`,
`final_score_delta = 0` and `S_final = S_base`.

## 6. Moltbook calibration (FUTURE WORK — not wired)

> **Status:** not shipped. The standalone learning module was removed; the
> arithmetic below is the *intended* design for when an entry-snapshot +
> close-event pipeline exists. Until then `calibration_multiplier` is the
> fixed `0.50` cold-start haircut and Kronos confidence is never raised by
> outcomes, because no outcomes are recorded.

Kronos would earn or lose trust only **after a real or paper trade outcome is
known**:

```
R_actual            = (exit_price - entry_price) / entry_price
actual_return_pct   = 100 * R_actual
forecast_error_pct  = |kronos_forecast_return_pct - actual_return_pct|
direction_correct   = sign(forecast_return_pct) == sign(actual_return_pct)

kronos_helped if:
    status == SUPPORTIVE and direction_correct and forecast_error_pct <= error_threshold
  OR
    status in {CONTRADICTORY, UNSTABLE} and actual_return_pct <= 0

false_confidence if:
    status == SUPPORTIVE and actual_return_pct < 0 and confidence_calibrated >= 0.50
```

Per-bucket calibration multiplier:

```
accuracy_b               = correct_forecasts_b / total_forecasts_b
calibration_multiplier_b = clip(accuracy_b / 0.55, 0.25, 1.25)
until total_forecasts_b >= 30:
    calibration_multiplier_b = min(0.50, calibration_multiplier_b)
```

Until a bucket has ≥ 30 outcomes the multiplier is capped at **0.50** —
**no prior proof means Kronos confidence is halved.**

## 7. Failure modes

| Condition | Status | Decision impact |
| --------- | ------ | --------------- |
| `KRONOS_ENABLED` not true | `DISABLED` | none (`delta = 0`) |
| fewer than `KRONOS_MIN_LOOKBACK_BARS` bars | `INSUFFICIENT_DATA` | none |
| model load / forecast raises | `ERROR_SAFE` | none, `proof = FAILED_SAFE_NO_DECISION_IMPACT` |
| `downside_path_risk >= 0.70` | `UNSTABLE` | risk-reducing only |
| `noise_penalty >= 0.35` | `NOISY` | low-confidence |
| agreement & `delta > 0` | `SUPPORTIVE` | small positive |
| disagreement & `sign_forecast == -1` | `CONTRADICTORY` | human review |

Every failure degrades *safe*: a missing dependency, an unreachable model,
or a bad forecast can never raise a score or unlock execution.

## 8. How to enable locally

Kronos is **disabled by default**. The runtime gate is the adapter config,
not an env var:

```yaml
# config/external_adapters.yaml
external_adapters:
  kronos:
    enabled: true            # default false
    live_advisory: false     # true only after weights are vendored locally
    mock_mode: true
    real_execution_allowed: false   # must stay false
```

The default CI/test path uses the deterministic stub forecast — **no Hugging
Face download, no network**. The math-helper env tunables still apply when you
drive the helper directly (`KRONOS_MIN_LOOKBACK_BARS`, `KRONOS_DEFAULT_HORIZON_BARS`,
`KRONOS_MAX_ALIGNMENT_BONUS`, `KRONOS_MAX_DOWNSIDE_PENALTY`,
`KRONOS_MAX_NOISE_PENALTY`, `KRONOS_MODEL_NAME`, `KRONOS_TOKENIZER_NAME`,
`KRONOS_DEVICE`, `KRONOS_MAX_CONTEXT`).

For `live_advisory`, vendor the Kronos repo locally and install `torch` +
`pandas`. If either is missing, the adapter silently uses the deterministic
stub and `KronosAdapter.healthcheck()` reports `MODEL_UNAVAILABLE`.

## 9. Why it should not be trusted before 50–100 paper-trade outcomes

A foundation model that forecasts price paths is not the same as a model
that *improves your decisions on this universe, under these gates*. The
only honest evidence that Kronos helps is post-trade Moltbook calibration.
Until a bucket has ≥ 30 outcomes its multiplier is capped at 0.50, and a
practical confidence in the layer as a whole needs ~50–100 closed
paper-trade outcomes spread across statuses. Before then, treat every
Kronos read as **unproven technical context**, never as validation.

## 10. Investor-facing explanation

> Kronos is integrated as a read-only price-path foundation-model layer.
> It does not generate trades or execute orders. Instead, it forecasts
> short-horizon OHLCV path behavior and contributes calibrated technical
> evidence to the advisory signal-refinery. Outputs are constrained by
> survival-first gates, chaos vetoes, human review, and post-trade
> Moltbook calibration.

---

### Files

| File | Role |
| ---- | ---- |
| `scripts/external_adapters/kronos_adapter.py` | **canonical runtime integration** (`KronosAdapter`) |
| `scripts/kronos_price_path_evidence.py` | internal math helper: evidence math + status + `apply_kronos_to_signal` gating |
| `scripts/core/external_evidence_router.py` | routes `CANDLESTICK_FORECAST` → WATCH only (pre-existing) |
| `config/external_adapters.yaml` | adapter config (`kronos.enabled: false`) |
| `frontend/src/components/KronosEvidenceCard.tsx` | compact advisory card — **not mounted yet** |
| `tests/test_kronos_adapter.py` | adapter + router integration + no-parallel-paths tests |
| `tests/test_kronos_price_path_evidence.py` | math-helper backend tests |
| `tests/test_kronos_frontend_language.py` | card language + not-mounted truthful declaration |
| `frontend/src/components/__tests__/KronosEvidenceCard.spec.tsx` | card render tests |

Removed (avoided a parallel Kronos system; designs are future work):
`scripts/kronos_persistence.py`, `scripts/kronos_moltbook_learning.py`,
`scripts/kronos_source_health.py` (health folded into `KronosAdapter.healthcheck()`).
