"""Proofs for scripts/audit_github_owner_controls.py using mocked gh output.

The audit must: classify honestly (safe / unsafe / not-verifiable), never
fake success when gh is missing, exit non-zero ONLY on verified-unsafe
states, and produce the four-section markdown report.
"""
from __future__ import annotations

import json

from scripts import audit_github_owner_controls as goc

REPO = "akashguha9/sleeping-passenger-v1"


def _runner_factory(responses: dict[str, tuple[int, str]], default=(1, "denied")):
    """Build a mock runner keyed on a substring of the gh command."""
    calls: list[list[str]] = []

    def runner(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        joined = " ".join(args)
        for key, resp in responses.items():
            if key in joined:
                return resp
        return default

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


_GOOD_RESPONSES = {
    "auth status": (0, "logged in"),
    "repo view": (0, json.dumps({
        "visibility": "PRIVATE", "isPrivate": True,
        "defaultBranchRef": {"name": "main"}, "isFork": False,
    })),
    "branches/main/protection": (0, json.dumps({
        "required_status_checks": {"contexts": ["backend pytest", "defensive gate"]},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    })),
    "actions/permissions/workflow": (0, json.dumps({
        "default_workflow_permissions": "read",
        "can_approve_pull_request_reviews": False,
    })),
    "collaborators": (0, json.dumps([{"login": "akashguha9", "role_name": "admin"}])),
    "keys": (0, json.dumps([])),
    "hooks": (0, json.dumps([])),
    "actions/secrets": (0, json.dumps({"total_count": 0, "secrets": []})),
    "environments": (0, json.dumps({"environments": []})),
    "vulnerability-alerts": (0, ""),
    "security_and_analysis": (0, json.dumps({"secret_scanning": {"status": "enabled"}})),
}


def test_all_safe_when_gh_reports_good_state(monkeypatch):
    monkeypatch.setattr(goc.shutil, "which", lambda _: "/usr/bin/gh")
    runner = _runner_factory(_GOOD_RESPONSES)
    outcome = goc.audit(REPO, runner)
    assert outcome["gh"] is True
    statuses = {name: status for name, status, _ in outcome["results"]}
    assert statuses["repo visibility"] == goc.SAFE
    assert statuses["default branch"] == goc.SAFE
    assert statuses["branch protection on main"] == goc.SAFE
    assert statuses["required status checks"] == goc.SAFE
    assert statuses["force pushes"] == goc.SAFE
    assert statuses["branch deletion"] == goc.SAFE
    assert statuses["workflow default permissions"] == goc.SAFE
    assert statuses["deploy keys"] == goc.SAFE
    assert goc.UNSAFE not in statuses.values()


def test_public_repo_is_verified_unsafe(monkeypatch):
    monkeypatch.setattr(goc.shutil, "which", lambda _: "/usr/bin/gh")
    responses = dict(_GOOD_RESPONSES)
    responses["repo view"] = (0, json.dumps({
        "visibility": "PUBLIC", "isPrivate": False,
        "defaultBranchRef": {"name": "main"},
    }))
    outcome = goc.audit(REPO, _runner_factory(responses))
    statuses = {name: status for name, status, _ in outcome["results"]}
    assert statuses["repo visibility"] == goc.UNSAFE


def test_force_push_and_write_permissions_flagged_unsafe(monkeypatch):
    monkeypatch.setattr(goc.shutil, "which", lambda _: "/usr/bin/gh")
    responses = dict(_GOOD_RESPONSES)
    responses["branches/main/protection"] = (0, json.dumps({
        "required_status_checks": None,
        "allow_force_pushes": {"enabled": True},
        "allow_deletions": {"enabled": True},
    }))
    responses["actions/permissions/workflow"] = (0, json.dumps({
        "default_workflow_permissions": "write",
        "can_approve_pull_request_reviews": True,
    }))
    outcome = goc.audit(REPO, _runner_factory(responses))
    statuses = {name: status for name, status, _ in outcome["results"]}
    assert statuses["force pushes"] == goc.UNSAFE
    assert statuses["branch deletion"] == goc.UNSAFE
    assert statuses["required status checks"] == goc.UNSAFE
    assert statuses["workflow default permissions"] == goc.UNSAFE
    assert statuses["workflows can approve PRs"] == goc.UNSAFE


def test_permission_denied_is_not_verifiable_not_unsafe(monkeypatch):
    """Lack of API access must never be reported as unsafe (or safe)."""
    monkeypatch.setattr(goc.shutil, "which", lambda _: "/usr/bin/gh")
    responses = {"auth status": (0, "ok"), "repo view": _GOOD_RESPONSES["repo view"]}
    outcome = goc.audit(REPO, _runner_factory(responses, default=(1, "HTTP 403")))
    statuses = {name: status for name, status, _ in outcome["results"]}
    assert statuses["branch protection on main"] == goc.NOT_VERIFIABLE
    assert statuses["workflow default permissions"] == goc.NOT_VERIFIABLE
    assert goc.UNSAFE not in statuses.values()


def test_gh_missing_yields_all_not_verifiable(monkeypatch):
    monkeypatch.setattr(goc.shutil, "which", lambda _: None)
    outcome = goc.audit(REPO, _runner_factory({}))
    assert outcome["gh"] is False
    assert outcome["results"], "fallback must still enumerate every check"
    assert all(status == goc.NOT_VERIFIABLE for _, status, _ in outcome["results"])


def test_report_has_four_sections_and_no_fake_success(monkeypatch):
    monkeypatch.setattr(goc.shutil, "which", lambda _: None)
    outcome = goc.audit(REPO, _runner_factory({}))
    report = goc.render_report(REPO, outcome)
    for section in ("## Verified safe", "## Verified unsafe",
                    "## Not verifiable — manual check required",
                    "## Manual action required / recommended"):
        assert section in report, section
    assert "UNAVAILABLE" in report
    assert "nothing was mutated" in report.lower() or "Nothing was mutated" in report


def test_exit_codes(monkeypatch, tmp_path):
    # gh missing → exit 0 (report generated, nothing verified-unsafe).
    monkeypatch.setattr(goc.shutil, "which", lambda _: None)
    out = tmp_path / "r.md"
    assert goc.main(["--output", str(out)]) == 0
    assert out.exists()

    # Verified-unsafe state → exit 1.
    monkeypatch.setattr(goc.shutil, "which", lambda _: "/usr/bin/gh")
    responses = dict(_GOOD_RESPONSES)
    responses["repo view"] = (0, json.dumps({
        "visibility": "PUBLIC", "isPrivate": False,
        "defaultBranchRef": {"name": "main"},
    }))
    monkeypatch.setattr(goc, "run_command", _runner_factory(responses))
    assert goc.main(["--output", str(out)]) == 1


def test_audit_never_mutates(monkeypatch):
    """Every gh invocation must be a read (view/api GET/auth status)."""
    monkeypatch.setattr(goc.shutil, "which", lambda _: "/usr/bin/gh")
    runner = _runner_factory(_GOOD_RESPONSES)
    goc.audit(REPO, runner)
    for call in runner.calls:  # type: ignore[attr-defined]
        joined = " ".join(call)
        for forbidden in ("--method", "PUT", "POST", "DELETE", "PATCH", "edit", "delete"):
            assert forbidden not in joined, joined
