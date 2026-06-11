"""Build the tamper-evident release evidence bundle.

One JSON document that a reviewer can verify instead of trusting:

    runtime/reports/release_evidence_bundle.json   (gitignored)

It extends the security evidence bundle (which it builds and embeds by
hash) with release-grade facts: branch + dirty-tree status, dependency
lockfile hashes, workflow and core-source hashes, the advisory-only
boundary / dependency-reproducibility / model-honesty audit results, the
release-readiness scorecard, an honest blockers list, and the permanent
``not_real_money_execution_software: true`` flag.

Tamper evidence: every critical file is SHA-256 fingerprinted, and a final
``bundle_sha256`` is computed over the canonicalized bundle (sorted keys,
compact separators) with the ``bundle_sha256`` field excluded. Any edit to
the bundle — or to a fingerprinted file afterward — is detected by
``scripts/verify_release_evidence_bundle.py``.

Honesty rules (test-pinned): skipped is never pass; ``overall_pass`` is
true only with zero failures and zero skips; a dirty working tree is
flagged in the bundle and can never be hidden; the bundle carries
commands, exit codes, hashes, and versions — never secret values.

Stdlib only:  python scripts/build_release_evidence_bundle.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = _REPO_ROOT / "runtime" / "reports" / "release_evidence_bundle.json"

try:
    from scripts import build_security_evidence_bundle as security_bundle
except ModuleNotFoundError:  # pragma: no cover - script-style invocation
    sys.path.insert(0, str(_REPO_ROOT))
    from scripts import build_security_evidence_bundle as security_bundle

SCHEMA_VERSION = 1

REQUIRED_FIELDS = (
    "schema_version",
    "generated_at_utc",
    "commit_sha",
    "branch",
    "dirty_tree",
    "python_version",
    "node_version",
    "platform",
    "dependency_lockfile_hashes",
    "gitleaks_config_sha256",
    "workflow_hashes",
    "core_source_hashes",
    "checks",
    "security_evidence_bundle_sha256",
    "release_readiness_scorecard",
    "known_blockers",
    "not_real_money_execution_software",
    "overall_pass",
    "failed_checks",
    "skipped_checks",
    "bundle_sha256",
)

_LOCKFILES = ("requirements.lock", "frontend/package-lock.json")

_CORE_SOURCE = (
    "scripts/persistence.py",
    "scripts/runtime_config.py",
    "scripts/api_server.py",
    "scripts/advisory_contract.py",
    "scripts/data_quality.py",
    "scripts/audit_advisory_only_boundary.py",
    "scripts/audit_dependency_reproducibility.py",
    "scripts/audit_model_evaluation_honesty.py",
    "scripts/audit_security_gate_integrity.py",
    "scripts/secret_fixture_lint.py",
    "scripts/build_security_evidence_bundle.py",
    "scripts/build_release_evidence_bundle.py",
    "scripts/verify_release_evidence_bundle.py",
)

_PYTEST_RELEASE_SUBSET = [
    "tests/test_advisory_only_boundary.py",
    "tests/test_dependency_reproducibility.py",
    "tests/test_model_evaluation_honesty.py",
    "tests/test_release_evidence_bundle.py",
    "tests/test_security_gate_integrity.py",
]

_SCORECARD = _REPO_ROOT / "docs" / "release" / "release_readiness_scorecard.md"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _hash_list(repo_root: Path, patterns: tuple[str, ...]) -> list[dict[str, str]]:
    # {path, sha256} object pairs (never "<name>": "<hex>" maps — see the
    # scanner-bait note in build_security_evidence_bundle).
    out: list[dict[str, str]] = []
    for pattern in patterns:
        for path in sorted(repo_root.glob(pattern)):
            if path.is_file():
                out.append({
                    "path": path.relative_to(repo_root).as_posix(),
                    "sha256": _sha256_file(path),
                })
    return out


def canonical_bundle_sha256(bundle: dict[str, Any]) -> str:
    """SHA-256 over the canonicalized bundle, excluding bundle_sha256."""
    stripped = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    canonical = json.dumps(
        stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return _sha256_bytes(canonical.encode("utf-8"))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=False,
    ).stdout.strip()


def _default_runner(cmd: list[str]) -> int:
    return subprocess.run(
        cmd, cwd=_REPO_ROOT, capture_output=True, text=True, check=False
    ).returncode


def _scorecard_summary() -> dict[str, Any]:
    if not _SCORECARD.exists():
        return {"status": "missing", "path": str(_SCORECARD)}
    text = _SCORECARD.read_text(encoding="utf-8")
    m = re.search(r"```json\n(.*?)```", text, re.DOTALL)
    summary: dict[str, Any] = {
        "path": _SCORECARD.relative_to(_REPO_ROOT).as_posix(),
        "sha256": _sha256_file(_SCORECARD),
    }
    if m:
        try:
            summary["segments"] = json.loads(m.group(1)).get("segments", {})
        except json.JSONDecodeError:
            summary["segments"] = "unparseable"
    return summary


def collect(
    *,
    skip_pytest: bool = False,
    runner: Callable[[list[str]], int] = _default_runner,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    py = sys.executable

    def run_check(name: str, cmd: list[str], checks: dict) -> None:
        rc = runner(cmd)
        checks[name] = {
            "status": "pass" if rc == 0 else "fail",
            "command": " ".join(cmd),
            "returncode": rc,
        }

    checks: dict[str, dict[str, Any]] = {}
    run_check("advisory_only_boundary",
              [py, "scripts/audit_advisory_only_boundary.py"], checks)
    run_check("dependency_reproducibility",
              [py, "scripts/audit_dependency_reproducibility.py"], checks)
    run_check("model_evaluation_honesty",
              [py, "scripts/audit_model_evaluation_honesty.py"], checks)
    run_check("security_gate_integrity",
              [py, "scripts/audit_security_gate_integrity.py"], checks)

    # Build the security evidence bundle in-process and embed it by hash;
    # its own pass/fail aggregation becomes one check here.
    sec = security_bundle.collect(skip_pytest=True, runner=runner)
    sec_serialized = json.dumps(sec, indent=2) + "\n"
    sec_path = security_bundle.DEFAULT_OUTPUT
    sec_path.parent.mkdir(parents=True, exist_ok=True)
    sec_path.write_text(sec_serialized, encoding="utf-8")
    sec_failed = bool(sec["failed_checks"])
    checks["security_evidence_bundle"] = {
        "status": "fail" if sec_failed else "pass",
        "command": "scripts/build_security_evidence_bundle.py (in-process)",
        "returncode": 1 if sec_failed else 0,
    }

    if skip_pytest:
        checks["pytest_release_subset"] = {
            "status": "skipped",
            "command": f"{py} -m pytest -q " + " ".join(_PYTEST_RELEASE_SUBSET),
            "returncode": None,
        }
    else:
        run_check("pytest_release_subset",
                  [py, "-m", "pytest", "-q", *_PYTEST_RELEASE_SUBSET], checks)

    node_probe = subprocess.run(
        ["node", "--version"], capture_output=True, text=True, check=False
    )
    failed = sorted(k for k, c in checks.items() if c["status"] == "fail")
    skipped = sorted(k for k, c in checks.items() if c["status"] == "skipped")

    honesty_report = repo_root / "runtime" / "reports" / "model_evaluation_honesty.json"
    blockers = [
        "no live out-of-sample performance evidence (advisory tooling is "
        "not validated alpha)",
        "dev dependency path uses bounded ranges by policy (release path "
        "is hash-locked)",
        "evidence bundle is hash-verified but not cryptographically signed",
    ]
    if honesty_report.exists():
        try:
            card = json.loads(honesty_report.read_text(encoding="utf-8"))
            blockers.extend(
                f"model evidence missing: {item}"
                for item, entry in card.get("evidence_scorecard", {}).items()
                if entry.get("status") == "missing"
                and item != "live_out_of_sample_results"
            )
        except json.JSONDecodeError:
            pass

    config = repo_root / ".gitleaks.toml"
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        # A dirty tree means the hashes below describe content that is NOT
        # the named commit. Never hidden, always loud.
        "dirty_tree": bool(_git("status", "--porcelain")),
        "python_version": platform.python_version(),
        "node_version": node_probe.stdout.strip() or "unavailable",
        "platform": platform.platform(),
        "dependency_lockfile_hashes": _hash_list(repo_root, _LOCKFILES),
        "gitleaks_config_sha256": _sha256_file(config) if config.exists() else None,
        "workflow_hashes": _hash_list(repo_root, (".github/workflows/*.yml",)),
        "core_source_hashes": _hash_list(repo_root, _CORE_SOURCE),
        "checks": checks,
        "security_evidence_bundle_sha256": _sha256_bytes(
            sec_serialized.encode("utf-8")
        ),
        "release_readiness_scorecard": _scorecard_summary(),
        "known_blockers": sorted(set(blockers)),
        # Permanent product fact, not a status: this software cannot and
        # does not execute trades.
        "not_real_money_execution_software": True,
        "overall_pass": not failed and not skipped,
        "failed_checks": failed,
        "skipped_checks": skipped,
    }
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--allow-skips", action="store_true",
                        help="exit 0 despite skipped checks (the bundle "
                             "still records them honestly)")
    args = parser.parse_args(argv)

    bundle = collect(skip_pytest=args.skip_pytest)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

    print(f"release evidence bundle: {out}")
    for name, check in sorted(bundle["checks"].items()):
        print(f"  {check['status']:7s} {name}")
    print(f"  dirty_tree: {bundle['dirty_tree']}")
    print(f"  bundle_sha256: {bundle['bundle_sha256']}")
    print(f"  overall_pass: {bundle['overall_pass']}")
    if bundle["failed_checks"]:
        return 1
    if bundle["skipped_checks"] and not args.allow_skips:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
