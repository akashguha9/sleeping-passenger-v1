# Private Recovery Runbook (Sprint 10C)

This runbook is for the **operator alone**. It is not a public document.
It assumes a single-user, local MVP, advisory-only deployment. None of
the steps below trade, place orders, contact a broker, or unlock the
execution gate. The recovery flow is reconstructive only.

> Paired tools:
> - `scripts/backup_local_state.py` — bundles DB + paper ledger + last summary
> - `scripts/verify_backup.py` — checksums + SQLite integrity_check
> - `scripts/backup_db.py` — older, DB-only safe SQLite copy (still works)
> - `docs/LIVE_SIGNAL_REFRESH.md` — re-registering the 6-hour scheduler
> - `docs/PRIVATE_OPERATOR_DAILY_CHECKLIST.md` — daily ritual that uses these

---

## 0. What private state actually lives on this laptop

| Artifact | Path | Backed up by this script? |
|---|---|---|
| Local SQLite DB | `runtime/mvp_local.db` | Yes (hot-copy via `sqlite3.backup()`) |
| Paper ledger working copies | `exports/paper_trade_*.csv` | Yes |
| Paper ledger template | `exports/paper_trade_template.csv` | Yes |
| Last refresh summary | `logs/live_signal_refresh_summary.json` | Yes |
| Refresh log file | `logs/live_signal_refresh.log` | Only with `--include-logs` |
| `.env` (API keys + `MVP_API_TOKEN`) | `.env` | **NO** — back up manually |
| Source code | Git working tree | Tracked in GitHub (`origin/main`) |
| Scheduled task registration | Windows Task Scheduler | Re-register via PS1 script |

`.env` is never copied. Treat it as a separate secret — put a copy in a
password manager, an encrypted USB stick, or another secure offline vault.

---

## 1. Routine backup (run daily)

Dry-run first to see exactly what will be copied:

```powershell
python scripts/backup_local_state.py --dry-run
```

Real backup to the default location (`backup_local_state/<UTC-stamp>/`):

```powershell
python scripts/backup_local_state.py
```

To a different drive or external folder:

```powershell
python scripts/backup_local_state.py --output D:\sleeping-passenger-backups
```

Include the rolling log file (only if you want a full forensic record):

```powershell
python scripts/backup_local_state.py --include-logs
```

The script always writes a `manifest.json` containing the UTC timestamp,
the current git commit, a per-file sha256, and the advisory-only safety
stamps. The default output directory `backup_local_state/` is gitignored.

---

## 2. Verify a backup (always do this immediately)

```powershell
python scripts/verify_backup.py backup_local_state/20260516T090717Z
```

This checks every file against the manifest checksums and runs
`PRAGMA integrity_check` on the copied SQLite DB **read-only**. It will
never touch the live `runtime/mvp_local.db`.

Exit code is 0 on PASS, non-zero on FAIL. Skip the integrity check if
you already know SQLite is unavailable on the restore machine:

```powershell
python scripts/verify_backup.py <backup_dir> --skip-db-integrity
```

---

## 3. Restore from a verified backup

This is a **manual file copy**. There is no destructive automation.

```powershell
# 1. Stop anything that might be writing to the DB.
.\scripts\windows\stop_mvp_stack_silent.ps1   # if registered
Get-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh |
    Disable-ScheduledTask                       # pause cadence during restore

# 2. Move the current DB aside (do not delete).
$ts = Get-Date -Format yyyyMMdd-HHmmss
Move-Item runtime\mvp_local.db "runtime\mvp_local.db.before-restore-$ts"

# 3. Copy the backup DB into place.
Copy-Item "<backup_dir>\runtime\mvp_local.db" runtime\mvp_local.db

# 4. Restore paper ledger CSVs by hand. The script makes no decision
#    about which working copy you want to keep.
Copy-Item "<backup_dir>\exports\paper_trade_2026Q2.csv" exports\

# 5. Re-enable the scheduler and run a dry-run refresh.
Enable-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh
.\scripts\windows\run_live_signal_refresh_once.ps1
```

