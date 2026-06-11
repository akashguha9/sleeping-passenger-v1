"""Dependency reproducibility audit — deterministic installs are provable.

Two install paths exist by policy (docs/release/dependency-reproducibility.md):

  * DEV path (convenience): ``pip install -r requirements-dev.txt`` —
    bounded ranges (``>=X,<Y``), deliberately floating so the weekly
    ``pip-audit --strict`` + dependency advisory register can pick up
    patched releases without churn.
  * RELEASE path (deterministic): ``pip install --require-hashes -r
    requirements.lock`` — a pip-compile-generated, SHA-256-hash-locked
    resolution of the full dev set for Python 3.13.

This audit fails when the deterministic path decays:

  * ``requirements.lock`` missing, or any pinned line missing a
    ``--hash=sha256:`` (hash enforcement is all-or-nothing in pip);
  * a top-level requirement added to requirements*.txt but absent from
    the lock (stale lock → silent drift);
  * a workflow using ``npm install`` where ``npm ci`` is required, or
    ``frontend/package-lock.json`` missing;
  * a workflow setup-python that is not pinned to the repo's 3.13 policy.

It also REPORTS (without failing) the known, deliberate nondeterminism so
the residual risk is visible instead of forgotten.

Stdlib only:  python scripts/audit_dependency_reproducibility.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

PYTHON_VERSION_POLICY = "3.13"
LOCKFILE = "requirements.lock"

_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def top_level_requirements(repo_root: Path = _REPO_ROOT) -> set[str]:
    """Package names declared in requirements.txt + requirements-dev.txt."""
    names: set[str] = set()
    for fname in ("requirements.txt", "requirements-dev.txt"):
        path = repo_root / fname
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-r", "--")):
                continue
            m = _REQ_NAME_RE.match(stripped)
            if m:
                names.add(_normalize(m.group(1)))
    return names


def audit_python_lock(repo_root: Path = _REPO_ROOT) -> list[str]:
    violations: list[str] = []
    lock = repo_root / LOCKFILE
    if not lock.exists():
        return [f"{LOCKFILE} missing — no deterministic release install path"]
    text = lock.read_text(encoding="utf-8")
    pinned: set[str] = set()
    pending_pkg: str | None = None
    pending_has_hash = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--hash=sha256:") or (
            stripped.startswith("--hash=") and "sha256:" in stripped
        ):
            pending_has_hash = True
            continue
        if stripped.startswith("--"):
            continue  # other pip options
        # a new "name==version \" line begins
        if pending_pkg is not None and not pending_has_hash:
            violations.append(
                f"{LOCKFILE}: {pending_pkg} pinned without a sha256 hash"
            )
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", stripped)
        if m:
            pending_pkg = _normalize(m.group(1))
            pinned.add(pending_pkg)
            pending_has_hash = "--hash=sha256:" in stripped
        else:
            pending_pkg = None
    if pending_pkg is not None and not pending_has_hash:
        violations.append(f"{LOCKFILE}: {pending_pkg} pinned without a sha256 hash")

    missing = sorted(top_level_requirements(repo_root) - pinned)
    for name in missing:
        violations.append(
            f"{LOCKFILE}: stale — declared requirement {name!r} is not in "
            f"the lock (regenerate: see docs/release/dependency-"
            "reproducibility.md)"
        )
    return violations


def audit_node_lock(repo_root: Path = _REPO_ROOT) -> list[str]:
    violations: list[str] = []
    lock = repo_root / "frontend" / "package-lock.json"
    if not lock.exists():
        return ["frontend/package-lock.json missing"]
    try:
        version = json.loads(lock.read_text(encoding="utf-8")).get(
            "lockfileVersion", 0
        )
    except json.JSONDecodeError:
        return ["frontend/package-lock.json is not valid JSON"]
    if int(version) < 2:
        violations.append(
            f"frontend/package-lock.json lockfileVersion {version} < 2"
        )
    return violations


def audit_workflows(workflows_dir: Path | None = None) -> list[str]:
    violations: list[str] = []
    wf_dir = workflows_dir or (_REPO_ROOT / ".github" / "workflows")
    for wf in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        for lineno, line in enumerate(
            wf.read_text(encoding="utf-8").splitlines(), start=1
        ):
            code = line.split("#", 1)[0]
            # npm ci is the only deterministic install; npm install both
            # mutates the lockfile and floats transitive resolution.
            if re.search(r"\bnpm\s+install\b", code) and "npm ci" not in code:
                violations.append(
                    f"{wf.name}:{lineno}: uses 'npm install' — must be "
                    "'npm ci' (lockfile-exact, fails on drift)"
                )
            m = re.search(r"python-version:\s*[\"']?([\w.]+)", code)
            if m and m.group(1) != PYTHON_VERSION_POLICY:
                violations.append(
                    f"{wf.name}:{lineno}: python-version {m.group(1)!r} "
                    f"diverges from the {PYTHON_VERSION_POLICY} policy"
                )
    return violations


def known_residual_nondeterminism() -> list[str]:
    """Documented-and-accepted drift surfaces (reported, never failed)."""
    return [
        "dev install path uses bounded ranges by policy (paired with "
        "pip-audit --strict per push + weekly + advisory register)",
        f"python-version '{PYTHON_VERSION_POLICY}' floats on patch level "
        "(GitHub runner controls the patch)",
        "node-version '20' floats on minor/patch; ubuntu-latest floats "
        "the runner image",
    ]


def audit_all(repo_root: Path = _REPO_ROOT) -> list[str]:
    return (
        audit_python_lock(repo_root)
        + audit_node_lock(repo_root)
        + audit_workflows(repo_root / ".github" / "workflows")
    )


def main() -> int:
    violations = audit_all()
    print(f"dependency reproducibility audit: {_REPO_ROOT}")
    print(f"  python version policy: {PYTHON_VERSION_POLICY} (workflow-pinned)")
    lock = _REPO_ROOT / LOCKFILE
    if lock.exists():
        hashes = lock.read_text(encoding="utf-8").count("--hash=sha256:")
        print(f"  {LOCKFILE}: present, {hashes} sha256 hashes "
              "(install: pip install --require-hashes -r requirements.lock)")
    print("  frontend: package-lock.json + npm ci enforced")
    print("  known residual nondeterminism (accepted, documented):")
    for item in known_residual_nondeterminism():
        print(f"    * {item}")
    if violations:
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("PASS — deterministic release install path intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
