# Security Policy

Owner-only, local/private, advisory-only MVP. Proprietor: Akash Guha
(akashguha@outlook.com). See [OWNER_ACCESS.md](OWNER_ACCESS.md) for the
access-control model and [PROPRIETARY_NOTICE.md](PROPRIETARY_NOTICE.md)
for ownership posture.

## Reporting

This is a private, single-operator system with no third-party users. If
you somehow obtained access and found a vulnerability, email
akashguha@outlook.com. Do not open public issues for security findings.

## Threat model (summary)

| Actor | Primary defense |
| --- | --- |
| Random internet user | Loopback-only bind by default; non-loopback boot refused without a token; Docker ports map to `127.0.0.1` |
| Same-LAN user | Same as above; LAN exposure requires an explicit `HOST_BIND=0.0.0.0` **and** a configured `MVP_API_TOKEN` |
| Malicious website in the owner's browser (DNS rebinding / CSRF-style) | Host-header allowlist (421 on foreign Host), explicit CORS allowlist with `allow_credentials=false`, bearer token on all journal routes |
| Malicious guest / second user on the machine | Fail-closed startup: no `MVP_API_TOKEN`, no boot; token gates every read and write route |
| Compromised dependency | `pip-audit` + `npm audit --audit-level=high` fail CI; weekly scheduled audit; pinned version ranges |
| GitHub Actions attacker via PR/fork | `permissions: contents: read` on every workflow, `persist-credentials: false` on every checkout, no `pull_request_target`, no secrets in test workflows |
| Credential/token thief | Token lives only in gitignored `.env` and browser sessionStorage (never localStorage/cookies); constant-time comparison server-side; rotation = regenerate |
| Future collaborator over-permission | No collaborators by policy; manual GitHub settings checklist in OWNER_ACCESS.md |
| Owner misconfiguration | Startup preflight refuses unsafe states (no token; unauthenticated non-loopback is always refused); `/health/full` surfaces the active posture |

## Standing protections

- **Fail-closed auth:** the API refuses to start without `MVP_API_TOKEN`.
  With the token set, **all** journal reads and writes require
  `Authorization: Bearer <token>`. Only `/health` (minimal, no paths/env)
  and `/api/version` stay open for discovery.
- **No execution surface:** advisory-only contract is enforced by tests
  and CI gates; there are no broker modules, order routes, or trading
  credentials anywhere in the system.
- **Network:** default bind `127.0.0.1`; Streamlit dashboard refuses
  non-loopback unless explicitly overridden; Next.js dev binds loopback.
- **Headers/limits:** security headers, strict CSP (frontend), request
  size caps, per-scope rate limiting, sanitized error responses.
- **Secrets:** gitleaks in CI and pre-commit; `.env` gitignored; repo
  hygiene gate fails CI if a runtime DB or `.env` is ever tracked.

## Secret rotation

If `MVP_API_TOKEN` may have leaked:

```powershell
python scripts/generate_api_token.py --write-env   # new token
# restart the backend, re-paste the token in the frontend panel
```

If a provider API key in `.env` may have leaked (EDINET, OpenDART,
Etherscan, xAI, NewsAPI, …): revoke/rotate it in that provider's console,
update `.env`, restart. These keys are read-only data-source keys; none
can move money or place orders.

If a GitHub credential leaked: revoke the PAT/deploy key in GitHub
settings, then review the repo audit log.

## Incident response checklist

1. Stop the backend/frontend/dashboard processes.
2. Rotate `MVP_API_TOKEN` (above) and any provider keys.
3. Check `runtime/mvp_local.db` modification time and journal contents
   against your last known-good backup (`scripts/backup_db.py`,
   `scripts/backup_local_state.py`).
4. Review `logs/` for unexpected request patterns (no secrets are logged).
5. Restore from `backup_local_state/` if data integrity is in doubt
   (see docs/LOCAL_RECOVERY_RUNBOOK.md).
6. Re-run `python -m pytest tests -q` and `python scripts/repo_hygiene_gate.py`
   before resuming.

## Backups & retention

- `scripts/backup_db.py` / `scripts/windows/backup_sleepingpassenger_db.ps1`
  copy the SQLite DB to gitignored `backup_local_state/`.
- All private data (DB, logs, exports, backups, `.env`) is gitignored and
  stays on the owner's machine. Retention is owner-managed; deleting the
  repo directory deletes all data.