Then verify the live DB independently:

```powershell
python scripts/local_mvp_audit.py
```

---

## 4. Restore `.env` manually

`.env` is intentionally outside the backup script. The recovery steps:

1. Open your password manager / encrypted vault.
2. Copy the entire `.env` body back to `<repo>/.env`.
3. Confirm by running:

```powershell
python - <<'PY'
import os
keys = ("MVP_API_TOKEN", "XAI_API_KEY", "NEWS_API_KEY", "EVENT_REGISTRY_API_KEY",
        "ETHERSCAN_API_KEY", "SEC_USER_AGENT")
print({k: bool(os.environ.get(k)) for k in keys})
PY
```

Do not commit `.env`. The repo already gitignores it.

---

## 5. Reinstall the Windows scheduled task (after a fresh clone)

```powershell
# From an Administrator PowerShell:
cd <repo-root>
.\scripts\windows\register_live_signal_refresh_task.ps1 -Force
```

This is the Sprint 10B hardened script — it now refuses to declare
success unless `Register-ScheduledTask` succeeded AND a subsequent
`Get-ScheduledTask` lookup verified the task. Access-denied prints
explicit "re-run in an elevated PowerShell" guidance.

Confirm with:

```powershell
Get-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh
Get-ScheduledTaskInfo -TaskName SleepingPassengerLiveSignalRefresh
.\scripts\windows\run_local_mvp_audit.ps1
```

The audit now surfaces `state / last_run / next_run / last_result` in
one block.

---

## 6. Fresh-clone recovery (laptop died entirely)

```powershell
# 1. Clone from origin.
git clone https://github.com/akashguha9/sleeping-passenger-v1.git
cd sleeping-passenger-v1

# 2. Recreate the venv and install deps.
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

# 3. Build the frontend.
cd frontend
npm ci
npm run build
cd ..

# 4. Restore .env manually from your secure vault.

# 5. Restore the DB + paper ledger from your latest verified backup
#    (see sections 2 + 3).

# 6. Re-register the scheduled task in an Administrator PowerShell.
.\scripts\windows\register_live_signal_refresh_task.ps1 -Force

# 7. Run the audit.
.\scripts\windows\run_local_mvp_audit.ps1
```

If you do not have a recent backup, the system loses paper-ledger history
and reconciliation outcomes. The source code, live source registry, and
schema are recoverable from git; the operator-recorded judgement is not.

---

## 7. Weekly restore drill (do this for real)

Once a week, pick a recent backup directory and run a **dry-run restore
to a separate directory** so you know the bytes are good:

```powershell
$drill = "C:\Temp\sp-restore-drill"
Remove-Item $drill -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $drill | Out-Null
Copy-Item "<backup_dir>\*" $drill -Recurse

python scripts/verify_backup.py $drill
```

If verify fails, the backup is bad — **fix the backup pipeline, not the
restore**. Do not silently overwrite the next backup.

---

## 8. What this runbook does NOT do

- It does not authorize a trade.
- It does not connect to a broker.
- It does not unlock the execution gate.
- It does not claim any backed-up paper-trade outcome is "alpha".
- It does not copy `.env` or any secret material.
- It does not push the backup anywhere — it is local-only by design.

Safety stamps remain in force across every step:

```
ADVISORY_ONLY = true
HUMAN_EXECUTION_REQUIRED = true
execution_gate = LOCKED
BROKER_ORDER_PERMISSION = false
AI_EXECUTION = 0
broker_api_called = false
execution_permission = false
can_execute = false
PAPER_TRADE_ONLY = true for paper rows
REAL_CAPITAL_AT_RISK = false for paper rows
```

If you ever find yourself running this runbook *to* enable trading,
stop. This is a recovery procedure for a private advisory MVP, not a
deployment runbook for autonomous execution.
