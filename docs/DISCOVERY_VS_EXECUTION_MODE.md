# Discovery vs Execution vs Survival — Three-Lane Mode Model

> **Advisory-only.** Nothing in this document grants execution authority. BUY and
> PROBE_BUY are advisory paper-signal classifications. Human execution is always
> required, the execution gate stays `LOCKED`, and no broker call, order, or
> execution route exists anywhere in this path.

## Why this exists

The MVP used to collapse from *discovery mode* into *survival mode*:

```
price layer weak  ->  survival mode  ->  no discovery promotion
                  ->  no buy-like research signals  ->  operator feels the system is dead
```

That conflated three distinct ideas. The fix separates them explicitly:

```
price layer weak  ->  discovery still runs (DISCOVERED / WATCHLIST / CONDITIONAL_PROBE)
                  ->  execution / new-risk stays blocked until strict gates pass
```

**DISCOVERY MODE ≠ EXECUTION MODE ≠ SURVIVAL MODE.**

## The three lanes

| Lane | Purpose | Allowed outputs |
| --- | --- | --- |
| **SURVIVAL** | Protect the existing book: reconcile stop-hits, quarantine phantoms, fix leverage conflicts, block new risk while open-risk truth is dirty. | EXIT_REVIEW, STOP_HIT, CLOSE_TRADE, RECONCILE, QUARANTINE, NO_NEW_RISK |
| **DISCOVERY** | Surface and score fresh ideas, even when execution is blocked. | DISCOVERED, WEAK_DISCOVERY, WATCHLIST, STRONG_WATCHLIST, CONDITIONAL_PROBE_CANDIDATE, RESEARCH_ONLY |
| **EXECUTION** | Approve an advisory paper BUY/PROBE_BUY **only** when strict gates pass. | PROBE_BUY, BUY (advisory paper labels) |

## 1. Discovery is allowed even when execution is blocked

`discovery_allowed` depends only on:

```
discovery_allowed = candidate_source_available
                    AND system_can_parse_candidates
                    AND advisory_safety_lock_intact
```

It does **not** depend on price coverage, portfolio truth, phantom cleanliness,
leverage cleanliness, or exit-debt cleanliness. A weak price layer, a phantom
row, a leverage conflict, or an unresolved stop blocks **execution** — it never
erases a name from discovery.

## 2. Execution requires every hygiene gate

```
execution_allowed = H_price_coverage >= 0.80
                    AND C_price_coverage >= 0.80
                    AND portfolio_truth_clean
                    AND phantom_clean
                    AND leverage_clean
                    AND exit_debt_clean
                    AND source_health_ok
                    AND advisory_safety_lock_intact

new_risk_allowed   = execution_allowed AND candidate_quality_ok AND risk_budget_available

survival_attention_required = NOT(H_price_coverage>=0.80) OR NOT portfolio_truth_clean
                              OR NOT phantom_clean OR NOT leverage_clean OR NOT exit_debt_clean
```

Definitions (`scripts/discovery_execution_mode.py`):

- **Price validity** — `valid_price(t)` requires a non-null positive price, a
  source that is not `STATIC_FALLBACK / UNVERIFIED / MOCK_ONLY / UNKNOWN`, and
  (optionally) a fresh-enough age. `price_coverage(U) = |valid| / max(1, |U|)`.
- **Portfolio truth** — `Δ_open = U_S △ U_H`. Clean iff the symmetric difference
  is empty, no phantom ticker is marked open, and no closed row is in the open set.
- **Phantom** — phantom tickers (`GLD, UNG, TIP, TLT, FCG, ZIM`, unioned with the
  runtime `do_not_treat_as_open.json` override) marked open-like are violations.
  Phantoms are excluded from open exposure but remain valid in history/audit.
- **Leverage** — sheet leverage is compared to the per-instrument ceiling
  (India equity 4x, rest-of-world 1x) and to any policy/payload value. A
  divergence is surfaced as `LEVERAGE_TRUTH_CONFLICT` and **never silently
  resolved**.
