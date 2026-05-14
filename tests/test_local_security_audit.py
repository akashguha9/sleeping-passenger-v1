"""Tests for ``scripts.local_security_audit``.

Pin
---
- Secret values are NEVER printed in the output.
- Placeholder MVP_API_TOKEN raises a WARN, not a PASS.
- Wildcard / non-local ALLOWED_ORIGINS raises a WARN.
- Backup dir missing -> WARN (not FAIL).
- Safety stamps locked on every payload.
- Audit raises no exceptions even when .env is missing.
- Tracked .env or runtime DB triggers FAIL when git available.
- Forbidden execution-word in api_server.py triggers FAIL.
- Git unavailable degrades to WARN, not FAIL.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from scripts import local_security_audit as lsa


# ---------------------------------------------------------------------------
# Fixtures: synthetic repo structures (no real git involved)
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, *, with_api_server: bool = True) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "runtime" / "backups").mkdir(parents=True)
    if with_api_server:
        (root / "scripts" / "api_server.py").write_text(
            "# advisory-only api stub\n", encoding="utf-8"
        )
    return root


# ---------------------------------------------------------------------------
# Secrets / no leakage
# ---------------------------------------------------------------------------


def test_token_value_never_printed(tmp_path, capsys):
    root = _make_repo(tmp_path)
    env = {"MVP_API_TOKEN": "super-secret-token-xyz-12345"}
    payload = lsa.run_security_audit(root, env=env)
    serialized = json.dumps(payload)
    assert "super-secret-token-xyz-12345" not in serialized
    text = lsa._render_text(payload)
    assert "super-secret-token-xyz-12345" not in text


def test_placeholder_token_raises_warning(tmp_path):
    root = _make_repo(tmp_path)
    for placeholder in ["change-me", "CHANGE-ME", "your-token-here", "placeholder"]:
        env = {"MVP_API_TOKEN": placeholder}
        payload = lsa.run_security_audit(root, env=env)
        statuses = {c["name"]: c["status"] for c in payload["check_results"]}
        assert statuses["api_token_configured"] == "WARN", placeholder


def test_real_token_passes(tmp_path):
    root = _make_repo(tmp_path)
    env = {"MVP_API_TOKEN": "z9b8a7c6d5e4f3g2h1i0j9k8l7m6n5o4"}
    payload = lsa.run_security_audit(root, env=env)
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["api_token_configured"] == "PASS"


def test_token_missing_is_warn_not_fail(tmp_path):
    root = _make_repo(tmp_path)
    payload = lsa.run_security_audit(root, env={})
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["api_token_configured"] == "WARN"


# ---------------------------------------------------------------------------
# ALLOWED_ORIGINS
# ---------------------------------------------------------------------------


def test_wildcard_origin_warns(tmp_path):
    root = _make_repo(tmp_path)
    env = {"ALLOWED_ORIGINS": "*"}
    payload = lsa.run_security_audit(root, env=env)
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["allowed_origins_scope"] == "WARN"


def test_public_origin_warns(tmp_path):
    root = _make_repo(tmp_path)
    env = {"ALLOWED_ORIGINS": "https://example.com"}
    payload = lsa.run_security_audit(root, env=env)
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["allowed_origins_scope"] == "WARN"


def test_local_origins_pass(tmp_path):
    root = _make_repo(tmp_path)
    env = {"ALLOWED_ORIGINS": "http://127.0.0.1:3000,http://localhost:8000"}
    payload = lsa.run_security_audit(root, env=env)
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["allowed_origins_scope"] == "PASS"


def test_empty_origins_pass(tmp_path):
    root = _make_repo(tmp_path)
    payload = lsa.run_security_audit(root, env={})
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["allowed_origins_scope"] == "PASS"


# ---------------------------------------------------------------------------
# Backup dir
# ---------------------------------------------------------------------------


def test_backup_dir_missing_is_warn(tmp_path):
    root = tmp_path / "no_backup_repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "api_server.py").write_text("# stub\n", encoding="utf-8")
    payload = lsa.run_security_audit(root, env={})
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["backup_dir_present"] == "WARN"


def test_recent_backup_passes(tmp_path):
    root = _make_repo(tmp_path)
    (root / "runtime" / "backups" / "fresh.db").write_bytes(b"sqlite stub")
    payload = lsa.run_security_audit(root, env={})
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["backup_dir_present"] == "PASS"
    assert statuses["backup_recency"] == "PASS"


def test_stale_backup_warns(tmp_path):
    root = _make_repo(tmp_path)
    bk = root / "runtime" / "backups" / "old.db"
    bk.write_bytes(b"sqlite stub")
    import os
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=10)).timestamp()
    os.utime(bk, (old, old))
    payload = lsa.run_security_audit(root, env={})
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["backup_recency"] == "WARN"


# ---------------------------------------------------------------------------
# Execution surface
# ---------------------------------------------------------------------------


def test_forbidden_execution_word_in_api_server_fails(tmp_path):
    root = _make_repo(tmp_path, with_api_server=False)
    (root / "scripts" / "api_server.py").write_text(
        "def place_order():\n    pass\n", encoding="utf-8",
    )
    payload = lsa.run_security_audit(root, env={})
    assert "no_execution_surface" in payload["failed_checks"]
    assert payload["ok"] is False


def test_clean_api_server_passes(tmp_path):
    root = _make_repo(tmp_path)
    payload = lsa.run_security_audit(root, env={})
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["no_execution_surface"] == "PASS"


# ---------------------------------------------------------------------------
# Git tracking checks degrade gracefully
# ---------------------------------------------------------------------------


def test_git_unavailable_degrades_to_warn(tmp_path, monkeypatch):
    """When git is unavailable, tracking checks emit WARN, not FAIL."""
    root = _make_repo(tmp_path)
    monkeypatch.setattr(lsa, "_git_available", lambda: False)
    payload = lsa.run_security_audit(root, env={})
    statuses = {c["name"]: c["status"] for c in payload["check_results"]}
    assert statuses["env_not_tracked"] in {"WARN", "PASS"}
    assert statuses["runtime_not_tracked"] in {"WARN", "PASS"}
    # No FAILs from tracking checks.
    assert "env_not_tracked" not in payload["failed_checks"]
    assert "runtime_not_tracked" not in payload["failed_checks"]


def test_simulated_tracked_env_fails(tmp_path, monkeypatch):
    root = _make_repo(tmp_path)

    def _fake_tracked(repo_root, relpath):
        if relpath == ".env":
            return True
        return False

    monkeypatch.setattr(lsa, "_is_path_tracked_by_git", _fake_tracked)
    monkeypatch.setattr(lsa, "_is_glob_tracked_by_git", lambda r, p: False)
    payload = lsa.run_security_audit(root, env={})
    assert "env_not_tracked" in payload["failed_checks"]
    assert payload["ok"] is False


def test_simulated_tracked_runtime_db_fails(tmp_path, monkeypatch):
    root = _make_repo(tmp_path)
    monkeypatch.setattr(lsa, "_is_path_tracked_by_git", lambda r, p: False)
    monkeypatch.setattr(
        lsa, "_is_glob_tracked_by_git", lambda r, p: p == "runtime/*.db"
    )
    payload = lsa.run_security_audit(root, env={})
    assert "runtime_not_tracked" in payload["failed_checks"]


# ---------------------------------------------------------------------------
# Safety stamps + structural invariants
# ---------------------------------------------------------------------------


def test_safety_stamps_locked(tmp_path):
    root = _make_repo(tmp_path)
    payload = lsa.run_security_audit(root, env={})
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False


def test_no_crash_when_env_missing(tmp_path):
    """Audit must not crash when no .env is present and env-dict is empty."""
    root = _make_repo(tmp_path)
    # Should not raise.
    payload = lsa.run_security_audit(root, env={})
    assert "report" in payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_json(tmp_path, capsys, monkeypatch):
    root = _make_repo(tmp_path)
    # Force a clean env.
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    rc = lsa.main(["--repo-root", str(root), "--json"])
    out = capsys.readouterr().out
    assert "advisory_status" in out
    assert "ADVISORY_ONLY" in out
    # rc may be 0 or 1 depending on git availability + warnings; either is fine
    assert rc in (0, 1)
