# Historical secret-scan ledger

Status: **verified clean — synthetic bait only, no real secrets in history.**

A full-history gitleaks scan (CLI `8.24.3`, `.gitleaks.toml` = default
ruleset, all 291 commits of a complete unshallowed clone, 2026-06-11)
found **24 findings across 18 commits — every one a synthetic test
fixture**, manually verified line-by-line against the commit content.
The machine-readable companion file
[`historical_findings_ledger.json`](historical_findings_ledger.json) lists
every fingerprint; `scripts/audit_historical_secret_ledger.py` re-runs the
scan and fails on anything not in that list.

## What the historical findings are

All 24 findings are gitleaks `generic-api-key` matches on fabricated test
inputs, in two families:

1. **Redaction/refusal test probes** — tests proving that modules like
   `data_quality`, `ai_output_schema`, `source_health_summary`,
   `compliance_preflight` refuse or redact secret-shaped text fed obvious
   fakes (fake `sk-`/`xai-` prefixed tokens, alphabet-pattern values,
   strings literally containing words like LEAKED / fake / "should never
   appear") as literal source. Commit `418ead6` moved every such probe to
   runtime assembly (`tests/helpers/scanner_probes.py`), which is why the
   current tree is clean.
2. **One mis-named constant** — `scripts/runtime_config.py` historically
   named its hex-alphabet validation constant after the token hash it
   validates; renamed at `418ead6`.

None of the historical values are, or ever were, usable credentials: no
finding matches any provider's real token format with plausible entropy
sources, every affected line lives in test fixtures or a validation
constant, and the repo's secret custody design keeps real keys in `.env`
(gitignored) or Windows Credential Manager — never in tracked files.

## Why the current tree is clean

- Full-tree scan (`gitleaks detect --no-git --config=.gitleaks.toml`) at
  HEAD: **0 findings** (re-verified by `audit_historical_secret_ledger.py`
  on every run — current-tree findings are *never* suppressible via this
  ledger).
- `scripts/secret_fixture_lint.py` (pytest + pre-commit + CI step before
  gitleaks) forbids reintroducing secret-shaped fixtures.

## Why CI is protected going forward

- Every push: lint → full-tree gitleaks → commit-scope gitleaks
  (pinned CLI `8.24.3` + SHA-256, explicit config, strict exit code,
  SARIF artifact). `scripts/audit_security_gate_integrity.py` (pytest +
  kante gate + dep-audit policy job) fails CI if any of that drifts.
- The historical findings live only in *old commits*. CI's commit-scope
  scan only inspects newly pushed commits, and the full-tree scan only
  inspects HEAD content, so the historical bait cannot re-fail CI unless
  someone re-adds the strings — which the lint and tree scan then catch.

## Full history purge: what it would take, and why we don't do it

A purge would require rewriting all 18 affected commits and every
descendant (effectively the whole recent history) with
`git filter-repo --replace-text`, then force-pushing every branch.

Costs and risks:

- **Every commit SHA after the earliest affected commit changes** —
  including `418ead6` and all CI evidence, tags (`v5.7.x`), release
  provenance manifests, and the fingerprints in this very ledger.
- Open/closed **PR refs and review history break**; any clone, CI cache,
  or local branch must be re-cloned or hard-reset (force-push
  coordination across every consumer).
- The rewrite itself is a high-risk force-push against the only canonical
  copy of a private repo.

**Recommended default: no history rewrite.** The historical findings are
verified synthetic; rewriting history would destroy provenance to remove
strings that were never secrets. Revisit **only if** a real secret is
ever found in history — in that case: rotate the credential first
(rotation, not rewriting, is the actual security fix), then, optionally,
rewrite on a dedicated branch with a dry-run report
(`git filter-repo --analyze` + a documented replace-text plan) before any
force push. History rewriting is optional and dangerous; treat it as an
incident-response step, never housekeeping.

## How to re-verify

```bash
# complete clone required (the scan refuses shallow history)
python scripts/audit_historical_secret_ledger.py
```

Exit codes: `0` history matches the ledger and HEAD tree is clean ·
`1` unknown historical finding (investigate; if it is a real secret,
rotate it immediately) · `2` current-tree finding (always fatal) ·
`3` gitleaks binary unavailable · `4` shallow clone (history incomplete).
A JSON report is written to `runtime/reports/historical_secret_scan.json`
(gitignored).
