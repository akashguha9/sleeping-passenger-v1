# External Advisory Evidence Pipeline

`EXTERNAL_ADVISORY_EVIDENCE_ENRICHMENT`

This document describes how the canonical external-adapter framework is wired
into the daily five-model synthesis as an **evidence-only enrichment stage**.

## 1. What the external adapter framework does

The repo carries a small, canonical framework for ingesting *external*
analytical signals (price-path forecasts, prediction-market reads, agent
committees, narrative trends, terminal analytics):

| Component | File |
|---|---|
| Evidence contract + base adapter | `scripts/external_adapters/base.py` |
| Adapter registry + config loader | `scripts/external_adapters/registry.py` |
| Per-source adapters (Kronos, …) | `scripts/external_adapters/*.py` |
| Evidence router (safety gates) | `scripts/core/external_evidence_router.py` |
| Config | `config/external_adapters.yaml` |
| **Runtime invocation stage** | `scripts/external_advisory_evidence.py` |

Each adapter turns its source into a normalized `ExternalEvidence` object
carrying a `data_truth_origin`, a `license_boundary`, an
`execution_permission` (always `<= WATCH_ONLY`), and `real_execution_allowed=False`.

## 2. Where it is invoked in daily synthesis

`scripts/external_advisory_evidence.build_external_evidence_bundle()` is called
from `scripts/daily_synthesis_pipeline.run_daily_synthesis()` **after** base
candidate generation / daily-payload construction and **before** the final
advisory synthesis output. The flow:

```
daily candidate universe
    -> base advisory signal / candidate payload
    -> ExternalAdapterRegistry.collect_external_evidence()   (enabled adapters only)
    -> ExternalEvidenceRouter.route(evidence)                (per item)
    -> external_evidence bundle attached to result["external_evidence"]
    -> final advisory synthesis (render_portfolio_truth_context)
    -> human review only
```

The bundle is attached at `result["external_evidence"]` and rendered as a safe,
watch-only block in the synthesis context.

## 3. Why it is advisory-only

External evidence is *evidence, not authority*. The stage:

- never converts evidence into a trade or a BUY/SELL/ENTER/EXIT command;
- never calls a broker API;
- never mutates execution permission above `WATCH_ONLY`;
- never overrides a `DIABLO` / `CHAOS_VETO` / `NO_NEW_RISK` safety class;
- fails safe (any adapter/router/config error → zero decision impact).

Every bundle and item carries the canonical advisory safety stamps
(`advisory_only`, `human_execution_required`, `execution_gate=LOCKED`,
`broker_api_called=False`, `ai_execution_count=0`).

## 4. Adapter config defaults

`config/external_adapters.yaml`:

- Every adapter (`poly_data`, `kronos`, `tradingagents`, `trendradar`,
  `fincept_terminal`) is `enabled: false`, `real_execution_allowed: false`.
- Kronos is `mock_mode: true`, `enabled: false`.
- A separate framework flag block gates the whole stage:

```yaml
external_advisory_evidence:
  enabled: false                 # disabled-and-safe by default
  decision_impact: ADVISORY_CONTEXT_ONLY
  max_positive_score_delta: 0.50
  max_negative_score_delta: -1.00
  require_human_review: true
  real_execution_allowed: false
  execution_permission: WATCH_ONLY
```

## 5. Router role

`ExternalEvidenceRouter.route()` assigns each evidence type a recommended
pipeline path and a `max_allowed_action`, and hard-blocks promotion when the
license boundary is missing, Apollo returns `ABORT`, or the pipeline chaos
state is `DIABLO`. Candlestick/narrative/prediction evidence is capped at
`WATCH`; agent-committee evidence at `PAPER_TRADE`. `REAL_EXECUTION` is always
in `blocked_actions`.

## 6. Score-delta formula

For each routed, **accepted** evidence item `i`:

```
w_i = reliability weight    in [0, 1]    (evidence.confidence_proxy)
a_i = alignment score       in [-1, +1]
r_i = router multiplier     in {0, 0.25, 0.50, 1.00}
q_i = quality multiplier    in [0, 1]    (evidence.evidence_quality_score)

delta_ext_raw = sum_i ( w_i * a_i * r_i * q_i )
delta_ext     = clip(delta_ext_raw, -1.00, +0.50)
S_candidate   = clip(S_base + delta_ext, 0, 10)
```

Router multiplier mapping (`_route_safety_multiplier`):

| `max_allowed_action` | `r_i` |
|---|---|
| `REJECT` | 0.00 |
| `WATCH` | 0.25 |
| `PAPER_TRADE` | 0.50 |
| (unrestricted — never granted) | 1.00 |

