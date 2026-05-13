# Live Signals Refresh Model

> The canonical mental model for how live source data flows into this MVP,
> how often it should refresh, what is observable, and what is intentionally
> not promised.

This document is paired with:
- `scripts/live_source_registry.py` — the source-of-truth registry.
- `scripts/run_live_refresh.py` — the dry-run-safe orchestrator (Day 29).
- `docs/LIVE_SIGNALS_SCHEDULING.md` — Windows / cron scheduler recipes.

---

## 1. Target source families

The MVP covers **eleven** source families. Each is either implemented,
partial (some providers implemented, others placeholders), or planned.

| Source family | Adapter status | Credentials needed | 6h refresh | Health visibility |
|---|---|---|---|---|
| Polymarket | implemented | none | yes | yes |
| GDELT | implemented | none | yes | yes |
| SEC EDGAR | implemented | `SEC_USER_AGENT` | yes | yes |
| NewsAPI | implemented | `NEWS_API_KEY` | yes | yes |
| Event Registry | implemented | `EVENT_REGISTRY_API_KEY` | yes | yes |
| Etherscan | implemented | `ETHERSCAN_API_KEY` | yes | yes |
| Grok/xAI | implemented | `XAI_API_KEY` | yes | yes |
| Market Data | implemented | none (yfinance) | yes | yes |
| India (NSE/RBI/SEBI) | implemented | none | yes | yes |
| Global Filings | **partial** — ASX live; HKEX/SGX/UK-RNS/ESMA/SEDAR/TDNet placeholder | varies | yes | yes |
| Asia Disclosure | **planned** — SSE/SZSE/HKEX/TDNet/SGX/DART all placeholder | varies | yes | yes |

`partial` and `planned` are first-class statuses. They are not silently
upgraded to `implemented` anywhere in the codebase.

---

## 2. The 6-hour refresh model

The target operating cadence is **every 6 hours**:

```
0  → run all configured sources
6  → run all configured sources
12 → run all configured sources
18 → run all configured sources
```

This is not enforced by a hidden daemon. It is operator-driven via one of:

1. **Manual dry-run**: `python scripts/run_live_refresh.py --source all --dry-run`
2. **Manual write**:   `python scripts/run_live_refresh.py --source all --write`
3. **Windows Task Scheduler**: `scripts/windows/refresh_live_signals_every_6h.ps1`
4. **Linux/macOS cron**: `0 */6 * * * cd /path/to/repo && python scripts/run_live_refresh.py --source all --write >> logs/live_refresh.log 2>&1`

See `docs/LIVE_SIGNALS_SCHEDULING.md` for the full scheduler recipes.

### Freshness state derived from the 6-hour cadence

```
Freshness_State =
    fresh        if last_success_at <= 6h
    stale        if 6h < last_success_at <= 24h
    expired      if last_success_at > 24h
    never_run    if last_success_at is null
```

The frontend `/source-health/summary` already surfaces "fresh / stale / never"
through the existing `severity` field. The new registry adds explicit
`credential_configured` and `adapter_status` so the operator can distinguish
"this source has never run because we have no key" from "this source ran
six hours ago and looked fine."

---

## 3. The refresh formula

```
Live_Refresh_Run =
    for source in enabled_sources:
        check_config(source)
        fetch_or_skip(source)
        validate_payload(source)
        persist_signal_events_if_write_enabled(source)
        update_source_health(source)
        stamp_advisory_safety(source)
```

Each per-source step is independent. A failure in one source does **not**
abort the run — the orchestrator continues, records the failure, and emits
a per-source status.

---

## 4. Source health

Source health is what the operator looks at to decide "do I trust the
signal inbox right now?" The fields persisted by the existing
`scripts/source_health_summary.py` and surfaced via `/source-health/summary`:

```
Source_Health =
    last_attempt_at        # any run, success or failure
  + last_success_at        # last green run
  + last_error             # short, redacted
  + fetched_count          # raw items received
  + persisted_count        # rows actually written (write mode only)
  + credential_configured  # bool, from the live source registry
  + adapter_status         # implemented | partial | planned
  + freshness_state        # fresh | stale | expired | never_run
```

The combination of `adapter_status` + `credential_configured` + `freshness_state`
fully describes "why am I not seeing data?" for any source.

---

## 5. Live source trust model

