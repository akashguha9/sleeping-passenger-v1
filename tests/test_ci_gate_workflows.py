"""CI defensive-gate workflow + repo hygiene gate (Kanté Sprint 2 — Task 4).

Proves the merge-blocking gate is wired in CI (release gate, compliance
preflight, hygiene, defensive test subset) and that the hygiene gate fails
closed when a runtime DB / secret is tracked.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import repo_hygiene_gate as hygiene

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "kante_defensive_gate.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert _WORKFLOW.exists(), f"missing workflow: {_WORKFLOW}"
    return _WORKFLOW.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Workflow content
# ---------------------------------------------------------------------------


def test_workflow_exists_and_parseable(workflow_text):
    assert "name:" in workflow_text
    assert "jobs:" in workflow_text
    assert "on:" in workflow_text


def test_workflow_runs_release_gate(workflow_text):
    assert "scripts/release_gate.py" in workflow_text


def test_workflow_runs_compliance_preflight(workflow_text):
    assert "scripts/compliance_preflight.py" in workflow_text


def test_workflow_runs_hygiene_and_architecture(workflow_text):
    assert "scripts/repo_hygiene_gate.py" in workflow_text
    assert "scripts/architecture_fitness.py" in workflow_text


def test_workflow_runs_defensive_test_subset(workflow_text):
    for t in ("test_operator_auth_enforcement.py", "test_reactor_canonical_inputs.py",
              "test_performance_query_bounds.py", "test_compliance_preflight.py"):
        assert t in workflow_text, t


def test_workflow_documents_merge_condition(workflow_text):
    lower = workflow_text.lower()
    assert "merge is allowed iff" in lower or "merge allowed" in lower
    assert "fail" in lower and "closed" in lower


def test_workflow_has_no_secrets_or_broker(workflow_text):
    assert "secrets." not in workflow_text
    assert "git push" not in workflow_text
    lower = workflow_text.lower()
    for forbidden in ("place_order", "submit_order", "execute_trade",
                      "broker_execute", "auto-trading"):
        for line in lower.splitlines():
            if forbidden in line:
                negators = (" not ", " never ", "no ", "must not", "doesn't")
                assert any(n in line for n in negators), line


# ---------------------------------------------------------------------------
# Repo hygiene gate
# ---------------------------------------------------------------------------


def test_hygiene_gate_passes_on_clean_repo():
    report = hygiene.evaluate(_REPO_ROOT)
    assert report["verdict"] == "PASS", report["violations"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_hygiene_gate_fails_on_tracked_runtime_db(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "mvp_local.db").write_bytes(b"SQLite format 3\x00")
    subprocess.run(["git", "add", "-A", "-f"], cwd=tmp_path, check=True)
    report = hygiene.evaluate(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "runtime_db_committed" in report["violations"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_hygiene_gate_fails_on_tracked_dotenv(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / ".env").write_text("SECRET=abc123", encoding="utf-8")
    (tmp_path / ".env.example").write_text("SECRET=", encoding="utf-8")
    subprocess.run(["git", "add", "-A", "-f"], cwd=tmp_path, check=True)
    report = hygiene.evaluate(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "dotenv_secret_committed" in report["violations"]
    # .env.example must NOT be flagged.
    assert ".env.example" not in str(report["violations"])
