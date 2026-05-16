"""Sprint ceiling-push — private operator cold restore drill.

Exercises the *restore half* of the recovery loop without ever touching
the live runtime DB.  Given a backup directory (or the most-recent one
under ``backup_local_state/``), the drill:

1. Locates the ``manifest.json`` and refuses to proceed if the target
   directory does not look like a backup the script produced.
2. Copies the backup tree byte-for-byte into a fresh temporary
   directory (or an operator-provided ``--temp-dir``).
3. Re-runs the same checksum + size verification ``verify_backup.py``
   performs against the copied tree.
4. Opens any copied SQLite DB ``mode=ro`` and runs ``PRAGMA
   integrity_check``.
5. Emits ``PASS`` / ``WARN`` / ``FAIL`` with a structured report and
   advisory-only safety stamps.

Safety
------
* Read-only with respect to the source backup *and* the live runtime
  DB.  The drill never opens ``runtime/mvp_local.db`` for any reason.
* stdlib only.
* No broker call, no order placement, no execution-gate change.
* The temporary restore directory is created with
  ``tempfile.mkdtemp`` and, by default, cleaned up after the drill
  passes; ``--keep`` preserves it for post-mortem inspection.

Usage
-----
    python scripts/restore_drill.py                # latest backup, auto temp
    python scripts/restore_drill.py <backup_dir>   # explicit backup
    python scripts/restore_drill.py <backup_dir> --temp-dir C:\\Temp\\drill
    python scripts/restore_drill.py --keep --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BACKUP_ROOT = _REPO_ROOT / "backup_local_state"
_LIVE_RUNTIME_DB = _REPO_ROOT / "runtime" / "mvp_local.db"

_ADVISORY_STAMPS = {
    "advisory_only": True,
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_order_permission": False,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "paper_trade_only_for_paper_rows": True,
    "real_capital_at_risk_for_paper_rows": False,
}

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _find_latest_backup(backup_root: Path) -> Path | None:
    if not backup_root.is_dir():
        return None
    candidates = [
        p
        for p in backup_root.iterdir()
        if p.is_dir() and (p / "manifest.json").is_file()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.name)
    return candidates[-1]


def _copy_tree(src: Path, dst: Path) -> dict[str, Any]:
    try:
        shutil.copytree(src, dst, dirs_exist_ok=False)
    except (OSError, shutil.Error) as exc:
        return {"copied": False, "error": f"{type(exc).__name__}: {exc}"}
    # Tally bytes for the operator's situational awareness.
    total = 0
    file_count = 0
    for path in dst.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
            file_count += 1
    return {"copied": True, "bytes": total, "file_count": file_count}


def _verify_copy(restored_dir: Path) -> dict[str, Any]:
    """Use the existing verify_backup logic against the copied tree."""
    try:
        try:
            from scripts.verify_backup import verify_backup
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from verify_backup import verify_backup  # type: ignore[no-redef]
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "ok": False,
            "error": f"verify_module_import_failed: {type(exc).__name__}: {exc}",
        }
    return verify_backup(restored_dir)


def _classify_status(verify_report: dict[str, Any]) -> str:
    if not verify_report.get("manifest_present"):
        return STATUS_FAIL
    if not verify_report.get("ok"):
        # Distinguish DB-only failures (operator may still recover the rest)
        # from a structural break in the manifest.
        errors = list(verify_report.get("errors") or [])
        if errors == ["db_integrity_failed"]:
            return STATUS_WARN
        return STATUS_FAIL
    return STATUS_PASS


def perform_drill(
    *,
    backup_dir: Path | None,
    backup_root: Path = _DEFAULT_BACKUP_ROOT,
    temp_dir: Path | None = None,
    keep: bool = False,
) -> dict[str, Any]:
    started_at = _utc_iso()
    report: dict[str, Any] = {
        "report": "restore_drill",
        "started_at": started_at,
        "backup_root": str(backup_root),
        "backup_dir": None,
        "temp_dir": None,
        "restored_dir": None,
        "kept_temp_dir": keep,
        "status": STATUS_FAIL,
        "copy": None,
        "verify": None,
        "live_runtime_db_path": str(_LIVE_RUNTIME_DB),
        "live_runtime_db_touched": False,
        "errors": [],
        **_ADVISORY_STAMPS,
    }

    chosen = backup_dir if backup_dir is not None else _find_latest_backup(backup_root)
    if chosen is None:
        report["errors"].append(
            f"no_backup_found in {backup_root} — run scripts/backup_local_state.py first"
        )
        return report
    chosen = chosen.expanduser().resolve()
    report["backup_dir"] = str(chosen)
    if not (chosen / "manifest.json").is_file():
        report["errors"].append(f"manifest_missing in {chosen}")
        return report

    # Refuse to ever point at the live runtime DB directory.  The drill
    # is purely read-only with respect to live state.
    runtime_parent = (_LIVE_RUNTIME_DB.parent).resolve()
    if chosen == runtime_parent or chosen == _REPO_ROOT.resolve():
        report["errors"].append("refusing_to_use_live_runtime_as_backup")
        return report

    # Decide where the restored copy goes.  If the operator gave a
    # ``--temp-dir`` we use exactly that; otherwise we create a fresh
    # ``tempfile.mkdtemp`` directory.  Both paths are required to be
    # *outside* the runtime dir to keep the live DB safe.
    if temp_dir is not None:
        temp_dir = temp_dir.expanduser().resolve()
        temp_dir.mkdir(parents=True, exist_ok=True)
        owns_temp_dir = False
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="mvp-restore-drill-")).resolve()
        owns_temp_dir = True
    report["temp_dir"] = str(temp_dir)

    if _LIVE_RUNTIME_DB.resolve().parent in temp_dir.parents or temp_dir == _LIVE_RUNTIME_DB.resolve().parent:
        report["errors"].append("temp_dir_overlaps_runtime")
        return report

    restored_dir = temp_dir / chosen.name
    if restored_dir.exists():
        # Never reuse a half-populated previous run.
        shutil.rmtree(restored_dir, ignore_errors=True)
    report["restored_dir"] = str(restored_dir)

    # Snapshot the live DB so we can prove it was untouched.
    live_db_bytes_before: bytes | None = None
    try:
        if _LIVE_RUNTIME_DB.is_file():
            live_db_bytes_before = _LIVE_RUNTIME_DB.read_bytes()
    except OSError:
        live_db_bytes_before = None

    copy_result = _copy_tree(chosen, restored_dir)
    report["copy"] = copy_result
    if not copy_result.get("copied"):
        report["errors"].append(
            f"copy_failed: {copy_result.get('error')}"
        )
        if owns_temp_dir and not keep:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return report

    verify_result = _verify_copy(restored_dir)
    report["verify"] = verify_result
    if verify_result.get("error"):
        report["errors"].append(str(verify_result["error"]))

    # Re-check the live DB has not been touched.
    if live_db_bytes_before is not None and _LIVE_RUNTIME_DB.is_file():
        try:
            after = _LIVE_RUNTIME_DB.read_bytes()
            if after != live_db_bytes_before:
                report["live_runtime_db_touched"] = True
                report["errors"].append("live_runtime_db_changed_during_drill")
        except OSError:
            pass

    status = _classify_status(verify_result)
    if report["live_runtime_db_touched"]:
        status = STATUS_FAIL
    report["status"] = status

    if owns_temp_dir and not keep and status == STATUS_PASS:
        shutil.rmtree(temp_dir, ignore_errors=True)
        report["kept_temp_dir"] = False
        report["temp_dir_cleaned_up"] = True
    else:
        report["temp_dir_cleaned_up"] = False

    report["finished_at"] = _utc_iso()
    return report


def _emit_text(report: dict[str, Any]) -> None:
    print("Sleeping Passenger - Cold Restore Drill")
    print(f"started_at        : {report.get('started_at')}")
    print(f"backup_dir        : {report.get('backup_dir')}")
    print(f"temp_dir          : {report.get('temp_dir')}")
    print(f"restored_dir      : {report.get('restored_dir')}")
    print(f"kept_temp_dir     : {report.get('kept_temp_dir')}")
    copy_info = report.get("copy") or {}
    if copy_info.get("copied"):
        print(
            f"copied            : {copy_info.get('file_count', 0)} files "
            f"({copy_info.get('bytes', 0)} bytes)"
        )
    else:
        print(f"copied            : FAILED ({copy_info.get('error')})")
    verify = report.get("verify") or {}
    if verify:
        db = verify.get("db_integrity") or {}
        print(
            f"verify.ok         : {verify.get('ok')}  manifest={verify.get('manifest_present')}"
        )
        if db:
            print(f"db_integrity      : {db.get('result')}  ok={db.get('ok')}")
    print(
        f"live_db_touched   : {report.get('live_runtime_db_touched')} "
        f"(path={report.get('live_runtime_db_path')})"
    )
    for e in report.get("errors") or []:
        print(f"  [ERR] {e}")
    print("")
    print(
        "Safety: ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false, "
        "ai_execution_count=0, can_execute=false."
    )
    print(f"RESULT: {report.get('status')}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="restore_drill.py",
        description=(
            "Cold restore drill: copies a verified backup into a temp "
            "directory, re-verifies it, and confirms the live runtime "
            "DB was never touched.  Read-only on the live system."
        ),
    )
    p.add_argument(
        "backup_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Path to a backup dir; defaults to the most-recent one under backup_local_state/.",
    )
    p.add_argument(
        "--backup-root",
        type=Path,
        default=None,
        help="Override the directory the drill scans for backups (default: <repo>/backup_local_state).",
    )
    p.add_argument(
        "--temp-dir",
        type=Path,
        default=None,
        help="Override the temp directory the backup is copied into.  Must be outside runtime/.",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Keep the temp directory after a successful drill so you can inspect it.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object instead of human text.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    backup_root = (
        (args.backup_root or _DEFAULT_BACKUP_ROOT).expanduser().resolve()
    )
    report = perform_drill(
        backup_dir=args.backup_dir.expanduser().resolve() if args.backup_dir else None,
        backup_root=backup_root,
        temp_dir=args.temp_dir,
        keep=bool(args.keep),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _emit_text(report)
    return 0 if report.get("status") == STATUS_PASS else 1


__all__ = [
    "perform_drill",
    "STATUS_PASS",
    "STATUS_WARN",
    "STATUS_FAIL",
]


if __name__ == "__main__":
    raise SystemExit(main())
