# Advisory Disclosure

> **Engineering and product honesty — not legal or financial advice.**

## What this software does

This is an **advisory-only**, local, single-operator decision-support tool. It
ingests signals, scores them, helps a person reflect and journal, logs manual
trades the operator entered by hand, and reconciles outcomes for learning.

## What this software does NOT do

- It does **not** place, modify, or cancel any broker order.
- It does **not** execute trades, automatically or otherwise.
- It does **not** connect to a broker, custodian, wallet, or settlement layer.
- It does **not** provide personalized financial advice or act as your
  financial advisor.
- It does **not** guarantee that any signal, score, or AI interpretation is
  correct, complete, or current.

## A human makes the final decision

Every output of this system is an interpretation, a score, or a flag for
**human review**. **A human makes the final decision** on every trade. The
final human decision is required before any action in the real world; the
software cannot and will not act on the operator's behalf.

Auto-execution is structurally impossible by design: there is no code path in
this repository that calls a broker or submits an order. The
`scripts/compliance_preflight.py` and `scripts/release_gate.py` checks fail the
build if a broker route or an unlocked execution flag ever appears.

## Safety invariants

```
advisory_status      = ADVISORY_ONLY
execution_gate       = LOCKED
execution_permission = false
can_execute          = false
broker_api_called    = false
ai_execution_count   = 0
human_review_required = true
```

## Your responsibility

Any trade or decision you make using this software is **entirely your own**.
You are responsible for verifying data, complying with the terms of service of
every data source, and obtaining qualified legal and financial advice before
acting.
