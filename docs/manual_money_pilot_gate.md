# Manual-Money Pilot Gate

> Advisory-only. This gate governs **what an operator is allowed to rely on**,
> not what the system executes. Sleeping Passenger never places orders, never
> calls a broker, and never authorizes real-money trades. These tiers describe
> how much trust the *operator* may place in the advisory output as evidence
> accumulates.

The gate is driven by `scripts/operational_readiness_audit.py`, whose headline
number is deliberately evidence-penalised:

```
readiness_score = raw_readiness_score
                  * evidence_quality_score
                  * (1 - 0.50 * no_data_ratio)
```

A perfectly-structured, fully-tested but **field-untested** system (zero real
outcomes) scores low on purpose — it cannot pretend to be field-ready.

## Release tiers

| Tier | Required | Meaning |
| --- | --- | --- |
| **Local development** | no `BLOCKER`. `_NO_REAL_OUTCOMES` is acceptable and expected. | Build, test, rehearse. No reliance on performance numbers. |
| **Paper-trading release** | `readiness_score >= 0.70`, no `BLOCKER`, and sections **Dashboard Truthfulness**, **Manual Trade Integrity**, **Reconciliation Integrity** all `PASS`. | Operator may paper-trade and journal outcomes. Still no real-money proof. |
| **Real manual-money pilot** | `readiness_score >= 0.80`, no `BLOCKER`, **no synthetic/live or paper/live contamination**, all financial-metric sample-size gates active, and real outcomes displayed honestly even when small. | Operator may act manually on advisories at their own risk, with eyes open. |

## Why this audit is not (yet) a hard release-gate blocker

`scripts/release_gate.py` aggregates the local deploy preflight into a single
PASS/WARN/FAIL verdict. The operational-readiness audit is **documented as a
pilot-gate input** rather than wired in as a hard blocker because:

1. With **zero real operator outcomes**, the audit correctly grades
   `NOT_READY_NO_REAL_OUTCOMES`. Making that a hard `FAIL` on the release gate
   would block all local development and paper rehearsal — which is the very
   work needed to *produce* real outcomes. That would be a coordination
   deadlock, not a safety improvement.
2. The honest path to a higher grade is **capturing real LIVE_MANUAL closed
   outcomes with auditable provenance** — not lowering thresholds. Once real
   outcomes exist (`mode == MEASURED`), wiring the paper/pilot thresholds above
   into the release gate becomes meaningful.

Until then, run the audit explicitly before any paper/pilot decision:

```
python -m scripts.operational_readiness_audit --format markdown --out docs/operational_readiness_audit.md
python -m scripts.operational_readiness_audit --format json --out runtime/operational_readiness_audit.json
```

## What can never change at any tier

- Advisory-only positioning (`advisory_status = ADVISORY_ONLY`,
  `execution_mode = HUMAN_ONLY`, `broker_api_called = false`,
  `ai_execution_count = 0`).
- No broker execution, ever. No automatic real-money trading, ever.
- Synthetic fixtures and imported backtests can never be presented as live
  performance. Paper outcomes can never be aggregated as real-money outcomes.
- Missing real outcomes surface as `NO_DATA`, never as fabricated confidence.
