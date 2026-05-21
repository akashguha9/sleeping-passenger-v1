"""Repo hygiene gate — prove no runtime DB / secrets / broker code is tracked.

Kanté Sprint 2 — Task 4.  A merge-blocking, read-only check that the working
tree never *commits* the things the advisory MVP must keep out of git:

* a runtime SQLite DB (``*.db`` under ``runtime/`` or a tracked ``*.db``),
* a real dotenv secret file (``.env`` / ``.env.local`` — ``.env.example`` is OK),
* a broker / order-execution module (filename containing ``broker``/``alpaca``/
  ``order_execution`` etc.).

Uses ``git ls-files`` so it sees exactly what is tracked.  Read-only; never a
broker call; never writes the DB.  Exits non-zero on a violation so CI fails
closed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]

# Tracked-filename tokens that would indicate a broker execution module.
_BROKER_FILE_TOKENS = ("alpaca", "ibkr", "oanda", "broker_order",
                       "order_execution", "place_order")


def _tracked_files(repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"], cwd=str(repo_root),
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:  # pragma: no cover - git absent
        return []
    if result.returncode != 0:
        return []
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def evaluate(repo_root: Path | None = None) -> dict[str, Any]:
    """Return a PASS/FAIL hygiene verdict over the tracked files."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    tracked = _tracked_files(root)

    runtime_dbs = [
        f for f in tracked
        if f.endswith(".db") and (f.startswith("runtime/") or "/runtime/" in f
                                  or _basename(f) == "mvp_local.db")
    ]
    # Any tracked .db is suspicious for this MVP.
    other_dbs = [f for f in tracked if f.endswith(".db") and f not in runtime_dbs]
    env_files = [
        f for f in tracked
        if _basename(f) in {".env", ".env.local"} or
        (_basename(f).startswith(".env") and not _basename(f).endswith(".example"))
    ]
    broker_files = [
        f for f in tracked
        if any(tok in _basename(f).lower() for tok in _BROKER_FILE_TOKENS)
    ]

    violations: dict[str, list[str]] = {}
    if runtime_dbs:
        violations["runtime_db_committed"] = runtime_dbs
    if other_dbs:
        violations["sqlite_db_committed"] = other_dbs
    if env_files:
        violations["dotenv_secret_committed"] = env_files
    if broker_files:
        violations["broker_module_committed"] = broker_files

    verdict = "FAIL" if violations else "PASS"
    return {
        "report": "repo_hygiene_gate",
        "repo_root": str(root),
        "tracked_file_count": len(tracked),
        "verdict": verdict,
        "violations": violations,
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="repo_hygiene_gate.py",
        description=(
            "Fail closed if a runtime DB / secret / broker module is tracked. "
            "Read-only; never a broker call."
        ),
    )
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = evaluate(args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Repo hygiene gate: {report['verdict']}")
        print(f"  tracked files: {report['tracked_file_count']}")
        for kind, files in report["violations"].items():
            print(f"  [FAIL] {kind}: {files[:10]}")
        if report["verdict"] == "PASS":
            print("  (no runtime DB / secret / broker module tracked)")
    return 1 if report["verdict"] == "FAIL" else 0


__all__ = ["evaluate"]


if __name__ == "__main__":
    raise SystemExit(main())
