"""
Sprint 9A — local MVP audit summary (Python helper).

Pure-Python summary helpers that the PowerShell wrapper
(``scripts/windows/run_local_mvp_audit.ps1``) calls when it wants a
structured JSON section.  Each helper is read-only with respect to the
DB; no DB writes, no refresh runs, no broker calls, no order placements.

Run directly for a quick local readout:

    python scripts/local_mvp_audit.py
    python scripts/local_mvp_audit.py --json
    python scripts/local_mvp_audit.py --section safety
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "runtime"
DEFAULT_DB = RUNTIME_DIR / "mvp_local.db"


def _safety_stamps() -> dict[str, Any]:
    return {
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "human_review_required": True,
    }


def _safety_invariants() -> dict[str, Any]:
    return {
        "section": "safety_invariants",
        "advisory_only": True,
        "human_execution_required": True,
        "execution_gate": "LOCKED",
        "broker_order_permission": False,
        "ai_execution_count": 0,
        "broker_api_called": False,
        "execution_permission": False,
        "can_execute": False,
        "paper_trade_only_for_paper_rows": True,
        "real_capital_at_risk_for_paper_rows": False,
        **_safety_stamps(),
    }


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def paper_ledger_section(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Summarise the paper-trade ledger state.

    Read-only — never imports, never writes, never calls a broker.
    """
    out: dict[str, Any] = {
        "section": "paper_ledger",
        "db_path": str(db_path),
        "db_available": False,
        "trade_mode_column_present": False,
        "paper_trade_count": 0,
        "real_manual_trade_count": 0,
        "unknown_trade_count": 0,
        "template_present": (REPO_ROOT / "exports" / "paper_trade_template.csv").exists(),
        **_safety_stamps(),
    }
    conn = _readonly_connect(db_path)
    if conn is None:
        out["warning"] = "db_missing_or_unreadable"
        return out
    try:
        out["db_available"] = True
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        if "trade_mode" not in cols:
            return out
        out["trade_mode_column_present"] = True
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(trade_mode),''),'UNKNOWN') AS tm,"
            " COUNT(*) AS n FROM manual_trades GROUP BY tm"
        ).fetchall()
        for tm, n in rows:
            mode = str(tm).upper()
            if mode == "PAPER":
                out["paper_trade_count"] = int(n)
            elif mode == "REAL_MANUAL":
                out["real_manual_trade_count"] = int(n)
            else:
                out["unknown_trade_count"] = int(n)
    finally:
        conn.close()
    return out


def calibration_section(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    out: dict[str, Any] = {
        "section": "calibration",
        "db_path": str(db_path),
        "available": False,
        **_safety_stamps(),
    }
    try:
        try:
            from scripts.reactor_calibration_report import build_report
        except ModuleNotFoundError:
            from reactor_calibration_report import build_report  # type: ignore[no-redef]
        rep = build_report(db_path)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}"
        return out
    out["available"] = bool(rep.get("db_available"))
    out["confidence_band"] = rep.get("confidence_band")
    out["calibration_confidence_band"] = rep.get("calibration_confidence_band")
    out["manual_trade_count"] = rep.get("manual_trade_count", 0)
    out["reconciled_count"] = rep.get("reconciled_count", 0)
    calibration = rep.get("calibration") or {}
    out["reactor_snapshot_count"] = calibration.get("reactor_snapshot_count", 0)
    out["reactor_snapshot_with_outcome"] = calibration.get(
        "reactor_snapshot_with_outcome", 0
    )
    out["limitations"] = list(rep.get("limitations") or [])
    return out


def learning_completeness_section(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    out: dict[str, Any] = {
        "section": "learning_completeness",
        "db_path": str(db_path),
        "available": False,
        **_safety_stamps(),
    }
    try:
        try:
            from scripts.learning_completeness_report import build_report
        except ModuleNotFoundError:
            from learning_completeness_report import build_report  # type: ignore[no-redef]
        rep = build_report(db_path)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}"
        return out
    out["available"] = bool(rep.get("db_available"))
    out["reconciled_count"] = rep.get("reconciled_count", 0)
    out["learning_complete_count"] = rep.get("learning_complete_count", 0)
    out["learning_incomplete_count"] = rep.get("learning_incomplete_count", 0)
    dist = rep.get("missing_field_distribution") or {}
    top = sorted(dist.items(), key=lambda kv: -kv[1])[:5]
    out["top_missing_fields"] = [{"field": k, "count": v} for k, v in top]
    return out


