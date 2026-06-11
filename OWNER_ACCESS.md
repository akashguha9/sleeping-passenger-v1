# Owner access model

One owner. One token. Fail closed.

This MVP is owner-only by construction: there is no user model, no signup,
no roles exposed over the network, and no anonymous mode in a supported
configuration. The single privileged principal is the operator who holds
`MVP_API_TOKEN`.

## First-run setup (Windows PowerShell)

```powershell
# 1. Generate the owner token. HASH MODE: only the SHA-256 lands in the
#    gitignored .env (MVP_API_TOKEN_HASH); the raw token is printed ONCE.
python scripts/generate_api_token.py --write-env

# 2. Start the backend (it refuses to start without the token)
python -m uvicorn scripts.api_server:app --host 127.0.0.1 --port 8000

# 3. Start the frontend, open it, and paste the token into the
#    "Local API token" panel (stored in sessionStorage only)
cd frontend; npm run dev
```

The token printed by step 1 is shown once; it also lands in `.env`, which
the server reads at startup (real environment variables always win, and
`.env` is never read under pytest).

## Enforcement points

| Layer | Behavior |
| --- | --- |
| Startup preflight | No owner token (`MVP_API_TOKEN_HASH` preferred, plaintext `MVP_API_TOKEN` legacy+warned) → `StartupSecurityError`, server refuses to boot. `MVP_ALLOW_UNAUTH=1` is the only bypass and works **only on a loopback bind** — an unauthenticated non-loopback server is never bootable. |
| Exposure hard stop | Non-loopback bind (or `MVP_PUBLIC_MODE=1`) needs the token **plus** a transport acknowledgement: `MVP_TLS_TERMINATED=1`, `MVP_TRUSTED_PROXIES=…`, `MVP_PUBLISHED_BIND=127.0.0.1` (container loopback portmap), or `MVP_UNSAFE_LAN_HTTP=I_UNDERSTAND_THIS_EXPOSES_MY_TOKEN`. |
| Read routes | `require_api_token_for_reads` — 401 without a valid bearer token. |
| Write routes | `require_api_token` — structural test walks every mutating route and fails if one is unguarded. |
| Host header | Allowlist (localhost/127.0.0.1/::1/sleepingpassenger + `MVP_ALLOWED_HOSTS`); foreign Host → 421. Defeats DNS rebinding from the owner's browser. |
| CORS | Explicit origin allowlist, `allow_credentials=false`, GET/POST/OPTIONS only. |
| Streamlit dashboard | Refuses non-loopback bind unless `MVP_DASHBOARD_ALLOW_NONLOOPBACK=1`; beyond loopback the owner token is additionally REQUIRED (same hash verification as the API). Loopback stays promptless by default (`MVP_DASHBOARD_REQUIRE_TOKEN=1` to force the prompt). |
| Public surface | `/health` (minimal: no paths, no env, no data) and `/api/version` only. |

There are internal role labels (VIEWER/OPERATOR/ADMIN in
`scripts/operator_auth.py`) used by local CLI tooling for least-privilege
discipline; they are not network identities and grant nothing without the
owner token.

## Rotation & recovery

`python scripts/generate_api_token.py --rotate --write-env` any time;
restart the backend; re-paste in the browser panel. The old token dies
immediately (its hash is overwritten). The raw token is unrecoverable by
design — only its hash is stored — so "I lost the token" recovery is
simply another rotation. Check a candidate token with
`--verify-token` (stdin, prints MATCH / NO MATCH).

## GitHub repository settings checklist (manual — verify yourself)

Pass 2 verified read-only via the authenticated GitHub API: repo is
**private**, default branch **main**, exactly **one collaborator**
(akashguha9, admin), Pages/wiki/discussions disabled. Branch protection,
Actions defaults, deploy keys, webhooks, and secrets are not exposed to
this session's token — verify them in the UI. Full, current checklist:
[reports/github_owner_settings_manual_checklist.md](reports/github_owner_settings_manual_checklist.md).
Summary:

- [ ] Repo visibility is **Private** (it is the owner's IP; keep it private unless deliberately public).
- [ ] Collaborators: none (or explicitly intended people only).
- [ ] Branch protection on `main`: require status checks (pytest, kante-defensive-gate, dep-audit), restrict who can push.
- [ ] Actions → General: "Require approval for all external contributors" for fork PRs; default workflow permissions = **Read repository contents**.
- [ ] Secrets and variables → Actions: only secrets you recognize; no deployment credentials this repo doesn't need.
- [ ] Deploy keys: none stale.
- [ ] GitHub Apps / OAuth apps: review and remove unused.
- [ ] Fine-grained PATs: review, rotate, minimize.
- [ ] Code security: enable Dependabot alerts, secret scanning, and push protection (free on private repos for most plans; enable what your plan allows).
- [ ] Webhooks: remove stale ones.
- [ ] Packages/Pages: nothing published unintentionally.
