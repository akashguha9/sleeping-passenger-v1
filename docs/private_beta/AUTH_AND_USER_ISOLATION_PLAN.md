# Auth and User-Isolation Plan

> Design-only.  No real multi-user auth has shipped.  The MVP's only
> auth-shaped surface today is a local API-token gate.

## Threat model assumptions

- Operators run their own copy of the MVP on a machine they trust.
- The local SQLite DB is on disk, not in the cloud, by default.
- The MVP never holds broker credentials — there is no execution.

## Tier ladder

### Tier 0 — Local single-operator (today)

- One copy of the MVP, one operator.
- `LocalApiTokenPanel` shows a single bearer token configured via env.
- All canonical state in `runtime/mvp_local.db`.
- No user concept.  Trivially "isolated" because there is one user.

### Tier 1 — Local multi-namespace stub (thin-slice target)

- Same machine.  One DB.  Different operators get different namespaces
  via a column `owner_id` (or similar) on the mutation tables.
- The advisory contract still gates everything.  ``HUMAN_ONLY`` stays
  the only execution path.
- The probability snapshot table is namespaced the same way.

### Tier 2 — Hosted DB + real auth (out of scope this sprint)

- Hosted Postgres.
- Real auth (Auth0 / Clerk / custom JWT signing).
- Row-level security on `owner_id`.
- Mandatory: backup + restore drill before any operator pairing goes
  live.

### Tier 3 — Public SaaS (intentionally not pursued)

- Multi-tenant.
- Billing.
- Compliance review.
- Public sign-up.

## Stubs to be tested in this sprint

- `private_beta_readiness_report.py` includes a `user_isolation` field
  that is `0.0` if no stub exists, `0.5` if design-only, and `1.0` if a
  testable local stub is present.
- The "testable local stub" is satisfied when a `owner_id` column is
  added to `manual_trades` and `probability_snapshots` and a contract
  test asserts cross-namespace reads are filtered.  That contract test
  is **not yet written**; the field starts at 0.5 (design-only) until
  the test lands.

## What is intentionally not tested in this sprint

- Real auth tokens.
- Real session lifecycle.
- Real password rotation.

Each of those is its own work item, gated by separate readiness math.
