# Security scorecard — trust-closure pass

Scores are 0–10, awarded **only for behavior verified by tests, audits, or
CI evidence**. "Pre" = commit `418ead6` (CI-hardening pass, all CI green).
"Post" = this trust-closure pass. The fenced JSON block at the bottom is
the machine-readable form; `tests/test_security_scorecard.py` keeps it
parseable and consistent with this table.

| Segment | Pre | Post | Δ | Why |
|---|---|---|---|---|
| Secret scanning | 8 | 9 | +1 | The scan pipeline is now self-auditing: `audit_security_gate_integrity.py` (pytest + kante + dep-audit policy) fails CI if the pinned CLI, checksum, explicit config, strict exit code, lint-first ordering, tree+commit scans, or SARIF artifact ever drift. |
| Fixture hygiene | 8 | 8 | 0 | Already enforced (lint + runtime-assembled probes + clean tree); nothing measurable changed this pass. |
| Runtime file custody | 8 | 9 | +1 | New adversarial proofs: DB created under umask 000 still lands at 0600, and a pre-existing 0644 `runtime/mvp_local.db` is healed by the next persistence touch before the custody audit runs. |
| CI determinism | 6 | 7 | +1 | `*.sarif` can no longer be committed (gitignore + audited), the single checksum-pinned gitleaks source is now audit-enforced across all workflows, and the remaining nondeterminism is documented below instead of unknown. |
| Workflow pinning | 9 | 9 | 0 | Already SHA-pinned and audit/test-enforced pre-pass; the new audit adds redundancy (nested/renamed-workflow detection) but no new pinning property. |
| Historical exposure containment | 3 | 8 | +5 | Full-history scan over the complete 291-commit clone enumerated all 24 findings; each verified synthetic and pinned by fingerprint in a ledger; `audit_historical_secret_ledger.py` + manual `history-audit` workflow fail on unknown findings and always fail on current-tree findings. Not 10: the bait strings still exist in old commits by deliberate no-rewrite policy. |
| Release evidence | 4 | 8 | +4 | `build_security_evidence_bundle.py` emits a schema-tested JSON bundle (commit, environment, per-check exit codes, SHA-256 of every security-relevant file), uploaded as a CI artifact; tests prove failed/skipped checks can never read as passed and the bundle is scanner-clean. Pre-pass evidence was release manifests without security-check attestation. |
| Regression resistance | 5 | 9 | +4 | 22 adversarial tests feed broken workflow/config snippets (continue-on-error, dropped `--no-git`, gitleaks-action revival, unpinned version, dropped checksum/config/SARIF, lint-after-gitleaks, shallow fetch, nested/renamed/deleted workflows, broad allowlists/ignores) and prove the audit fails closed on each. |
| Real-money readiness impact | 5 | 6 | +1 | Security/ops posture is now evidence-backed (bundle + self-auditing gates), removing one class of operational unknowns; actual trading readiness is still governed by the model-quality gates, which this pass deliberately did not touch. |

## CI determinism notes (current facts)

- **Pinned & verified:** all GitHub actions SHA-pinned (audit + tests);
  gitleaks CLI pinned by version *and* SHA-256, downloaded fresh per run
  (never cached, so caches cannot poison the security binary); npm uses
  `npm ci` with a committed lockfile; the npm cache is keyed by the
  lockfile and holds only the package cache.
- **Deliberately floating (documented, not fixed):** Python deps use
  bounded ranges (`>=X,<Y`) instead of a hash-locked set — repo policy
  pairs this with `pip-audit --strict` on every push plus a weekly
  schedule and the dependency advisory register; `python-version: "3.13"`
  and `node-version: "20"` float on patch level; `ubuntu-latest` floats
  the runner image. Hash-locking remains a known improvement (see
  blockers).
- **Artifacts:** `runtime/` and (new) `*.sarif` are gitignored; the
  hygiene gates fail if a runtime DB or scanner report is ever tracked.
- **Test ordering:** the session-wide `_isolate_runtime_db` conftest
  fixture isolates the canonical DB. Known quirk: four tests in
  `tests/test_pre_real_money_preflight.py` are order-sensitive when that
  file runs standalone (they pass in the full suite); pre-existing, out
  of scope here.

## Remaining blockers (to 10s)

1. No hash-locked Python dependency set (`pip-compile --generate-hashes`)
   — supply-chain resolution can drift within the declared ranges.
2. Historical bait strings remain in old commits (deliberate: rewrite is
   incident-response only — see the historical ledger doc).
3. GitHub-side push protection / org secret scanning is not part of this
   repo's evidence (server-side controls can't be attested from CI).
4. The evidence bundle attests checks executed at build time; it is not
   cryptographically signed (no provenance attestation/SLSA).

```json
{
  "schema_version": 1,
  "baseline_commit": "418ead6",
  "scale": "0-10, verified behavior only",
  "segments": {
    "secret_scanning": {"pre": 8, "post": 9, "delta": 1},
    "fixture_hygiene": {"pre": 8, "post": 8, "delta": 0},
    "runtime_file_custody": {"pre": 8, "post": 9, "delta": 1},
    "ci_determinism": {"pre": 6, "post": 7, "delta": 1},
    "workflow_pinning": {"pre": 9, "post": 9, "delta": 0},
    "historical_exposure_containment": {"pre": 3, "post": 8, "delta": 5},
    "release_evidence": {"pre": 4, "post": 8, "delta": 4},
    "regression_resistance": {"pre": 5, "post": 9, "delta": 4},
    "real_money_readiness_impact": {"pre": 5, "post": 6, "delta": 1}
  }
}
```
