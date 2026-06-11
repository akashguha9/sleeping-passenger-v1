# Final external checklist (owner actions outside this repo)

Checked by `python scripts/final_external_readiness_check.py` — which
reports VERIFIED / PENDING / UNSAFE and **never** fakes verification or
creates confirmation markers. When you complete an item, create the
marker file yourself with a dated note; the checker then flips it to
VERIFIED.

| # | Action | Where | Marker to create after completion |
| - | ------ | ----- | ---------------------------------- |
| 1 | Enable branch protection on `main` (required checks: backend pytest, safety floor, frontend, defensive gate, dep-audit; restrict pushes; no force-push/delete) | GitHub → Settings → Branches | `reports/manual_confirmations/github_branch_protection_confirmed.md` |
| 2 | Enable Dependabot alerts, secret scanning, push protection | GitHub → Settings → Code security | `reports/manual_confirmations/github_security_features_confirmed.md` |
| 3 | Trigger the e2e workflow once and watch it pass | GitHub → Actions → e2e → Run workflow | `reports/manual_confirmations/e2e_first_green_run_confirmed.md` |
| 4 | Migrate provider keys to Windows Credential Manager and verify on your Windows machine (`SECRET_PROVIDER=windows-credential-manager`; `python scripts/manage_secrets.py set/get/audit`; delete plaintext lines from `.env`) | your Windows laptop | `reports/manual_confirmations/wcm_migration_confirmed.md` |
| 5 | Re-run the full owner-controls audit wherever `gh` is authenticated | `python scripts/audit_github_owner_controls.py` | (machine-verified; no marker needed) |

Marker file content suggestion:

```markdown
# Confirmed by Akash Guha
Date: YYYY-MM-DD
What I verified: <one line>
```

Markers are tracked in git (they are owner attestations, not secrets).
The readiness checker treats missing markers as **PENDING — honestly
unverified**, never as failures; only machine-verified UNSAFE states
fail it.
