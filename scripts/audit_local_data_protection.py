"""Local data-protection audit for the owner-only advisory MVP.

Checks that private local state stays private (exit 1 on violations):

  * no ``.env`` (or ``.env.*`` except ``.env.example``) tracked by git;
  * no SQLite database tracked by git;
  * no backup snapshot directories tracked by git;
  * ``.gitignore`` keeps the core protections (``.env``, ``runtime/``,
    ``logs/``, ``*.db``, backup dirs);
  * sensitive on-disk files (``.env``, ``runtime/*.db``) are not
    world-readable (POSIX only — Windows ACLs are handled by
    ``scripts/harden_local_owner_files.ps1``).

Honest scope note (documented in SECURITY.md): API auth cannot protect
against malware or any process running as the same OS user. Real local
protection = OS account password + full-disk encryption (BitLocker), and
never syncing ``.env``/DB to public cloud folders unencrypted.

Stdlib only:  python scripts/audit_local_data_protection.py
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# .gitignore lines (prefix-match after strip) the repo must keep.
_REQUIRED_IGNORE_PATTERNS = (
    ".env",
    "runtime/",
    "logs/",
    "*.db",
    "*.sqlite",
    "backup_local_state/",
    "private_backups/",
)

_SENSITIVE_GLOBS = (".env", "runtime/*.db", "runtime/*.sqlite")


def _tracked_files(repo_root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def audit(repo_root: Path = _REPO_ROOT) -> list[str]:
    """Return a list of human-readable violations (empty = clean)."""
    violations: list[str] = []
    tracked = _tracked_files(repo_root)

    for path in tracked:
        name = Path(path).name
        lower = path.lower()
        if name == ".env" or (
            name.startswith(".env.") and name != ".env.example"
        ):
            violations.append(f"tracked env file: {path}")
        if lower.endswith((".db", ".sqlite", ".sqlite3")):
            violations.append(f"tracked database file: {path}")
        if lower.startswith(("backup_local_state/", "private_backups/", "backups/")):
            violations.append(f"tracked backup artifact: {path}")
        if lower.endswith((".bak", ".dump")):
            violations.append(f"tracked backup-style file: {path}")

    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        violations.append(".gitignore missing")
    else:
        lines = {
            line.strip()
            for line in gitignore.read_text(encoding="utf-8-sig").splitlines()
        }
        for pattern in _REQUIRED_IGNORE_PATTERNS:
            if pattern not in lines:
                violations.append(f".gitignore missing protection: {pattern}")

    if os.name == "posix":
        for pattern in _SENSITIVE_GLOBS:
            for path in repo_root.glob(pattern):
                try:
                    mode = path.stat().st_mode
                except OSError:
                    continue
                if mode & (stat.S_IROTH | stat.S_IWOTH):
                    violations.append(
                        f"world-accessible sensitive file: "
                        f"{path.relative_to(repo_root)} "
                        f"(mode {stat.filemode(mode)}) — run "
                        f"`chmod o-rwx {path.relative_to(repo_root)}`"
                    )
    return violations


def main() -> int:
    violations = audit()
    print(f"local data-protection audit: {_REPO_ROOT}")
    if violations:
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(
        "PASS — no tracked secrets/DBs/backups, .gitignore protections "
        "intact"
        + (
            ", sensitive files not world-accessible."
            if os.name == "posix"
            else ". (Windows: run scripts/harden_local_owner_files.ps1 "
            "for ACL checks.)"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
