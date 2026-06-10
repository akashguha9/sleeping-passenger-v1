"""Generate / verify SHA-256 checksums for release artifacts.

Writes ``dist/SHA256SUMS`` (sha256sum-compatible format) covering the
newest release manifest, dependency lockfiles, key docs, and workflow
files. ``--verify`` recomputes everything and fails on any mismatch —
the tamper check for "is what I have what was released?".

Usage:
    python scripts/generate_checksums.py            # write dist/SHA256SUMS
    python scripts/generate_checksums.py --verify   # recompute + compare
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIST = _REPO_ROOT / "dist"
_SUMS_NAME = "SHA256SUMS"

_TARGETS = (
    "requirements.txt",
    "requirements-dev.txt",
    "frontend/package-lock.json",
    "LICENSE",
    "SECURITY.md",
    "OWNER_ACCESS.md",
    "PROPRIETARY_NOTICE.md",
    ".github/workflows/pytest.yml",
    ".github/workflows/dep_audit.yml",
    ".github/workflows/kante_defensive_gate.yml",
    ".github/workflows/e2e.yml",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_targets(repo_root: Path | None = None, dist: Path | None = None) -> list[Path]:
    root = repo_root or _REPO_ROOT
    dist = dist or _DIST
    targets = [root / rel for rel in _TARGETS if (root / rel).exists()]
    if dist.exists():
        manifests = sorted(dist.glob("release_manifest_*.json"))
        if manifests:
            targets.append(manifests[-1])  # newest manifest
    return targets


def write_sums(repo_root: Path | None = None, dist: Path | None = None) -> Path:
    root = repo_root or _REPO_ROOT
    dist = dist or _DIST
    dist.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in collect_targets(root, dist):
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        lines.append(f"{sha256_file(path)}  {rel}")
    sums_path = dist / _SUMS_NAME
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sums_path


def verify_sums(repo_root: Path | None = None, dist: Path | None = None) -> list[str]:
    """Return mismatches/missing entries (empty = everything verifies)."""
    root = repo_root or _REPO_ROOT
    dist = dist or _DIST
    sums_path = dist / _SUMS_NAME
    if not sums_path.exists():
        return [f"checksum file missing: {sums_path}"]
    problems: list[str] = []
    for lineno, line in enumerate(
        sums_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            expected, rel = line.split(None, 1)
        except ValueError:
            problems.append(f"line {lineno}: unparsable")
            continue
        path = (root / rel.strip()) if not Path(rel.strip()).is_absolute() else Path(rel.strip())
        if not path.exists():
            problems.append(f"{rel.strip()}: file missing")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"{rel.strip()}: checksum MISMATCH (tampered or modified)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        problems = verify_sums()
        if problems:
            print(f"FAIL — {len(problems)} problem(s):")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("PASS — all checksums verify.")
        return 0

    sums_path = write_sums()
    count = len(sums_path.read_text(encoding='utf-8').splitlines())
    print(f"[ok] wrote {sums_path} ({count} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
