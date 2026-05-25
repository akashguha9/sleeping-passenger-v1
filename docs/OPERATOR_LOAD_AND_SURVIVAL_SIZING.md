# Operator Load & Rawlsian Survival Sizing

## Purpose

Two operator-protection doctrines, both already implemented as pure engines and
both advisory-only:

1. **Operator overload is a real risk variable.** When signal arrival outruns
   processing capacity, the right advice is *NO NEW RISK / RECONCILE FIRST* — not
   another idea to chase.
2. **Survival sizing beats confidence sizing.** Size is reduced by uncertainty,
   operator load, crowding, low source independence, and unrepaired Moltbook debt.
   India equities allow leverage up to a **4x ceiling** (never a default);
   rest-of-world is spot-only.

## Fields / formulas

### Operator queue (attention gate)

```
queue_pressure_ratio (rho) = arrival_rate / max(operator_processing_capacity, 1)
arrival = open_reconciliation + live_signals + unreconciled_trades + moltbook_pending
no_new_risk_recommended = rho >= 0.85
```
Output: `operator_load_score`, `queue_rho`, `arrival_count`, `intake_state`
(`normal`/`elevated`/`overloaded`/`intake_freeze_recommended`), `no_new_risk_flag`.

### Survival sizing

```
survival_quality = clamp(1 - 0.3*uncertainty - 0.25*operator_load
                           - 0.25*crowding - 0.2*(1 - moltbook_repair))
suggested_position_band in {avoid, watchlist, probe, small, normal}
leverage_ceiling = 4.0 (India) | 1.0 (rest-of-world)   # ceiling, not default
```
Output also carries `survival_reason`, `not_execution_instruction=True`,
`human_review_required=True`.

## Scripts / engines

- `scripts/complex_systems_diagnostics.py`:
  `compute_queueing_attention_gate(...)` (Task 6),
  `compute_rawlsian_survival_sizing(...)` (Task 7).
- `scripts/leverage_safety_layer.py` — regime leverage caps.
- `scripts/attention_proxy_engine.py` — operator attention/heat proxy.
- Surfaced operator-side by `scripts/business_value_report.py` and the cockpit.

## Tests

`tests/test_complex_systems_diagnostics.py`:
- `test_queue_gate_normal_vs_overloaded`, `test_queue_gate_defaults_capacity`;
- `test_rawlsian_india_leverage_capped_not_default` (India ceiling recognised but
  not defaulted; rest-of-world spot-only; uncertainty/load/crowding reduce size).

## Failure modes

- **Capacity unset** → a conservative default capacity is used and flagged
  (`capacity_was_defaulted`).
- **India leverage misread as a default** → guarded: leverage is only *permitted*
  up to the ceiling, default remains 1.0x (spot).

## Advisory-only safety note

Both engines are pure and advisory. Overload produces a *recommendation* to take
no new risk; it never blocks the operator from acting manually and creates no
execution endpoint. Sizing output is explicitly `not_execution_instruction`.

## How to verify locally

```powershell
python -m pytest tests\test_complex_systems_diagnostics.py -q
```
