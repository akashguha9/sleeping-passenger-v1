# Architecture Boundaries

Kanté Sprint 2 — Task 8.  As the MVP grows, `scripts/architecture_fitness.py`
keeps the dependency graph honest with cheap **static** import-graph checks
(parsed from source, never executed), enforced by
`tests/test_architecture_fitness.py` so a boundary regression fails CI.

## Layer model

```
1. contracts      advisory_contract, operator_auth        (bedrock; pure)
2. config         config_contract, runtime_config
3. persistence    persistence, schema_migrations           (owns sqlite3)
4. diagnostics    complex_systems_diagnostics, model_signal_normalizer (pure)
5. bridges        complex_systems_sqlite_bridge, moltbook_reconciliation_bridge
6. reactor        reactor_canonical_inputs, signal_reactor, adaptive_signal_router
7. reports        operator_readiness_report, *_report
8. api            api_server
9. frontend       frontend/ (TypeScript)
```

A higher layer may depend on a lower one; the reverse is forbidden.

## Enforced rules (all currently satisfied)

| Rule | Why |
|---|---|
| **Contract purity** — `advisory_contract` / `operator_auth` import no persistence, reactor, API, DB driver, or network | the bedrock everything stamps against must stay dependency-free |
| **Diagnostic purity** — `complex_systems_diagnostics` / `model_signal_normalizer` do not import `sqlite3` | pure scorers; the *bridge* layer owns canonical reads |
| **No broker/execution module** — no script imports a broker SDK (alpaca, ib_insync, oanda, ccxt, …) | advisory-only; the broker is never called |
| **No frontend import in scripts** | the Python backend never depends on the TS frontend |
| **Tests don't write the runtime DB** — `conftest.py` autouse isolation fixture present | historical Moltbook pollution came from tests writing the real DB |

## Score

```
ArchScore = 1 − (violations + circular_imports + hidden_side_effects
                 + runtime_db_writes_in_tests) / (total_modules + 1)
```

## Adding a module

Place it in the right layer and respect the matrix.  If a pure diagnostic needs
canonical data, read it through a **bridge** module (e.g.
`complex_systems_sqlite_bridge`) rather than importing `sqlite3` directly — that
keeps the scorer testable and the boundary intact.
