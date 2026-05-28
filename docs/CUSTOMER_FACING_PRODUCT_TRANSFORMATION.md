# Customer-Facing Product Transformation

## Purpose

Sleeping Passenger started life as an internal signal engine: an
operator's cockpit built around a dense state-machine vocabulary
(MIURA, MURCIÉLAGO, AVENTADOR, GALLARDO, HURACÁN, ISLERO, DIABLO) and
one-off ticker calls. The internal engine is sophisticated, but the
*customer-facing* layer needs to be simple, repeatable, and legible to
a normal retail user who does not share the founder's mental model.

This document explains the transformation from "internal cockpit" to
"customer-facing advisory-only model portfolio research product." The
internal engine remains intact. What changed is the *surface* a
non-operator user sees.

## 1. From Signals to Baskets

The old framing was: "Today's signals: RHM, VALE, ZIM."

The new framing is a small, named set of thematic baskets:

- **Defense Sovereignty Basket** — European/NATO defense exposure
- **Energy Shock Basket** — oil, gas, LNG, energy security
- **AI Infrastructure Basket** — chips, fabs, data centers, cloud
- **Commodity Repricing Basket** — metals, mining, industrial demand
- **Shipping Dislocation Basket** — freight, container, dry bulk
- **India Domestic Compounding Basket** — Indian telecom, banking,
  consumption, infrastructure
- **Cash / Risk-Off Basket** — dry powder and defensive hedges

Why: users understand themes and portfolio exposures better than
isolated stock calls. "Defense Sovereignty Basket, 15%" is something a
non-operator can hold in their head; "buy RHM" is a free-floating
trade idea with no risk-management container around it.

## 2. From Operator Language to User Language

| Internal State | Customer Label | Meaning |
|---|---|---|
| MIURA | Watch | Early signal; not ready yet. |
| MURCIÉLAGO | Strong Watch | Durable signal; still needs confirmation. |
| AVENTADOR | Enter/Add | Suitable for model inclusion within risk limits. |
| GALLARDO | Hold/Manage | Manage existing exposure with discipline. |
| HURACÁN | Momentum Alert | Fast-moving, higher-risk opportunity. |
| ISLERO | Shock Alert | External event requires review. |
| DIABLO | Avoid/Exit Risk | Chaos or contradiction too high. |

The translation lives in `scripts/customer_language.py`. The engine
keeps emitting raw internal states; the customer surface translates at
the edge. Unknown / missing input degrades safely to `Review` — never
to an execution instruction.

## 3. From One-Off Stock Calls to Portfolio Construction

The product now presents:

- target weights per basket
- weight ranges (min / max)
- per-basket risk bands and drawdown triggers
- portfolio-level drawdown rules (review at -10%, defensive at -15%,
  full thesis audit at -20%)
- per-basket rebalance rules (monthly, earnings-cycle, event-driven)
- per-basket invalidation logic ("what would break the thesis")
- basket-level thesis explanations
- a portfolio-level total that always sums to 100%

The default model is **Sleeping Passenger Balanced Research Model**:

- AI Infrastructure Basket: 20%
- India Domestic Compounding Basket: 20%
- Defense Sovereignty Basket: 15%
- Energy Shock Basket: 10%
- Commodity Repricing Basket: 10%
- Shipping Dislocation Basket: 5%
- Cash / Risk-Off Basket: 20%
- **Total: 100%**

## 4. From Trading to Advisory Model Portfolios

The product category is **educational model portfolio research and
decision support**. It is not:

- a broker
- an execution engine
- a copy-trading service
- a financial-advice service
- a guaranteed-return product

Concretely:

- No code path places, cancels, or modifies a broker order.
- `ai_execution_count` is always `0`.
- `execution_gate` is always `LOCKED`.
- `broker_api_called` is always `false`.
- Every customer-facing API response carries
  `advisory_only=true`, `human_execution_required=true`,
  `execution_permission="LOCKED"`, and `no_execution=true`.
- The user remains responsible for their own decisions and should
  consult a licensed advisor where appropriate.

## 5. From Founder-Only System to Repeatable Product

A user should be able to understand a basket without needing the
founder's brain. Each basket carries:

- name
- thesis (plain English)
- representative tickers
- risk level (`Low` / `Medium` / `Medium/High` / `High` / `Extreme`)
- target weight + min/max range
- drawdown trigger
- rebalance rule
- invalidation logic
- customer status (customer-facing label, not internal state)
- advisory disclaimer

The basket registry and model portfolio are pure deterministic
modules; the customer-facing API is read-only; the customer-facing
frontend is a single new page (`/model-portfolio`). Adding a new
basket or rebalancing the model means editing one Python registry,
not the engine.

## Product Mantra

> Sleeping Passenger converts noisy global signals into understandable
> thematic model portfolios, with clear basket weights, risk bands,
> thesis explanations, and advisory-only action labels.

## Safety Language

> This product provides educational research and decision support
> only. It is not financial advice, not a promise of returns, and not
> an instruction to trade. Users are responsible for their own
> decisions and should consult a licensed advisor where appropriate.

## Implementation Summary

| Layer | Module / Path | Purpose |
|---|---|---|
| Translation | `scripts/customer_language.py` | Internal-state → customer-label translation, with safe degradation. |
| Basket taxonomy | `scripts/basket_registry.py` | Seven thematic baskets, ticker→basket mapping, validation. |
| Portfolio | `scripts/model_portfolio.py` | Default model portfolio, weight validation, drawdown rules. |
| API | `scripts/api/routers/customer_router.py` | Read-only `/api/customer/*` endpoints with advisory stamps. |
| Frontend | `frontend/src/app/model-portfolio/page.tsx` | Customer-facing page with hero, summary, allocation table, basket cards, ticker explanations, translation table. |
| Tests | `tests/test_customer_language.py`, `tests/test_basket_registry.py`, `tests/test_model_portfolio.py`, `tests/test_customer_api.py`, `tests/test_customer_frontend_language.py` | Lock down translation, validation, advisory stamps, and forbidden-phrase scans. |

The customer surface routes through five new GET endpoints under
`/api/customer/*`:

- `GET /api/customer/baskets`
- `GET /api/customer/baskets/{basket_id}`
- `GET /api/customer/model-portfolio`
- `GET /api/customer/translate-state/{state}`
- `GET /api/customer/ticker/{ticker}/basket`

Every endpoint is read-only, deterministic, and stamped with the
advisory-only safety contract.
