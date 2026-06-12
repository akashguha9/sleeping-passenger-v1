# Live Surface — which code can actually touch the user

Generated from real imports by `scripts/live_surface_census.py`
(`--json` for machine output) and **pinned by
`tests/test_live_surface.py`** — this document cannot silently rot:
the guard fails CI if the map and the code disagree.

Two consecutive forensic audits misclassified `src/scoring` as dead
code because the repo had no authoritative answer to *"which `src/`
modules can influence a number the operator sees?"*. This is that
answer.

## The three lanes

| Lane | Count (2026-06-12) | Meaning |
|---|---|---|
| **api_lane** | 71 modules | Transitively imported by `scripts/api_server.py`. The ONLY code that can influence user-facing API output. Every score in the UI traces here. |
| **batch_lane** | 31 modules | Reachable only from the documented standalone CLIs (`run_scoring`, `run_paper_trading`, `run_ingestion`, `run_dashboard`, `run_live_refresh`, `refresh_live_signals`, `run_live_sources_phase1`, `kalshi_live_smoke`, `import_outcomes`; README "Run scoring"). Real, supported, operator-run code — not dead, not API. |
| **quarantine** | 6 modules | Reachable from NO entry point. Pinned exactly; may not grow. |

**`src/scoring` verdict (formal):** batch lane. It is the prediction-
market batch scorer behind `python scripts/run_scoring.py --summary`
(README), tested by 24 test files. It is not dead, and it is proven
unable to affect API output (`test_scoring_stack_is_batch_lane_not_dead_and_not_api`).

## Quarantine — wire or retire

Each entry is tested-but-unwired (or wholly unreferenced). The guard
pins this set both ways: new entries fail CI, and resolving one
requires updating the pin consciously.

| Module | Status | Disposition |
|---|---|---|
| `src.simulator.driver_derivation` | imported only by its own test | wire into pipeline driver scoring, or retire module + test |
| `src.simulator.live_adapter` | imported only by its own test | wire into live-refresh chain, or retire |
| `src.simulator.reality_replay` | imported only by its own test | wire into wind-tunnel/backtest lane, or retire |
| `src.paper.paper_position_tracker` | imported by nothing at all | retire (verify cross-branch first per REPO_DISCIPLINE_CENSUS §6) |
| `src.ingestion.kalshi_public_client` | superseded legacy REST client | retire with `src.models.kalshi_market`, or wire if kalshi returns |
| `src.models.kalshi_market` | used only by the above | follows its client |

## Why this matters for coverage claims

"Tests pass" is only meaningful for code that can run. **Effective
coverage = tests exercising api_lane + batch_lane.** Tests whose only
subject is a quarantined module are inventory, not assurance — the
guard keeps that set visible and frozen so the suite's headline number
stays honest.

## Companion censuses

* `docs/module_census.md` + `docs/REPO_DISCIPLINE_CENSUS.md` — the
  `scripts/` tree census (ACTIVE ratchet at 70, orphan list, deletion
  checklist). This document is the `src/` counterpart.
* `docs/THREAT_MODEL.md` — the security boundary the api_lane sits
  behind.

ADVISORY_ONLY everywhere: no lane contains an execution path, and the
compliance gates verify that independently of this map.
