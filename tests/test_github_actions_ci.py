"""Static guard tests for the GitHub Actions workflow.

The workflow is allowed to install dependencies and run tests, but it
must NOT:

* reference broker execution / order placement / auto-trading language
* depend on live secrets (`secrets.X`)
* run the live refresh writer (`refresh_live_signals.py --write`)
* copy `.env`
* commit a runtime DB
* skip safety hooks

These checks are intentionally lightweight: they parse YAML and scan
the workflow text for forbidden substrings.  They never execute the
workflow.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "pytest.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert _WORKFLOW.exists(), f"missing workflow file: {_WORKFLOW}"
    return _WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists_and_is_yaml_parseable(workflow_text: str) -> None:
    # Light parse: required top-level keys.  We don't import PyYAML
    # to keep this test dependency-free; the structural keys are
    # enough of a smoke check.
    assert "name:" in workflow_text
    assert "jobs:" in workflow_text
    assert "on:" in workflow_text


def test_workflow_has_safety_doctrine_comment(workflow_text: str) -> None:
    """The workflow file documents its own safety constraints so a
    future reviewer doesn't have to grep the codebase to find them."""
    lower = workflow_text.lower()
    assert "advisory" in lower or "private-operator" in lower or "safety" in lower
    assert "broker" in lower  # forbidden-words section names broker explicitly


def test_workflow_does_not_reference_broker_or_execution(
    workflow_text: str,
) -> None:
    """Forbidden phrases must only appear in NEGATED form (e.g. inside
    the safety-doctrine comment that says "Must NOT reference broker").
    A standalone affirmative use is a regression."""
    lower = workflow_text.lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "auto-trading",
        "ai-approved",
        "permission to trade",
    ):
        for line in lower.splitlines():
            if forbidden in line:
                negators = (" not ", " never ", "no ", "does not", "must not", "doesn't")
                assert any(n in line for n in negators), (
                    f"forbidden phrase {forbidden!r} appears un-negated in CI: "
                    f"{line!r}"
                )


def test_workflow_does_not_use_live_refresh_writer(workflow_text: str) -> None:
    """`refresh_live_signals.py --write` makes live network calls and
    writes DB rows; it is operator-only and must never run in CI.

    We strip YAML comments before scanning so the safety-doctrine
    header (which names the forbidden command) does not trigger a
    false positive."""
    code_lines = [
        line for line in workflow_text.splitlines()
        if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "refresh_live_signals.py --write" not in code
    assert "refresh_live_signals.py -w" not in code


def test_workflow_does_not_reference_dotenv(workflow_text: str) -> None:
    """`.env` is never copied or sourced inside CI — secrets live on
    the operator's machine only."""
    lower = workflow_text.lower()
    assert "cp .env" not in lower
    assert "copy .env" not in lower
    assert "source .env" not in lower
    assert ".env." not in lower or ".env.example" in lower  # example is OK
    # Bare ".env " (or '.env\n') would indicate sourcing.
    assert not re.search(r"(^|\s)\.env(\s|$)", workflow_text)


def test_workflow_has_no_secrets_references(workflow_text: str) -> None:
    """No ``${{ secrets.* }}`` references should be needed — the safety
    floor is built on guards, not on shared secrets."""
    assert "secrets." not in workflow_text


def test_workflow_does_not_skip_safety_hooks(workflow_text: str) -> None:
    """Hook-bypass flags would let unsafe changes land silently."""
    lower = workflow_text.lower()
    assert "--no-verify" not in lower
    assert "--no-gpg-sign" not in lower


def test_workflow_runs_no_alpaca_or_broker_sdk(workflow_text: str) -> None:
    for pat in (r"\balpaca\b", r"\bibkr\b", r"\binteractive[\s_-]?brokers\b", r"\boanda\b"):
        assert re.search(pat, workflow_text, flags=re.IGNORECASE) is None, pat


def test_workflow_runs_safety_floor_subset(workflow_text: str) -> None:
    """The safety-floor job must include the no-execution language test
    and the private-scope guard so a regression there fails CI."""
    assert "test_frontend_no_execution_language.py" in workflow_text
    assert "test_private_scope_guard.py" in workflow_text
    assert "test_db_hygiene_report.py" in workflow_text


def test_workflow_frontend_job_runs_typecheck_and_build(workflow_text: str) -> None:
    """If the frontend job exists, it must include the type-check and
    the production build to prove reproducibility."""
    if "frontend:" not in workflow_text:
        pytest.skip("frontend job not defined")
    assert "npx tsc --noEmit" in workflow_text
    assert "npm run build" in workflow_text
    assert "npm ci" in workflow_text


def test_workflow_declares_least_privilege_permissions(workflow_text: str) -> None:
    """Every workflow must pin the GITHUB_TOKEN to read-only contents so a
    compromised step cannot push code, tags, or releases."""
    assert "permissions:" in workflow_text
    assert "contents: read" in workflow_text
    for forbidden in ("contents: write", "packages: write", "id-token: write"):
        assert forbidden not in workflow_text, forbidden


def test_all_workflows_declare_least_privilege_permissions() -> None:
    """Same guarantee across every workflow file, not just pytest.yml."""
    workflows_dir = _REPO_ROOT / ".github" / "workflows"
    for wf in sorted(workflows_dir.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        assert "permissions:" in text, f"{wf.name} missing permissions block"
        assert "contents: read" in text, f"{wf.name} not read-only"
        assert "pull_request_target" not in text, (
            f"{wf.name} uses pull_request_target (untrusted-fork secret risk)"
        )


def test_checkout_steps_do_not_persist_credentials() -> None:
    """No job pushes back to the repo, so the checkout token must not be
    persisted into .git/config where later steps could read it."""
    workflows_dir = _REPO_ROOT / ".github" / "workflows"
    for wf in sorted(workflows_dir.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        checkouts = text.count("actions/checkout@")
        persisted_off = text.count("persist-credentials: false")
        assert checkouts == persisted_off, (
            f"{wf.name}: {checkouts} checkout step(s) but only "
            f"{persisted_off} persist-credentials: false"
        )


def test_workflow_does_not_commit_runtime_db(workflow_text: str) -> None:
    """No step should add `runtime/mvp_local.db` or push artefacts."""
    assert "mvp_local.db" not in workflow_text
    # `git push` from inside CI would be a red flag.
    assert "git push" not in workflow_text
