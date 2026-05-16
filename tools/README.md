# tools/ — quarantined, out-of-MVP-scope code

This directory is **not** part of the Sleeping Passenger private-operator
MVP runtime surface. Anything that has been moved here was previously
under `scripts/` and was either:

1. An experimental / reference module that does not contribute to the
   advisory-only decision pipeline, or
2. A scraper / external-data utility whose ongoing maintenance cost
   outweighs its MVP value.

The `scripts/private_scope_guard.py` discipline tool registers every
top-level directory here as a **quarantined tool**, so:

* the scope-guard report explicitly lists them as quarantined,
* the test suite asserts they exist *outside* `scripts/`,
* importing `tools.*` from any module under `scripts/` or `src/` is a
  scope violation,
* deletion is never required — quarantine is reversible.

## Current contents

| Path | Why it is here |
|---|---|
| `tools/gmat_scraper/` | GMAT Club forum scraper + advisory reasoning bridge. Not part of the private-operator MVP. ToS / anti-bot considerations apply — see `tools/gmat_scraper/README.md`. |

## Safety invariants

Quarantined tools inherit the same safety invariants as the MVP:

```
ADVISORY_ONLY = true
HUMAN_EXECUTION_REQUIRED = true
execution_gate = LOCKED
broker_api_called = false
ai_execution_count = 0
execution_permission = false
can_execute = false
```

No code under `tools/` may call a broker, place an order, or grant
execution permission. The private scope guard verifies this is enforced
by file location, not by trust.
