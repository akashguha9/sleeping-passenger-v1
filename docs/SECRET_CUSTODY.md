# Secret custody — provider API keys

The MVP's provider keys (EDINET, OpenDART, Etherscan, xAI, NewsAPI, …)
are **read-only data-source keys**: none can place trades or move money,
because no such integration exists. Custody still matters — a leaked key
is someone else burning your quota under your identity.

## Modes (`SECRET_PROVIDER` in `.env`)

| Mode | At rest | Notes |
| --- | --- | --- |
| `env` (default) | plaintext in `.env` / process env | Works everywhere. Lower security: readable by any same-user process; protect with NTFS ACLs (`scripts/harden_local_owner_files.ps1`) + BitLocker. |
| `windows-credential-manager` | Windows Credential Manager (DPAPI, bound to your Windows account) | Implemented via `ctypes`/`advapi32` — zero added dependencies. Windows only; the provider says so plainly elsewhere. |

There is deliberately **no encrypted-file mode**: an encryption key
sitting next to the encrypted file is theater, and this repo has no
separate key-custody channel to hold one — on Windows, Credential
Manager *is* that channel.

The **owner API token is not managed here** — it already has stronger
custody (only its SHA-256 ever touches disk; `generate_api_token.py`).

## Managing keys (PowerShell)

```powershell
# Move to OS custody
"SECRET_PROVIDER=windows-credential-manager"  # set in .env

python scripts/manage_secrets.py list-names
python scripts/manage_secrets.py set --name EDINET_API_KEY      # value via stdin
python scripts/manage_secrets.py get --name EDINET_API_KEY      # redacted
python scripts/manage_secrets.py get --name EDINET_API_KEY --show-secret I_UNDERSTAND
python scripts/manage_secrets.py delete --name EDINET_API_KEY
python scripts/manage_secrets.py audit                          # custody hygiene
```

Then delete the plaintext lines from `.env`. At startup the server
hydrates the keys from Credential Manager into its own process
environment (setdefault — real env vars always win), so every existing
loader works unchanged. Unavailable custody never blocks boot: keys
simply read as unset and the loaders skip cleanly.

## Rules (test-pinned)

- `get` is redacted by default; raw reveal requires the literal
  `--show-secret I_UNDERSTAND`.
- Values enter via stdin, never argv (no shell history).
- No secret value is logged anywhere, including the audit log (its
  redactor strips secret-shaped metadata as defense in depth).
- Missing secrets fail safe (`None` → source skips), never crash.
