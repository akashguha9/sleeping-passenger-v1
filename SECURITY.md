# Security Policy

Owner-only, local/private, advisory-only MVP. Proprietor: Akash Guha
(akashguha@outlook.com). See [OWNER_ACCESS.md](OWNER_ACCESS.md) for the
access-control model and [PROPRIETARY_NOTICE.md](PROPRIETARY_NOTICE.md)
for ownership posture.

## Reporting

This is a private, single-operator system with no third-party users. If
you somehow obtained access and found a vulnerability, email
akashguha@outlook.com. Do not open public issues for security findings.

**This system is advisory-only. It does not place trades, route orders, custody assets, or connect to broker execution APIs.**
This boundary is machine-enforced by `scripts/audit_advisory_only_boundary.py`.

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

## Secret fixture hygiene (tests & docs)

CI scans every push with the gitleaks CLI (pinned `v8.24.3`, checksum
verified — no license/API dependency) using `.gitleaks.toml`, which keeps
the **full default ruleset**. Scanners cannot tell a synthetic fixture
from a real leak, so the rule is enforced at the source:

- **Never commit a `<keyword><operator><value>` credential shape**, even
  with a fake or `REDACTED` value. That means no `…key=REDACTED`, no
  realistic-looking fake tokens (`sk-…`, `xai-…`, `ghp_…`, `AKIA…`), and
  no high-entropy values beside names containing key/token/secret/
  password/credential.
- Tests that need secret-*shaped* strings (to prove redaction/refusal)
  assemble them at runtime via `tests/helpers/scanner_probes.py` — the
  probe never exists in tracked source.
- Everything else uses the approved sentinels
  (`DUMMY_VALUE_FOR_TESTS_ONLY`, `SENTINEL_VALUE_FOR_TESTS_ONLY`,
  `PLACEHOLDER_VALUE_FOR_TESTS_ONLY`, `NOT_A_SECRET_TEST_VALUE`).
- `scripts/secret_fixture_lint.py` enforces this (pytest:
  `tests/test_secret_fixture_hygiene.py`; pre-commit; CI step before
  gitleaks). It is an early tripwire, **not** a gitleaks replacement —
  gitleaks still fails CI on real leaks.
- Sensitive runtime files are created owner-only: `runtime/*.db` is
  hardened to `0600` (dir `0700`) on POSIX by
  `scripts.persistence.harden_db_permissions` at every create/connect;
  Windows ACLs via `scripts/harden_local_owner_files.ps1`.
- Never add gitleaks allowlists to hide fixtures; if a one-off false
  positive must be suppressed, use a fingerprint-specific
  `.gitleaksignore` entry with a justification comment.

Trust closure (the gates cannot silently drift):
`scripts/audit_security_gate_integrity.py` verifies the whole scan
pipeline in every workflow file and runs in pytest, pre-commit, the kante
gate, and the dep-audit policy job. Historical findings are enumerated and
verified synthetic in `docs/security/historical-secret-scan-ledger.md`
(re-checkable via `scripts/audit_historical_secret_ledger.py` / the manual
`history-audit` workflow). Every dep-audit run uploads a machine-readable
attestation built by `scripts/build_security_evidence_bundle.py`; scores
and residual risk live in `docs/security/security_scorecard.md`.

## Secret rotation

If the owner token may have leaked:

```powershell
python scripts/generate_api_token.py --rotate --write-env   # new token, old one dies
# restart the backend, re-paste the new token in the frontend panel
```

Preferred storage is hash mode: only `MVP_API_TOKEN_HASH` (SHA-256) sits
in `.env`; the raw token is printed once at generation and is otherwise
unrecoverable — if lost, rotate. Verify a candidate token without
exposing it: `python scripts/generate_api_token.py --verify-token`
(reads from stdin, prints MATCH / NO MATCH). The legacy plaintext
`MVP_API_TOKEN` still authenticates but logs a startup warning.

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

## Local data protection (honest scope)

API auth protects the network surface only. It does **not** protect
against malware or any process running as your own OS user — those can
read `runtime/mvp_local.db` and `.env` directly. For meaningful local
protection:

- use a password-protected Windows account and **BitLocker / device
  encryption**;
- run `scripts/harden_local_owner_files.ps1` (dry-run by default,
  `-Apply` to set NTFS ACLs) to restrict `.env`, `runtime/`, `logs/`,
  and local backups to your user;
- never let `.env` or the SQLite DB sync into public cloud folders
  (OneDrive/Dropbox/Drive) unencrypted — the hardening script warns when
  the repo path looks cloud-synced;
- `scripts/audit_local_data_protection.py` (CI-enforced) fails if a
  secret, DB, or backup ever becomes git-tracked or world-readable.

Provider API keys can now live in **Windows Credential Manager**
instead of plaintext `.env` (`SECRET_PROVIDER=windows-credential-manager`;
`scripts/manage_secrets.py`; docs/SECRET_CUSTODY.md). Encrypted backups
(scrypt + AES-256-GCM, optional `cryptography` package) cover the DB:
docs/BACKUP_RESTORE.md, including the owner recovery pack. Full at-rest
DB encryption (SQLCipher) remains future work — BitLocker is the at-rest
baseline.

## LAN / public exposure hard stop

Binding beyond loopback (or `MVP_PUBLIC_MODE=1`) requires the owner token
**plus** an explicit transport-security acknowledgement, otherwise the
server refuses to boot: `MVP_TLS_TERMINATED=1` (TLS proxy/tunnel in
front), `MVP_TRUSTED_PROXIES=<ips>` (declared reverse proxy),
`MVP_PUBLISHED_BIND=127.0.0.1` (container port mapped to host loopback),
or the deliberately ugly last resort
`MVP_UNSAFE_LAN_HTTP=I_UNDERSTAND_THIS_EXPOSES_MY_TOKEN`.

## Tamper-evident audit log

Sensitive actions (journal writes/deletes, exports, reconciliation,
backup/restore, auth-failure bursts, unsafe-override boots, lockdown
blocks) are recorded in a hash-chained append-only JSONL at
`logs/audit_log.jsonl` (gitignored): each event commits to everything
before it, so edits/deletions/insertions are detected by
`python scripts/verify_audit_log.py`. Metadata is aggressively redacted —
the chain records THAT something happened, never tokens, secrets, or
journal payloads.

## Emergency lockdown

`MVP_LOCKDOWN_MODE=1` freezes the MVP read-only: every mutating route
returns 423 Locked (audit-logged), reads stay token-gated, the frontend
and Streamlit show lockdown banners, and restore is refused. Engage on
suspected compromise; full runbook: docs/INCIDENT_LOCKDOWN.md.

## Release provenance

`scripts/build_release_manifest.py` + `scripts/generate_checksums.py`
record commit, dirty state, toolchain versions, lockfile and
safety-module hashes; `--verify` recomputes and fails on tamper
(docs/RELEASE_PROVENANCE.md).

## Dependency advisory register

Unresolved (CI-tolerated) advisories are tracked with mandatory review
dates in `docs/DEPENDENCY_ADVISORY_REGISTER.md`;
`scripts/audit_dependency_advisory_register.py` fails CI when an entry
goes stale. High/Critical advisories are never "accepted".

## Backups & retention

- `scripts/backup_db.py` / `scripts/windows/backup_sleepingpassenger_db.ps1`
  copy the SQLite DB to gitignored `backup_local_state/`.
- All private data (DB, logs, exports, backups, `.env`) is gitignored and
  stays on the owner's machine. Retention is owner-managed; deleting the
  repo directory deletes all data.
