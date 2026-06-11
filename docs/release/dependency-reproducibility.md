# Dependency reproducibility

Two install paths, by policy. The audit
(`scripts/audit_dependency_reproducibility.py`, CI-blocking in the
dep-audit policy job) fails if the deterministic path decays.

## Python

| Path | Command | Guarantees |
|---|---|---|
| Dev (convenience) | `pip install -r requirements-dev.txt` | Bounded ranges (`>=X,<Y`). Deliberately floating so `pip-audit --strict` (every push + weekly) and the dependency advisory register pick up patched releases without lock churn. |
| Release (deterministic) | `pip install --require-hashes -r requirements.lock` | Exact versions **and** SHA-256 artifact hashes for the entire resolved tree (prod + test deps), generated for Python 3.13. pip refuses anything unhashed or tampered. |

`requirements.lock` is generated with:

```bash
python3.13 -m piptools compile --generate-hashes --strip-extras \
    --output-file=requirements.lock requirements-dev.txt
```

Regenerate it whenever `requirements.txt` / `requirements-dev.txt` change —
the audit fails closed on a stale lock (any declared top-level package
missing from the lock).

Python version policy: **3.13**, pinned in every workflow
(`python-version: "3.13"`); the patch level floats with the GitHub runner
(accepted, documented residual).

## Node (frontend)

- `frontend/package-lock.json` is committed and required
  (lockfileVersion ≥ 2).
- CI must use `npm ci` (lockfile-exact, fails on drift); the audit fails
  any workflow that uses `npm install`.
- `node-version: "20"` floats on minor/patch (accepted residual).

## Security binaries

gitleaks is downloaded fresh every run, pinned by version **and** SHA-256
(never cached — caches cannot poison it). Enforced by
`scripts/audit_security_gate_integrity.py`.

## Remaining nondeterminism (accepted)

1. Dev-path version ranges (deliberate; see table above).
2. Python/Node patch-level float; `ubuntu-latest` runner image float.
3. The lock is resolved for Linux/CPython 3.13 (the CI/release target);
   other platforms may need a platform-specific lock.
