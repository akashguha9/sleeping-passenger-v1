"""Build a release-provenance manifest for the advisory MVP.

Produces ``dist/release_manifest_<timestamp>.json`` recording exactly
what a "release" of this owner-only system is: the commit, tree state,
toolchain versions, dependency-lock hashes, key source/workflow file
hashes, and the advisory-only invariant status — enough to later prove
"the thing I ran is the thing that was tested" without a heavyweight
supply-chain platform.

Pair with ``scripts/generate_checksums.py`` (checksums the manifest and
key artifacts) and verify either with ``--verify``-style recomputation.

Usage:
    python scripts/build_release_manifest.py
    python scripts/build_release_manifest.py --test-summary "6551 passed"
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIST = _REPO_ROOT / "dist"

# The provenance-bearing files: dependency locks, safety gates, workflows.
_KEY_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "frontend/package.json",
    "frontend/package-lock.json",
    "scripts/api_server.py",
    "scripts/runtime_config.py",
    "scripts/advisory_contract.py",
    "scripts/persistence.py",
    ".github/workflows/pytest.yml",
    ".github/workflows/dep_audit.yml",
    ".github/workflows/kante_defensive_gate.yml",
    ".github/workflows/e2e.yml",
)


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(_REPO_ROOT), *args],
            capture_output=True, text=True, check=True, timeout=20,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _node_version() -> str:
    try:
        return subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def advisory_invariants() -> dict:
    """Pull the invariant constants straight from the safety module."""
    try:
        from scripts import runtime_config as rc
    except ModuleNotFoundError:  # pragma: no cover
        import runtime_config as rc  # type: ignore[no-redef]
    return {
        "advisory_status": rc.ADVISORY_STATUS,
        "execution_mode": rc.EXECUTION_MODE,
        "execution_gate": rc.EXECUTION_GATE,
        "ai_execution_count": rc.AI_EXECUTION_COUNT,
        "broker_api_called": rc.BROKER_API_CALLED,
    }


def build_manifest(test_summary: str | None = None, repo_root: Path | None = None) -> dict:
    root = repo_root or _REPO_ROOT
    dirty = bool(_git("status", "--porcelain"))
    manifest = {
        "manifest_version": 1,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_dirty": dirty,
        "dirty_warning": (
            "WORKING TREE DIRTY — this manifest does not describe a "
            "reproducible state" if dirty else None
        ),
        "python_version": platform.python_version(),
        "node_version": _node_version(),
        "file_hashes": {},
        "test_summary": test_summary or "not provided",
        "advisory_invariants": advisory_invariants(),
    }
    for rel in _KEY_FILES:
        path = root / rel
        manifest["file_hashes"][rel] = (
            sha256_file(path) if path.exists() else "MISSING"
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-summary", default=None)
    parser.add_argument("--output-dir", default=str(_DIST))
    args = parser.parse_args(argv)

    manifest = build_manifest(args.test_summary)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"release_manifest_{stamp}.json"
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"[ok] release manifest: {out_path}")
    print(f"  commit : {manifest['git_commit'][:12]} ({manifest['git_branch']})")
    print(f"  dirty  : {manifest['git_dirty']}")
    print(f"  python : {manifest['python_version']}  node: {manifest['node_version']}")
    print(f"  files  : {len(manifest['file_hashes'])} hashed")
    if manifest["git_dirty"]:
        print("[warn] working tree is DIRTY — commit first for a "
              "reproducible manifest", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
