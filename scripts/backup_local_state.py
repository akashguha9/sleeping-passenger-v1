"""Sprint 10C — private operator backup of local MVP state.

Bundles the *runtime* state the operator would lose if the laptop or the
runtime/ directory disappears:

  * ``runtime/mvp_local.db``         (SQLite, hot-copied via sqlite3.backup)
  * ``exports/paper_trade_*.csv``    (paper-trade ledger working files)
  * ``exports/paper_trade_template.csv`` (the template, if present)
  * ``logs/live_signal_refresh_summary.json`` (last refresh summary)
  * ``logs/*.log`` ONLY when ``--include-logs`` is passed

Writes a ``manifest.json`` next to the copied files describing exactly
what was captured, with sha256 checksums and the current repo commit hash
when discoverable.

Safety
------
* stdlib only (no third-party imports).
* Read-only with respect to the source repo — never mutates the DB, the
  paper-ledger CSVs, or the logs.
* Never reads ``.env`` and never copies it.  Prints a one-line reminder
  that secrets must be backed up manually to a separate secure location.
* Advisory-only invariants are embedded in the manifest:
    advisory_only=true, execution_gate=LOCKED, broker_api_called=false,
    ai_execution_count=0, can_execute=false.
* No network calls.  No broker connection.  No order placement.

Usage
-----
    python scripts/backup_local_state.py --dry-run
    python scripts/backup_local_state.py
    python scripts/backup_local_state.py --output /path/to/private_backups
    python scripts/backup_local_state.py --include-logs --json
"""  # noqa: D205
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "runtime" / "mvp_local.db"
_DEFAULT_OUT_ROOT = _REPO_ROOT / "backup_local_state"

_PAPER_LEDGER_GLOBS = ("paper_trade_*.csv", "paper_trades_*.csv")
_SUMMARY_FILES = ("live_signal_refresh_summary.json",)
_LOG_GLOBS = ("*.log",)

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

