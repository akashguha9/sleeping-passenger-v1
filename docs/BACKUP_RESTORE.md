# Backup & restore (private data)

`scripts/backup_private_data.py` / `scripts/restore_private_data.py`
protect the journal DB with integrity always and confidentiality on
request. Output lands in gitignored `backups/`.

## Backup

```powershell
python scripts/backup_private_data.py                    # tar.gz + manifest + sha256
python scripts/backup_private_data.py --encrypt          # + AES-256-GCM (passphrase)
python scripts/backup_private_data.py --include-reports  # + reports/ scorecards/
```

Every backup produces `private_backup_<UTC>.tar.gz[.enc]` plus
`private_backup_<UTC>.manifest.json` (sources, SHA-256, encryption
status). Contents: the SQLite DB, optionally reports, and a **redacted**
config summary (which keys are set — never values). **`.env` and raw
secrets are never included**, by construction and by test.

### Encryption status (honest)

`--encrypt` = `hashlib.scrypt` KDF (n=2¹⁵, r=8, p=1 — stdlib) +
AES-256-GCM via the **optional** `cryptography` package
(`pip install cryptography`; reputable, audited — hand-rolling AES would
be malpractice, so without the package the script refuses `--encrypt`
rather than pretending). An unencrypted backup is integrity-protected
(checksum) but **not confidential** — that's stated in its manifest;
BitLocker/device encryption remains the at-rest baseline.

## Restore

```powershell
python scripts/restore_private_data.py --manifest backups/private_backup_<UTC>.manifest.json          # DRY RUN
python scripts/restore_private_data.py --manifest ... --apply           # writes (DB must not exist)
python scripts/restore_private_data.py --manifest ... --apply --force   # overwrite; previous DB kept aside
python scripts/restore_private_data.py --manifest ... --apply --passphrase-prompt   # encrypted backups
```

Safety contract (test-pinned): checksum verified **before** anything is
touched; corrupted/tampered archives are refused; dry-run is the default;
`--force` required to overwrite (a `*.pre_restore.<stamp>` copy of the
current DB is kept); secrets are never restored; refused entirely under
`MVP_LOCKDOWN_MODE=1`; every run writes a restore report and a
tamper-evident audit event.

## Owner recovery pack

If the laptop dies, what you need to stand the MVP back up elsewhere:

1. the newest `backups/private_backup_*.tar.gz.enc` + its manifest
   (encrypted → safe to keep off-machine, e.g. a USB key or private
   cloud);
2. the backup **passphrase** (password manager — it is stored nowhere);
3. a clone of this repo (GitHub is the canonical copy);
4. provider keys (re-issue from each provider console, or export from
   Windows Credential Manager on a surviving machine);
5. a fresh owner token: `python scripts/generate_api_token.py --write-env`
   — the old token never needs recovering; tokens are rotated, not
   restored.

Recovery: clone → `pip install -r requirements.txt -r requirements-dev.txt`
→ generate token → restore with `--apply` → run
`python scripts/verify_audit_log.py` and the test suite before trusting
the journal.

Schedule: `scripts/windows/backup_sleepingpassenger_db.ps1` remains the
quick unencrypted local snapshot; run the encrypted backup before any
machine change, OS reinstall, or travel.
