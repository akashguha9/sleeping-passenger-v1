# Backtest report — <signal name>

> Template for reports produced from `scripts/backtest_advisory_signals.py`
> output. A backtest report without every section below is incomplete and
> must not be quoted.

**Advisory-only.** No orders were or can be placed; returns describe what
the signal pointed at, at reference prices, after assumed costs, had a
human acted.

## Assumptions (mandatory — copy from `report["assumptions"]`)

- Transaction cost per side: `…`
- Slippage: `…`
- Risk-free rate per period: `…`
- Price basis: reference observation prices, not fills.

## Data hygiene

- Samples in: `…` · rejected by temporal guard: `…`
- Rejection reasons (all of them — silent drops hide bias): `…`
- Abstention rate: `…`

## Walk-forward results (`headline_basis` must be quoted verbatim)

| Split | N | Hit rate | Expectancy | Sharpe | Sortino | MDD | Excess vs benchmark |
| ----- | - | -------- | ---------- | ------ | ------- | --- | ------------------- |
| Train | | | | | | | |
| Validation | | | | | | | |
| **Test (headline)** | | | | | | | |

- If `headline_basis` says `IN_SAMPLE_ONLY`: this section may not be
  used to claim expected performance, full stop.
- If test N < 30: quote the small-sample warning alongside every number.

## Regime segmentation (if tagged)

| Regime | N | Hit rate | Expectancy |
| ------ | - | -------- | ---------- |

## Interpretation (human-written)

- What would falsify this result:
- What the result does NOT show:
- Decision: (advisory note only — execution is human, elsewhere, always)