_SECRETS_REMINDER = (
    ".env is NOT copied by this script. Back up your secrets manually to "
    "a separate, encrypted location (password manager, encrypted drive, "
    "or offline vault). This script never reads or transmits secret values."
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_of(path: Path, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _detect_repo_commit() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603, S607 — local git, no shell
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (out.stdout or "").strip()
    return sha if sha and len(sha) >= 7 else None


def _safe_sqlite_copy(src: Path, dst: Path) -> dict[str, Any]:
    """Hot-copy a SQLite DB via the sqlite3.backup API.

    Returns ``{"copied": True, "bytes": int}`` on success, or
    ``{"copied": False, "error": str}`` on failure.  Never mutates src.
    """
    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    try:
        src_conn = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst_conn = sqlite3.connect(str(dst))
        src_conn.backup(dst_conn)
    except sqlite3.Error as exc:
        return {"copied": False, "error": f"sqlite3.Error: {exc}"}
    finally:
        for c in (dst_conn, src_conn):
            if c is not None:
                try:
                    c.close()
                except sqlite3.Error:
                    pass
    try:
        size = dst.stat().st_size
    except OSError as exc:
        return {"copied": False, "error": f"stat after copy failed: {exc}"}
    return {"copied": True, "bytes": int(size)}


def _plain_file_copy(src: Path, dst: Path) -> dict[str, Any]:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        size = dst.stat().st_size
    except OSError as exc:
        return {"copied": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"copied": True, "bytes": int(size)}


def _discover_inputs(include_logs: bool) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    db_path = _DEFAULT_DB
    entries.append(
        {
            "kind": "sqlite_db",
            "source": str(db_path),
            "relative": "runtime/mvp_local.db",
            "present": db_path.exists(),
        }
    )

    exports_dir = _REPO_ROOT / "exports"
    if exports_dir.is_dir():
        seen: set[Path] = set()
        for pattern in _PAPER_LEDGER_GLOBS:
            for path in sorted(exports_dir.glob(pattern)):
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                entries.append(
                    {
                        "kind": "paper_ledger_csv",
                        "source": str(path),
                        "relative": f"exports/{path.name}",
                        "present": True,
                    }
                )
        template = exports_dir / "paper_trade_template.csv"
        if template.is_file() and template not in seen:
            entries.append(
                {
                    "kind": "paper_ledger_template",
                    "source": str(template),
                    "relative": f"exports/{template.name}",
                    "present": True,
                }
            )

    logs_dir = _REPO_ROOT / "logs"
    if logs_dir.is_dir():
        for name in _SUMMARY_FILES:
            path = logs_dir / name
            if path.is_file():
                entries.append(
                    {
                        "kind": "refresh_summary",
                        "source": str(path),
                        "relative": f"logs/{name}",
                        "present": True,
                    }
                )
        if include_logs:
            for pattern in _LOG_GLOBS:
                for path in sorted(logs_dir.glob(pattern)):
                    if not path.is_file():
                        continue
                    entries.append(
                        {
                            "kind": "log",
                            "source": str(path),
                            "relative": f"logs/{path.name}",
                            "present": True,
                        }
                    )

    return entries


def perform_backup(
    *,
    output_root: Path,
    include_logs: bool,
    dry_run: bool,
    label: str | None = None,
) -> dict[str, Any]:
    stamp = _utc_stamp()
    name_parts = [stamp]
    if label:
        # Restrict the label to a safe charset; the manifest captures the
        # raw value but the directory name stays predictable.
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label)[:32]
        if safe:
            name_parts.append(safe)
    backup_dir = output_root / "-".join(name_parts)

    inputs = _discover_inputs(include_logs)
    present_inputs = [e for e in inputs if e["present"]]
    missing_inputs = [e for e in inputs if not e["present"]]

    result: dict[str, Any] = {
        "ok": False,
        "dry_run": dry_run,
        "include_logs": include_logs,
        "created_at": _utc_iso(),
        "repo_root": str(_REPO_ROOT),
        "repo_commit": _detect_repo_commit(),
        "output_root": str(output_root),
        "backup_dir": str(backup_dir),
        "label": label,
        "files_copied": [],
        "files_skipped": [{"relative": e["relative"], "reason": "source_missing"} for e in missing_inputs],
        "totals": {
            "bytes": 0,
            "files_copied": 0,
            "files_planned": len(present_inputs),
        },
        "errors": [],
        "secrets_reminder": _SECRETS_REMINDER,
        **_ADVISORY_STAMPS,
    }

    if dry_run:
        # In dry-run we still report exactly what *would* be copied — but we
        # do not create the backup dir, do not read DB pages, and do not
        # compute checksums (the source file may legitimately be in use).
        for entry in present_inputs:
            result["files_copied"].append(
                {
                    "kind": entry["kind"],
                    "source": entry["source"],
                    "relative": entry["relative"],
                    "would_copy": True,
                    "size_bytes": Path(entry["source"]).stat().st_size
                    if Path(entry["source"]).exists()
                    else 0,
                }
            )
        result["ok"] = True
        return result

    try:
        backup_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        result["errors"].append(f"backup dir already exists: {backup_dir}")
        return result
    except OSError as exc:
        result["errors"].append(f"could not create backup dir: {exc}")
        return result

    for entry in present_inputs:
        rel = entry["relative"]
        src = Path(entry["source"])
        dst = backup_dir / rel
        if entry["kind"] == "sqlite_db":
            copy_result = _safe_sqlite_copy(src, dst)
        else:
            copy_result = _plain_file_copy(src, dst)
        if not copy_result.get("copied"):
            result["errors"].append(
                f"copy failed for {rel}: {copy_result.get('error')}"
            )
            continue
        try:
            checksum = _sha256_of(dst)
        except OSError as exc:
            result["errors"].append(f"checksum failed for {rel}: {exc}")
            checksum = None
        result["files_copied"].append(
            {
                "kind": entry["kind"],
                "source": str(src),
                "relative": rel,
                "destination": str(dst),
                "size_bytes": copy_result.get("bytes", 0),
                "sha256": checksum,
            }
        )
        result["totals"]["bytes"] += int(copy_result.get("bytes", 0))
        result["totals"]["files_copied"] += 1

    manifest = {
        "created_at": result["created_at"],
        "repo_root": result["repo_root"],
        "repo_commit": result["repo_commit"],
        "label": label,
        "include_logs": include_logs,
        "files_copied": result["files_copied"],
        "files_skipped": result["files_skipped"],
        "totals": result["totals"],
        "errors": list(result["errors"]),
        "secrets_reminder": _SECRETS_REMINDER,
        **_ADVISORY_STAMPS,
    }
    try:
        (backup_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        result["errors"].append(f"manifest write failed: {exc}")
        return result

    result["ok"] = not result["errors"]
    return result


def _emit_text(result: dict[str, Any]) -> None:
    print("Sleeping Passenger - Private Operator Backup")
    print(f"created_at      : {result['created_at']}")
    print(f"dry_run         : {result['dry_run']}")
    print(f"include_logs    : {result['include_logs']}")
    print(f"output_root     : {result['output_root']}")
    print(f"backup_dir      : {result['backup_dir']}")
    print(f"repo_commit     : {result['repo_commit']}")
    if result["label"]:
        print(f"label           : {result['label']}")
    print(f"files_copied    : {result['totals']['files_copied']}/{result['totals']['files_planned']}")
    print(f"bytes_copied    : {result['totals']['bytes']}")
    for f in result["files_copied"][:20]:
        marker = "[PLAN]" if result["dry_run"] else "[OK]"
        print(f"  {marker} {f['relative']}  ({f.get('size_bytes', 0)} bytes)")
    if len(result["files_copied"]) > 20:
        print(f"  ... and {len(result['files_copied']) - 20} more")
    for s in result["files_skipped"]:
        print(f"  [SKIP] {s['relative']} ({s['reason']})")
    for e in result["errors"]:
        print(f"  [ERR ] {e}")
    print("")
    print(f"WARNING: {_SECRETS_REMINDER}")
    print("")
    print(
        "Safety: ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false, "
        "ai_execution_count=0, can_execute=false."
    )
    print(f"RESULT: {'PASS' if result['ok'] else 'FAIL'}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backup_local_state.py",
        description=(
            "Private operator backup of local MVP state: DB, paper-ledger "
            "CSVs, last refresh summary, optionally logs. Never touches "
            ".env. No broker call. No order placement."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Backup root directory (default: <repo>/backup_local_state).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without writing anything.",
    )
    p.add_argument(
        "--include-logs",
        action="store_true",
        help="Also copy logs/*.log files. Off by default to keep backups small.",
    )
    p.add_argument(
        "--label",
        type=str,
        default=None,
        help="Optional label appended to the backup directory name.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object instead of human text.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output_root = (args.output or _DEFAULT_OUT_ROOT).expanduser().resolve()
    result = perform_backup(
        output_root=output_root,
        include_logs=bool(args.include_logs),
        dry_run=bool(args.dry_run),
        label=args.label,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        _emit_text(result)
    return 0 if result.get("ok") else 1


__all__ = ["perform_backup", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