- **Exit debt** — `exit_debt(r) = max(stop_hit_unresolved, close_required_unresolved,
  moltbook_missing)`. A `STOP_CLOSED` / `CLOSED_RECONCILED` stop does not count;
  an open-like unresolved stop does.

## 3. Why-today is tiered (not a single hard 0.70 filter)

| why_today_score | tier |
| --- | --- |
| `[0.00, 0.40)` | NOISE_OR_STALE |
| `[0.40, 0.55)` | WEAK_DISCOVERY |
| `[0.55, 0.65)` | VALID_DISCOVERY |
| `[0.65, 0.73)` | STRONG_WATCHLIST |
| `[0.73, 0.80)` | PROBE_CANDIDATE (if execution gates pass) |
| `[0.80, 1.00]` | HIGH_CONVICTION (if execution gates pass) |

A why-today tier never creates a BUY on its own.

## 4. BUY_SCORE composition

```
BUY_SCORE(c) = 0.30*why_today_score
             + 0.25*price_confirmation
             + 0.20*source_quality
             + 0.15*cross_model_agreement
             + 0.10*portfolio_fit          (each component clamped to [0,1]; weights sum to 1)
```

Classification by BUY_SCORE band, gated by `execution_allowed` and per-candidate
proof floors:

| BUY_SCORE | execution_allowed=false | execution_allowed=true + proof |
| --- | --- | --- |
| `< 0.40` | NOISE_OR_STALE | NOISE_OR_STALE |
| `[0.40, 0.55)` | WEAK_DISCOVERY | WEAK_DISCOVERY |
| `[0.55, 0.65)` | DISCOVERED | DISCOVERED |
| `[0.65, 0.73)` | WATCHLIST | WATCHLIST |
| `[0.73, 0.80)` | CONDITIONAL_PROBE_CANDIDATE_EXECUTION_BLOCKED | PROBE_BUY |
| `>= 0.80` | HIGH_CONVICTION_WATCHLIST_EXECUTION_BLOCKED | BUY |

PROBE_BUY/BUY additionally require price/volume/source (and, for BUY,
portfolio-fit) proof floors. A news/filing-only candidate with no price/volume
confirmation can reach DISCOVERED/WATCHLIST but never PROBE_BUY/BUY.

### Relationship to the existing executable path

The new BUY_SCORE tiering is an **additive advisory discovery surface**. It does
**not** replace `scripts/candidate_executable_split.py`, which remains the single
authoritative path for actual paper-buy approval (`executable_paper_buys`). The
execution board surfaces only what that strict split already approved, and only
when `execution_allowed` is true.

## 5. Operator override is separate from model approval

Operator overrides (e.g. the hard `do_not_treat_as_open.json` truth file) are
manual human declarations. They are never converted into a model-approved buy,
and a model classification of BUY/PROBE_BUY never becomes an operator-authorized
execution. The two remain orthogonal.

## 6. Advisory-only safety is unchanged

Every artifact this model produces carries the canonical advisory-only stamps
(`advisory_status=ADVISORY_ONLY`, `execution_gate=LOCKED`, `broker_api_called=false`,
`ai_execution_count=0`, `can_execute=false`, `human_execution_required=true`,
`real_money_sizing_impact=PROHIBITED`). No gate in this sprint weakens any
pre-existing safety, advisory-only, or no-execution invariant.

## Where it lives

- `config/thresholds.yaml` → `discovery_execution` block (single source of truth).
- `scripts/discovery_execution_config.py` → loader (merge-over-defaults).
- `scripts/discovery_execution_mode.py` → pure functions + mode_state + report.
- `scripts/daily_synthesis_pipeline.py` → wiring: `mode_state`, boards, MODE
  SUMMARY in the context block, and `mode_state` in `daily_synthesis_context.json`
  (exposed for a future frontend sprint; no frontend changes in this sprint).
- Tests: `tests/test_discovery_execution_mode.py`,
  `tests/test_discovery_execution_gate_separation.py`,
  `tests/test_candidate_proof_tiers.py`,
  `tests/test_discovery_execution_advisory_invariants.py`.
