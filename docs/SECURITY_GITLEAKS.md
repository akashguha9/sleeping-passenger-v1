# gitleaks secret-scanning policy

## What runs

- **CI:** `.github/workflows/dep_audit.yml` → `gitleaks/gitleaks-action@v2`,
  checked out with `fetch-depth: 0`, so gitleaks scans the **entire git
  history** on every push, PR, and the weekly schedule.
- **Local pre-commit:** `.pre-commit-config.yaml` pins `gitleaks v8.18.4`
  (scans staged content).
- Both auto-discover `.gitleaks.toml` (config) and `.gitleaksignore`
  (per-finding fingerprint allowlist) at the repo root.

## Root cause of the scheduled dep-audit #42 failure

gitleaks scans full history, and several **historical** commits contain
intentional synthetic / redacted secret **placeholders** inside test fixtures —
literal values like `REDACTED`, `fake_secret = "REDACTED"`,
`NEWS_API_KEY: "REDACTED"`, `XAI_API_KEY: REDACTED`. The `generic-api-key` rule
flagged 16 of them. None are real credentials; they exist so the redaction /
provider-secret / source-health tests have something to assert against. No real
secret is currently exposed.

## The fix (least privilege)

We suppress **only the exact 16 known false positives, by fingerprint**, in
`.gitleaksignore`. A fingerprint is `commit:file:rule:line` — the narrowest
allowlist gitleaks supports. It pins one finding, at one line, in one commit.

`.gitleaks.toml` only sets `[extend] useDefault = true`, which keeps the full
upstream default ruleset (including `generic-api-key`) active across the whole
repo and history. We define no `[[rules]]`, and add **no** path globs, value
regexes, or commit-wide allowlists.

### Why fingerprints, not a path/regex allowlist

- A path allowlist (`tests/**`) would blind gitleaks to a *real* secret
  accidentally committed to a test file.
- A value regex like `REDACTED` is effectively `.*REDACTED.*` and, under
  gitleaks 8.18.4's OR semantics for a single `[allowlist]`, would apply
  repo-wide.
- `condition = "AND"` and the `[[allowlists]]` array form (which could tie a
  regex to a path) only exist in gitleaks **8.19+**; we are pinned to 8.18.4.
- Fingerprints avoid all of that: detection stays fully active everywhere,
  including on a **new** line of one of these same test files.

## Adding a new intentional fixture

If a future commit legitimately adds a synthetic placeholder and CI flags it:

1. Confirm by eye that the value is a placeholder, not a real key.
2. Copy the exact fingerprint gitleaks prints (`commit:file:rule:line`) into
   `.gitleaksignore` under the relevant comment, and only that line.
3. Never add a production-code path. `tests/test_gitleaks_allowlist_config.py`
   enforces that every fingerprint is a `tests/` path and that no broad
   allowlist is introduced.

## What was explicitly NOT done

- gitleaks not disabled; full-history scan unchanged.
- No git-history rewrite.
- No broad allowlist, no global rule weakening.
- No change to execution / advisory safety behavior anywhere in the codebase.
