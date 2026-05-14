# Advisory-Only Safety Model

> This document is the canonical, human-readable statement of what this
> MVP is and what it is not. Every code change must preserve the
> invariants listed below.

## What this MVP is

A local, signal-refinery / decision-support / operator-discipline
system. Its outputs are:

- diagnostic labels (signal state, reactor state, gallardo block,
  meltdown risk, echo risk, fusion validity, etc.),
- advisory recommendations (`observe`, `watch`, `review_candidate`,
  `human_review_only`, `cool_down`, `decay_archive`, …),
- record-keeping (manual trade log, reflections, AI-discussion
  summaries, reconciliation queue, journal-quality scores, Moltbook
  entries, calibration reports).

Every output carries the safety stamps below.

## What this MVP is NOT

- An autonomous trading system.
- A broker integration.
- An order-placement system.
- An AI-execution system.
- A wallet, custodian, or settlement layer.

There is no code path — in any module, route, or component — that
calls a broker, submits an order, or transfers capital. Auto-execution
is structurally impossible by design.

## Non-negotiable safety invariants

Every backend response and every UI surface must carry these values:

| Field | Required value |
|---|---|
| `advisory_status` | `"ADVISORY_ONLY"` |
| `execution_mode` / `HUMAN_EXECUTION_REQUIRED` | `"HUMAN_ONLY"` / `true` |
| `execution_gate` | `"LOCKED"` |
| `broker_api_called` | `false` |
| `ai_execution_count` | `0` |
| `execution_permission` | `false` |
| `can_execute` | `false` |
| `broker_order_id` | `"NONE"` |

These are verified by:

- `tests/test_signal_inbox_api.py`
- `tests/test_signal_reactor_safety_invariants.py`
- `tests/test_signal_reactor_wiring.py`
- `tests/test_pre_real_money_preflight.py`
- `tests/test_self_test_report.py`
- `tests/test_reactor_calibration_report.py`
- `tests/test_frontend_no_execution_language.py`
- `tests/test_local_security_floor.py`

Any module that *removes* one of these stamps from a response, or
returns `true` for any of the false-only fields, must be rejected at
review.

## Doctrine reminders (one-liners)

- Signal is not truth.
- Signal Reactor is not permission.
- Preflight is not execution.
- Frontend badge is not a recommendation.
- Moltbook learning is not a guaranteed edge.
- Calibration is not certainty.
- Backlog block is primary; reactor enthusiasm cannot override it.
- The operator is one of the pendulums.
- No signal bypasses the veto layer.

See `docs/SIGNAL_REACTOR_MODEL.md` §2 for the full 13-principle list.

## Forbidden language

The frontend must never render — and the backend must never emit —
copy that implies execution. The static scan in
`tests/test_frontend_no_execution_language.py` enforces this. Examples
of phrases that are blocked unless explicitly negated:

- "place order"
- "execute trade"
- "trade now"
- "auto-trade"
- "broker order"
- "broker connected"
- "AI-approved"
- "permission granted"
- "authorized to trade"
- "order ready"

A label like `Broker order: NONE` (record-keeping) is acceptable
because the value is the literal denial `NONE`.

## What changing this document requires

This is doctrine. Edits should be made only when the *structural*
nature of the system changes (e.g., the operator chooses to start
building a separate, sandboxed execution module — in which case
this document must be re-scoped, not weakened).

A pull request that merely *adds* a feature should never need to
edit this document.
