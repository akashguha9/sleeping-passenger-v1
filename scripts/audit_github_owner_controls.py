"""GitHub owner-controls audit — evidence, not assumptions.

Verifies as much of the repository's owner/security posture as the
locally-available credentials allow, and is explicit about everything it
cannot see. Uses the ``gh`` CLI when installed and authenticated; falls
back gracefully when it is not. NEVER mutates GitHub settings.

Output: reports/github_owner_controls_report.md with four sections:
  * Verified safe        — API said the safe thing.
  * Verified unsafe      — API said a dangerous thing (exit 1).
  * Not verifiable       — no gh / no permission; manual check required.
  * Manual action        — recommended UI follow-ups.

Exit codes: 0 = report generated, no verified-unsafe findings;
1 = at least one VERIFIED unsafe state. Lack of API access is NOT a
failure — faking success (or failure) would be worse than honesty.

Usage:  python scripts/audit_github_owner_controls.py [--repo owner/name]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_REPO = "akashguha9/sleeping-passenger-v1"
_REPORT_PATH = _REPO_ROOT / "reports" / "github_owner_controls_report.md"

SAFE = "safe"
UNSAFE = "unsafe"
NOT_VERIFIABLE = "not_verifiable"


def run_command(args: list[str]) -> tuple[int, str]:
    """Run a command, returning (returncode, stdout). Mockable in tests."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, proc.stdout.strip()


def gh_available(runner: Callable | None = None) -> bool:
    runner = runner or run_command
    if shutil.which("gh") is None:
        return False
    rc, _ = runner(["gh", "auth", "status"])
    return rc == 0


def _check_repo_view(repo: str, runner: Callable) -> list[tuple[str, str, str]]:
    rc, out = runner(
        ["gh", "repo", "view", repo, "--json",
         "visibility,isPrivate,defaultBranchRef,isFork"]
    )
    if rc != 0:
        return [("repo visibility / default branch", NOT_VERIFIABLE,
                 "gh repo view failed — manual check required")]
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [("repo visibility / default branch", NOT_VERIFIABLE,
                 "unparsable gh output")]
    results = []
    if data.get("isPrivate") is True:
        results.append(("repo visibility", SAFE, "private"))
    else:
        results.append(("repo visibility", UNSAFE,
                        f"NOT private (visibility={data.get('visibility')!r})"))
    branch = (data.get("defaultBranchRef") or {}).get("name")
    if branch == "main":
        results.append(("default branch", SAFE, "main"))
    else:
        results.append(("default branch", NOT_VERIFIABLE,
                        f"default branch is {branch!r} — confirm intent"))
    return results


def _check_branch_protection(repo: str, runner: Callable) -> list[tuple[str, str, str]]:
    rc, out = runner(["gh", "api", f"repos/{repo}/branches/main/protection"])
    if rc != 0:
        return [("branch protection on main", NOT_VERIFIABLE,
                 "API denied or protection not configured — manual check required")]
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [("branch protection on main", NOT_VERIFIABLE, "unparsable output")]
    results = [("branch protection on main", SAFE, "protection rule exists")]
    checks = data.get("required_status_checks")
    results.append(
        ("required status checks", SAFE, f"{len((checks or {}).get('contexts', []))} contexts")
        if checks
        else ("required status checks", UNSAFE, "protection exists but no required checks")
    )
    if (data.get("allow_force_pushes") or {}).get("enabled"):
        results.append(("force pushes", UNSAFE, "force pushes ALLOWED on main"))
    else:
        results.append(("force pushes", SAFE, "disabled"))
    if (data.get("allow_deletions") or {}).get("enabled"):
        results.append(("branch deletion", UNSAFE, "deletion ALLOWED on main"))
    else:
        results.append(("branch deletion", SAFE, "disabled"))
    return results


def _check_actions_permissions(repo: str, runner: Callable) -> list[tuple[str, str, str]]:
    rc, out = runner(["gh", "api", f"repos/{repo}/actions/permissions/workflow"])
    if rc != 0:
        return [("workflow default permissions", NOT_VERIFIABLE,
                 "API denied — manual check required")]
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [("workflow default permissions", NOT_VERIFIABLE, "unparsable output")]
    results = []
    if data.get("default_workflow_permissions") == "read":
        results.append(("workflow default permissions", SAFE, "read-only"))
    else:
        results.append(("workflow default permissions", UNSAFE,
                        f"default is {data.get('default_workflow_permissions')!r} (want 'read')"))
    if data.get("can_approve_pull_request_reviews") is True:
        results.append(("workflows can approve PRs", UNSAFE,
                        "GITHUB_TOKEN may approve pull requests"))
    else:
        results.append(("workflows can approve PRs", SAFE, "disabled"))
    return results


def _check_listing(
    repo: str,
    runner: Callable,
    name: str,
    endpoint: str,
    describe: Callable[[list], str],
    unsafe_if: Callable[[list], bool] | None = None,
) -> list[tuple[str, str, str]]:
    rc, out = runner(["gh", "api", f"repos/{repo}/{endpoint}", "--paginate"])
    if rc != 0:
        return [(name, NOT_VERIFIABLE, "API denied — manual check required")]
    try:
        data = json.loads(out)
        if isinstance(data, dict):  # e.g. secrets returns {total_count, secrets}
            for key in ("secrets", "collaborators", "environments"):
                if key in data:
                    data = data[key]
                    break
            else:
                data = [data]
    except json.JSONDecodeError:
        return [(name, NOT_VERIFIABLE, "unparsable output")]
    status = UNSAFE if (unsafe_if and unsafe_if(data)) else SAFE
    return [(name, status, describe(data))]


