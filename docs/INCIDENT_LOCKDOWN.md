# Emergency lockdown mode

`MVP_LOCKDOWN_MODE=1` turns the MVP read-only in one move. Use it the
moment you suspect: a token leak, a compromised browser/machine, a bad
dependency advisory, someone else using your laptop, or any
incident-response situation where you want the journal frozen while you
investigate.

## What it does (test-pinned)

| Surface | Behavior |
| --- | --- |
| Mutating routes (journal writes/deletes, reconciliation, imports, moltbook, bootstrap) | **423 Locked** with advisory stamps; each refusal is recorded in the tamper-evident audit log |
| Reads | unchanged — still owner-token-gated |
| `/health`, `/api/version` | open as usual; `/health` reports `lockdown_mode: true` |
| Frontend | red lockdown banner on every page (reads `/health`) |
| Streamlit | lockdown warning at the top of the dashboard |
| `restore_private_data.py` | refuses to run (restore is a mutation); lift lockdown deliberately first |
| Advisory invariants | unaffected — `execution_gate=LOCKED` etc. stamp every response, locked or not |

## Engage

```powershell
# .env (server reads it at startup):
#   MVP_LOCKDOWN_MODE=1
# then restart the backend. Or for one shell:
$env:MVP_LOCKDOWN_MODE = "1"
python -m uvicorn scripts.api_server:app --host 127.0.0.1 --port 8000
```

Startup logs a loud warning and writes a `lockdown_engaged` audit event.

## While locked

1. Rotate the owner token: `python scripts/generate_api_token.py --rotate --write-env`.
2. Rotate any provider keys you suspect (provider consoles; `docs/SECRET_CUSTODY.md`).
3. Verify the audit chain: `python scripts/verify_audit_log.py` — review
   recent events for writes you didn't make.
4. Take an encrypted backup of current state for forensics:
   `python scripts/backup_private_data.py --encrypt` (backup is allowed —
   it's a read; restore is not).
5. Compare the DB against your last known-good backup checksum
   (`docs/BACKUP_RESTORE.md`).

## Lift

Set `MVP_LOCKDOWN_MODE=0` (or remove the line), restart, and re-run
`python -m pytest tests -q` plus `python scripts/repo_hygiene_gate.py`
before trusting writes again.
