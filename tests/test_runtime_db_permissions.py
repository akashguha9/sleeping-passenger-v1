"""Guard: runtime SQLite DBs are created owner-only (not world-accessible).

This reproduces — and locks — the exact CI failure class behind the
secret-custody audit:

    FAIL — world-accessible sensitive file: runtime/mvp_local.db (-rw-r--r--)

SQLite honours the process umask when creating a DB file, so on CI/Linux
(umask 022) a fresh DB lands as 0o644 = world-readable, which
``audit_local_data_protection`` correctly flags. ``persistence.init_schema``
now clamps the mode to 0o600 at the single canonical creation point, so the
audit stays strict *and* passes.

The assertion is POSIX-only (Windows uses NTFS ACLs, not mode bits); on
Windows we still prove the hardening helper is a safe no-op.
"""
from __future__ import annotations

import os
import stat

import pytest

from scripts import persistence


def test_init_schema_creates_non_world_accessible_db(tmp_path):
    db_path = tmp_path / "mvp_local.db"
    persistence.init_schema(db_path)
    assert db_path.exists()

    if os.name != "posix":
        pytest.skip("POSIX mode bits not meaningful on this host (NTFS ACLs)")

    mode = db_path.stat().st_mode
    # The precise predicate the secret-custody audit uses.
    assert not (mode & (stat.S_IROTH | stat.S_IWOTH)), (
        f"runtime DB is world-accessible (mode {stat.filemode(mode)}); "
        f"init_schema must clamp it to 0o600 so the custody audit passes."
    )
    # Group access is likewise dropped by 0o600.
    assert not (mode & (stat.S_IRGRP | stat.S_IWGRP))


def test_harden_helper_is_safe_noop_when_file_absent(tmp_path):
    """The hardening step must never raise — a chmod failure cannot break
    persistence."""
    # Non-existent path: helper swallows the OSError on POSIX, no-ops elsewhere.
    persistence._harden_db_permissions(tmp_path / "does_not_exist.db")


def test_audit_passes_after_canonical_db_initialized(tmp_path):
    """End-to-end: a DB hardened by init_schema satisfies the audit's
    world-accessibility check for runtime/*.db."""
    from scripts import audit_local_data_protection as adp

    # Build a fake repo root with a runtime/ DB created via init_schema, plus
    # the .gitignore protections the audit also checks, so the only thing
    # under test here is the DB-permission rule.
    repo = tmp_path
    (repo / "runtime").mkdir()
    persistence.init_schema(repo / "runtime" / "mvp_local.db")

    gitignore = repo / ".gitignore"
    gitignore.write_text(
        "\n".join(sorted(adp._REQUIRED_IGNORE_PATTERNS)) + "\n",
        encoding="utf-8",
    )

    violations = adp.audit(repo)
    world_access = [v for v in violations if "world-accessible" in v]
    assert world_access == [], f"unexpected world-access violations: {world_access}"
