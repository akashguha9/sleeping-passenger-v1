"""
Local security audit — secret hygiene + tracking checks.

Purpose
-------
Before logging real-money manual trades, the operator should know:
- is .env present and *not* tracked by git?
- is runtime/ (which holds the SQLite DB) *not* tracked by git?
- is MVP_API_TOKEN configured to a real (non-placeholder) value?
- is ALLOWED_ORIGINS scoped to localhost, or has it been opened up?
- is a backup directory present, and is the latest backup recent?
- does the API token gate exist (no execution surface)?

Read-only.  Never prints secret values.  Never calls a broker.  Never
mutates the DB.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----
    python scripts/local_security_audit.py
    python scripts/local_security_audit.py --json
    python scripts/local_security_audit.py --repo-root .
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

PLACEHOLDER_TOKEN_VALUES = {
    "", "change-me", "changeme", "placeholder", "your-token-here",
    "set-me", "TOKEN", "TODO", "xxx", "xxxx", "secret", "password",
}


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _check(
    results: list[dict[str, Any]],
    failed: list[str],
    warnings: list[str],
    *,
    name: str,
    status: str,
    detail: str = "",
) -> None:
    results.append({"name": name, "status": status, "detail": detail})
    if status == "FAIL":
        failed.append(name)
    elif status == "WARN":
        warnings.append(name)


def _git_available() -> bool:
    return shutil.which("git") is not None


def _is_path_tracked_by_git(repo_root: Path, relpath: str) -> bool | None:
    """Return True if git tracks ``relpath`` (or any file under it).

    Returns ``None`` if git is unavailable or the call fails.
    """
    if not _git_available():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", relpath],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0 and proc.stdout.strip():
        return True
    # ls-files with --error-unmatch returns 1 if not tracked; also try
    # a wildcard match for directory cases.
    try:
        proc2 = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", relpath],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc2.returncode == 0 and proc2.stdout.strip():
        return True
    return False


def _is_glob_tracked_by_git(repo_root: Path, pathspec: str) -> bool | None:
    if not _git_available():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", pathspec],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return bool(proc.stdout.strip())


def _looks_like_placeholder(token: str) -> bool:
    if not token:
        return True
    norm = token.strip().lower()
    return norm in {p.lower() for p in PLACEHOLDER_TOKEN_VALUES}


def _allowed_origins_scope(origins: list[str]) -> tuple[str, str]:
    """Return (status, detail) for an ALLOWED_ORIGINS list.

    PASS  - all origins are localhost/127.0.0.1/::1.
    WARN  - public origin or wildcard present.
    """
    if not origins:
        return "PASS", "default (empty list)"
    bad: list[str] = []
    for o in origins:
        norm = o.strip().lower()
        if norm in {"*", "null"}:
            bad.append(o)
            continue
        if "localhost" in norm or "127.0.0.1" in norm or "[::1]" in norm:
            continue
        bad.append(o)
    if bad:
        return "WARN", f"non-local origins: {','.join(bad)}"
    return "PASS", f"all local ({len(origins)} entries)"


def _backup_summary(backup_dir: Path, now: _dt.datetime) -> dict[str, Any]:
    info: dict[str, Any] = {
        "backup_dir": str(backup_dir),
        "exists": False,
        "latest_backup_age_hours": None,
        "backup_count": 0,
    }
    if not backup_dir.exists() or not backup_dir.is_dir():
        return info
    info["exists"] = True
    files = [p for p in backup_dir.iterdir() if p.is_file()]
    db_files = [
        p for p in files if p.suffix.lower() in (".db", ".sqlite", ".sqlite3")
    ]
    info["backup_count"] = len(db_files)
    if not db_files:
        return info
    newest = max(db_files, key=lambda p: p.stat().st_mtime)
    age = (
        now - _dt.datetime.fromtimestamp(newest.stat().st_mtime, tz=_dt.timezone.utc)
    ).total_seconds() / 3600.0
    info["latest_backup_age_hours"] = round(age, 4)
    return info


def _find_execution_words_in_source(repo_root: Path) -> list[str]:
    """Cheap scan for forbidden execution surface in mutating routes.

    Walks ``scripts/api_server.py`` if present.  Returns a list of forbidden
    button/operation names that appear there.  Anything found is a FAIL.
    """
    target = repo_root / "scripts" / "api_server.py"
    if not target.exists():
        return []
    forbidden = (
        "place_order",
        "execute_order",
        "submit_order",
        "execute_trade",
        "send_to_broker",
        "broker_execute",
    )
    hits: list[str] = []
    try:
        text = target.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return []
    for word in forbidden:
        if word in text:
            hits.append(word)
    return hits


def run_security_audit(
    repo_root: Path | None = None,
    *,
    env: dict[str, str] | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Run the read-only local security audit.

    Parameters
    ----------
    repo_root : Path | None
        Repo root.  Defaults to the parent directory of this script.
    env : dict | None
        Override the process environment for deterministic tests.
    now : datetime | None
        Override the current time.
    """
    repo_root = (Path(repo_root) if repo_root else _default_repo_root()).resolve()
    env_map = env if env is not None else os.environ
    now = now or _dt.datetime.now(_dt.timezone.utc)

    check_results: list[dict[str, Any]] = []
    failed: list[str] = []
    warnings: list[str] = []

    payload: dict[str, Any] = {
        "report": "local_security_audit",
        "repo_root": str(repo_root),
        "ok": False,
        "check_results": check_results,
        "failed_checks": failed,
        "warnings": warnings,
        "operator_action": "",
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    payload.update(_SAFETY_STAMPS)

    # 1. .env presence (do NOT print values).
    env_file = repo_root / ".env"
    if env_file.exists():
        _check(check_results, failed, warnings,
               name="env_file_present", status="INFO",
               detail=".env exists locally")
    else:
        _check(check_results, failed, warnings,
               name="env_file_present", status="INFO",
               detail=".env not present (using process env / defaults)")

    # 2. .env not tracked by git.
    env_tracked = _is_path_tracked_by_git(repo_root, ".env")
    if env_tracked is True:
        _check(check_results, failed, warnings,
               name="env_not_tracked", status="FAIL",
               detail=".env is tracked by git!")
    elif env_tracked is False:
        _check(check_results, failed, warnings,
               name="env_not_tracked", status="PASS")
    else:
        _check(check_results, failed, warnings,
               name="env_not_tracked", status="WARN",
               detail="could not verify (git unavailable)")

    # 3. runtime/ not tracked by git.
    runtime_tracked = _is_path_tracked_by_git(repo_root, "runtime")
    runtime_db_tracked = _is_glob_tracked_by_git(repo_root, "runtime/*.db")
    if runtime_tracked is True or runtime_db_tracked is True:
        _check(check_results, failed, warnings,
               name="runtime_not_tracked", status="FAIL",
               detail="runtime/ or runtime/*.db tracked by git!")
    elif runtime_tracked is False:
        _check(check_results, failed, warnings,
               name="runtime_not_tracked", status="PASS")
    else:
        _check(check_results, failed, warnings,
               name="runtime_not_tracked", status="WARN",
               detail="could not verify (git unavailable)")

    # 4. *.db / *.sqlite not tracked by git.
    db_tracked = _is_glob_tracked_by_git(repo_root, "*.db")
    sqlite_tracked = _is_glob_tracked_by_git(repo_root, "*.sqlite")
    if db_tracked or sqlite_tracked:
        _check(check_results, failed, warnings,
               name="no_db_files_tracked", status="FAIL",
               detail="*.db or *.sqlite tracked by git!")
    elif db_tracked is False and sqlite_tracked is False:
        _check(check_results, failed, warnings,
               name="no_db_files_tracked", status="PASS")
    else:
        _check(check_results, failed, warnings,
               name="no_db_files_tracked", status="WARN",
               detail="could not verify (git unavailable)")

    # 5. Owner auth: hash mode preferred, plaintext legacy.  NEVER PRINT.
    token_raw = str(
        env_map.get("MVP_API_TOKEN_HASH", "") or env_map.get("MVP_API_TOKEN", "") or ""
    )
    if not token_raw.strip():
        _check(check_results, failed, warnings,
               name="api_token_configured", status="WARN",
               detail="MVP_API_TOKEN not set (mutating routes unprotected)")
    elif _looks_like_placeholder(token_raw):
        _check(check_results, failed, warnings,
               name="api_token_configured", status="WARN",
               detail="MVP_API_TOKEN looks like a placeholder")
    else:
        _check(check_results, failed, warnings,
               name="api_token_configured", status="PASS",
               detail="non-placeholder value set (redacted)")

    # 6. ALLOWED_ORIGINS scope.
    raw_origins = str(env_map.get("ALLOWED_ORIGINS", "") or "").strip()
    if not raw_origins:
        _check(check_results, failed, warnings,
               name="allowed_origins_scope", status="PASS",
               detail="default (no override)")
    else:
        origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
        status, detail = _allowed_origins_scope(origins)
        _check(check_results, failed, warnings,
               name="allowed_origins_scope", status=status, detail=detail)

    # 7. Backup directory + age.
    backup_dir = repo_root / "runtime" / "backups"
    bk = _backup_summary(backup_dir, now)
    if not bk["exists"]:
        _check(check_results, failed, warnings,
               name="backup_dir_present", status="WARN",
               detail=f"missing: {bk['backup_dir']}")
    elif bk["backup_count"] == 0:
        _check(check_results, failed, warnings,
               name="backup_dir_present", status="WARN",
               detail="backup dir exists but no .db files")
    else:
        _check(check_results, failed, warnings,
               name="backup_dir_present", status="PASS",
               detail=f"{bk['backup_count']} backups; latest age "
                      f"{bk['latest_backup_age_hours']}h")
        if (bk["latest_backup_age_hours"] or 0) > 7 * 24:
            _check(check_results, failed, warnings,
                   name="backup_recency", status="WARN",
                   detail=f"latest backup older than 7 days")
        else:
            _check(check_results, failed, warnings,
                   name="backup_recency", status="PASS")

    # 8. No execution surface.
    forbidden_hits = _find_execution_words_in_source(repo_root)
    if forbidden_hits:
        _check(check_results, failed, warnings,
               name="no_execution_surface", status="FAIL",
               detail="found: " + ",".join(forbidden_hits))
    else:
        _check(check_results, failed, warnings,
               name="no_execution_surface", status="PASS")

    payload["ok"] = len(failed) == 0
    payload["backup_dir_summary"] = bk

    if not payload["ok"]:
        payload["operator_action"] = (
            "Fix the failing checks immediately. Tracked secrets or DB "
            "files in git is a P0; rewrite the offending file and history "
            "before logging real-money trades."
        )
    elif warnings:
        payload["operator_action"] = (
            "Local security baseline OK with warnings: set MVP_API_TOKEN, "
            "narrow ALLOWED_ORIGINS, refresh backup. Re-run after fixing."
        )
    else:
        payload["operator_action"] = (
            "Local security baseline OK.  Safe for local self-test logging."
        )
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Local Security Audit")
    lines.append(f"Repo: {payload['repo_root']}")
    for c in payload["check_results"]:
        line = f"[{c['status']}] {c['name']}"
        if c["detail"]:
            line += f" {c['detail']}"
        lines.append(line)
    lines.append(f"RESULT: {'PASS' if payload['ok'] else 'FAIL'}")
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="local_security_audit.py",
        description=(
            "Local secret/tracking/CORS audit. Never prints secret values."
        ),
    )
    p.add_argument("--repo-root", type=str, default=None,
                   help="Repo root (default: parent of this script).")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = Path(args.repo_root) if args.repo_root else None
    payload = run_security_audit(repo_root)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload["ok"] else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "PLACEHOLDER_TOKEN_VALUES",
    "run_security_audit",
]


if __name__ == "__main__":
    raise SystemExit(main())
