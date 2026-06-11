"""Verify a release evidence bundle: tamper-evidence made checkable.

    python scripts/verify_release_evidence_bundle.py \
        runtime/reports/release_evidence_bundle.json

Checks, in order (all must hold):

  1. ``bundle_sha256`` matches the canonicalized bundle content — any
     post-generation edit to the JSON fails here (exit 1);
  2. every fingerprinted file (lockfiles, workflows, core source) still
     hashes to the recorded SHA-256 — any file changed since the bundle
     was built fails here (exit 2);
  3. internal honesty invariants hold: failed/skipped checks imply
     ``overall_pass`` is false, statuses use the closed vocabulary, and
     ``not_real_money_execution_software`` is present and true (exit 3).

Stdlib only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.build_release_evidence_bundle import canonical_bundle_sha256
except ModuleNotFoundError:  # pragma: no cover - script-style invocation
    sys.path.insert(0, str(_REPO_ROOT))
    from scripts.build_release_evidence_bundle import canonical_bundle_sha256

EXIT_OK = 0
EXIT_TAMPERED_BUNDLE = 1
EXIT_FILE_DRIFT = 2
EXIT_INCONSISTENT = 3

_HASH_LIST_FIELDS = (
    "dependency_lockfile_hashes",
    "workflow_hashes",
    "core_source_hashes",
)


def verify(bundle: dict, repo_root: Path = _REPO_ROOT) -> tuple[int, list[str]]:
    """Pure verification. Returns (exit_code, problem list)."""
    problems: list[str] = []

    recorded = bundle.get("bundle_sha256", "")
    actual = canonical_bundle_sha256(bundle)
    if recorded != actual:
        return EXIT_TAMPERED_BUNDLE, [
            "bundle_sha256 mismatch — the bundle JSON was modified after "
            f"generation (recorded {recorded[:12]}…, actual {actual[:12]}…)"
        ]

    import hashlib

    for field in _HASH_LIST_FIELDS:
        for entry in bundle.get(field, []):
            path = repo_root / entry["path"]
            if not path.exists():
                problems.append(f"{field}: {entry['path']} no longer exists")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry["sha256"]:
                problems.append(
                    f"{field}: {entry['path']} changed since the bundle was "
                    "built (hash mismatch)"
                )
    if problems:
        return EXIT_FILE_DRIFT, problems

    checks = bundle.get("checks", {})
    statuses = {c.get("status") for c in checks.values()}
    if not statuses <= {"pass", "fail", "skipped"}:
        problems.append(f"unknown check status values: {statuses}")
    has_bad = any(c.get("status") in ("fail", "skipped") for c in checks.values())
    if has_bad and bundle.get("overall_pass") is True:
        problems.append(
            "overall_pass=true despite failed/skipped checks — "
            "dishonest aggregation"
        )
    if bundle.get("not_real_money_execution_software") is not True:
        problems.append(
            "not_real_money_execution_software flag missing or not true"
        )
    if problems:
        return EXIT_INCONSISTENT, problems
    return EXIT_OK, []


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: verify_release_evidence_bundle.py <bundle.json>")
        return EXIT_INCONSISTENT
    path = Path(args[0])
    bundle = json.loads(path.read_text(encoding="utf-8"))
    code, problems = verify(bundle)
    print(f"release evidence bundle verification: {path}")
    if code != EXIT_OK:
        print(f"FAIL (exit {code}):")
        for p in problems:
            print(f"  - {p}")
        return code
    print(
        f"PASS — bundle intact (sha256 {bundle['bundle_sha256'][:16]}…), "
        f"all fingerprinted files unchanged, aggregation honest, "
        f"dirty_tree={bundle.get('dirty_tree')}."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
