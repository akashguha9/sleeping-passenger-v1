"""Proofs for scripts/audit_local_data_protection.py.

The audit must PASS on the real repo and FAIL on synthetic bad states
(tracked .env, tracked DB, tracked backups, weakened .gitignore,
world-readable secrets) built in temp git repos.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import audit_local_data_protection as adp

_REPO_ROOT = Path(__file__).resolve().parents[1]

_GOOD_GITIGNORE = "\n".join(adp._REQUIRED_IGNORE_PATTERNS) + "\n!.env.example\n"


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(_GOOD_GITIGNORE, encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    return tmp_path


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


def test_real_repo_passes_audit():
    """Repo-state violations must be zero.

    World-accessible-mode findings are machine state (umask of whatever
    process created runtime artifacts), not repo state — they are excluded
    here and proven separately on synthetic repos below; the standalone
    script still reports them to the operator.
    """
    violations = [v for v in adp.audit(_REPO_ROOT) if "world-accessible" not in v]
    assert violations == []


@needs_git
def test_clean_synthetic_repo_passes(tmp_path):
    repo = _git_repo(tmp_path)
    assert adp.audit(repo) == []


@needs_git
def test_tracked_env_detected(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".env").write_text("MVP_API_TOKEN_HASH=" + "a" * 64 + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env"], cwd=repo, check=True)
    violations = adp.audit(repo)
    assert any("tracked env file" in v for v in violations), violations


@needs_git
def test_env_example_is_allowed(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".env.example").write_text("MVP_API_TOKEN_HASH=\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env.example"], cwd=repo, check=True)
    assert adp.audit(repo) == []


@needs_git
def test_tracked_sqlite_db_detected(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "runtime").mkdir()
    (repo / "runtime" / "mvp_local.db").write_bytes(b"SQLite format 3\x00")
    subprocess.run(["git", "add", "-f", "runtime/mvp_local.db"], cwd=repo, check=True)
    violations = adp.audit(repo)
    assert any("tracked database file" in v for v in violations), violations


@needs_git
def test_tracked_backup_artifact_detected(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "backup_local_state").mkdir()
    (repo / "backup_local_state" / "manifest.json").write_text("{}", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", "backup_local_state/manifest.json"], cwd=repo, check=True
    )
    violations = adp.audit(repo)
    assert any("tracked backup artifact" in v for v in violations), violations


@needs_git
def test_weakened_gitignore_detected(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".gitignore").write_text("runtime/\n", encoding="utf-8")
    violations = adp.audit(repo)
    assert any(".gitignore missing protection: .env" in v for v in violations)
    assert any(".gitignore missing protection: *.db" in v for v in violations)


@needs_git
@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_world_readable_env_detected(tmp_path):
    repo = _git_repo(tmp_path)
    env = repo / ".env"
    env.write_text("MVP_API_TOKEN_HASH=" + "a" * 64 + "\n", encoding="utf-8")
    env.chmod(0o644)
    violations = adp.audit(repo)
    assert any("world-accessible sensitive file" in v for v in violations), violations
    env.chmod(0o600)
    assert not any("world-accessible" in v for v in adp.audit(repo))


def test_hardening_powershell_script_exists_with_dry_run_default():
    ps1 = _REPO_ROOT / "scripts" / "harden_local_owner_files.ps1"
    assert ps1.exists()
    text = ps1.read_text(encoding="utf-8")
    assert "[switch]$Apply" in text  # dry-run unless -Apply
    assert "DRY RUN" in text
    assert "icacls" in text
    assert "BitLocker" in text  # honest-scope documentation
    # Never destructive.
    for forbidden in ("Remove-Item", "rm -rf", "del /", "Format-"):
        assert forbidden not in text, forbidden
