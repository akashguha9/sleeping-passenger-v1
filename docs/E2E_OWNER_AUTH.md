# Owner-auth E2E verification

What the suite proves (`frontend/e2e/owner-auth.spec.ts`):

1. the frontend loads;
2. with no token, data pages show the locked/empty state — protected data
   never renders;
3. a wrong token stays locked;
4. the valid token unlocks a harmless protected read;
5. the token lives in `sessionStorage` only — never `localStorage`;
6. the token input is masked (`type=password`) and the raw token never
   appears in the DOM after entry.

## How it runs

The specs are **route-mocked** (`page.route` stubs every backend call and
enforces the `Authorization: Bearer` contract), so the suite is hermetic:
no live backend, no `.env`, no GitHub Secrets. Any token string in the
specs is a synthetic fixture. The "is the real backend actually wired
this way?" question is answered separately by the live probe below and by
the backend tests (`tests/test_owner_only_hardening.py`).

### CI (`.github/workflows/e2e.yml`)

Manual dispatch + weekly (Tue 07:23 UTC). Least-privilege
(`contents: read`), SHA-pinned actions, `persist-credentials: false`,
Playwright browsers cached by version, **zero stored secrets** — anything
secret-shaped is generated inside the job.

Trigger: GitHub → Actions → *e2e* → **Run workflow**.

### Locally (Windows PowerShell)

```powershell
cd frontend; npm ci; npx playwright install chromium; cd ..
.\scripts\run_e2e_owner_auth.ps1              # hermetic suite
.\scripts\run_e2e_owner_auth.ps1 -RealStack   # + live 401/200/421 probe
```

`-RealStack` generates a throwaway token, exports only its **hash** into
process env (`MVP_SKIP_DOTENV=1`; your `.env` is never read or written),
boots the real backend, asserts 401-without / 200-with / 421-foreign-host,
and tears everything down. The raw temp token is never printed unless you
pass `-VerboseTokenForDebug` (off by default).

If Playwright's Chromium is missing the helper exits with the exact
`npx playwright install chromium` command instead of failing cryptically.
Some sandboxed/dev-container networks block the browser CDN — run the CI
workflow in that case; GitHub-hosted runners can always fetch it.
