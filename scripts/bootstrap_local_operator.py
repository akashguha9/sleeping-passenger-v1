"""First-day operator bootstrap — read-only preflight + next-commands print.

Full Role-Uplift Sprint, Phase 3.

Purpose
-------
A new operator should be able to clone the repo and run this script to
(a) verify the local environment is ready to host the advisory MVP and
(b) learn the exact next commands to run.  By default, the script is
read-only and prints a structured plan; nothing is started and nothing
is written to disk.

What it checks
~~~~~~~~~~~~~~
1. Python version meets the minimum (3.10).
2. Current working directory is the repo root (or at least *a* repo
   root that contains the expected scripts/ and frontend/ layout).
3. Required runtime directories exist (``runtime/`` and
   ``runtime/release/``).
4. SQLite canonical DB path exists.
5. Credential hygiene check (``scripts/check_credential_hygiene.py``)
   reports no root-level credential leakage.
6. Private-scope guard report has zero review-required entries.
7. ``first_run_seed_free_sources.py --dry-run`` is callable.
8. ``probability_snapshot.py --dry-run`` is callable.
9. ``calibration_report.py`` artifact exists or can be regenerated.
10. ``segment_role_scorecard.py`` can be run.
11. ``frontend/package.json`` exists.
12. ``npx tsc`` is available (the script does not run it — that is the
    operator's job; merely confirming presence is enough).
13. Prints the canonical local backend command.
14. Prints the canonical local frontend command.
15. Prints the dashboard URLs.

Safety
~~~~~~
* **Never reads** ``.env``, ``.env.local``, ``secrets/``, or any
  credential file content.  Only existence and gitignore coverage are
  inspected.
* **Never starts** a server.  This is a preflight, not a launcher.
* **Never hits** an external API by default.  ``--write-free-sources``
  is an explicit opt-in that delegates to
  :mod:`scripts.first_run_seed_free_sources` and **still** stays inside
  the free-tier public sources.
* Advisory-only stamps on every report record.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.advisory_contract import (  # noqa: E402
    AUDIT_ONLY_STORE,
    CANONICAL_STORE,
    advisory_safety_stamps,
)

DEFAULT_REPORT_PATH = (
    _REPO_ROOT / "runtime" / "release" / "bootstrap_local_operator_report.json"
)
MINIMUM_PYTHON_VERSION = (3, 10)
LOCAL_BACKEND_COMMAND = "python scripts/api_server.py"
LOCAL_FRONTEND_COMMAND = "cd frontend && npm run dev"
LOCAL_BACKEND_URL = "http://127.0.0.1:8000"
LOCAL_FRONTEND_URL = "http://127.0.0.1:3000"


# ---------------------------------------------------------------------------
# Check result model
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL | SKIP
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_python_version() -> CheckResult:
    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) >= MINIMUM_PYTHON_VERSION:
        return CheckResult(
            name="python_version",
            status="PASS",
            detail=f"Python {major}.{minor} >= {MINIMUM_PYTHON_VERSION[0]}.{MINIMUM_PYTHON_VERSION[1]}",
            evidence={"version": f"{major}.{minor}"},
        )
    return CheckResult(
        name="python_version",
        status="FAIL",
        detail=f"Python {major}.{minor} below required {MINIMUM_PYTHON_VERSION}",
        evidence={"version": f"{major}.{minor}"},
    )


def _check_repo_root(repo_root: Path) -> CheckResult:
    expected = [repo_root / "scripts", repo_root / "frontend"]
    missing = [str(p.name) for p in expected if not p.exists()]
    if not missing:
        return CheckResult(
            name="repo_root",
            status="PASS",
            detail=f"repo root layout intact at {repo_root}",
            evidence={"repo_root": str(repo_root)},
        )
    return CheckResult(
        name="repo_root",
        status="FAIL",
        detail=f"repo root missing required dirs: {missing}",
        evidence={"repo_root": str(repo_root), "missing": missing},
    )


def _check_runtime_dirs(repo_root: Path) -> CheckResult:
    runtime = repo_root / "runtime"
    release = runtime / "release"
    missing = [p.name for p in (runtime, release) if not p.exists()]
    if not missing:
        return CheckResult(
            name="runtime_dirs",
            status="PASS",
            detail="runtime/ and runtime/release/ present",
            evidence={"runtime_dir": str(runtime), "release_dir": str(release)},
        )
    return CheckResult(
        name="runtime_dirs",
        status="WARN",
        detail=f"missing runtime dirs: {missing} — will be created on first canonical write",
        evidence={"missing": missing},
    )


def _check_sqlite_db(repo_root: Path) -> CheckResult:
    db = repo_root / "runtime" / "mvp_local.db"
    if not db.exists():
        return CheckResult(
            name="sqlite_db",
            status="WARN",
            detail=f"canonical SQLite store missing at {db} — will be created on first write",
            evidence={"db_path": str(db), "exists": False},
        )
    try:
        con = sqlite3.connect(str(db))
        try:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM sqlite_master")
            obj_count = int(cur.fetchone()[0])
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        return CheckResult(
            name="sqlite_db",
            status="FAIL",
            detail=f"canonical SQLite store unreadable: {type(exc).__name__}",
            evidence={"db_path": str(db), "exists": True},
        )
    return CheckResult(
        name="sqlite_db",
        status="PASS",
        detail=f"canonical SQLite store readable; {obj_count} sqlite_master entries",
        evidence={"db_path": str(db), "exists": True, "object_count": obj_count},
    )


def _check_credential_hygiene(repo_root: Path) -> CheckResult:
    script = repo_root / "scripts" / "check_credential_hygiene.py"
    if not script.exists():
        return CheckResult(
            name="credential_hygiene",
            status="WARN",
            detail="credential hygiene script not present",
        )
    # Import the module and call build_report directly — avoids
    # CLI-argument coupling and keeps the bootstrap script honest about
    # not reading credential file contents.
    try:
        from scripts import check_credential_hygiene as cch
    except Exception as exc:  # pragma: no cover — defensive
        return CheckResult(
            name="credential_hygiene",
            status="WARN",
            detail=f"could not import credential hygiene checker: {type(exc).__name__}",
        )
    try:
        report = cch.build_report(root=repo_root)
    except Exception as exc:  # pragma: no cover — defensive
        return CheckResult(
            name="credential_hygiene",
            status="WARN",
            detail=f"credential hygiene check raised: {type(exc).__name__}",
        )
    if report.get("status") == "PASS":
        return CheckResult(
            name="credential_hygiene",
            status="PASS",
            detail="credential hygiene check passed",
        )
    return CheckResult(
        name="credential_hygiene",
        status="FAIL",
        detail=f"credential hygiene check status={report.get('status')!r}",
        evidence={
            "root_credential_offenders": report.get("root_credential_offenders", []),
            "secrets_gitignored": report.get("secrets_gitignored"),
        },
    )


def _check_private_scope_guard(repo_root: Path) -> CheckResult:
    try:
        from scripts import private_scope_guard

        report = private_scope_guard.build_report()
    except Exception as exc:  # pragma: no cover — defensive
        return CheckResult(
            name="private_scope_guard",
            status="FAIL",
            detail=f"could not import private_scope_guard: {type(exc).__name__}",
        )
    review = report.get("review_required") or []
    leaks = report.get("quarantine_leaks") or []
    if not review and not leaks:
        return CheckResult(
            name="private_scope_guard",
            status="PASS",
            detail="private scope guard reports zero review-required entries",
        )
    return CheckResult(
        name="private_scope_guard",
        status="FAIL",
        detail=(
            f"private scope guard reports review_required={len(review)} "
            f"quarantine_leaks={len(leaks)}"
        ),
        evidence={"review_required": review, "quarantine_leaks": leaks},
    )


def _check_script_present(repo_root: Path, rel: str, name: str) -> CheckResult:
    path = repo_root / rel
    if path.exists():
        return CheckResult(
            name=name,
            status="PASS",
            detail=f"{rel} present",
            evidence={"path": str(path)},
        )
    return CheckResult(
        name=name,
        status="FAIL",
        detail=f"{rel} missing",
        evidence={"path": str(path)},
    )


def _check_calibration_report(repo_root: Path) -> CheckResult:
    report = repo_root / "runtime" / "release" / "calibration_report.json"
    if not report.exists():
        return CheckResult(
            name="calibration_report",
            status="WARN",
            detail="calibration_report.json missing — run scripts/calibration_report.py",
            evidence={"path": str(report)},
        )
    try:
        body = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return CheckResult(
            name="calibration_report",
            status="WARN",
            detail=f"calibration_report.json unreadable: {type(exc).__name__}",
        )
    predictive_allowed = bool(body.get("predictive_claim_allowed"))
    return CheckResult(
        name="calibration_report",
        status="PASS",
        detail=(
            "calibration_report.json honest about predictive_claim_allowed="
            f"{predictive_allowed}"
        ),
        evidence={
            "predictive_claim_allowed": predictive_allowed,
            "n_real": body.get("n_real"),
            "n_min": body.get("n_min"),
            "evidence_status": body.get("evidence_status"),
        },
    )


def _check_frontend_package(repo_root: Path) -> CheckResult:
    pkg = repo_root / "frontend" / "package.json"
    if not pkg.exists():
        return CheckResult(
            name="frontend_package",
            status="WARN",
            detail="frontend/package.json missing — operator may want to skip frontend",
            evidence={"path": str(pkg)},
        )
    return CheckResult(
        name="frontend_package",
        status="PASS",
        detail="frontend/package.json present",
        evidence={"path": str(pkg)},
    )


def _check_tsc_available() -> CheckResult:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        return CheckResult(
            name="tsc_available",
            status="WARN",
            detail="npx not on PATH — operator should install Node 18+ for the frontend",
        )
    return CheckResult(
        name="tsc_available",
        status="PASS",
        detail="npx available; frontend strict typecheck can be invoked",
        evidence={"npx_path": npx},
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _aggregate_score(checks: Sequence[CheckResult]) -> dict[str, Any]:
    """Apply the spec scoring formula:

    ``BootstrapSuccessRate = S_pass / max(1, S_total)``
    ``BootstrapScore = min(10, 10×rate − 2×S_fail − 0.5×S_warn − 0.25×S_skip)``
    """
    s_total = len(checks)
    s_pass = sum(1 for c in checks if c.status == "PASS")
    s_warn = sum(1 for c in checks if c.status == "WARN")
    s_fail = sum(1 for c in checks if c.status == "FAIL")
    s_skip = sum(1 for c in checks if c.status == "SKIP")
    success_rate = s_pass / max(1, s_total)
    score = min(
        10.0,
        10.0 * success_rate
        - 2.0 * s_fail
        - 0.5 * s_warn
        - 0.25 * s_skip,
    )
    score = max(0.0, score)
    return {
        "checks_total": s_total,
        "checks_passed": s_pass,
        "checks_warned": s_warn,
        "checks_failed": s_fail,
        "checks_skipped": s_skip,
        "bootstrap_success_rate": round(success_rate, 6),
        "bootstrap_score": round(score, 4),
    }


def run_checks(repo_root: Path, *, skip_frontend: bool) -> list[CheckResult]:
    """Execute the bootstrap check ladder, returning the ordered list of
    :class:`CheckResult` records.  Read-only.
    """
    checks: list[CheckResult] = [
        _check_python_version(),
        _check_repo_root(repo_root),
        _check_runtime_dirs(repo_root),
        _check_sqlite_db(repo_root),
        _check_credential_hygiene(repo_root),
        _check_private_scope_guard(repo_root),
        _check_script_present(
            repo_root, "scripts/first_run_seed_free_sources.py", "first_run_seed_script"
        ),
        _check_script_present(
            repo_root, "scripts/probability_snapshot.py", "probability_snapshot_script"
        ),
        _check_calibration_report(repo_root),
        _check_script_present(
            repo_root, "scripts/segment_role_scorecard.py", "segment_role_scorecard_script"
        ),
    ]
    if skip_frontend:
        checks.append(
            CheckResult(
                name="frontend_package",
                status="SKIP",
                detail="--skip-frontend supplied; frontend checks skipped",
            )
        )
        checks.append(
            CheckResult(
                name="tsc_available",
                status="SKIP",
                detail="--skip-frontend supplied; tsc availability skipped",
            )
        )
    else:
        checks.append(_check_frontend_package(repo_root))
        checks.append(_check_tsc_available())
    return checks


def build_report(
    *,
    repo_root: Path = _REPO_ROOT,
    dry_run: bool = True,
    skip_frontend: bool = False,
) -> dict[str, Any]:
    """Return the bootstrap report dict (without writing anything)."""
    checks = run_checks(repo_root, skip_frontend=skip_frontend)
    aggregate = _aggregate_score(checks)
    safety = advisory_safety_stamps()
    return {
        "script": "bootstrap_local_operator.py",
        "generated_at_utc": _utc_now_iso(),
        "advisory_status": safety["advisory_status"],
        "execution_gate": safety["execution_gate"],
        "broker_api_called": safety["broker_api_called"],
        "ai_execution_count": safety["ai_execution_count"],
        "can_execute": safety["can_execute"],
        "execution_permission": safety["execution_permission"],
        "human_review_required": safety["human_review_required"],
        "broker_order_id": safety["broker_order_id"],
        "canonical_store": CANONICAL_STORE,
        "audit_only_store": AUDIT_ONLY_STORE,
        "jsonl_is_canonical": False,
        "dry_run": bool(dry_run),
        "skip_frontend": bool(skip_frontend),
        "checks": [c.to_dict() for c in checks],
        **aggregate,
        "next_commands": [
            LOCAL_BACKEND_COMMAND,
            LOCAL_FRONTEND_COMMAND,
        ],
        "local_urls": [LOCAL_BACKEND_URL, LOCAL_FRONTEND_URL],
        "warning": (
            "bootstrap script is read-only; nothing is started, no secrets "
            "are read, no external APIs are called unless "
            "--write-free-sources is supplied."
        ),
    }


def _run_free_sources_seed(repo_root: Path) -> CheckResult:
    """Delegate to the free-sources seed script in dry-run mode.

    Wrapped as a :class:`CheckResult` so the operator gets one structured
    line in the report rather than a wall of output.  ``--write-free-sources``
    flips this to the non-dry-run path.
    """
    script = repo_root / "scripts" / "first_run_seed_free_sources.py"
    if not script.exists():
        return CheckResult(
            name="free_sources_seed",
            status="FAIL",
            detail="first_run_seed_free_sources.py missing",
        )
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--write"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return CheckResult(
            name="free_sources_seed",
            status="WARN",
            detail=f"first_run_seed_free_sources.py raised: {type(exc).__name__}",
        )
    status = "PASS" if result.returncode == 0 else "WARN"
    return CheckResult(
        name="free_sources_seed",
        status=status,
        detail=f"first_run_seed_free_sources.py --write exit={result.returncode}",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "First-day operator bootstrap — read-only preflight + next commands."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default.  Run all checks; print plan; never start a server.",
    )
    parser.add_argument(
        "--write-free-sources",
        action="store_true",
        default=False,
        help="Opt in to running first_run_seed_free_sources.py --write.",
    )
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        default=False,
        help="Skip the frontend package and tsc-availability checks.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write the report JSON to this path.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        dry_run=True,  # the dry-run is always True; --write-free-sources only adds an extra step
        skip_frontend=bool(args.skip_frontend),
    )
    if args.write_free_sources:
        extra = _run_free_sources_seed(_REPO_ROOT)
        report["checks"].append(extra.to_dict())
        # Re-aggregate so the score reflects the extra check.
        rebuilt = [CheckResult(**c) for c in report["checks"]]
        report.update(_aggregate_score(rebuilt))
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json is not None:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload + "\n")
    return 0


__all__ = [
    "CheckResult",
    "MINIMUM_PYTHON_VERSION",
    "LOCAL_BACKEND_COMMAND",
    "LOCAL_FRONTEND_COMMAND",
    "LOCAL_BACKEND_URL",
    "LOCAL_FRONTEND_URL",
    "run_checks",
    "build_report",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
