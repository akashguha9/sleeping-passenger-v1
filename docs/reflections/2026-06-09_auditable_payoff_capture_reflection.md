# 2026-06-09 — Make the Demoter Harder to Fool (Auditable Payoff Capture)

> **Status:** strategy reflection + integration record. Shipped an auditable
> diagnostic layer on `signal_payoff_capture_estimator.py` (explanatory-only;
> no change to demotion math). Momentum + calibration-audit pieces are
> doctrine/backlog (blocked on time-series / historical-outcome feeds).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `execution_permission = false`

## 0. The reflection in one line

> *Move from "score says weak capture" to "here is exactly where value leaks
> before it reaches the owner, how confident we are, and what evidence would
> prove us wrong."*

This is a meta-upgrade to the payoff-capture demoter shipped 2026-06-08. Its own
prioritisation is explicit: **better explanations first, not new scoring** —
make the demoter auditable, not more aggressive.

## 1. Shipped — auditable Payoff-Capture Diagnostic (Priorities 1, 2, 7 + false-house)

`scripts/signal_payoff_capture_estimator.py` now emits a `diagnostic` block on
every payoff-capture record. **Explanatory-only**: it never changes
`payoff_capture_risk` or `capture_grade`, so every P1/P2/P3 invariant holds
unchanged (`test_J`/`test_L`: expanded IDS ≤ P1).

Fields (each `unknown`/`insufficient_evidence` when data is absent — no guessing):

- `gross_to_margin_capture` — does revenue convert to operating profit? (operating margin)
- `profit_to_cash_capture` — does profit convert to cash? (OCF / net income)
- `cash_to_owner_capture` — does cash reach equity after debt/capex/dilution? (FCFE / net income)
- `bargaining_capture` — pricing power − customer/supplier dependence − platform toll
- `primary_value_leak` — upstream-to-downstream attribution: one of
  `weak_margin_capture`, `weak_cash_conversion`, `working_capital_drag`,
  `capex_burden`, `debt_or_interest_burden`, `platform_or_intermediary_toll`,
  `supplier_power`, `customer_power`, `dilution_or_minority_leakage`,
  `none_detected`, `insufficient_evidence`
- `owner_capture_confidence` — `high`/`medium`/`low` from count of real (non-proxy) evidence points
- `false_house_risk` (Priority 3) — "player in a house costume": big reach (GMV/
  distribution) but weak toll economics (low take-rate, thin margin/cash, high
  incentives/churn). `high`/`low`/`not_evaluated`.
- `falsification_hint` (Layer 7) — concise statement of what evidence would
  weaken/remove the demoter (e.g. "OCF/Net Income > 0.8 for 2 consecutive periods").

### Representative cases (synthetic; minimal fixtures omit market-structure so headline grade is WEAK — the diagnostic is what differentiates)

| Case | primary_value_leak | confidence | false_house |
|---|---|---|---|
| high revenue / weak margin | `weak_margin_capture` | high | not_evaluated |
| high profit / weak cash | `weak_cash_conversion` | high | not_evaluated |
| strong cash / capex burden | `capex_burden` | high | not_evaluated |
| platform / toll risk | `platform_or_intermediary_toll` | high | **high** |
| insufficient evidence | `insufficient_evidence` | low | not_evaluated |

## 2. Deliberately NOT shipped (doctrine / backlog)

- **Capture momentum (Priority 4)** — Δ over time (margin, OCF/NI, receivable
  days, debt/EBITDA). The fresh-discovery candidate carries no prior-period
  series, so this would be `insufficient_evidence` in production today. Doctrine
  until a per-ticker time-series feed exists.
- **Demoter audit table + outcome calibration (Priority 5, Layer 6)** — requires
  historical signal→outcome data. The repo's calibration corpus already honestly
  reports `INSUFFICIENT_EVIDENCE` (no historical model_probability); wiring a
  demoter-audit table is the right next step once forward outcomes mature, not a
  fabricated metric now.
- **Role / lane / research-depth / watchlist labels** — the reflection notes
  these are advisory-safe (unlike sizing). True, but they are portfolio-framing,
  not interpretation-defense; kept out to preserve module focus.

## 3. Why this respects the locks

The diagnostic is explanatory metadata. It introduces no allocation, no position
sizing, no buy/sell, no role/lane output, and does not make demotion more
aggressive (`test_diag_does_not_change_risk_or_grade`). A high `false_house_risk`
or a named `primary_value_leak` only *explains* an existing penalty; it never
unlocks anything. Expanded IDS remains ≤ P1.

## 4. The maturity arc this advances

    Signal → Demoter → Evidence → Confidence → Falsification → (Outcome calibration)
                       └──────── shipped 2026-06-09 ────────┘   └ backlog (data-gated) ┘
