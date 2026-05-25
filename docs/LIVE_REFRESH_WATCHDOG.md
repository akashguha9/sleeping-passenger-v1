# Live Refresh Watchdog (advisory-only stale-source automation)

## Why scheduled-task success is not the same as source-freshness success

The 6-hour scheduled task (`SleepingPassengerLiveSignalRefresh`) ran cleanly
does not mean the upstream APIs returned fresh data. Adapters can:

- return `TIMEOUT` for GDELT and quietly mark the row as skipped,
- rate-limit Kalshi during a tournament hour and emit no `OK` row,
- skip Prediction Market Disagreement because either Polymarket or
  Kalshi was not fresh.

Subprocess exit code `0` from `scripts/refresh_live_signals.py --write`
only proves the orchestrator did not crash. Health requires
**source timestamp / health actually improved**.

## Two-layer automation model

| Layer | Cadence | Task | What it does |
| --- | --- | --- | --- |
| Refresh | every 6 hours | `SleepingPassengerLiveSignalRefresh` | invokes `refresh_live_signals.py --write` for every configured source |
| Watchdog | every 30 minutes | `SleepingPassengerRefreshWatchdog` | reads the canonical stale-active list and retries only the sources that have aged past TTL |

The watchdog reuses the same `compute_source_freshness` helper that backs
the cockpit `/live-sources/status` endpoint, so the two cannot disagree
about which sources are stale.

## Current stale-source scenario (as of the last cockpit screenshot)

Stale active sources:

- Kalshi
- GDELT
- Prediction Market Disagreement

Excluded optional / not-configured:

- Etherscan (no `ETHERSCAN_API_KEY` set)

## Source state taxonomy

| State | Meaning |
| --- | --- |
| `OK` / `FRESH` | adapter returned successfully within the TTL window |
| `STALE` | data older than the TTL but newer than 2× TTL |
| `OVERDUE` | data older than 2× TTL |
| `TIMEOUT` | upstream request timed out — retryable |
| `RATE_LIMITED` | upstream throttled — retryable |
| `SKIPPED` | adapter skipped for a structural reason (missing credential, planned adapter) |
| `CONFIG_MISSING` | required env var unset |
| `OPTIONAL_CONFIG_MISSING` | optional source (e.g. Etherscan) without a key — **excluded** from the failure count |
| `DEGRADED` | adapter ran but quality fell below threshold |
| `DEGRADED_PARENT_STALE` | derived source whose parent is stale (e.g. disagreement when Kalshi is stale) |
| `UNHEALTHY` | repeated failures past the retry budget |

## Per-source notes

### Kalshi
First-class registry source. Refresh path: `refresh_live_signals.py
--sources kalshi`. When stale, the watchdog retries it explicitly and
records `last_refresh_attempt_at` / `last_refresh_error` /
`last_refresh_skipped_reason`. Kalshi is **not** treated as
`optional_config_missing`: it has no required env var. If the upstream
API is unavailable, the watchdog truthfully records the timeout reason
rather than masking it.

### GDELT
Core tier source. Retryable timeout. `GDELT_TIMEOUT_SECONDS` env var
tunes the upstream timeout. The watchdog retries GDELT and never
classifies a timeout as `optional_config_missing`.

### Prediction Market Disagreement
Derived signal. Parents: Polymarket and Kalshi. The watchdog will only
invoke `prediction_market_disagreement_scanner.py --write` when both
parents are `FRESH` in the snapshot built **after** the refresh attempt
completes. If a parent remains stale, the watchdog records
`derived_source_dependency_status.prediction_market_disagreement` with
the parent freshness states and leaves the derived row in a truthful
stale state.

### Etherscan
Optional. Without `ETHERSCAN_API_KEY` (or one of `ETHERSCAN_ADDRESS` /
`ETHEREUM_ADDRESS` / `PUBLIC_ETH_ADDRESS`) the source is reported as
`optional_config_missing` and excluded from the watchdog failure count.
The watchdog does not fabricate addresses to make Etherscan look
configured.

## Manual commands

```powershell
# Full bulk refresh (what the 6-hour task runs):
python scripts/refresh_live_signals.py --write

# One watchdog tick with defaults (TTL=6h, retries=3):
python scripts/watchdog_refresh_stale_sources.py --ttl-hours 6 --max-retries 3

# Watchdog dev-mode: no sleeps, JSON to stdout:
python scripts/watchdog_refresh_stale_sources.py --ttl-hours 6 --max-retries 3 --no-sleep --json

# Operator-readable health summary:
python scripts/source_health_summary.py

# Operator-readable score with per-source rows:
python scripts/source_health_score.py

# Diagnostic for the 6-hour scheduled task:
python scripts/check_live_signal_refresh_task.py --task-name SleepingPassengerLiveSignalRefresh
```

## Registering the watchdog task

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\windows\register_refresh_watchdog_task.ps1"
```

If the task already exists, add `-Force` to overwrite. Access-denied
errors mean the shell isn't elevated — re-run in an Administrator
PowerShell.

## Running and inspecting

```powershell
Start-ScheduledTask -TaskName "SleepingPassengerRefreshWatchdog"

Get-ScheduledTaskInfo -TaskName "SleepingPassengerRefreshWatchdog"

Get-Content .\runtime\refresh_watchdog_summary.json

Get-Content .\logs\refresh_watchdog.log -Tail 80
```

## Final-status meaning

| Status | Exit code | Meaning |
| --- | --- | --- |
| `HEALTHY` | 0 | no active stale sources after this tick |
| `IMPROVED_BUT_STALE` | 0 | at least one source improved; some active stale remain — visibly degraded but the tick did useful work |
| `STALE_UNCHANGED` | 1 | active stale sources remain and nothing improved |
| `ERROR` | 1 | watchdog crashed, snapshot load failed, or DB unavailable |

A status of `HEALTHY` while `stale_sources_after` is non-empty is
forbidden — the watchdog tests assert against this exact lie.

## Safety note

This is advisory-only source-freshness automation. It does not trade.
It does not call brokers. It does not create execution permission. The
watchdog only invokes existing local Python scripts and reads SQLite
metadata; every output stamps:

```
advisory_only:           true
human_execution_required: true
execution_gate:          LOCKED
broker_api_called:       false
can_execute:             false
ai_execution_count:      0
```
