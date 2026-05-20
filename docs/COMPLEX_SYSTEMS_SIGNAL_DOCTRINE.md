# Complex Systems Signal Doctrine

> **Advisory-only.** This layer never places orders, never calls a broker,
> never executes. It produces diagnostics for **human review**. The
> strongest positive output it can emit is `probe_candidate` — which still
> requires the operator to act manually. SQLite remains canonical truth;
> JSONL is audit/fallback only.

Implemented in [`scripts/complex_systems_diagnostics.py`](../scripts/complex_systems_diagnostics.py).
Tested in [`tests/test_complex_systems_diagnostics.py`](../tests/test_complex_systems_diagnostics.py).

It is the sibling of the
[Signal Geometry Reflection Layer](SIGNAL_GEOMETRY_REFLECTION_LAYER.md):
same purity, same safety stamps, same degrade-safely posture. Where the
geometry layer translates *spatial / calculus* metaphors, this layer
translates *complex-systems / feedback* metaphors into disciplined
advisory diagnostics.

## The doctrine

> **Survive first. Learn second. Scale later.**

## The update equation

The whole MVP loop is a discrete state update:

```
X_{t+1} = F(X_t, A_t, E_t, G, theta)
```

| Symbol | Meaning | In this MVP |
|---|---|---|
| `X_t` | current state | live signal score, phase state |
| `A_t` | actions / signals | advisory bias, suggested size band |
| `E_t` | environment | chaos regime, operator intake state |
| `G` | structure / network | sector flocking, keystone role, diffusion |
| `theta` | parameters | half-life, operator capacity, leverage ceiling |
| `F` | update rule | **deterministic advisory diagnostics — no prediction, no execution** |

`F` does **not** forecast price and does **not** execute. It routes signals
to human review. This is surfaced verbatim as `state_update_model` in the
orchestrator output.

## The operating formula

```
              Signal Strength × Source Independence × Freshness
              × Narrative Durability × Risk/Reward × Learning Value
Quality = ---------------------------------------------------------------
              Noise + Crowding + Chaos + Contradiction
              + Invalidation Ambiguity + Operator Load
```

Exposed as `final_trade_quality_components`. The literal product/sum
(`raw_trade_quality`, `numerator_product`, `denominator_sum`) is kept for
transparency, but the advisory bias is driven by a numerically stable
normalised ratio of the factor *means* — so one near-zero factor does not
silently zero the whole score. **This is a decomposition for human review,
not an execution signal.**

## The sixteen modules

| # | Module | Function | Real job | Honest limits |
|---|---|---|---|---|
| 1 | Signal Half-Life | `compute_signal_half_life` | `S_live = S0·e^(−λΔt) + reinforcement − contradiction`; buckets fresh/aging/stale/expired | Needs `initial_strength` and/or `age_hours`; else `insufficient_data`. Half-life default 48h. |
| 2 | Source Independence | `compute_source_independence` | 5 models on 1 catalyst ≠ 5 confirmations; missing citations downgrade | Catalyst similarity is a hash of text fields, not semantic. |
| 3 | Narrative Cascade | `detect_narrative_cascade` | Rises with agreement+momentum; low novelty → crowded/fragile | Inputs are proxies; no real order-flow. |
| 4 | Winner's Curse / Crowding | `compute_winner_curse_risk` | Penalises late entries after consensus + move | `recent_return` is a proxy, not realised PnL. |
| 5 | Phase Transition | `classify_phase_transition` | ignored→forming→confirmed→crowded→exhausted→collapsing | `insufficient_data` if <2 regime inputs. |
| 6 | Ant-Mill Loop Breaker | `detect_ant_mill` | High agreement + low independence ⇒ forced contradiction search + promotion block | Heuristic thresholds. |
| 7 | Queueing Attention Gate | `compute_queueing_attention_gate` | `ρ = arrivals / capacity`; intake normal→freeze | Capacity defaults to 8/day if unset. |
| 8 | Rawlsian Survival Sizer | `compute_rawlsian_survival_sizing` | Survival-first sizing; India ≤4× **ceiling not default**, ROW spot-only | Bands are advisory; no capital model. |
| 9 | Broken Windows / Moltbook Repair | `compute_broken_windows_discipline` | Unrepaired closed losses raise decay & block promotion | Counts come from caller-supplied Moltbook state. |
| 10 | Sector Flocking | `map_sector_flocking` | isolated→leader/follower→crowded flock→unstable rotation | Leader = highest intensity proxy. |
| 11 | Keystone Node | `detect_keystone_node` | Centrality + source diversity → theme/liquidity/sentiment/fragility anchor | Centrality from repeated mentions only. |
| 12 | Firebreak / Support Failure | `detect_firebreak_support` | Invalidation + liquidity + stop distance → cascade brakes | `insufficient_data` if no inputs. |
| 13 | Voting Aggregator | `aggregate_model_votes` | Adjusts naive consensus by independence & contradiction; emits *bias* not order | Direction votes only; no price targets. |
| 14 | Narrative Diffusion | `map_narrative_diffusion` | Second-order beneficiaries; contained→spreading→sector-wide→overheated | Relies on caller `related_tickers`. |
| 15 | Chaos Regime | `classify_chaos_regime` | stable→unstable→whiplash→nonlinear; caps safe forecast horizon | Volatility is a proxy. |
| 16 | Trade Quality Decomposition | `decompose_trade_quality` | Makes the operating formula visible; advisory bias only | **Never** BUY/SELL/EXECUTE. |

`build_complex_systems_diagnostics(...)` orchestrates all sixteen, wires
their outputs together (e.g. independence feeds the ant-mill and voting;
queue load and crowding feed the Rawlsian sizer; broken-windows repair
feeds sizing), and rolls up a single `advisory_decision_bias` from
{`avoid`, `wait`, `watchlist`, `review`, `probe_candidate`,
`insufficient_data`}. **Hard blocks** (ant-mill promotion block,
unrepaired Moltbook losses, nonlinear chaos, operator intake freeze,
survival-sizing `avoid`) cap the bias at `review`/`wait` regardless of
quality.

## Where it is wired

- **Signal reactor** (`scripts/signal_reactor.py`): attached as a *parallel*
  `complex_systems` component + `complex_systems_summary`. It is **not** fed
  into the reactor's criticality / decision-grade math — purely additive for
  human review.
- **Self-test report** (`scripts/self_test_report.py`):
  `_complex_systems_self_check()` proves the layer imports and keeps its
  safety contract; failures surface as `limitations`.
- **Pre-real-money preflight** (`scripts/pre_real_money_preflight.py`): eighth
  subcheck; a broken safety contract is a **blocking** regression. The layer
  can never unlock execution.

## Safety contract

Every output carries:

```
safety.advisory_status       == "ADVISORY_ONLY"
safety.execution_gate        == "LOCKED"
safety.broker_api_called     is False
safety.ai_execution_count    == 0
safety.execution_permission  is False
safety.can_execute           is False
safety.broker_order_id       == "NONE"
safety.human_review_required is True
```

The module is pure: no DB writes, no live API, no filesystem writes, no
broker calls, no AI execution. Missing data degrades to
`wait` / `review` / `insufficient_data` — **never** to a buy.