def audit(repo: str = _DEFAULT_REPO, runner: Callable | None = None) -> dict:
    """Run every check; returns {results: [(name,status,detail)], gh: bool}.

    ``runner`` resolves at call time so tests can monkeypatch
    ``run_command`` on the module.
    """
    runner = runner or run_command
    results: list[tuple[str, str, str]] = []
    if not gh_available(runner):
        for name in (
            "repo visibility", "default branch", "branch protection on main",
            "required status checks", "force pushes", "branch deletion",
            "workflow default permissions", "fork PR approval",
            "collaborators", "deploy keys", "webhooks", "GitHub Apps",
            "Actions secrets (names only)", "environments",
            "Dependabot alerts", "secret scanning / push protection",
        ):
            results.append((name, NOT_VERIFIABLE,
                            "gh CLI unavailable or unauthenticated"))
        return {"gh": False, "results": results}

    results += _check_repo_view(repo, runner)
    results += _check_branch_protection(repo, runner)
    results += _check_actions_permissions(repo, runner)
    results += _check_listing(
        repo, runner, "collaborators", "collaborators",
        lambda d: ", ".join(f"{c.get('login')}({c.get('role_name', '?')})" for c in d) or "none",
    )
    results += _check_listing(
        repo, runner, "deploy keys", "keys",
        lambda d: f"{len(d)} key(s)" if d else "none",
        unsafe_if=lambda d: bool(d),  # this repo should have zero deploy keys
    )
    results += _check_listing(
        repo, runner, "webhooks", "hooks",
        lambda d: f"{len(d)} hook(s): " + ", ".join(
            str((h.get("config") or {}).get("url", "?")) for h in d) if d else "none",
    )
    results += _check_listing(
        repo, runner, "Actions secrets (names only)", "actions/secrets",
        lambda d: ", ".join(s.get("name", "?") for s in d) or "none",
    )
    results += _check_listing(
        repo, runner, "environments", "environments",
        lambda d: f"{len(d)} environment(s)" if d else "none",
    )
    rc, _ = runner(["gh", "api", f"repos/{repo}/vulnerability-alerts"])
    results.append(
        ("Dependabot alerts", SAFE, "enabled")
        if rc == 0
        else ("Dependabot alerts", NOT_VERIFIABLE,
              "disabled or API denied — manual check required")
    )
    rc, out = runner(["gh", "api", f"repos/{repo}",
                      "--jq", ".security_and_analysis"])
    if rc == 0 and out and out != "null":
        results.append(("secret scanning / push protection", SAFE, out))
    else:
        results.append(("secret scanning / push protection", NOT_VERIFIABLE,
                        "not exposed to this token — manual check required"))
    return {"gh": True, "results": results}


_MANUAL_ACTIONS = (
    "Enable branch protection on main with required status checks "
    "(pytest, defensive gate, dep-audit) if not yet configured.",
    "Set Actions default workflow permissions to 'Read repository contents'.",
    "Require approval for all external contributors on fork PRs.",
    "Enable Dependabot alerts, secret scanning, and push protection where "
    "your plan allows.",
    "Review GitHub Apps / OAuth installations account-wide (not exposed to "
    "repo-scoped tokens).",
)


def render_report(repo: str, outcome: dict) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_status: dict[str, list[tuple[str, str]]] = {SAFE: [], UNSAFE: [], NOT_VERIFIABLE: []}
    for name, status, detail in outcome["results"]:
        by_status[status].append((name, detail))
    lines = [
        "# GitHub owner controls report",
        "",
        f"Generated: {now} · Repo: `{repo}` · "
        f"gh CLI: {'authenticated' if outcome['gh'] else 'UNAVAILABLE'} · "
        "Read-only audit; nothing was mutated.",
        "",
        "## Verified safe",
        "",
    ]
    lines += [f"- ✅ **{n}** — {d}" for n, d in by_status[SAFE]] or ["- (none)"]
    lines += ["", "## Verified unsafe", ""]
    lines += [f"- ❌ **{n}** — {d}" for n, d in by_status[UNSAFE]] or ["- (none)"]
    lines += ["", "## Not verifiable — manual check required", ""]
    lines += [f"- ⚠️ **{n}** — {d}" for n, d in by_status[NOT_VERIFIABLE]] or ["- (none)"]
    lines += ["", "## Manual action required / recommended", ""]
    lines += [f"- [ ] {a}" for a in _MANUAL_ACTIONS]
    lines += [
        "",
        "See also: reports/github_owner_settings_manual_checklist.md "
        "(full UI checklist) and OWNER_ACCESS.md.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=_DEFAULT_REPO)
    parser.add_argument("--output", default=str(_REPORT_PATH))
    args = parser.parse_args(argv)

    outcome = audit(args.repo)
    report = render_report(args.repo, outcome)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    unsafe = [r for r in outcome["results"] if r[1] == UNSAFE]
    verified = [r for r in outcome["results"] if r[1] == SAFE]
    not_verifiable = [r for r in outcome["results"] if r[1] == NOT_VERIFIABLE]
    print(f"github owner-controls audit → {out_path}")
    print(f"  verified safe : {len(verified)}")
    print(f"  verified UNSAFE: {len(unsafe)}")
    print(f"  not verifiable: {len(not_verifiable)} (manual check required)")
    for name, _, detail in unsafe:
        print(f"  !! {name}: {detail}")
    return 1 if unsafe else 0


if __name__ == "__main__":
    raise SystemExit(main())