def source_health_section() -> dict[str, Any]:
    out: dict[str, Any] = {
        "section": "source_health",
        **_safety_stamps(),
        "available": False,
    }
    try:
        try:
            from scripts.api_server import _build_live_sources_status
        except ModuleNotFoundError:
            from api_server import _build_live_sources_status  # type: ignore[no-redef]
        payload = _build_live_sources_status()
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}"
        return out
    out["available"] = True
    out["source_count"] = payload.get("source_count", 0)
    out["stale_sources"] = list(payload.get("stale_sources") or [])
    out["refresh_configured"] = bool(payload.get("refresh_configured"))
    summary = payload.get("health_summary") or {}
    out["core_health_label"] = summary.get("core_health_label")
    out["average_scored_health"] = summary.get("average_scored_health")
    out["scored_count"] = summary.get("scored_count")
    out["planned_count"] = summary.get("planned_count")
    out["optional_missing_config_count"] = summary.get(
        "optional_missing_config_count"
    )
    out["health_label_distribution"] = summary.get("health_label_distribution") or {}
    # Operator-actionable surfaces.  ``issue_classification`` lets the
    # audit pass/warn/fail decision distinguish "core source is broken"
    # (real failure) from "optional source has no API key" (operator
    # action — not a failure).  ``actionable_next_steps`` is the short
    # punch-list a human reads to know what to do next.
    out["issue_classification"] = dict(summary.get("issue_classification") or {})
    out["actionable_next_steps"] = list(summary.get("actionable_next_steps") or [])
    return out


