"""Supply-chain pin guard — every external GitHub Action is SHA-pinned.

Complements tests/test_github_actions_ci.py (least privilege, no
pull_request_target, persist-credentials) with the mutable-tag defense:
a 40-hex commit pin plus a readable version comment on every external
``uses:``. Also exercises scripts/audit_github_actions_pinning.py against
synthetic bad workflows so the CI gate itself is proven to fail closed.
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts import audit_github_actions_pinning as pin

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml")) + sorted(
    (_REPO_ROOT / ".github" / "workflows").glob("*.yaml")
)

_USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)\s*(#.*)?$")


def test_workflow_files_exist():
    assert _WORKFLOWS, "no workflow files found"


def test_every_external_action_is_sha_pinned_with_version_comment():
    offenders: list[str] = []
    for wf in _WORKFLOWS:
        for lineno, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = _USES_RE.match(line)
            if not m:
                continue
            ref, comment = m.group(1), m.group(2)
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            if not re.match(r"^[^@]+@[0-9a-f]{40}$", ref):
                offenders.append(f"{wf.name}:{lineno} not SHA-pinned: {ref}")
            elif not comment or not comment.strip("# ").strip():
                offenders.append(f"{wf.name}:{lineno} missing version comment: {ref}")
    assert offenders == [], offenders


def test_repo_audit_script_passes_on_current_workflows():
    assert pin.audit_all() == []


def test_audit_script_catches_unpinned_action(tmp_path):
    wf = tmp_path / "bad.yml"
    wf.write_text(
        "permissions:\n  contents: read\njobs:\n  j:\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n          persist-credentials: false\n",
        encoding="utf-8",
    )
    violations = pin.audit_all(tmp_path)
    assert any("not SHA-pinned" in v for v in violations), violations


def test_audit_script_catches_missing_version_comment(tmp_path):
    wf = tmp_path / "bad.yml"
    wf.write_text(
        "permissions:\n  contents: read\njobs:\n  j:\n    steps:\n"
        "      - uses: actions/checkout@"
        + "a" * 40
        + "\n        with:\n          persist-credentials: false\n",
        encoding="utf-8",
    )
    violations = pin.audit_all(tmp_path)
    assert any("missing readable version comment" in v for v in violations), violations


def test_audit_script_catches_pull_request_target_and_write_scopes(tmp_path):
    wf = tmp_path / "bad.yml"
    wf.write_text(
        "on:\n  pull_request_target:\npermissions:\n  contents: write\n",
        encoding="utf-8",
    )
    violations = pin.audit_all(tmp_path)
    assert any("pull_request_target" in v for v in violations)
    assert any("write scope" in v for v in violations)


def test_audit_script_catches_persisted_checkout_credentials(tmp_path):
    wf = tmp_path / "bad.yml"
    wf.write_text(
        "permissions:\n  contents: read\njobs:\n  j:\n    steps:\n"
        "      - uses: actions/checkout@" + "b" * 40 + " # v4\n",
        encoding="utf-8",
    )
    violations = pin.audit_all(tmp_path)
    assert any("persist-credentials" in v for v in violations), violations


def test_audit_script_allows_local_actions(tmp_path):
    wf = tmp_path / "ok.yml"
    wf.write_text(
        "permissions:\n  contents: read\njobs:\n  j:\n    steps:\n"
        "      - uses: ./.github/actions/local-thing\n",
        encoding="utf-8",
    )
    violations = pin.audit_all(tmp_path)
    assert violations == [], violations
