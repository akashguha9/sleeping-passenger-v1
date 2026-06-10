"""S4-A5 regression: runtime isolation checker + boot gate + health posture.

The sandbox itself runs in a real venv, so the positive case is exercised
for real; the global-interpreter case is simulated by patching the
prefix markers.  PowerShell scripts get a structural sanity check (no
pwsh on this runner).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import runtime_isolation as ri

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_checker_reports_factual_venv_state():
    """The checker must mirror what the interpreter/environment actually
    indicate — true in a local venv AND on a GitHub Actions toolcache
    interpreter that is honestly not a venv.  (CI escape: the old test
    asserted in_venv is True unconditionally.)"""
    import os

    expected_in_venv = (
        sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        or hasattr(sys, "real_prefix")
        or bool(os.environ.get("VIRTUAL_ENV"))
    )
    status = ri.check_runtime_isolation()
    assert status["in_venv"] is expected_in_venv
    assert status["python_executable"] == sys.executable
    assert status["python_prefix"] == sys.prefix
    assert status["execution_gate"] == "LOCKED"
    assert status["broker_api_called"] is False


def test_checker_detects_venv_when_prefix_differs(monkeypatch):
    """Hermetic positive case: PEP 405 prefix split ⇒ in_venv True."""
    monkeypatch.setattr(ri.sys, "prefix", "/tmp/project/.venv", raising=False)
    monkeypatch.setattr(ri.sys, "base_prefix", "/usr", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    status = ri.check_runtime_isolation()
    assert status["in_venv"] is True


def test_checker_detects_venv_via_virtual_env_var(monkeypatch):
    """Hermetic positive case: activated env signalled only by VIRTUAL_ENV."""
    monkeypatch.setattr(ri.sys, "prefix", "/usr", raising=False)
    monkeypatch.setattr(ri.sys, "base_prefix", "/usr", raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/project/.venv")
    status = ri.check_runtime_isolation()
    assert status["in_venv"] is True


def test_checker_detects_non_venv_when_prefixes_match(monkeypatch):
    """Hermetic negative case: toolcache-style interpreter ⇒ in_venv False."""
    monkeypatch.setattr(ri.sys, "prefix", "/usr", raising=False)
    monkeypatch.setattr(ri.sys, "base_prefix", "/usr", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    if hasattr(ri.sys, "real_prefix"):  # pragma: no cover - legacy virtualenv
        monkeypatch.delattr(ri.sys, "real_prefix", raising=False)
    status = ri.check_runtime_isolation()
    assert status["in_venv"] is False
    assert status["global_site_packages_enabled"] is True


def test_dependency_lock_hash_present_and_stable():
    h1 = ri.dependency_lock_hash()
    h2 = ri.dependency_lock_hash()
    assert h1 is not None and len(h1) == 64
    assert h1 == h2


def test_global_interpreter_fails_closed(monkeypatch):
    monkeypatch.setattr(sys, "base_prefix", sys.prefix, raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("MVP_ALLOW_GLOBAL_PYTHON", raising=False)
    status = ri.check_runtime_isolation()
    assert status["runtime_isolated"] is False
    assert status["global_site_packages_enabled"] is True
    with pytest.raises(ri.RuntimeIsolationError) as exc:
        ri.enforce_isolation_or_die()
    assert "bootstrap_venv.ps1" in str(exc.value)


def test_global_interpreter_override_runs_degraded(monkeypatch):
    monkeypatch.setattr(sys, "base_prefix", sys.prefix, raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("MVP_ALLOW_GLOBAL_PYTHON", "1")
    status = ri.enforce_isolation_or_die()  # must NOT raise
    assert status["runtime_isolated"] is False
    assert status["global_python_override_active"] is True


def test_health_full_reports_isolation_posture():
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    h = client.get("/health/full")
    assert h.status_code == 200
    body = h.json()
    assert "runtime_isolated" in body
    assert "global_site_packages_enabled" in body
    assert "python_executable" in body
    assert "dependency_lock_hash" in body
    assert body["execution_gate"] == "LOCKED"


@pytest.mark.parametrize(
    "script",
    [
        "bootstrap_venv.ps1",
        "check_runtime_isolation.ps1",
        "run_tests_clean_venv.ps1",
        "start_mvp_clean_venv.ps1",
    ],
)
def test_powershell_scripts_structural_sanity(script):
    """No pwsh on this runner — verify presence, lockfile discipline, and
    balanced braces as a syntax smoke check."""
    path = REPO_ROOT / "scripts" / "windows" / script
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{script} is empty"
    assert text.count("{") == text.count("}"), f"{script}: unbalanced braces"
    if script == "bootstrap_venv.ps1":
        assert "requirements.lock" in text  # pinned installs only
        assert "pip check" in text
        assert "pip_audit" in text or "pip-audit" in text
    if script in ("run_tests_clean_venv.ps1", "start_mvp_clean_venv.ps1"):
        assert "check_runtime_isolation.ps1" in text
