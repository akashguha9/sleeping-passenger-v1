# Release readiness scorecard — ceiling-breaker sprint

Scores are 0–10 and are awarded **only for behavior verified by tests,
scripts, artifacts, or CI**. "Pre" = trust-closure state (commit
`a3ec8ae`, all CI green). "Post" = this sprint. The fenced JSON block at
the bottom is the machine-readable form, kept consistent by
`tests/test_release_readiness_scorecard.py` and embedded by hash in the
release evidence bundle.

| Segment | Pre | Post | Δ | Why (evidence) |
|---|---|---|---|---|
| Secret scanning | 9 | 9 | 0 | Unchanged this sprint — already pinned CLI + dual scans + self-audit + history ledger. |
| Security gate integrity | 9 | 9 | 0 | Unchanged — 23 adversarial tests, three CI surfaces. |
| Dependency reproducibility | 5 | 8 | +3 | `requirements.lock` (pip-compile, 1,325 SHA-256 hashes, full prod+test tree, Python 3.13) gives a deterministic `--require-hashes` release path; `audit_dependency_reproducibility.py` (CI-blocking) fails on stale locks, hashless pins, `npm install`, or Python-version drift; 9 tests. Not 10: dev path floats by policy; lock targets Linux/CPython 3.13 only. |
| Release evidence | 8 | 9 | +1 | Tamper-evident `release_evidence_bundle.json` (canonical `bundle_sha256`, per-file SHA-256, dirty-tree flag, branch/commit, lockfile+workflow+core hashes, embedded security-bundle hash) plus `verify_release_evidence_bundle.py` with distinct exit codes for tampering/file-drift/dishonest aggregation; 14 tests. Not 10: hash-verified, not cryptographically signed. |
| Advisory-only boundary | 6 | 9 | +3 | Previously distributed implicit guards; now one content-level audit (broker SDK imports, order-call shapes, execution routes, trading loops, broker webhooks) + required disclaimers that can never substitute for the code scan + live FastAPI route semantics test; 19 adversarial tests; CI-blocking. Not 10: static analysis — no runtime egress allowlist. |
| Model evaluation honesty | 4 | 7 | +3 | Overclaim gate on human-facing text (negation/term-of-art aware) + a *computed* evidence scorecard: 7 capabilities present (backtest, walk-forward, leakage, calibration, drawdown, manual review, disclaimer), `uncertainty_intervals` and `false_positive_analysis` honestly **missing**, and `live_out_of_sample_results` permanently flagged missing; 12 tests. Not 10: capability ≠ validated results — and the scorecard says so. |
| Operator demo readiness | 4 | 8 | +4 | `run_release_readiness_check.py` runs 9 gates in order with `--quick/--full/--json`, compact table, distinct exit codes, and `PASS_WITH_SKIPS` can never read as `PASS`; 7 tests. Not 10: no scripted end-to-end UI demo flow. |
| Regression resistance | 9 | 9 | 0 | Already strong; this sprint adds the route-manifest tripwire and ~70 new tests but the property class is the same. |
| CI determinism | 7 | 8 | +1 | Deterministic hash-locked install path now exists and is audit-enforced, alongside the existing pinned actions/binaries; residual floats documented. |
| Real-money readiness | 2 | 2 | 0 | **Deliberately unchanged.** Advisory-only by contract (machine-enforced); no live out-of-sample evidence; no execution capability exists or is planned. The bundle carries `not_real_money_execution_software: true` permanently. |
| Investor/demo readiness | 4 | 7 | +3 | A reviewer can now verify instead of trust: one-command gate table, tamper-evident evidence bundle + verifier, honest model-evidence scorecard, frozen API surface. Not higher: no live track record; single-operator product. |

## Blockers (with the path up)

1. **No live out-of-sample results** (model honesty 7→8: run the existing
   walk-forward/calibration tooling on ≥3 months of recorded live signals
   and publish the report through the evidence bundle; 8→10: independent
   replication + uncertainty intervals + false-positive analysis on that
   live record).
2. **Evidence bundle unsigned** (release evidence 9→10: sign
   `bundle_sha256` with an operator key, e.g. ssh-keygen -Y / sigstore,
   and verify the signature in `verify_release_evidence_bundle.py`).
3. **Dependency lock is single-platform** (repro 8→10: per-platform locks
   or a container digest pin for the release runtime, plus a CI job that
   installs from the lock to prove it resolves).
4. **No runtime egress control** (boundary 9→10: an outbound-domain
   allowlist enforced at the HTTP-client layer with tests).
5. **Real-money readiness stays 2 until** a regulated human process
   exists around it (sizing limits, kill criteria, recorded decisions) —
   that is operator process, not code, and no code change should move
   this score alone.

```json
{
  "schema_version": 1,
  "baseline_commit": "a3ec8ae",
  "scale": "0-10, verified behavior only",
  "segments": {
    "secret_scanning": {"pre": 9, "post": 9, "delta": 0},
    "security_gate_integrity": {"pre": 9, "post": 9, "delta": 0},
    "dependency_reproducibility": {"pre": 5, "post": 8, "delta": 3},
    "release_evidence": {"pre": 8, "post": 9, "delta": 1},
    "advisory_only_boundary": {"pre": 6, "post": 9, "delta": 3},
    "model_evaluation_honesty": {"pre": 4, "post": 7, "delta": 3},
    "operator_demo_readiness": {"pre": 4, "post": 8, "delta": 4},
    "regression_resistance": {"pre": 9, "post": 9, "delta": 0},
    "ci_determinism": {"pre": 7, "post": 8, "delta": 1},
    "real_money_readiness": {"pre": 2, "post": 2, "delta": 0},
    "investor_demo_readiness": {"pre": 4, "post": 7, "delta": 3}
  }
}
```
