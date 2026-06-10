#!/usr/bin/env python3
"""S4-A4: staged restore with guarded promote-to-live — never blind overwrite.

Pipeline:
1. **Stage** (default, safe): decrypt if needed (fail closed without the
   key), restore via the native API to a STAGING path, then run the full
   check battery: PRAGMA integrity_check, expected-schema presence,
   per-table row counts, sha256 checksum of the journal tables, and an
   advisory-invariant smoke test (no manual_trades row may claim
   broker_api_called!=0).
2. **--promote-live** (guarded): requires the OPERATOR/ADMIN-role
   permission guard with a recent dry-run receipt (the stage step writes
   one), takes an automatic PRE-PROMOTE backup of the current live DB,
   and only then swaps the staged file into place.

Usage:
    python scripts/restore_to_live.py --backup <file>                # stage+verify
    python scripts/restore_to_live.py --backup <file> --promote-live # guarded swap

Advisory-only record-keeping maintenance: no broker, no execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import persistence  # noqa: E402
from scripts.backup_crypto import (  # noqa: E402
    BackupCryptoError,
    decrypt_file,
    is_encrypted_backup,
)
from scripts.backup_db import perform_backup, perform_restore  # noqa: E402
from scripts import operator_permission_guard as _guard  # noqa: E402

OPERATION_NAME = "restore_to_live"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE

_EXPECTED_TABLES = (
    "manual_trades",
    "reconciliation_results",
    "user_reflections",
    "moltbook_entries",
    "audit_log",
)

_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _table_summary(db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    out: dict[str, Any] = {"row_counts": {}, "checksums": {}}
    try:
        for table in _EXPECTED_TABLES:
            try:
                rows = conn.execute(
                    f"SELECT * FROM {persistence._safe_identifier(table)} ORDER BY 1"
                ).fetchall()
            except sqlite3.OperationalError:
                out["row_counts"][table] = None
                continue
            out["row_counts"][table] = len(rows)
            out["checksums"][table] = hashlib.sha256(
                repr([tuple(r) for r in rows]).encode()
            ).hexdigest()
    finally:
        conn.close()
    return out


def stage_restore(backup_path: Path, staging_path: Path) -> dict[str, Any]:
    """Decrypt-if-needed + restore to staging + full check battery."""
    result: dict[str, Any] = {**_STAMPS, "ok": False, "checks": {}}
    src = backup_path
    tmp_plain: Path | None = None
    try:
        if is_encrypted_backup(backup_path):
            tmp_plain = Path(tempfile.mkdtemp()) / "decrypted.db"
            decrypt_file(backup_path, tmp_plain)  # fails closed without key
            src = tmp_plain
            result["checks"]["decryption"] = "ok"
        restore = perform_restore(src, staging_path)
        if not restore.get("ok"):
            result["error"] = f"restore failed: {restore.get('error')}"
            return result
        result["checks"]["integrity_check"] = restore["integrity_check"]

        conn = sqlite3.connect(str(staging_path))
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            conn.close()
        missing = [t for t in _EXPECTED_TABLES if t not in tables]
        result["checks"]["schema_missing_tables"] = missing
        if missing:
            result["error"] = f"staged DB is missing expected tables: {missing}"
            return result

        result["checks"].update(_table_summary(staging_path))

        # Advisory invariant smoke: no journal row may claim a broker call.
        conn = sqlite3.connect(str(staging_path))
        try:
            bad = conn.execute(
                "SELECT COUNT(*) FROM manual_trades WHERE broker_api_called != 0"
            ).fetchone()[0]
        finally:
            conn.close()
        result["checks"]["broker_api_called_violations"] = int(bad)
        if int(bad) != 0:
            result["error"] = (
                f"staged DB violates the advisory invariant: {bad} row(s) "
                "claim broker_api_called!=0 — refusing"
            )
            return result
        result["ok"] = True
        return result
    except BackupCryptoError as exc:
        result["error"] = str(exc)
        return result
    finally:
        if tmp_plain is not None and tmp_plain.exists():
            tmp_plain.unlink()


@_guard.guarded_mutation(
    operation_name=OPERATION_NAME,
    operation_class=OPERATION_CLASS,
    expected_role_floor=_guard.OperatorRole.ADMIN,
    require_dry_run=True,
)
def promote_live(
    staging_path: Path,
    live_path: Path,
    *,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Guarded swap: automatic pre-promote backup, then staged → live."""
    pre = perform_backup(live_path, live_path.parent / "backups", label="pre-promote")
    if live_path.exists() and not pre.get("ok"):
        return {**_STAMPS, "ok": False,
                "error": f"pre-promote backup failed: {pre.get('error')}"}
    shutil.copy2(staging_path, live_path)
    return {
        **_STAMPS,
        "ok": True,
        "live_path": str(live_path),
        "pre_promote_backup": pre.get("backup_path"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--live-db", type=Path, default=persistence.DB_PATH)
    parser.add_argument("--staging", type=Path, default=None)
    parser.add_argument("--promote-live", action="store_true")
    parser.add_argument("--operator-role", default=None)
    args = parser.parse_args(argv)

    staging = args.staging or args.live_db.with_name(
        args.live_db.stem + ".staged.db"
    )
    if staging.exists():
        print(f"[restore_to_live] staging path exists, refusing: {staging}")
        return 2

    staged = stage_restore(args.backup, staging)
    print(json.dumps({k: v for k, v in staged.items() if k != "checks"}, indent=2))
    print(json.dumps(staged.get("checks", {}), indent=2, default=str))
    if not staged["ok"]:
        print(f"[restore_to_live] STAGING FAILED: {staged.get('error')}")
        return 2

    if not args.promote_live:
        try:
            receipt = _guard.write_dry_run_receipt(
                OPERATION_NAME, target_count=1, db_path=str(args.live_db)
            )
            print(f"[restore_to_live] staged OK; dry-run receipt: {receipt.name}")
        except Exception as exc:
            print(
                f"[restore_to_live] WARNING: receipt not written "
                f"({type(exc).__name__}); --promote-live will be refused"
            )
        print("[restore_to_live] inspect the staged DB, then re-run with "
              "--promote-live (ADMIN role required).")
        return 0

    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(args.live_db),
            operator_role=args.operator_role,
        )
        result = promote_live(staging, args.live_db, permission_decision=decision)
    except PermissionError as exc:
        print(f"[restore_to_live] [DENY] {exc}", file=sys.stderr)
        return 2
    if not result["ok"]:
        print(f"[restore_to_live] PROMOTE FAILED: {result.get('error')}")
        return 2
    print(f"[restore_to_live] promoted; pre-promote backup: "
          f"{result['pre_promote_backup']}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
