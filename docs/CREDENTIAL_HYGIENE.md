# Credential Hygiene

**Sprint:** Calibration Corpus + Hosted Canary, Phase 5.

Service-account JSON files MUST NOT sit at the repository root.  They
belong in `secrets/`, which is gitignored.  This sprint moves the
existing `google-service-account.json` and adds a check script + tests
that refuse a root-level placement.

> **Path-only operations.**  The hygiene check NEVER opens, reads,
> prints, or copies a credential file.  It inspects path metadata and
> `.gitignore` lines only.  Tests monkey-patch `open` to assert that
> the script does not accidentally touch credential contents.

## What changed

* `google-service-account.json` moved from repo root → `secrets/google-service-account.json` (path move only).
* `.gitignore` already covers `secrets/` and `google-service-account.json`.
* `scripts/check_credential_hygiene.py` added — file-shape-only audit.
* `tests/test_credential_hygiene.py` added — 10 cases including a
  `no-open` invariant.

## Run the check

```bash
python scripts/check_credential_hygiene.py
# → exits 0 on PASS, 1 on FAIL.  Never reads credential contents.

python scripts/check_credential_hygiene.py --json runtime/release/credential_hygiene_report.json
# → also writes the structured report.
```

Report shape:

```jsonc
{
  "script": "check_credential_hygiene.py",
  "generated_at_utc": "…",
  "advisory_status": "ADVISORY_ONLY",
  "execution_gate": "LOCKED",
  "broker_api_called": false,
  "ai_execution_count": 0,
  "root_service_account_present": false,
  "root_offenders": [],
  "secrets_service_account_present": true,
  "secrets_gitignored": true,
  "status": "PASS",
  "credential_hygiene_pass": 1,
  "credential_risk_score": 0.0,
  "recommendation": "…"
}
```

## Mathematics

* `CredentialHygienePass = 1` iff
  `root_service_account_present == false AND secrets_gitignored == true`.
* `CredentialRiskScore = 10 * (1 - CredentialHygienePass)`.

## Use the credential

Point the Google client library at the moved path:

```bash
# Bash
export GOOGLE_APPLICATION_CREDENTIALS=secrets/google-service-account.json

# PowerShell
$env:GOOGLE_APPLICATION_CREDENTIALS = "secrets\google-service-account.json"
```

The credential never appears in environment files committed to the
repo — `.env`, `.env.local`, `.env.*` are all gitignored.

## What the check is NOT

* Not a secret scanner.  It inspects filenames, not file contents.
* Not a key-rotation policy.  Rotation lives in your cloud console.
* Not an execution gate.  The script is advisory-only.
