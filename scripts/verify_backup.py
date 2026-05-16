"""Sprint 10C — verify a private operator backup produced by
``scripts/backup_local_state.py``.

Behavior
--------
* Reads ``manifest.json`` from the backup directory.
* Confirms every ``files_copied`` entry exists on disk.
* Recomputes sha256 for each file and compares against the manifest.
* If a sqlite_db entry is present, opens it ``mode=ro`` and runs
  ``PRAGMA integrity_check`` — read-only, never overwrites the live
  ``runtime/mvp_local.db``.
* Returns ``PASS`` / ``FAIL`` and a structured per-file report.

Safety
------
* stdlib only.
* Read-only with respect to both the backup AND the live runtime DB.
* No broker call, no execution, no decryption of secrets.
* Carries the standard advisory_only / execution_gate=LOCKED stamps.

Usage
-----
    python scripts/verify_backup.py <backup_dir>
    python scripts/verify_backup.py <backup_dir> --json
    python scripts/verify_backup.py <backup_dir> --skip-db-integrity
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_ADVISORY_STAMPS = {
    "advisory_only": True,
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


def _sha256_of(path: Path, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _sqlite_integrity(path: Path) -> dict[str, Any]:
    """Run PRAGMA integrity_check on the backup DB, read-only.

    Returns ``{"ok": bool, "result": str, "error": str | None}``.
    """
    out: dict[str, Any] = {"ok": False, "result": None, "error": None}
    if not path.exists():
        out["error"] = "db_missing"
        return out
    try:
        # mode=ro guarantees no writes; the integrity check itself is
        # read-only at the sqlite3 layer.
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        out["error"] = f"open_failed: {exc}"
        return out
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        out["error"] = f"integrity_pragma_failed: {exc}"
        conn.close()
        return out
    conn.close()
    if not row:
        out["error"] = "integrity_no_row"
        return out
    out["result"] = str(row[0])
    out["ok"] = out["result"].lower() == "ok"
    return out


def verify_backup(
    backup_dir: Path,
    *,
    skip_db_integrity: bool = False,
) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    report: dict[str, Any] = {
        "ok": False,
        "backup_dir": str(backup_dir),
        "manifest_path": None,
        "manifest_present": False,
        "files_checked": [],
        "errors": [],
        "db_integrity": None,
        **_ADVISORY_STAMPS,
    }

    manifest_path = backup_dir / "manifest.json"
    report["manifest_path"] = str(manifest_path)
    if not manifest_path.is_file():
        report["errors"].append("manifest_missing")
        return report
    report["manifest_present"] = True

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["errors"].append(f"manifest_unreadable: {exc}")
        return report

    files = manifest.get("files_copied") or []
    if not isinstance(files, list):
        report["errors"].append("manifest_files_copied_not_list")
        return report

    db_path: Path | None = None
    for entry in files:
        rel = entry.get("relative") or entry.get("destination") or ""
        expected_sha = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        kind = entry.get("kind", "")
        dest = backup_dir / rel
        file_report: dict[str, Any] = {
            "relative": rel,
            "kind": kind,
            "exists": dest.is_file(),
            "size_bytes": None,
            "sha256_match": None,
            "expected_sha256": expected_sha,
            "actual_sha256": None,
            "error": None,
        }
        if not dest.is_file():
            file_report["error"] = "missing_on_disk"
            report["files_checked"].append(file_report)
            report["errors"].append(f"missing: {rel}")
            continue
        try:
            size = dest.stat().st_size
        except OSError as exc:
            file_report["error"] = f"stat_failed: {exc}"
            report["files_checked"].append(file_report)
            report["errors"].append(f"stat: {rel}")
            continue
        file_report["size_bytes"] = int(size)
        if expected_size is not None and int(expected_size) != int(size):
            file_report["error"] = (
                f"size_mismatch expected={expected_size} actual={size}"
            )
            report["errors"].append(f"size: {rel}")
        if expected_sha:
            try:
                actual_sha = _sha256_of(dest)
            except OSError as exc:
                file_report["error"] = f"checksum_failed: {exc}"
                report["files_checked"].append(file_report)
                report["errors"].append(f"checksum_read: {rel}")
                continue
            file_report["actual_sha256"] = actual_sha
            file_report["sha256_match"] = actual_sha == expected_sha
            if not file_report["sha256_match"]:
                report["errors"].append(f"checksum: {rel}")
        if kind == "sqlite_db" and dest.is_file():
            db_path = dest
        report["files_checked"].append(file_report)

    if db_path is not None and not skip_db_integrity:
        report["db_integrity"] = _sqlite_integrity(db_path)
        if not report["db_integrity"]["ok"]:
            report["errors"].append("db_integrity_failed")

    report["ok"] = not report["errors"]
    return report


def _emit_text(report: dict[str, Any]) -> None:
    print("Sleeping Passenger - Backup Verification")
    print(f"backup_dir    : {report['backup_dir']}")
    print(f"manifest      : {'present' if report['manifest_present'] else 'MISSING'}")
    for f in report["files_checked"]:
        status = "OK" if not f.get("error") and (f.get("sha256_match") in (True, None)) else "FAIL"
        match = (
            "sha256=match"
            if f.get("sha256_match") is True
            else "sha256=skip"
            if f.get("sha256_match") is None
            else "sha256=MISMATCH"
        )
        print(f"  [{status}] {f['relative']:<48} {match}  ({f.get('size_bytes')} bytes)")
        if f.get("error"):
            print(f"          error: {f['error']}")
    if report["db_integrity"] is not None:
        di = report["db_integrity"]
        tag = "OK" if di["ok"] else "FAIL"
        print(f"  [DB ] integrity_check = {di.get('result')}  -> {tag}")
        if di.get("error"):
            print(f"          error: {di['error']}")
    for e in report["errors"]:
        print(f"  [ERR] {e}")
    print("")
    print(
        "Safety: ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false, "
        "ai_execution_count=0."
    )
    print(f"RESULT: {'PASS' if report['ok'] else 'FAIL'}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verify_backup.py",
        description=(
            "Verify a private operator backup produced by "
            "scripts/backup_local_state.py. Read-only. Never overwrites "
            "the live runtime DB."
        ),
    )
    p.add_argument("backup_dir", type=Path, help="Path to a backup directory containing manifest.json")
    p.add_argument(
        "--skip-db-integrity",
        action="store_true",
        help="Skip the SQLite PRAGMA integrity_check on the backup DB.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object instead of human text.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = verify_backup(args.backup_dir, skip_db_integrity=args.skip_db_integrity)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _emit_text(report)
    return 0 if report.get("ok") else 1


__all__ = ["verify_backup", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
