from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pytest_workflow_exists_and_runs_required_commands() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "pytest.yml"
    assert workflow_path.exists()
    body = workflow_path.read_text(encoding="utf-8")

    assert "python -m compileall scripts tests" in body
    assert "python -m pytest tests -q" in body


def test_requirements_manifest_exists_with_minimal_runtime_dependencies() -> None:
    requirements_path = REPO_ROOT / "requirements.txt"
    assert requirements_path.exists()
    body = requirements_path.read_text(encoding="utf-8")

    # Runtime-only manifest still carries the genuine runtime deps.
    assert "yfinance" in body
    # S4 (completed): pytest is a TEST-ONLY dependency.  It must NOT appear
    # in the runtime requirements.txt (it leaked CVE-2025-71176 into the
    # prod image/manifest and tripped pip-audit).  It now lives in
    # requirements-dev.txt only.
    assert "pytest" not in body
    dev_path = REPO_ROOT / "requirements-dev.txt"
    assert dev_path.exists()
    assert "pytest" in dev_path.read_text(encoding="utf-8")
