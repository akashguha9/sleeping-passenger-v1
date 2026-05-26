# Kalshi semantic freshness

The Kalshi integration is **read-only, advisory-only, and cannot place
trades**.  It never calls a non-GET endpoint, never logs the
`KALSHI_API_KEY_ID` or the private key path, never stamps
`broker_api_called=true`, and never increments `ai_execution_count`.

This document describes the *truth model* the cockpit, watchdog and the
parent refresh share so a stale Kalshi can be diagnosed precisely.

## Five orthogonal concepts

Before this work the cockpit conflated:

| # | Concept                                  | Source of truth                                      |
| - | ---------------------------------------- | ---------------------------------------------------- |
| A | Scheduled task / process success         | Windows Task Scheduler exit code                     |
| B | Kalshi API / source-health success       | `runtime/release/kalshi_source_health.json`          |
| C | Accepted Kalshi records observed         | `records_allowed` in the health artifact             |
| D | Canonical `signal_events` freshness      | SQLite `signal_events` table                         |
| E | UI live-signal freshness                 | `/live-sources/status` + `/live-signals` API         |

A scheduled task can succeed (A) while the Kalshi API is healthy (B) and
records are accepted (C) — yet canonical `signal_events` remains stale
(D), so the UI shows zero live signals (E).  The fix forces each
concept to be reported on its own axis.

## Formulas

Let `τ` be the current UTC timestamp and `H` the TTL in hours
(default `H = 6`).

```
age_hours(t, τ) =
    +∞ if t is null / unparsable
    max(0, (τ − parse_utc(t)).total_seconds() / 3600) otherwise

fresh_H(t, τ) = 1 if age_hours(t, τ) ≤ H else 0
```

### Canonical freshness

```
K_events = { e ∈ signal_events : lower(e.source_name) = "kalshi" }
latest_kalshi_signal_ts = max{ e.fetched_at : e ∈ K_events }
canonical_live_count_H = | { e ∈ K_events : fresh_H(e.fetched_at, τ) = 1 } |
canonical_signal_fresh = 1[canonical_live_count_H > 0]
```

### Source-health freshness

```
health_artifact = runtime/release/kalshi_source_health.json
source_health_live = 1 iff
    health_artifact exists
    ∧ health_artifact.source_freshness_status = "LIVE_VERIFIED"
    ∧ fresh_H(health_artifact_timestamp, τ) = 1
```