`1.00` is structurally unreachable because external adapters never receive an
unrestricted action — real execution is never allowed.

## 7. Safety caps

- Max positive external boost: **+0.50**
- Max negative external penalty: **-1.00**

External adapters are deliberately **stronger as risk reducers than hype
boosters.**

Applied in `apply_external_evidence_to_score()`:

- `if safety_veto: S_final = min(S_candidate, S_base)` and the original veto
  class is kept (Kronos/external evidence can never upgrade a veto).
- If external evidence is the *only* positive evidence: `final_class <= WATCHLIST`.
- If the bundle status is `ERROR_SAFE` / `DISABLED` / `CONFIG_MISSING` /
  `ROUTER_REJECTED` / `NO_ENABLED_ADAPTERS`: `delta = 0`, `S_final = S_base`.
- Negative external evidence sets `human_review_required = true`.

## 8. Failure-safe behavior

| Condition | `external_evidence_status` | `decision_impact` | per-item `proof_status` |
|---|---|---|---|
| Config file missing | `CONFIG_MISSING` | `NONE` | — |
| Framework disabled | `DISABLED` | `NONE` | — |
| Enabled, no adapter enabled | `NO_ENABLED_ADAPTERS` | `NONE` | — |
| Adapter raised | `ERROR_SAFE` | `NONE` | `FAILED_SAFE_NO_DECISION_IMPACT` |
| Unsafe permission claimed | (accepted) | `ADVISORY_CONTEXT_ONLY` | `EXECUTION_PERMISSION_DOWNGRADED_OR_REJECTED` |
| Router rejected all items | `ROUTER_REJECTED` | `NONE` | `ROUTER_REJECTED_NO_DECISION_IMPACT` |
| Evidence accepted | `ACCEPTED_EVIDENCE_ONLY` | `ADVISORY_CONTEXT_ONLY` | `ACCEPTED_EVIDENCE_ONLY` |

No exception escapes `build_external_evidence_bundle()`.

## 9. Why Kronos remains disabled by default

Kronos is an *optional* price-path foundation model. It stays
`enabled: false` / `mock_mode: true` so that:

- CI and the default daily run never download model weights or hit the network;
- it never contributes to a live decision until an operator explicitly opts in;
- its uncalibrated forecast confidence cannot leak into real-money sizing.

When explicitly enabled in an isolated test/local config, Kronos flows through
the same single path (`config → registry → KronosAdapter → kronos_price_path_evidence
→ ExternalEvidence(CANDLESTICK_FORECAST) → router`) and is capped at `WATCH`.

## 10. Why external evidence cannot create trades

Three independent guards:

1. **Adapter contract** — `real_execution_allowed=False`,
   `execution_permission <= WATCH_ONLY`, sanitized actions collapse to `WATCH`.
2. **Router** — `REAL_EXECUTION` is always blocked; advisory evidence types are
   capped at `WATCH`/`PAPER_TRADE`; DIABLO/Apollo force `REJECT`.
3. **Enrichment stage** — output permission forced to `WATCH_ONLY`/`REJECT_ONLY`;
   score delta clamped to `[-1.00, +0.50]`; veto classes preserved; only-positive
   evidence capped at `WATCHLIST`.

## 11. How Moltbook calibration should later evaluate accepted evidence

When close-event snapshots exist, Moltbook should pair each
`ACCEPTED_EVIDENCE_ONLY` item's `score_delta` / alignment with the realized
outcome to derive a per-source reliability weight `w_i` and a router safety
multiplier prior. Until calibrated, `w_i` stays uncalibrated and external
evidence cannot influence real-money sizing. This is **future-only** — no
calibration is wired today.

## 12. Current limitations

- The live daily pipeline **attaches** the bundle as advisory context; it does
  not mutate the existing per-candidate scores (those use a different CQS/EQS
  scale). `apply_external_evidence_to_score()` is the tested, pure scoring
  function for any future per-candidate application.
- No persistence of accepted evidence (no canonical close-event store yet).
- No Moltbook calibration of external evidence yet.
- No frontend card is mounted (no real enabled payload reaches the UI).
- External adapters are disabled by default; enabling is an explicit operator
  decision.

## Status table

| Component | Status |
|---|---|
| ExternalAdapterRegistry | wired (invoked by daily synthesis) |
| ExternalEvidenceRouter | wired (per-item routing) |
| KronosAdapter | registered, disabled by default |
| Daily synthesis invocation | wired |
| Frontend display | future-only (not wired) |
| Moltbook calibration | future-only (not wired) |
| Real-money sizing impact | prohibited before evidence is calibrated |
