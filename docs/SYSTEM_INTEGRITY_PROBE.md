# System Integrity Probe

**Module:** `scripts/system_integrity_probe.py`
**API:** `GET /api/system/integrity` (token-gated read)
**CLI:** `python scripts/system_integrity_probe.py [--json]` — exit 0 on
PASS/DEGRADED, exit 1 on FAIL.

## Role

`/health` answers *is the process alive*; `/health/full` answers *what is
the security posture*. Neither answers the operator's real question after
a deploy, dependency upgrade, or suspicious morning: **does the analytical
machine still work?** This probe does — one read-only sweep:

| Check | What it proves |
|---|---|
| `schema_tables` | every table in the canonical DDL exists |
| `additive_migrations` | sentinel columns from every migration era applied |
| `config_titration` | half-life families load and are positive |
| `config_outcome_contract` | versioned horizons valid, no config problems |
| `config_causal_graph` | curated graph loads, validates, is non-empty |
| `engine_titration_determinism` | same synthetic input twice → byte-identical output |
| `engine_freshness_determinism` | freshness gate deterministic + correct |
| `engine_linguistic_determinism` | lexical extractor deterministic; `UNVALIDATED` honesty labels intact |
| `cascade_honest_degradation` | narrative cascade runs on the real DB and degrades to honest zeros |
| `clock_injection_discipline` | every time-sensitive evaluator accepts `now` |
| `db_path_discipline` | eager `DB_PATH` default ratchet at/below frozen baseline |
| `scope_guards` | private-scope + core-boundary reports clean |

Statuses are `PASS` / `WARN` / `FAIL` per check; overall is `PASS`,
`DEGRADED` (warns only), or `FAIL`.

## Contract

* **Read-only.** The database is opened in SQLite read-only URI mode and
  is *never created* if absent — absence is an honest `WARN`, not a side
  effect. Proven by test: probing a missing path leaves no file behind
  and probing a real DB leaves its bytes identical.
* **Never raises.** Every check is exception-walled; an unexpected error
  becomes a `FAIL` result carrying the exception name.
* **Deterministic.** Given a pinned `now` and unchanged repo/DB state,
  two runs are identical (latency fields excluded).
* **Advisory-only.** Stamped payloads; evaluates software health only —
  `non_claims` says so explicitly.

## The two ratchets

Both encode bug classes this repository actually shipped, frozen so they
cannot grow back (enforced twice: live in the probe, statically in
`tests/test_repo_discipline_ratchets.py`):

1. **Eager `db_path` defaults** (`db_path: Path = DB_PATH`) bind the
   database path at import time and silently ignore test/runtime
   injection. Legacy occurrences are frozen per-file in
   `EAGER_DB_PATH_BASELINE` (58 across three legacy modules); they may
   shrink, never grow. New code uses `db_path: Path | None = None` with
   lazy resolution.
2. **Wall-clock leaks.** A pure evaluator without an injectable clock
   made nine chart-structure CI tests fail purely by calendar passage
   (STALE boundary crossed 2026-06-13). `CLOCK_INJECTED_EVALUATORS`
   registers every time-sensitive evaluator on the runtime path; each
   must accept `now`, and the registry itself may not shrink.

## Degradation drills

`tests/test_defensive_degradation_drills.py` fires hostile inputs at the
live spine — corrupt/scalar/None payloads through the inbox bridge,
hostile item shapes into the titration engine, future-dated candles and
garbage timestamps into the freshness gate, an exploding quote fetcher
into price-truth, malformed causal-graph files — and asserts one
doctrine everywhere: **broken input degrades into an honest, structured,
advisory-stamped state; it never crashes and never fabricates.**