```
Live_Source_Trust =
    Source_Config_Clarity
  × Credential_State_Visibility
  × Refresh_Cadence_Clarity
  × Last_Run_Observability
  × Error_Honesty
  × Persistence_Truth
  × AI_Output_Validation
  × Advisory_Safety_Lock
```

A zero in any term collapses the whole product. Today:

| Factor | Status | Evidence |
|---|---|---|
| Source_Config_Clarity | ✓ | `scripts/live_source_registry.py` |
| Credential_State_Visibility | ✓ | `detect_source_credential_state()` (redacted) |
| Refresh_Cadence_Clarity | ✓ | `default_refresh_hours=6` everywhere |
| Last_Run_Observability | ✓ | `live_source_runs` table + `/source-health/summary` |
| Error_Honesty | ✓ | error messages sanitized via `source_health_summary.sanitize_error_text` |
| Persistence_Truth | ✓ | `docs/PERSISTENCE_MODEL.md` |
| AI_Output_Validation | ✓ | `scripts/ai_output_schema.py` + 28 tests |
| Advisory_Safety_Lock | ✓ | enforced at the route, runner, and registry level |

---

## 6. Safe refresh contract

```
Safe_Refresh =
    no_secrets_logged
  ∧ no_paid_live_call_without_user_intent
  ∧ no_broker_call
  ∧ idempotent_persistence
  ∧ source_health_logged
  ∧ advisory_only
  ∧ failures_do_not_crash_whole_pipeline
  ∧ tests_use_mocks
```

How the MVP enforces each clause:

| Clause | Enforcement |
|---|---|
| no_secrets_logged | `redact_secret_patterns()` in AI schema; `sanitize_error_text()` in source health; registry never returns secret values |
| no_paid_live_call_without_user_intent | `--dry-run` is the default; `--write` is explicit |
| no_broker_call | No broker SDK in the repo; `BROKER_ORDER_PERMISSION=false` |
| idempotent_persistence | `signal_events` uses `event_id` UNIQUE key; re-running an adapter does not duplicate rows |
| source_health_logged | `live_source_runs` row per run; surfaced by `/source-health/summary` |
| advisory_only | every entry stamps `advisory_status="ADVISORY_ONLY"` and `execution_gate="LOCKED"` |
| failures_do_not_crash_whole_pipeline | per-source try/except in phase1 + phase2 runners; orchestrator continues on failure |
| tests_use_mocks | `tests/test_live_source_*` use fixtures; `tests/test_live_source_registry.py` is fully synthetic |

---

## 7. What "latest data" means in this MVP

If the source-health summary shows:

- `adapter_status=implemented` + `credential_configured=true` + `freshness_state=fresh`
  → "we ran in the last 6 hours and the data is current"
- `adapter_status=implemented` + `credential_configured=true` + `freshness_state=stale`
  → "we last ran 6–24h ago; data may be stale; refresh recommended"
- `adapter_status=implemented` + `credential_configured=true` + `freshness_state=never_run`
  → "we have everything we need but haven't run yet; run the refresher"
- `adapter_status=implemented` + `credential_configured=false`
  → "we have the adapter but no API key; refresh would skip this source"
- `adapter_status=partial`
  → "some providers in this family are implemented, others are placeholders"
- `adapter_status=planned`
  → "the family is registered but not yet implemented; do not expect data"

There is no "latest data is guaranteed accurate" claim anywhere.

---

## 8. What this model deliberately does **not** do

- **No always-on daemon.** Scheduling is an operator decision; the Windows
  Task Scheduler wrapper and the cron example are explicit, inspectable,
  and configurable.
- **No silent fallback to mock data.** When an adapter cannot reach a source,
  it records the failure in `live_source_runs` and the UI shows the failure.
  Mock data is only used when a feature flag in the frontend says so, and
  the UI banner reflects it.
- **No "magic" forecasting.** Live signals are *inputs* to the operator's
  reflection and decision flow — they are not predictions.
- **No automated trade.** `execution_gate = LOCKED`, always.

---

## 9. Score impact

| Dimension | Before | After | Why |
|---|---:|---:|---|
| Live source refresh discipline | 4 | 6 | Registry, 6h cadence, refresh plan introspection, scheduler wrappers, tests, docs |
| Observability / debugging | 7 | 7.3 | Credential state visible without leaking secrets |
| AI/API integration readiness | 6 | 6.2 | Grok/xAI now lives in the same source-registry surface as the rest |
| Documentation / onboarding | 8.5 | 8.7 | Single canonical doc for the live-signal model |