def calibration_gate_section(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Surface the Sprint 10F calibration readiness gate inside the audit.

    Returns a compact summary (status + rows-needed) so the operator can
    see at a glance whether paper / real-manual outcomes should be
    interpreted yet.  Read-only.
    """
    out: dict[str, Any] = {
        "section": "calibration_gate",
        "db_path": str(db_path),
        "available": False,
        **_safety_stamps(),
    }
    try:
        try:
            from scripts.calibration_gate import build_report
        except ModuleNotFoundError:
            from calibration_gate import build_report  # type: ignore[no-redef]
        rep = build_report(db_path)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}"
        return out
    out["available"] = bool(rep.get("db_available"))
    out["paper_calibration_ready"] = rep["paper"]["status"]
    out["paper_rows_needed_next"] = rep["paper"]["rows_needed_next"]
    out["paper_with_snapshot_and_outcome"] = rep["paper"]["rows"]["with_snapshot_and_outcome"]
    out["paper_fully_qualifying"] = rep["paper"]["rows"]["fully_qualifying"]
    out["real_calibration_ready"] = rep["real"]["status"]
    out["real_rows_needed_next"] = rep["real"]["rows_needed_next"]
    out["real_with_snapshot_and_outcome"] = rep["real"]["rows"]["with_snapshot_and_outcome"]
    out["no_claims"] = list(rep["paper"].get("no_claims", []))
    return out


def token_status_section() -> dict[str, Any]:
    """Whether MVP_API_TOKEN is set on this process (no value leaked)."""
    set_locally = bool(os.environ.get("MVP_API_TOKEN", "").strip())
    return {
        "section": "token_status",
        "mvp_api_token_set": set_locally,
        "policy": (
            "When set, mutating POST routes require Bearer auth.  When unset, "
            "they are permissive (local-only single-user MVP)."
        ),
        "frontend_token_storage": "sessionStorage (cleared on tab close)",
        **_safety_stamps(),
    }


def scope_guard_section() -> dict[str, Any]:
    """Surface the private-operator scope guard inside the audit.

    Informational/WARN-level only — the guard never destroys files and
    never fails the audit just because pre-existing out-of-scope modules
    are present.  Newly-introduced out-of-scope modules trigger
    REVIEW_REQUIRED so they cannot dilute the MVP unnoticed.
    """
    out: dict[str, Any] = {
        "section": "scope_guard",
        "available": False,
        **_safety_stamps(),
    }
    try:
        try:
            from scripts.private_scope_guard import build_report
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from private_scope_guard import build_report  # type: ignore[no-redef]
        rep = build_report()
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}"
        return out
    out["available"] = True
    out["in_scope_count"] = rep.get("in_scope_count", 0)
    out["out_of_scope_count"] = rep.get("out_of_scope_count", 0)
    out["review_required_count"] = rep.get("review_required_count", 0)
    out["review_required"] = list(rep.get("review_required") or [])
    out["known_out_of_scope"] = list(rep.get("known_out_of_scope") or [])
    out["operator_message"] = rep.get("operator_message", "")
    return out


def run_audit(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Build the full audit payload (read-only)."""
    payload: dict[str, Any] = {
        "report": "local_mvp_audit",
        "repo_root": str(REPO_ROOT),
        "runtime_dir": str(RUNTIME_DIR),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "sections": {
            "safety_invariants": _safety_invariants(),
            "token_status": token_status_section(),
            "paper_ledger": paper_ledger_section(db_path),
            "calibration": calibration_section(db_path),
            "calibration_gate": calibration_gate_section(db_path),
            "learning_completeness": learning_completeness_section(db_path),
            "source_health": source_health_section(),
            "scope_guard": scope_guard_section(),
        },
        **_safety_stamps(),
    }
    # Compute a final advisory pass/warn/fail per section.
    statuses: dict[str, str] = {}
    statuses["safety_invariants"] = "PASS"
    statuses["token_status"] = "PASS"
    pl = payload["sections"]["paper_ledger"]
    statuses["paper_ledger"] = (
        "PASS" if pl.get("db_available") and pl.get("trade_mode_column_present")
        else "WARN"
    )
    cal = payload["sections"]["calibration"]
    statuses["calibration"] = (
        "PASS" if cal.get("available") and cal.get("manual_trade_count", 0) > 0
        else "WARN"
    )
    cg = payload["sections"]["calibration_gate"]
    # Gate is informational, not pass/fail — NOT_READY is the expected
    # default before evidence exists.  We surface it as INFO/WARN only.
    if not cg.get("available"):
        statuses["calibration_gate"] = "WARN"
    elif cg.get("paper_calibration_ready") in {"REVIEWABLE", "LOW_CONFIDENCE"}:
        statuses["calibration_gate"] = "PASS"
    else:
        statuses["calibration_gate"] = "INFO"
    lc = payload["sections"]["learning_completeness"]
    statuses["learning_completeness"] = "PASS" if lc.get("available") else "WARN"
    sh = payload["sections"]["source_health"]
    if not sh.get("available"):
        statuses["source_health"] = "WARN"
    else:
        # Action-oriented classification: a stale core source is a real
        # failure, but optional sources without an API key are an operator
        # config gap (WARN, not FAIL).  This stops the audit from masking
        # genuine refresh errors behind "missing optional config" noise.
        classification = sh.get("issue_classification") or {}
        core_stale = int(classification.get("core_stale", 0))
        core_config_missing = int(classification.get("core_config_missing", 0))
        refresh_error = int(classification.get("refresh_error", 0))
        core_label = sh.get("core_health_label")
        if core_stale > 0 or core_config_missing > 0 or refresh_error > 0:
            statuses["source_health"] = "FAIL"
        elif core_label in {"unhealthy"}:
            statuses["source_health"] = "FAIL"
        elif core_label in {"degraded", "watch"}:
            statuses["source_health"] = "WARN"
        else:
            statuses["source_health"] = "PASS"
    sg = payload["sections"].get("scope_guard") or {}
    if not sg.get("available"):
        statuses["scope_guard"] = "WARN"
    elif sg.get("review_required_count", 0) > 0:
        statuses["scope_guard"] = "WARN"
    else:
        statuses["scope_guard"] = "PASS"
    payload["statuses"] = statuses
    payload["overall"] = (
        "FAIL" if "FAIL" in statuses.values()
        else "WARN" if "WARN" in statuses.values()
        else "PASS"
    )
    return payload


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Local MVP Audit")
    lines.append("=" * 16)
    lines.append(f"Repo root          : {payload['repo_root']}")
    lines.append(f"DB                 : {payload['db_path']} (exists={payload['db_exists']})")
    lines.append(f"Overall            : {payload['overall']}")
    for name, status in payload.get("statuses", {}).items():
        lines.append(f"  - {name:<24} {status}")
    sections = payload["sections"]
    pl = sections["paper_ledger"]
    lines.append("")
    lines.append("Paper ledger:")
    lines.append(f"  trade_mode column : {pl.get('trade_mode_column_present')}")
    lines.append(f"  paper rows        : {pl.get('paper_trade_count')}")
    lines.append(f"  real_manual rows  : {pl.get('real_manual_trade_count')}")
    lines.append(f"  template present  : {pl.get('template_present')}")
    cal = sections["calibration"]
    lines.append("")
    lines.append("Calibration:")
    lines.append(f"  confidence_band       : {cal.get('confidence_band')}")
    lines.append(f"  calibration_confidence: {cal.get('calibration_confidence_band')}")
    lines.append(f"  reactor_snapshot_count: {cal.get('reactor_snapshot_count')}")
    cg = sections.get("calibration_gate", {})
    lines.append("")
    lines.append("Calibration gate (Sprint 10F):")
    lines.append(f"  paper_calibration_ready : {cg.get('paper_calibration_ready')}")
    lines.append(f"  paper rows needed next  : {cg.get('paper_rows_needed_next')}")
    lines.append(f"  real_calibration_ready  : {cg.get('real_calibration_ready')}")
    lines.append(f"  real rows needed next   : {cg.get('real_rows_needed_next')}")
    lc = sections["learning_completeness"]
    lines.append("")
    lines.append("Learning completeness:")
    lines.append(f"  reconciled           : {lc.get('reconciled_count')}")
    lines.append(f"  complete             : {lc.get('learning_complete_count')}")
    lines.append(f"  incomplete           : {lc.get('learning_incomplete_count')}")
    sh = sections["source_health"]
    lines.append("")
    lines.append("Source health:")
    lines.append(f"  core_health_label    : {sh.get('core_health_label')}")
    lines.append(f"  average_score        : {sh.get('average_scored_health')}")
    lines.append(f"  stale_sources        : {len(sh.get('stale_sources') or [])}")
    ts = sections["token_status"]
    lines.append("")
    lines.append("Token status:")
    lines.append(f"  MVP_API_TOKEN set    : {ts.get('mvp_api_token_set')}")
    lines.append("")
    lines.append(
        "Safety invariants:  ADVISORY_ONLY · HUMAN_EXECUTION_REQUIRED · "
        "execution_gate=LOCKED · broker_api_called=False · "
        "ai_execution_count=0"
    )
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="local_mvp_audit.py",
        description=(
            "Read-only summary of MVP local state: safety invariants, "
            "paper ledger, calibration, learning completeness, source "
            "health, token policy.  No DB mutation, no broker call."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--section",
        choices=[
            "safety",
            "token",
            "paper",
            "calibration",
            "calibration_gate",
            "learning",
            "source_health",
            "all",
        ],
        default="all",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = args.db_path if args.db_path else DEFAULT_DB
    section = args.section
    if section == "all":
        payload = run_audit(db)
        if args.json:
            print(json.dumps(payload, sort_keys=True, indent=2, default=str))
        else:
            print(_render_text(payload))
        return 0 if payload.get("overall") != "FAIL" else 1

    fn_by_section = {
        "safety": _safety_invariants,
        "token": token_status_section,
        "paper": lambda: paper_ledger_section(db),
        "calibration": lambda: calibration_section(db),
        "calibration_gate": lambda: calibration_gate_section(db),
        "learning": lambda: learning_completeness_section(db),
        "source_health": source_health_section,
    }
    payload = fn_by_section[section]()
    print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    return 0


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "run_audit",
    "paper_ledger_section",
    "calibration_section",
    "calibration_gate_section",
    "learning_completeness_section",
    "source_health_section",
    "token_status_section",
]


if __name__ == "__main__":
    raise SystemExit(main())
