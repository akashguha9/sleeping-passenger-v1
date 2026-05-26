# Private Beta — Thin-Slice Design

> Advisory-only.  This document describes the **smallest** change to the
> local-first MVP that would make it usable by a hand-picked private-beta
> operator other than the project author, **without** turning into a
> public SaaS.

## What "private beta" means here

- Two to ten trusted operators, each running their own copy of the
  Sleeping Passenger MVP.
- Each operator's data stays on their machine OR on a small hosted DB
  that only they have credentials for.
- No multi-tenant fan-out, no billing, no public sign-up.
- All the advisory safety contracts continue to apply: no broker
  execution, no order placement, no API trading writes.

## What is **NOT** in scope for private beta

- Public sign-up.
- Multi-tenant SaaS data isolation.
- Hosted broker integration.
- Real-money trading.

If any of these become in-scope, the readiness report stays capped and a
separate public-SaaS sprint is required.

## Thin-slice axes (mapped to scoring dimensions)

| Axis            | Definition                                                          | Local-first stub                                   |
|-----------------|---------------------------------------------------------------------|----------------------------------------------------|
| Auth            | Real multi-user auth (token, session, or SSO)                       | `LocalApiTokenPanel` — single-operator placeholder |
| HostedDB        | A hosted DB the operator can point at via env var                    | `runtime/mvp_local.db` SQLite                       |
| UserIsolation   | Per-user namespace inside the DB                                    | Single-namespace by design                          |
| StagingDeploy   | One-shot staging URL that runs the canary                           | `docs/HOSTED_CANARY.md` describes the contract      |
| Monitoring      | Health/metrics endpoints + log retention                            | `runtime/release/release_gate_proof.json` artefact  |
| Legal           | Privacy + license disclosures                                       | `docs/LEGAL_PRIVACY_NOTES.md`                        |
| Backup          | Restore drill that proves backups are real                          | `scripts/backup_local_state.py`                      |

## Readiness math

The readiness report (`runtime/release/private_beta_readiness_report.json`)
combines these axes with the spec weights:

```
PrivateBetaScore = 10 × (
    0.20×Auth + 0.20×HostedDB + 0.15×UserIsolation
  + 0.15×StagingDeploy + 0.10×Monitoring + 0.10×Legal + 0.10×Backup
)
```

Until real Auth and HostedDB ship, ``PrivateBetaScore`` is capped at
~6.2.  Until a staging deploy is up, the cap is closer to ~5.5.

## Phasing

1. **Now**: design docs + readiness report (this sprint).
2. **Next**: a single-tenant local stub for `UserIsolation` (per-user
   namespace inside the local DB) so the readiness math has an honest
   "0.5 for design-only" → "1.0 for tested stub" path.
3. **Later**: real Auth and hosted DB selection.  Each must come with
   its own contract test before it lifts the cap.

## Safety invariants that never relax

- `advisory_status = ADVISORY_ONLY`
- `execution_gate = LOCKED`
- `broker_api_called = false`
- `ai_execution_count = 0`
- `predictive_claim_allowed = false` until calibration unlocks
- Public SaaS readiness stays NOT_TARGETED_THIS_YEAR
