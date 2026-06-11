"""One-command operator release-readiness check.

    python scripts/run_release_readiness_check.py            # default = --quick
    python scripts/run_release_readiness_check.py --full     # + pytest subset
    python scripts/run_release_readiness_check.py --json     # machine-readable

Runs the repo's gates in dependency order and prints one compact table.
Honesty rules match the evidence bundles: skipped is never pass. FINAL is
PASS only when every gate ran and passed; a quick run that skips gates
reports PASS_WITH_SKIPS and exits 2, so it can never masquerade as a
full run.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.audit_historical_secret_ledger import find_gitleaks
except ModuleNotFoundError:  # pragma: no cover - script-style invocation
    sys.path.insert(0, str(_REPO_ROOT))
    from scripts.audit_historical_secret_ledger import find_gitleaks

SCHEMA_VERSION = 1

_PYTEST_SECURITY_SUBSET = [
    "tests/test_secret_fixture_hygiene.py",
    "tests/test_security_gate_integrity.py",
    "tests/test_advisory_only_boundary.py",
    "tests/test_model_evaluation_honesty.py",
    "tests/test_dependency_reproducibility.py",
    "tests/test_release_evidence_bundle.py",
    "tests/test_runtime_db_permissions.py",
]


def _default_runner(cmd: list[str]) -> int:
    return subprocess.run(
        cmd, cwd=_REPO_ROOT, capture_output=True, text=True, check=False
    ).returncode


def build_plan(*, full: bool, gitleaks_bin: str | None) -> list[dict[str, Any]]:
    """Ordered gate plan. Each entry: name, cmd (None ⇒ skipped+reason)."""
    py = sys.executable
    plan: list[dict[str, Any]] = [
        {"name": "secret_fixture_lint",
         "cmd": [py, "scripts/secret_fixture_lint.py"]},
        {"name": "gitleaks_tree_scan",
         "cmd": (
             [gitleaks_bin, "detect", "--no-git", "--config=.gitleaks.toml",
              "--redact", "--exit-code=2", "--source=."]
             if gitleaks_bin else None
         ),
         "skip_reason": "gitleaks binary unavailable (install per "
                        ".github/workflows/dep_audit.yml)"},
        {"name": "security_gate_integrity",
         "cmd": [py, "scripts/audit_security_gate_integrity.py"]},
        {"name": "dependency_reproducibility",
         "cmd": [py, "scripts/audit_dependency_reproducibility.py"]},
        {"name": "advisory_only_boundary",
         "cmd": [py, "scripts/audit_advisory_only_boundary.py"]},
        {"name": "model_evaluation_honesty",
         "cmd": [py, "scripts/audit_model_evaluation_honesty.py"]},
        {"name": "local_data_protection",
         "cmd": [py, "scripts/audit_local_data_protection.py"]},
        {"name": "release_evidence_bundle",
         "cmd": [py, "scripts/build_release_evidence_bundle.py",
                 "--skip-pytest", "--allow-skips"]},
        {"name": "pytest_security_subset",
         "cmd": (
             [py, "-m", "pytest", "-q", *_PYTEST_SECURITY_SUBSET]
             if full else None
         ),
         "skip_reason": "quick mode (--full runs the pytest subset)"},
    ]
    return plan


def run_checks(
    *,
    full: bool,
    runner: Callable[[list[str]], int] = _default_runner,
    gitleaks_bin: str | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for step in build_plan(full=full, gitleaks_bin=gitleaks_bin):
        if step["cmd"] is None:
            results.append({
                "name": step["name"],
                "status": "skipped",
                "returncode": None,
                "detail": step.get("skip_reason", "skipped"),
            })
            continue
        rc = runner(step["cmd"])
        results.append({
            "name": step["name"],
            "status": "pass" if rc == 0 else "fail",
            "returncode": rc,
            "detail": " ".join(str(c) for c in step["cmd"]),
        })
    failed = [r["name"] for r in results if r["status"] == "fail"]
    skipped = [r["name"] for r in results if r["status"] == "skipped"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "full" if full else "quick",
        "checks": results,
        "failed": failed,
        "skipped": skipped,
        # PASS requires everything to have actually run and passed.
        "final_status": "PASS" if not failed and not skipped else (
            "FAIL" if failed else "PASS_WITH_SKIPS"
        ),
    }


def render_table(report: dict[str, Any]) -> str:
    lines = [
        f"release readiness check — mode={report['mode']}",
        f"{'gate':32s} status",
        f"{'-' * 32} ------",
    ]
    for check in report["checks"]:
        lines.append(f"{check['name']:32s} {check['status'].upper()}")
    lines.append(f"{'-' * 32} ------")
    lines.append(f"{'FINAL':32s} {report['final_status']}")
    if report["skipped"]:
        lines.append(f"skipped: {', '.join(report['skipped'])}")
    if report["failed"]:
        lines.append(f"failed:  {', '.join(report['failed'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true",
                      help="skip the pytest subset (default)")
    mode.add_argument("--full", action="store_true",
                      help="run everything including the pytest subset")
    parser.add_argument("--json", action="store_true",
                        help="emit the machine-readable report")
    args = parser.parse_args(argv)

    report = run_checks(full=args.full, gitleaks_bin=find_gitleaks())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_table(report))
    if report["failed"]:
        return 1
    if report["skipped"]:
        return 2  # distinct: nothing failed, but the run is not complete
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
