# WINDOWS_BACKUP_TASK — automate the local DB backup

> **What this is.** The `runtime/mvp_local.db` SQLite file is the source of
> truth for everything you've recorded: reflections, manual trades,
> reconciliations, the moltbook. Lose it, lose your trade journal. This
> doc explains how to make Windows back it up on a schedule using the
> Python script that already ships with the repo.

> **What this is not.** A disaster-recovery plan. A hosted-backup story.
> Off-machine backup. This automates exactly one thing: a daily local
> snapshot of the DB into `runtime/backups/`. Moving those snapshots
> off-machine (OneDrive sync, external drive, etc.) is a separate
> operator habit.

## Files

- `scripts/backup_db.py` — Python backup script. Uses the SQLite hot-copy
  backup API so it never mutates the source DB and is safe to run while
  the API server is up.
- `scripts/windows/backup_sleepingpassenger_db.ps1` — PowerShell wrapper
  that you point Task Scheduler at. Resolves the repo root, picks a
  Python interpreter, and forwards arguments.

## Manual backup (verify the path works first)

```powershell
# From the repo root
.\scripts\windows\backup_sleepingpassenger_db.ps1
```

Expected output ends with:

```
[PASS] backup written (NNNN bytes)
[PASS] advisory_status=ADVISORY_ONLY
[PASS] execution_gate=LOCKED
RESULT: PASS
Backup complete.
```

The backup file lands in `runtime/backups/` and is named
`mvp_local-YYYYMMDD-HHMMSS.db`.

### With a label (e.g. before a demo)

```powershell
.\scripts\windows\backup_sleepingpassenger_db.ps1 -Label predemo
```

Produces `mvp_local-YYYYMMDD-HHMMSS-predemo.db`. Labels must match
`[A-Za-z0-9._-]{1,32}`.

### JSON output for cron/CI parsing

```powershell
.\scripts\windows\backup_sleepingpassenger_db.ps1 -JsonOutput
```

## Daily scheduled backup — Task Scheduler setup

1. Open **Task Scheduler** (Win+R → `taskschd.msc`).
2. **Create Task** (not "Create Basic Task" — we want non-elevated, no
   user-prompt flags).
3. **General** tab:
   - Name: `SleepingPassenger Daily DB Backup`
   - "Run only when user is logged on"
   - **Do not** check "Run with highest privileges" unless you have a
     specific reason — this script does not need it.
4. **Triggers** tab → New:
   - Begin the task: **On a schedule**
   - Daily, at e.g. `02:30` (pick a time when the laptop is awake)
   - Stop the task if it runs longer than: 5 minutes
5. **Actions** tab → New:
   - Action: **Start a program**
   - Program/script: `powershell.exe`
   - Add arguments:
     ```
     -NoProfile -ExecutionPolicy Bypass -File "C:\Users\akash\sleeping-passenger-v1\scripts\windows\backup_sleepingpassenger_db.ps1"
     ```
   - Start in: `C:\Users\akash\sleeping-passenger-v1`
6. **Conditions** tab:
   - Uncheck "Start the task only if the computer is on AC power" unless
     you want the laptop's plug state to gate backups.
7. **Settings** tab:
   - Allow task to be run on demand
   - If the task fails, restart every: 10 minutes, up to 3 times.

## Verifying a backup file

```powershell
# Confirm the file is a real SQLite database
Get-Content runtime\backups\mvp_local-YYYYMMDD-HHMMSS.db -TotalCount 1 -Encoding Byte | ForEach-Object { [char]$_ }
```

The first 16 bytes should begin with `SQLite format 3`.

You can also dry-run the restore script — it does NOT restore by
default, it just reports what would happen:

```powershell
python scripts\restore_db.py --backup runtime\backups\mvp_local-YYYYMMDD-HHMMSS.db
```

## Retention — what to clean up, what to keep

The PowerShell wrapper does **not** delete old backups by design.
Retention is operator policy, not script policy. Suggested:

- Keep all backups from the last 7 days.
- Keep one backup per week for the last 8 weeks.
- Delete the rest manually.

If you want to automate retention, write a separate cleanup script and
schedule it independently. Do not mix retention logic into the backup
path — losing a snapshot to a buggy retention script is exactly the
failure mode this whole subsystem is meant to prevent.

## What NOT to do

- **Do not** schedule the backup as SYSTEM with elevated privileges. It
  doesn't need them and you'll just confuse the file ownership.
- **Do not** point Task Scheduler at `python.exe` directly with a CLI
  string — environment, working dir, and Python launcher resolution
  break in subtle ways. Use the PowerShell wrapper.
- **Do not** edit `scripts/backup_db.py` to "speed up" by switching from
  the `connection.backup()` API to a raw file copy. The hot-copy API is
  the only safe way to copy a WAL-enabled SQLite DB while it is open.
- **Do not** restore a backup over the live DB without first running
  `python scripts\restore_db.py` in dry-run mode and reading what it
  intends to do. Restore is destructive; dry-run is the safety net.
- **Do not** check `runtime/backups/` into git. `.gitignore` already
  excludes the runtime directory; preserve that.

## Disaster recovery sketch

If `runtime/mvp_local.db` is gone:

1. Stop the API server.
2. Pick the most recent valid backup from `runtime/backups/`.
3. Run `python scripts\restore_db.py --backup <file>` (dry-run) and
   read its plan.
4. If the plan looks right, re-run with the explicit confirmation flag
   the script asks for. The restore script automatically takes a
   pre-restore backup of whatever the target DB looks like at that
   moment.
5. Start the API server.
6. Run `python scripts\smoke_check.py --api http://127.0.0.1:8000` to
   verify the contract is healthy.

This sequence is the only currently supported way to recover. Off-machine
backup, hosted backup, or cross-region DR are out of scope for the local
MVP.