The health timestamp is resolved in this order:
`checked_at_utc → run_at → generated_at → timestamp_utc →
completed_at_utc → attempted_at_utc → file mtime fallback (marked
`timestamp_source="file_mtime_fallback"`).

### Combined semantic freshness

```
kalshi_semantic_fresh = canonical_signal_fresh OR source_health_live
```

The UI **must not** collapse these into one status.

## Status enums

### `api_health_status`

| Value                       | Meaning                                                    |
| --------------------------- | ---------------------------------------------------------- |
| `LIVE_VERIFIED`             | Health artifact fresh and reports the source is live.      |
| `STALE_HEALTH`              | Artifact is older than `H`.                                |
| `HEALTH_ARTIFACT_MISSING`   | No `kalshi_source_health.json` on disk.                    |
| `AUTH_FAILED`               | Artifact reports an auth error.                            |
| `API_ERROR`                 | Artifact reports a non-auth API/HTTP failure.              |
| `UNKNOWN`                   | Could not classify.                                        |

### `canonical_signal_status`

| Value                  | Meaning                                                                                         |
| ---------------------- | ----------------------------------------------------------------------------------------------- |
| `LIVE_CANONICAL`       | Fresh canonical rows present.                                                                   |
| `DUPLICATE_REFRESHED`  | `rows_added = 0`, `rows_refreshed > 0`, latest `fetched_at` fresh.                              |
| `ZERO_FRESH_ROWS`      | Accepted markets observed but no canonical row inserted or refreshed.                            |
| `FILTERED`             | Markets observed but quarantined by allowlist.                                                  |
| `HEALTH_ONLY`          | Source-health live; canonical write intentionally not attempted.                                |
| `STALE_CANONICAL`      | Latest canonical row older than `H`.                                                            |
| `MISSING_CANONICAL`    | No canonical rows.                                                                              |
| `UNKNOWN`              | Could not classify.                                                                             |

### `provider_result`

| Value                          | Meaning                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| `OK_INSERTED`                  | At least one new `signal_events` row written.                        |
| `OK_REFRESHED`                 | No new rows, but ≥1 row's `fetched_at` was refreshed.                |
| `DEGRADED_ZERO_CANONICAL`      | `records_allowed > 0`, `rows_added + rows_refreshed = 0`.            |
| `DEGRADED_FILTERED`            | `records_seen_total > 0`, `records_allowed = 0`, `records_quarantined > 0`. |
| `DEGRADED_HEALTH_ONLY`         | Source-health live, no canonical write expected.                     |
| `ERROR`                        | API / auth / parse / runtime failure.                                |
| `SKIPPED`                      | Explicit configured skip (e.g. missing credentials).                 |

> `rows_added = 0` combined with `OK_FILTERED` is **never** counted as
> full OK.  It is `DEGRADED_FILTERED` or `DEGRADED_ZERO_CANONICAL`
> depending on whether `records_allowed` is zero or positive.

## Retry semantics

The Kalshi phase-1 runner retries up to `KALSHI_MAX_ATTEMPTS` (default 2)
with deterministic back-off (0.5s, 1.0s, 2.0s).  A retry fires when:

- the previous attempt errored (`HTTP_ERROR`, `TIMEOUT`, `AUTH_TRANSIENT`);
- `records_seen_total = 0` (`EMPTY_RESPONSE`);
- accepted markets exist but `rows_added + rows_refreshed = 0`
  (`ACCEPTED_BUT_ZERO_CANONICAL_WRITE`);
- markets observed but all quarantined (`FILTERED_NO_ALLOWED`).

If the final attempt still has `rows_added = 0` and `rows_refreshed = 0`,
the runner classifies the result as `DEGRADED_ZERO_CANONICAL` or
`DEGRADED_FILTERED`.  Retries never count an erroring attempt as success.

## Persistence — `upsert_signal_event_observation`

`scripts/persistence.py` exposes
`upsert_signal_event_observation(event_id, source_name, raw_payload,
fetched_at, ...)`.  On conflict over the unique `event_id` index it
updates `raw_payload`, `fetched_at`, and **re-stamps** the advisory
safety fields.  This guarantees a re-observation refreshes canonical
freshness without breaking the deterministic id used by downstream
joins.

## Advisory invariants (always true)

- `advisory_only = true`
- `human_review_required = true`
- `execution_gate = "LOCKED"`
- `broker_api_called = false`
- `can_execute = false`
- `ai_execution_count = 0`

These are stamped on every row written by the upsert helper and every
artifact emitted by the watchdog / refresh / API layer.

## Runtime paths

All Kalshi runtime artifacts are resolved relative to the repo root,
never `cwd`:

- `runtime/release/kalshi_source_health.json`
- `runtime/release/kalshi_source_health_history.jsonl`
- `runtime/release/kalshi_quarantine.jsonl`
- `runtime/release/kalshi_watchdog_summary.json`
- `runtime/refresh_watchdog_summary.json`
- `runtime/mvp_local.db`

## Operator messages

The cockpit and the watchdog surface a single, plain-English line per
state.  Examples:

> Kalshi API health is LIVE_VERIFIED and canonical live signals are LIVE_CANONICAL.

> Kalshi API health is LIVE_VERIFIED, but canonical live signals are
> ZERO_FRESH_ROWS. Accepted markets were seen, but no fresh
> signal_events rows were inserted or refreshed.

> Kalshi API health is LIVE_VERIFIED, but canonical live signals are
> FILTERED because observed markets were quarantined by allowlist.

> Kalshi source-health artifact is missing and canonical live signals
> are stale.
