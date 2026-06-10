"""Supply-chain audit: every external GitHub Action must be SHA-pinned.

Tags like ``@v4`` are mutable — a compromised upstream can repoint them at
malicious code and every workflow that floats on the tag runs it with the
repo's token. Pinning to a full 40-hex commit SHA freezes the exact code.

Rules enforced (exit 1 on any violation):
  * every external ``uses:`` is pinned to a 40-character commit SHA;
  * the pin carries a human-readable trailing comment (e.g. ``# v4.3.1``);
  * ``pull_request_target`` never appears;
  * every workflow declares ``permissions:`` with ``contents: read`` and
    no write scopes;
  * every ``actions/checkout`` step sets ``persist-credentials: false``.

Local actions (``uses: ./...``) and docker actions are exempt from SHA
pinning. Stdlib only — runnable in CI without installing dependencies:

    python scripts/audit_github_actions_pinning.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

_USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)\s*(#.*)?$")
_SHA_PIN_RE = re.compile(r"^[^@]+@[0-9a-f]{40}$")
_WRITE_SCOPES = ("contents: write", "packages: write", "id-token: write",
                 "actions: write", "deployments: write")


def audit_workflow(path: Path) -> list[str]:
    """Return a list of human-readable violations for one workflow file."""
    violations: list[str] = []
    text = path.read_text(encoding="utf-8")
    name = path.name

    if "pull_request_target" in text:
        violations.append(f"{name}: uses pull_request_target (forbidden)")
    if "permissions:" not in text:
        violations.append(f"{name}: missing permissions block")
    elif "contents: read" not in text:
        violations.append(f"{name}: permissions block is not read-only")
    for scope in _WRITE_SCOPES:
        if scope in text:
            violations.append(f"{name}: write scope present ({scope})")

    checkout_steps = text.count("actions/checkout@")
    persisted_off = text.count("persist-credentials: false")
    if checkout_steps > persisted_off:
        violations.append(
            f"{name}: {checkout_steps} checkout step(s) but only "
            f"{persisted_off} persist-credentials: false"
        )

    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _USES_RE.match(line)
        if not m:
            continue
        ref, comment = m.group(1), m.group(2)
        if ref.startswith("./") or ref.startswith("docker://"):
            continue  # local / docker actions are not tag-pinnable
        if not _SHA_PIN_RE.match(ref):
            violations.append(
                f"{name}:{lineno}: external action not SHA-pinned: {ref}"
            )
        elif not comment or not comment.strip("# ").strip():
            violations.append(
                f"{name}:{lineno}: SHA pin missing readable version comment: {ref}"
            )
    return violations


def audit_all(workflows_dir: Path = _WORKFLOWS_DIR) -> list[str]:
    violations: list[str] = []
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    if not files:
        return [f"no workflow files found under {workflows_dir}"]
    for path in files:
        violations.extend(audit_workflow(path))
    return violations


def main() -> int:
    violations = audit_all()
    files = sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(_WORKFLOWS_DIR.glob("*.yaml"))
    print(f"github-actions pinning audit: {len(files)} workflow file(s)")
    if violations:
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("PASS — all external actions SHA-pinned, least-privilege, "
          "no pull_request_target, checkout credentials not persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
