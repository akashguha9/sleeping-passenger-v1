# Operator Calibration Checklist

Advisory-only. This document — and the module that generates its live
version (`src/alpha/operator_checklist.py`, surfaced on the dashboard
and inside the plumbing v4 case study) — answers one question: **what
must the operator journal for the system to actually improve?**

## The blocker, quantified

Position-candidate verdicts are locked behind outcome-backed
calibration:

```text
calibration_support = 100 × min(1, resolved_records / 50)
records_needed = max(0, 50 − current_resolved_records)
```

The journal currently has ~0 resolved records, so `records_needed = 50`.
No code change can shortcut this; only journaling can.

## Exact journaling requirements

Each advisory outcome needs, per record:

```text
as_of_date                  when the signal was scored
ticker                      what it referred to
original score              score_at_entry at decision time (0-100)
original verdict            the advisory container at decision time
subsequent outcome window   observation horizon (default 30 days)
realized outcome            price_return over the window
drawdown                    worst drawdown inside the window
fundamental confirmation    did filings/earnings later confirm the thesis?
narrative persistence       did attention persist (0-1)?
filing confirmation         did the next filing cycle support the claim?
```

Workflow: log the idea with its score (signal inbox → manual trade
log), then **reconcile** it after the window via the existing
reconciliation flow. Unreconciled entries are skipped with reason
`open_or_unknown_outcome` — they teach the calibrator nothing.

## Data quality score

```text
data_quality_score = 60 × min(1, resolved/50) + 40 × mean(field_coverage)
```

A field counts as covered when at least half the usable records carry
it. The checklist lists `missing_fields` and emits concrete
`next_actions` (reconcile N open entries; capture drawdown at
reconciliation; record score_at_entry; …). When the floor is reached
the next action becomes: re-fit calibration via
`scripts/build_alpha_replay_from_journal.py --fit-calibration` and
review the reliability diagram.

## Why this matters

Every layer above this is already built and tested: bridge, calibration
map, reliability data, gate, bundles. The 50-record journal is the only
input the machine cannot manufacture for itself — by design.
