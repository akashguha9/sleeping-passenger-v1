# Live Signals Scheduling (every 6 hours)

> Operator handbook for the 6-hour refresh model. Paired with:
> - `scripts/run_live_refresh.py` (orchestrator)
> - `scripts/live_source_registry.py` (registry of 11 source families)
> - `scripts/windows/refresh_live_signals_every_6h.ps1` (Windows wrapper)
> - `docs/LIVE_SIGNALS_REFRESH_MODEL.md` (the mental model)

The orchestrator never runs in `--write` mode by default. The Windows
scheduler template below also defaults to `--dry-run`. Switching to
`--write` is a deliberate operator action — make sure your API keys are
provisioned and your quotas can absorb every-6-hour calls before flipping.

---

## 1. Manual commands

### Dry-run (default; safe)

```powershell
# Plan-only — never invokes an adapter, lists what would happen.
python scripts/run_live_refresh.py --source all --plan-only

# Dry-run — also a plan, but reads credential state from the env.
python scripts/run_live_refresh.py --source all --dry-run

# JSON output, scripted scheduling.
python scripts/run_live_refresh.py --source all --dry-run --json
```

### Write mode (explicit opt-in)

```powershell
# This still uses the orchestrator's reporting; the actual ingestion calls
# remain in the phase1 / phase2 runners. The orchestrator's --write reports
# "would_write" entries for each source that has the necessary credentials.
python scripts/run_live_refresh.py --source all --write
```

To actually persist signal events, the operator invokes the per-phase runners
directly:

```powershell
python scripts/run_live_sources_phase1.py --source polymarket --write
python scripts/run_live_sources_phase1.py --source gdelt      --write
python scripts/run_live_sources_phase1.py --source sec_edgar  --write
python scripts/run_live_sources_phase2.py --source newsapi        --write
python scripts/run_live_sources_phase2.py --source event_registry --write
python scripts/run_live_sources_phase2.py --source etherscan      --write
python scripts/run_live_sources_phase2.py --source grok_xai       --write
python scripts/run_live_sources_phase2.py --source market_data    --write
python scripts/run_live_sources_phase2.py --source india          --write
python scripts/run_live_sources_phase2.py --source global_filings --write
# asia_disclosure is planned — all providers skip cleanly.
python scripts/run_live_sources_phase2.py --source asia_disclosure --write
```

### Single source

```powershell
python scripts/run_live_refresh.py --source polymarket --dry-run
python scripts/run_live_refresh.py --source grok_xai   --dry-run
```

---

## 2. Windows Task Scheduler — every 6 hours

The wrapper at `scripts/windows/refresh_live_signals_every_6h.ps1` defaults
to `--dry-run`. To register it as a task that runs at 00:00, 06:00, 12:00,
18:00:

```powershell
# From an elevated PowerShell, at the repo root:
schtasks /Create `
    /TN "SleepingPassengerLiveRefresh6h" `
    /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\windows\refresh_live_signals_every_6h.ps1`"" `
    /SC HOURLY /MO 6 /F
```

To remove it:

```powershell
schtasks /Delete /TN "SleepingPassengerLiveRefresh6h" /F
```

### Switching the scheduled task to --write

Don't switch the wrapper script's default. Either:

1. **(Recommended)** Register a second task that explicitly passes `-WriteMode`:

   ```powershell
   schtasks /Create `
       /TN "SleepingPassengerLiveRefresh6hWRITE" `
       /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\windows\refresh_live_signals_every_6h.ps1`" -WriteMode" `
       /SC HOURLY /MO 6 /F
   ```

2. Or run the per-phase runners on a separate schedule — that gives finer
   control over which sources actually persist.

**Logs land in** `logs/live_refresh.log`. The wrapper appends; trim by hand
or with `Clear-Content logs/live_refresh.log` if it grows.

---

## 3. Linux / macOS cron — every 6 hours

```cron
# Dry-run every 6 hours (00:00, 06:00, 12:00, 18:00 local).
0 */6 * * * cd /path/to/sleeping-passenger-v1 && /usr/bin/python3 scripts/run_live_refresh.py --source all --dry-run >> logs/live_refresh.log 2>&1
```

To switch to `--write`, change the line to:

```cron
0 */6 * * * cd /path/to/sleeping-passenger-v1 && /usr/bin/python3 scripts/run_live_refresh.py --source all --write >> logs/live_refresh.log 2>&1
```

---

## 4. Inspecting source health

Whether the scheduler ran or not, the operator can always inspect:

- `GET /source-health/summary` — aggregated per-source health JSON
- `GET /source-health`         — raw `live_source_runs` rows
- `python scripts/run_live_refresh.py --source all --plan-only` — current
  registry + credential state without any side effects

---

## 5. Disabling a source

Three layers, in order of reversibility:

| Layer | Action | Reversibility |
|---|---|---|
| **Cron / Task Scheduler** | Pass `--source <only-the-ones-you-want>` instead of `all` | trivial |
| **Environment**          | Unset the API key env var; the source will be skipped, not failed | trivial |
| **Registry**             | Edit `_SOURCE_REGISTRY` in `scripts/live_source_registry.py` to mark a family `not_configured` | code change |

Prefer the env approach — it is fully observable in the source-health UI.

---

## 6. Avoiding quota burn

- The free tiers of NewsAPI / Event Registry / Etherscan / xAI cannot
  comfortably absorb every-6-hour calls *and* manual debug calls. Pick one.
- The orchestrator skips sources with missing credentials — leave the API
  key unset on machines where you do not want to burn quota.
- For Polymarket and GDELT (no key needed), the constraint is courtesy
  rate-limit; the existing runners already self-throttle.

---

## 7. Avoiding paid-API surprises

- `--write` is **never** the default. If you have just cloned the repo and
  run `python scripts/run_live_refresh.py`, you have not called any paid API.
- The Windows wrapper defaults to `--dry-run`. The `cron` example above also
  defaults to `--dry-run`.
- Switching to `--write` is a separate operator action. Make sure your
  current plan/quota covers four runs per day across every configured
  source.

---

## 8. Rotating API keys

If a key leaks:

1. Rotate at the provider dashboard immediately.
2. Update the value in your local `.env`.
3. Run `python scripts/run_live_refresh.py --source all --dry-run` — the
   per-source `credential_configured` field should still report `true`.
4. Confirm the next scheduled run logs cleanly to `logs/live_refresh.log`.
5. If the key was ever committed to the repo, force-pull a clean clone and
   ensure the leaked commit is purged from your fork as well as origin.
6. Update `docs/SOURCE_TOS_CHECKLIST.md` with a "Last verified" date.

---

## 9. Confirming advisory-only safety

The orchestrator's text output prints, on every run:

```
Advisory: ADVISORY_ONLY  |  Execution gate: LOCKED  |  Broker calls: False
```

The JSON output's envelope and every per-source entry carries:

```json
"advisory_status": "ADVISORY_ONLY",
"execution_gate": "LOCKED",
"broker_api_called": false,
"ai_execution_count": 0,
"human_review_required": true
```

If any of those drift, the test `tests/test_live_refresh_orchestrator.py`
will fail in CI on the next push.
