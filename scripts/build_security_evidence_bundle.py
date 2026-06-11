"""Build a machine-readable security evidence bundle for the current commit.

Release readiness should be provable, not asserted. This script *re-runs*
the repo's security gates and writes one JSON document recording what was
verified, by which tool, with what result — plus SHA-256 hashes of every
security-relevant file so the evidence is tied to exact content:

    runtime/reports/security_evidence_bundle.json   (gitignored)

Honesty rules (test-pinned in tests/test_security_evidence_bundle.py):

  * every check is ``pass`` / ``fail`` / ``skipped`` — a skipped check is
    NEVER counted as passed;
  * ``overall_pass`` is true only when every check passed and none failed
    or were skipped;
  * the bundle contains command names, exit codes, hashes, and versions —
    never environment values or file contents, so it cannot leak secrets.

CI: generated in the dep-audit ``secrets`` job (after the gitleaks scans,
with ``--skip-pytest`` because test deps are not installed there) and
uploaded as the ``security-evidence-bundle`` artifact. The volatile output
itself is never committed (``runtime/`` is gitignored).

Stdlib only:  python scripts/build_security_evidence_bundle.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = _REPO_ROOT / "runtime" / "reports" / "security_evidence_bundle.json"

try:
    from scripts.audit_historical_secret_ledger import find_gitleaks
except ModuleNotFoundError:  # pragma: no cover - script-style invocation
    sys.path.insert(0, str(_REPO_ROOT))
    from scripts.audit_historical_secret_ledger import find_gitleaks

SCHEMA_VERSION = 1

# Top-level fields every bundle must carry (schema-stability contract).
REQUIRED_FIELDS = (
    "schema_version",
    "generated_at_utc",
    "commit_sha",
    "python_version",
    "platform",
    "gitleaks_version",
    "gitleaks_config_sha256",
    "checks",
    "security_file_hashes",
    "overall_pass",
    "failed_checks",
    "skipped_checks",
)

# Every check the bundle attests to. Each runs a real command; the bundle
# records its exit code. pytest/gitleaks entries may be skipped when the
# environment lacks them — skipped is reported as skipped, never as pass.
_PYTEST_SECURITY_SUBSET = [
    "tests/test_secret_fixture_hygiene.py",
    "tests/test_secret_custody.py",
    "tests/test_runtime_db_permissions.py",
    "tests/test_security_gate_integrity.py",
    "tests/test_historical_secret_ledger.py",
]

# Security-relevant files whose exact content the bundle fingerprints.
_HASHED_FILE_GLOBS = (
    ".gitleaks.toml",
    ".gitleaksignore",
    ".pre-commit-config.yaml",
    ".github/workflows/*.yml",
    "scripts/secret_fixture_lint.py",
    "scripts/audit_security_gate_integrity.py",
    "scripts/audit_historical_secret_ledger.py",
    "scripts/audit_github_actions_pinning.py",
    "scripts/audit_local_data_protection.py",
    "scripts/secret_provider.py",
    "scripts/manage_secrets.py",
    "scripts/persistence.py",
    "scripts/runtime_config.py",
    "scripts/build_security_evidence_bundle.py",
    "docs/security/historical_findings_ledger.json",
    "SECURITY.md",
    "CONTRIBUTING.md",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_runner(cmd: list[str]) -> int:
    """Run a command from the repo root; return its exit code."""
    return subprocess.run(
        cmd, cwd=_REPO_ROOT, capture_output=True, text=True, check=False
    ).returncode


def _check(status: str, command: list[str], returncode: int | None) -> dict[str, Any]:
    assert status in ("pass", "fail", "skipped")
    return {"status": status, "command": " ".join(command), "returncode": returncode}


def collect(
    *,
    skip_pytest: bool = False,
    runner: Callable[[list[str]], int] = _default_runner,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """Assemble the bundle dict. ``runner`` is injectable for tests."""
    py = sys.executable

    def run_check(cmd: list[str]) -> dict[str, Any]:
        rc = runner(cmd)
        return _check("pass" if rc == 0 else "fail", cmd, rc)

    checks: dict[str, dict[str, Any]] = {}
    checks["secret_fixture_lint"] = run_check([py, "scripts/secret_fixture_lint.py"])
    checks["workflow_pinning_audit"] = run_check(
        [py, "scripts/audit_github_actions_pinning.py"]
    )
    checks["security_gate_integrity_audit"] = run_check(
        [py, "scripts/audit_security_gate_integrity.py"]
    )
    checks["local_data_protection_audit"] = run_check(
        [py, "scripts/audit_local_data_protection.py"]
    )

    gitleaks = find_gitleaks()
    gitleaks_version = "unavailable"
    if gitleaks is None:
        checks["gitleaks_tree_scan"] = _check(
            "skipped", ["gitleaks", "detect", "--no-git"], None
        )
        checks["gitleaks_commit_scan"] = _check(
            "skipped", ["gitleaks", "detect", "--log-opts=-1"], None
        )
    else:
        version_probe = subprocess.run(
            [gitleaks, "version"], capture_output=True, text=True, check=False
        )
        gitleaks_version = version_probe.stdout.strip() or "unknown"
        # No --report-path: the bundle records exit codes, not findings,
        # and must never write scanner output anywhere it could linger.
        tree_cmd = [
            gitleaks, "detect", "--no-git", "--config=.gitleaks.toml",
            "--redact", "--exit-code=2", "--source=.",
        ]
        commit_cmd = [
            gitleaks, "detect", "--config=.gitleaks.toml", "--redact",
            "--exit-code=2", "--log-opts=-1",
        ]
        checks["gitleaks_tree_scan"] = run_check(tree_cmd)
        checks["gitleaks_commit_scan"] = run_check(commit_cmd)

    if skip_pytest:
        checks["pytest_security_subset"] = _check(
            "skipped", [py, "-m", "pytest", *_PYTEST_SECURITY_SUBSET], None
        )
    else:
        checks["pytest_security_subset"] = run_check(
            [py, "-m", "pytest", "-q", *_PYTEST_SECURITY_SUBSET]
        )

    # List of {path, sha256} objects, NOT a {path: hash} map: several of
    # these paths contain the word "secret", and a JSON line of the form
    # "<secret-ish name>": "<64 hex chars>" is exactly what gitleaks'
    # generic-api-key rule flags. Keeping the path and the hex digest on
    # separate lines keeps the bundle itself scanner-clean (it lives in
    # the working tree that the full-tree --no-git scan inspects).
    hashes: list[dict[str, str]] = []
    for pattern in _HASHED_FILE_GLOBS:
        for path in sorted(repo_root.glob(pattern)):
            if path.is_file():
                hashes.append({
                    "path": path.relative_to(repo_root).as_posix(),
                    "sha256": _sha256(path),
                })

    failed = sorted(k for k, c in checks.items() if c["status"] == "fail")
    skipped = sorted(k for k, c in checks.items() if c["status"] == "skipped")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root, capture_output=True, text=True, check=False,
    ).stdout.strip()

    config = repo_root / ".gitleaks.toml"
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": head,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "gitleaks_version": gitleaks_version,
        "gitleaks_config_sha256": _sha256(config) if config.exists() else None,
        "checks": checks,
        "security_file_hashes": hashes,
        # Honest aggregation: a skipped check is evidence of NOTHING, so it
        # blocks overall_pass just like a failure does.
        "overall_pass": not failed and not skipped,
        "failed_checks": failed,
        "skipped_checks": skipped,
    }
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--skip-pytest", action="store_true",
        help="record the pytest check as skipped (e.g. CI jobs without "
             "test dependencies installed); skipped is not pass",
    )
    parser.add_argument(
        "--allow-skips", action="store_true",
        help="exit 0 even when checks were skipped (overall_pass in the "
             "bundle still honestly reflects the skips)",
    )
    args = parser.parse_args(argv)

    bundle = collect(skip_pytest=args.skip_pytest)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

    print(f"security evidence bundle: {out}")
    for name, check in sorted(bundle["checks"].items()):
        print(f"  {check['status']:7s} {name}")
    print(f"  overall_pass: {bundle['overall_pass']}")
    if bundle["failed_checks"]:
        return 1
    if bundle["skipped_checks"] and not args.allow_skips:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
