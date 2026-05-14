"""
Pre-real-money preflight — one command before you log a real-money trade.

Purpose
-------
Bundle the local-operating-discipline checks (DB integrity, local security,
source refresh, self-test summary, reconciliation queue) into a single
read-only payload.  Run this BEFORE you start a real-money manual trading
day.

Read-only.  No live APIs.  No DB writes.  No broker calls.  No execution
permission.

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
    python scripts/pre_real_money_preflight.py
    python scripts/pre_real_money_preflight.py --json
    python scripts/pre_real_money_preflight.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
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

# Operator-action thresholds. Aligned with the runbook.
UNRECONCILED_WARN_THRESHOLD = 10
UNRECONCILED_BLOCK_THRESHOLD = 25
UNRECONCILED_FULL_REVIEW_THRESHOLD = 50


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _import_check(modname: str, attr: str):
    """Try importing ``attr`` from ``scripts.<modname>`` then ``<modname>``.
    Returns the callable or None if unavailable.
    """
    try:
        try:
            mod = __import__(f"scripts.{modname}", fromlist=[attr])
        except ImportError:
            mod = __import__(modname, fromlist=[attr])
        return getattr(mod, attr, None)
    except Exception:
        return None


def _safe_call(callable_, *args, **kwargs) -> dict[str, Any] | None:
    """Call ``callable_``; on any exception return None.  The preflight
    must never raise on a subcheck failure — that would block the operator
    from even seeing which subcheck broke."""
    if callable_ is None:
        return None
    try:
        return callable_(*args, **kwargs)
    except Exception as exc:  # pragma: no cover — defensive guard
        return {
            "ok": False,
            "subcheck_error": f"{type(exc).__name__}: {exc}",
        }


def run_preflight(
    db_path: Path | None = None,
    *,
    repo_root: Path | None = None,
    now: _dt.datetime | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run all subchecks and return a single payload."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    path = Path(db_path) if db_path else _default_db_path()
    rroot = (
        Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    )

    blocking_issues: list[str] = []
    warnings: list[str] = []

    payload: dict[str, Any] = {
        "report": "pre_real_money_preflight",
        "db_path": str(path),
        "repo_root": str(rroot),
        "ok": False,
        "subchecks": {},
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "operator_action": "",
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    payload.update(_SAFETY_STAMPS)

    # 1. DB integrity.
    dic_run = _import_check("db_integrity_check", "run_integrity_check")
    dic_result = _safe_call(dic_run, path, now=now)
    if dic_result is None:
        warnings.append("db_integrity_check_unavailable")
    else:
        payload["subchecks"]["db_integrity"] = dic_result
        if dic_result.get("ok") is False:
            blocking_issues.append("db_integrity_failed")

    # 2. Local security.
    lsa_run = _import_check("local_security_audit", "run_security_audit")
    lsa_result = _safe_call(lsa_run, rroot, env=env, now=now)
    if lsa_result is None:
        warnings.append("local_security_audit_unavailable")
    else:
        payload["subchecks"]["local_security"] = lsa_result
        if lsa_result.get("ok") is False:
            blocking_issues.append("local_security_failed")

    # 3. Source refresh.
    sra_run = _import_check("source_refresh_audit", "run_audit")
    sra_result = _safe_call(sra_run, path, now=now, env=env)
    if sra_result is None:
        warnings.append("source_refresh_audit_unavailable")
    else:
        payload["subchecks"]["source_refresh"] = sra_result
        if sra_result.get("ok") is False:
            # Source-refresh failing isn't a hard block, but warn loudly.
            warnings.append("source_refresh_degraded")

    # 4. Self-test summary (compact).
    str_run = _import_check("self_test_report", "build_self_test_summary")
    str_result = _safe_call(str_run, path)
    if str_result is None:
        warnings.append("self_test_summary_unavailable")
    else:
        payload["subchecks"]["self_test_summary"] = str_result

    # 5. Reconciliation queue.
    rq_run = _import_check("reconciliation_queue", "build_queue")
    rq_result = _safe_call(rq_run, path, limit=50, now=now)
    if rq_result is None:
        warnings.append("reconciliation_queue_unavailable")
    else:
        payload["subchecks"]["reconciliation_queue"] = rq_result
        summary = rq_result.get("summary", {}) or {}
        unreconciled = int(summary.get("unreconciled_count") or 0)
        payload["unreconciled_count"] = unreconciled
        if unreconciled >= UNRECONCILED_FULL_REVIEW_THRESHOLD:
            blocking_issues.append("unreconciled_backlog_full_review")
        elif unreconciled >= UNRECONCILED_BLOCK_THRESHOLD:
            blocking_issues.append("unreconciled_backlog_block")
        elif unreconciled >= UNRECONCILED_WARN_THRESHOLD:
            warnings.append("unreconciled_backlog_warn")

    payload["ok"] = len(blocking_issues) == 0

    if not payload["ok"]:
        payload["operator_action"] = (
            "BLOCKING ISSUES present (see blocking_issues list). DO NOT "
            "log real-money manual trades today. Fix the underlying "
            "issues and re-run scripts/pre_real_money_preflight.py."
        )
    elif warnings:
        payload["operator_action"] = (
            "Preflight passing with warnings (see warnings list). It is "
            "safe to proceed with discipline, but address each warning "
            "before week's end."
        )
    else:
        payload["operator_action"] = (
            "Preflight clean. Proceed with the daily checklist in "
            "docs/LOCAL_SELF_TEST_RUNBOOK.md."
        )

    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Pre-Real-Money Preflight")
    lines.append(f"DB: {payload['db_path']}")
    lines.append(f"Repo: {payload['repo_root']}")
    for name, sub in (payload.get("subchecks") or {}).items():
        ok = sub.get("ok") if isinstance(sub, dict) else None
        tag = "PASS" if ok else "FAIL" if ok is False else "INFO"
        lines.append(f"  [{tag}] {name}")
    if payload.get("warnings"):
        lines.append("Warnings: " + ", ".join(payload["warnings"]))
    if payload.get("blocking_issues"):
        lines.append("Blocking issues: " + ", ".join(payload["blocking_issues"]))
    lines.append(f"RESULT: {'PASS' if payload['ok'] else 'FAIL'}")
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pre_real_money_preflight.py",
        description=(
            "Pre-real-money preflight bundler. Read-only; aggregates the "
            "discipline checks into one decision."
        ),
    )
    p.add_argument("--db-path", type=str, default=None,
                   help="Path to runtime/mvp_local.db (default: persistence).")
    p.add_argument("--repo-root", type=str, default=None,
                   help="Repo root for the security audit (default: parent of scripts/).")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    repo_root = Path(args.repo_root) if args.repo_root else None
    payload = run_preflight(db_path, repo_root=repo_root)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload["ok"] else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "UNRECONCILED_WARN_THRESHOLD",
    "UNRECONCILED_BLOCK_THRESHOLD",
    "UNRECONCILED_FULL_REVIEW_THRESHOLD",
    "run_preflight",
]


if __name__ == "__main__":
    raise SystemExit(main())
