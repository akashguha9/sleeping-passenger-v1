"""Runtime DB files must be owner-only on POSIX (regression guard).

CI once failed ``tests/test_secret_custody.py::test_cli_audit_passes_on_clean_repo``
because the canonical runtime DB was created world-readable (0644, the
umask default for ``sqlite3.connect``) and the local data-protection audit
fails closed on world-accessible ``runtime/*.db``. The root-cause fix lives
in ``scripts.persistence.harden_db_permissions``: every create/connect path
through persistence enforces 0600 on the DB file (0700 on the canonical
``runtime/`` dir). These tests pin that behavior.

Windows note: chmod cannot express owner-only ACLs there, so hardening is
a deliberate no-op (covered by scripts/harden_local_owner_files.ps1); the
POSIX assertions are skipped.
"""
from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest

from scripts import persistence

posix_only = pytest.mark.skipif(
    os.name != "posix", reason="POSIX permission semantics only"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
def test_init_schema_creates_owner_only_db(tmp_path):
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    assert _mode(db) == 0o600


@posix_only
def test_init_schema_heals_world_readable_db(tmp_path):
    db = tmp_path / "mvp_local.db"
    db.touch(mode=0o644)
    os.chmod(db, 0o644)  # explicit: touch() is umask-masked
    persistence.init_schema(db)
    assert _mode(db) == 0o600


@posix_only
def test_get_conn_heals_preexisting_world_readable_db(tmp_path):
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    os.chmod(db, 0o644)  # simulate a raw sqlite3.connect creation
    conn = persistence._get_conn(db)
    conn.close()
    assert _mode(db) == 0o600


@posix_only
def test_canonical_runtime_dir_hardened_to_owner_only(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(persistence, "RUNTIME_DIR", runtime_dir, raising=False)
    db = runtime_dir / "mvp_local.db"
    persistence.init_schema(db)
    assert _mode(db) == 0o600
    assert _mode(runtime_dir) == 0o700


@posix_only
def test_non_canonical_parent_dirs_left_alone(tmp_path):
    before = _mode(tmp_path)
    persistence.init_schema(tmp_path / "side.db")
    assert _mode(tmp_path) == before  # only runtime/ is tightened


@posix_only
def test_hardened_db_passes_data_protection_audit(tmp_path, monkeypatch):
    """End-to-end: a freshly initialized runtime DB never trips the audit."""
    from scripts import audit_local_data_protection as adp

    repo = tmp_path / "repo"
    (repo / "runtime").mkdir(parents=True)
    gitignore_lines = "\n".join(adp._REQUIRED_IGNORE_PATTERNS) + "\n"
    (repo / ".gitignore").write_text(gitignore_lines, encoding="utf-8")
    db = repo / "runtime" / "mvp_local.db"
    monkeypatch.setattr(persistence, "RUNTIME_DIR", db.parent, raising=False)
    persistence.init_schema(db)
    violations = [v for v in adp.audit(repo) if "world-accessible" in v]
    assert violations == []


def test_harden_is_safe_when_paths_missing(tmp_path):
    # Never raises, even for nonexistent paths or on non-POSIX platforms.
    persistence.harden_db_permissions(tmp_path / "nope" / "missing.db")


def test_db_still_usable_after_hardening(tmp_path):
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    conn = sqlite3.connect(str(db))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert "manual_trades" in tables
