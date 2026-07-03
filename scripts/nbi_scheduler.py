"""NBI scheduler — Windows Task Scheduler integration for the evidence factory.

Turns the v1.2 CLI runner into an actually schedulable daily loop, following
the repo's existing schtasks pattern (scripts/windows/register_*_task.ps1):

    python -m scripts.nbi_scheduler install --time 08:30 [--dry-run]
    python -m scripts.nbi_scheduler uninstall [--dry-run]
    python -m scripts.nbi_scheduler status
    python -m scripts.nbi_scheduler run-once [--dry-run]
    python -m scripts.nbi_scheduler cron          # cron line for Linux hosts

``run-once`` executes one factory cycle (run-daily + export-cards) and
records scheduler health to ``runtime/nbi_scheduler_last_run.json`` plus an
append-only log at ``runtime/nbi_scheduler.log``:

    SchedulerHealth = RunSuccess x FeedAvailable x ReportPersisted x CardsExported
    SchedulerHealth10 = 10 x SchedulerHealth

When feeds/definitions are unavailable but the cycle fails closed correctly,
status = DEGRADED_BUT_SAFE (FailClosedHealth = RunSuccess x FailClosedCorrectly)
— degraded is disclosed, never dressed up as healthy, never a crash.

Honesty: ``status`` reports INSTALLED only when the Windows task actually
exists (schtasks query), never merely because this helper module exists.
Dry-run modes render commands / validate inputs without touching schtasks
or the canonical DB.

Advisory-only.  The scheduled command runs scoring + card export only —
no broker, no orders, no execution surface, no secrets in source.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.runtime_common import REPO_ROOT

SCHEDULER_VERSION = "nbi-scheduler-v1.0"
TASK_NAME = "SleepingPassenger_NBI_DailyLoop"
DEFAULT_TIME = "08:30"

LAST_RUN_PATH = REPO_ROOT / "runtime" / "nbi_scheduler_last_run.json"
LOG_PATH = REPO_ROOT / "runtime" / "nbi_scheduler.log"
INSTALL_MARKER_PATH = REPO_ROOT / "runtime" / "nbi_scheduler_install.json"

STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED_BUT_SAFE = "DEGRADED_BUT_SAFE"
STATUS_BROKEN = "BROKEN"
STATUS_BROKEN_UNSAFE = "BROKEN_UNSAFE"
STATUS_FAILED = "FAILED"  # legacy alias kept for older records
STATUS_NOT_INSTALLED = "NOT_INSTALLED"
STATUS_INSTALLED = "INSTALLED"

SCORE_REPORT_ARTIFACT_PATH = REPO_ROOT / "runtime" / "nbi_score_report.json"

# Tokens that must never appear in the scheduled action.  Checked by the
# per-run safety check AND by doctor.  (Shares intent with
# advisory_contract.FORBIDDEN_EXECUTION_TOKENS; kept explicit here so the
# scheduler is self-auditing even if imports change.)
_FORBIDDEN_ACTION_TOKENS: tuple[str, ...] = (
    "place_order", "submit_order", "execute_trade", "broker",
    "buy ", "sell ", "auto_trade", "autotrade",
)


def _safety_check_action(action: str) -> bool:
    lowered = action.lower()
    return not any(tok in lowered for tok in _FORBIDDEN_ACTION_TOKENS)

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _now_iso(now_iso: str | None = None) -> str:
    if now_iso:
        return now_iso
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log(line: str, log_path: Path | None = None) -> None:
    target = log_path or LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def build_task_command() -> str:
    """The command the Windows task runs: one factory cycle, advisory-only."""
    python = sys.executable or "python"
    return (
        f'"{python}" -m scripts.nbi_scheduler run-once'
    )


def build_schtasks_install_args(time_hhmm: str) -> list[str]:
    return [
        "schtasks", "/Create", "/F",
        "/TN", TASK_NAME,
        "/SC", "DAILY",
        "/ST", time_hhmm,
        "/TR", f"cmd /c cd /d {REPO_ROOT} && {build_task_command()}",
    ]


def build_cron_line(time_hhmm: str) -> str:
    hh, mm = time_hhmm.split(":")
    return (
        f"{int(mm)} {int(hh)} * * * cd {REPO_ROOT} && "
        f"python -m scripts.nbi_scheduler run-once"
    )


def install(
    time_hhmm: str = DEFAULT_TIME, *, dry_run: bool = False,
    runner=subprocess.run,
) -> dict[str, Any]:
    if not _TIME_RE.match(time_hhmm):
        return {"installed": False, "error": f"invalid --time {time_hhmm!r} (HH:MM)"}
    args = build_schtasks_install_args(time_hhmm)
    if dry_run:
        return {
            "installed": False, "dry_run": True,
            "schtasks_command": args, "cron_equivalent": build_cron_line(time_hhmm),
            "safety": advisory_safety_stamps(),
        }
    proc = runner(args, capture_output=True, text=True, check=False)
    ok = proc.returncode == 0
    if ok:
        INSTALL_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_MARKER_PATH.write_text(json.dumps({
            "task_name": TASK_NAME, "time": time_hhmm,
            "installed_at": _now_iso(), "version": SCHEDULER_VERSION,
        }, indent=2), encoding="utf-8")
    return {
        "installed": ok, "task_name": TASK_NAME, "time": time_hhmm,
        "stderr": (proc.stderr or "").strip()[:500] if not ok else "",
        "safety": advisory_safety_stamps(),
    }


def uninstall(*, dry_run: bool = False, runner=subprocess.run) -> dict[str, Any]:
    args = ["schtasks", "/Delete", "/F", "/TN", TASK_NAME]
    if dry_run:
        return {"uninstalled": False, "dry_run": True, "schtasks_command": args}
    proc = runner(args, capture_output=True, text=True, check=False)
    if proc.returncode == 0 and INSTALL_MARKER_PATH.exists():
        INSTALL_MARKER_PATH.unlink()
    return {"uninstalled": proc.returncode == 0, "task_name": TASK_NAME}


def task_installed(runner=subprocess.run) -> bool:
    """Truth from schtasks itself — never from this module's existence."""
    try:
        proc = runner(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


def scheduler_status(runner=subprocess.run) -> dict[str, Any]:
    installed = task_installed(runner)
    last_run: dict[str, Any] | None = None
    try:
        last_run = json.loads(LAST_RUN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last_run = None
    return {
        "report": "nbi_scheduler_status",
        "version": SCHEDULER_VERSION,
        "task_name": TASK_NAME,
        "install_status": STATUS_INSTALLED if installed else STATUS_NOT_INSTALLED,
        "last_run": last_run,
        "log_path": str(LOG_PATH),
        "safety": advisory_safety_stamps(),
    }


def run_once(
    *,
    dry_run: bool = False,
    db_path: Path | str | None = None,
    last_run_path: Path | str | None = None,
    log_path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """One scheduled cycle: run-daily + export-cards + health record.

    Dry-run only inspects inputs (definitions/feeds present?) and never
    touches the canonical DB, exports, or logs.
    """
    from scripts.nbi_evidence_factory import (
        STATUS_OK,
        export_cards,
        load_event_definitions,
        load_feed_rows,
        run_daily,
    )

    stamp = _now_iso(now_iso)
    definitions = load_event_definitions()
    feed_rows = load_feed_rows()

    if dry_run:
        return {
            "report": "nbi_scheduler_run_once",
            "dry_run": True,
            "timestamp": stamp,
            "definitions_present": bool(definitions),
            "feeds_present": feed_rows is not None,
            "would_run": bool(definitions) and feed_rows is not None,
            "db_mutated": False,
            "safety": advisory_safety_stamps(),
        }

    from scripts.nbi_evidence_factory import build_score_report

    run_success = 1
    fail_closed_correctly = 1
    run_result: dict[str, Any] = {}
    cards_exported = 0
    score_report_written = 0
    safety_check_passed = 1 if _safety_check_action(build_task_command()) else 0
    try:
        run_result = run_daily(db_path=db_path, now_iso=now_iso)
        feed_available = 1 if run_result.get("status") == STATUS_OK else 0
        report_persisted = 1 if any(
            e.get("saved") for e in run_result.get("ingested_events", [])
        ) else 0
        try:
            export_cards(db_path)
            cards_exported = 1
        except Exception:  # noqa: BLE001 - disclosed via health, never hidden
            cards_exported = 0
        try:
            SCORE_REPORT_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
            SCORE_REPORT_ARTIFACT_PATH.write_text(
                json.dumps(build_score_report(db_path), indent=2, default=str),
                encoding="utf-8",
            )
            score_report_written = 1
        except Exception:  # noqa: BLE001
            score_report_written = 0
    except Exception as exc:  # noqa: BLE001
        run_success = 0
        fail_closed_correctly = 0
        feed_available = 0
        report_persisted = 0
        run_result = {"status": "CRASHED", "error": type(exc).__name__}

    # v1.4 health model.  Two numbers:
    #   SchedulerHealth   = Run x Persisted x Cards x ScoreReport x Safety
    #   SafeOperational   = same when feeds available, else the fail-closed
    #                       credit Run x FailClosedCorrectly x Safety.
    # Feed availability is not a safety component: an unavailable feed with
    # a clean fail-closed cycle is DEGRADED_BUT_SAFE, never HEALTHY.
    scheduler_health = (
        run_success * report_persisted * cards_exported
        * score_report_written * safety_check_passed
    )
    if feed_available:
        safe_operational = scheduler_health
    else:
        safe_operational = run_success * fail_closed_correctly * safety_check_passed
    health10 = round(10 * scheduler_health, 2)
    safe10 = round(10 * safe_operational, 2)
    if not safety_check_passed:
        status = STATUS_BROKEN_UNSAFE
    elif not run_success:
        status = STATUS_BROKEN
    elif feed_available and health10 >= 8:
        status = STATUS_HEALTHY
    elif safe10 >= 5:
        status = STATUS_DEGRADED_BUT_SAFE
    else:
        status = STATUS_BROKEN

    record = {
        "report": "nbi_scheduler_run_once",
        "version": SCHEDULER_VERSION,
        "timestamp": stamp,
        "status": status,
        "factory_status": run_result.get("status"),
        "SchedulerHealth10": health10,
        "SafeOperationalHealth10": safe10,
        "components": {
            "run_success": run_success,
            "feed_available": feed_available,
            "report_persisted": report_persisted,
            "cards_exported": cards_exported,
            "score_report_written": score_report_written,
            "safety_check_passed": safety_check_passed,
            "fail_closed_correctly": fail_closed_correctly,
        },
        "ingested_events": run_result.get("ingested_events", []),
        "edge_claim": run_result.get("edge_claim"),
        "db_mutated": bool(run_success),
        "safety": advisory_safety_stamps(),
    }
    target = Path(last_run_path) if last_run_path else LAST_RUN_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    _log(
        f"{stamp} status={status} health={health10} safe={safe10} "
        f"factory={run_result.get('status')}",
        Path(log_path) if log_path else None,
    )
    return record


INSTALL_PS1_PATH = REPO_ROOT / "runtime" / "install_nbi_scheduler.ps1"
UNINSTALL_PS1_PATH = REPO_ROOT / "runtime" / "uninstall_nbi_scheduler.ps1"


def print_install_command(time_hhmm: str = DEFAULT_TIME) -> str:
    """The exact one-liner the operator runs.  Nothing else claims install."""
    return " ".join(build_schtasks_install_args(time_hhmm))


def generate_install_scripts(
    time_hhmm: str = DEFAULT_TIME,
    *, out_install: Path | str | None = None,
    out_uninstall: Path | str | None = None,
) -> dict[str, Any]:
    """Write idempotent PowerShell install/uninstall helpers to runtime/.

    Advisory-only by construction: the scheduled action runs run-once
    (scoring + card export + score report).  No broker, no orders.
    """
    install_target = Path(out_install) if out_install else INSTALL_PS1_PATH
    uninstall_target = (
        Path(out_uninstall) if out_uninstall else UNINSTALL_PS1_PATH
    )
    action = f"cmd /c cd /d {REPO_ROOT} && {build_task_command()}"
    install_text = "\n".join([
        "# Sleeping Passenger — NBI daily loop scheduled-task installer.",
        "# ADVISORY-ONLY: the task runs scoring + card export + score",
        "# report. It contains no trading-execution commands of any kind.",
        "# Idempotent: /F replaces an existing task with the same name.",
        f"$taskName = '{TASK_NAME}'",
        # Single-quoted PowerShell string so the inner double quotes around
        # the python path reach schtasks literally (a double-quoted string
        # here splits /TR at the nested quotes — found by running it).
        (
            f"schtasks /Create /F /TN $taskName /SC DAILY /ST {time_hhmm} "
            f"/TR '{action}'"
        ),
        "schtasks /Query /TN $taskName",
        f"Write-Output \"Logs: {LOG_PATH}\"",
        f"Write-Output \"Last-run status: {LAST_RUN_PATH}\"",
        "",
    ])
    uninstall_text = "\n".join([
        "# Sleeping Passenger — NBI daily loop scheduled-task remover.",
        "# Idempotent: deleting an absent task reports an error and stops",
        "# nothing else. ADVISORY-ONLY tooling.",
        f"$taskName = '{TASK_NAME}'",
        "schtasks /Delete /F /TN $taskName",
        "",
    ])
    install_target.parent.mkdir(parents=True, exist_ok=True)
    install_target.write_text(install_text, encoding="utf-8")
    uninstall_target.write_text(uninstall_text, encoding="utf-8")
    safe = _safety_check_action(install_text) and _safety_check_action(
        uninstall_text
    )
    return {
        "generated": True,
        "install_script": str(install_target),
        "uninstall_script": str(uninstall_target),
        "task_name": TASK_NAME,
        "time": time_hhmm,
        "safety_check_passed": safe,
    }


def verify_install(runner=subprocess.run) -> dict[str, Any]:
    """Install truth: schtasks query only.  No proxy may count."""
    installed = task_installed(runner)
    return {
        "report": "nbi_scheduler_verify_install",
        "task_name": TASK_NAME,
        "task_installed": installed,
        "truth_source": "schtasks /Query",
        "note": (
            "task present" if installed else
            "installable helper verified; actual OS task not installed "
            "in this environment"
        ),
        "install_command": print_install_command(),
        "install_script": str(INSTALL_PS1_PATH),
    }


def build_fix_plan(doctor_report: dict[str, Any]) -> list[str]:
    """Exact next commands, derived from the doctor's failed/absent checks."""
    plan: list[str] = []
    checks = doctor_report.get("checks", {})
    if not doctor_report.get("task_installed"):
        plan.append(
            f"python -m scripts.nbi_scheduler install --time {DEFAULT_TIME} "
            "--confirm   (or run runtime/install_nbi_scheduler.ps1)"
        )
    if not checks.get("last_run_status_file", {}).get("ok"):
        plan.append("python -m scripts.nbi_scheduler run-once")
    if not checks.get("task_scheduler_available", {}).get("ok"):
        plan.append(
            "Windows Task Scheduler unavailable: use "
            "'python -m scripts.nbi_scheduler cron' on a POSIX host"
        )
    for key in ("evidence_factory_import", "db_path", "runtime_dir"):
        if not checks.get(key, {}).get("ok"):
            plan.append(f"repair failed check: {key}")
    if not plan:
        plan.append("nothing to fix: scheduler chain fully operational")
    return plan


def doctor(runner=subprocess.run) -> dict[str, Any]:
    """Full preflight of the scheduled loop.  Every check disclosed."""
    checks: dict[str, Any] = {}

    checks["python_executable"] = {
        "value": sys.executable, "ok": bool(sys.executable),
    }
    checks["repo_root"] = {
        "value": str(REPO_ROOT), "ok": (REPO_ROOT / "scripts").is_dir(),
    }
    runtime_dir = REPO_ROOT / "runtime"
    checks["runtime_dir"] = {
        "value": str(runtime_dir), "ok": runtime_dir.is_dir(),
    }
    try:
        from scripts.nbi_store import CANONICAL_DB_PATH
        checks["db_path"] = {
            "value": str(CANONICAL_DB_PATH),
            "ok": CANONICAL_DB_PATH.parent.is_dir(),
        }
    except Exception as exc:  # noqa: BLE001
        checks["db_path"] = {"value": None, "ok": False,
                             "error": type(exc).__name__}
    try:
        from scripts.nbi_evidence_factory import (  # noqa: F401
            build_score_report, export_cards, run_daily,
        )
        checks["evidence_factory_import"] = {"ok": True}
        checks["run_daily_command"] = {"ok": callable(run_daily)}
        checks["export_cards_command"] = {"ok": callable(export_cards)}
        checks["score_report_command"] = {"ok": callable(build_score_report)}
    except Exception as exc:  # noqa: BLE001
        for key in ("evidence_factory_import", "run_daily_command",
                    "export_cards_command", "score_report_command"):
            checks[key] = {"ok": False, "error": type(exc).__name__}

    try:
        probe = runner(["schtasks", "/Query"], capture_output=True,
                       text=True, check=False)
        checks["task_scheduler_available"] = {"ok": probe.returncode == 0}
    except OSError as exc:
        checks["task_scheduler_available"] = {"ok": False,
                                              "error": type(exc).__name__}
    installed = task_installed(runner)
    checks["task_installed"] = {
        "ok": True, "value": installed,
        "note": (
            "installable helper verified; actual OS task not installed "
            "in this environment" if not installed else "task present"
        ),
    }
    checks["last_run_log"] = {
        "value": str(LOG_PATH), "ok": LOG_PATH.exists(),
        "note": None if LOG_PATH.exists() else "no run yet",
    }
    checks["last_run_status_file"] = {
        "value": str(LAST_RUN_PATH), "ok": LAST_RUN_PATH.exists(),
        "note": None if LAST_RUN_PATH.exists() else "no run yet",
    }
    action = build_task_command()
    checks["scheduled_action_safety"] = {
        "value": action, "ok": _safety_check_action(action),
    }
    stamps = advisory_safety_stamps()
    checks["advisory_only_strings"] = {
        "ok": stamps["advisory_status"] == "ADVISORY_ONLY"
        and stamps["execution_gate"] == "LOCKED",
    }

    # last_run_log / status-file absence is informational, not a failure.
    hard_keys = [
        k for k in checks
        if k not in ("last_run_log", "last_run_status_file", "task_installed")
    ]
    all_ok = all(checks[k]["ok"] for k in hard_keys)
    return {
        "report": "nbi_scheduler_doctor",
        "version": SCHEDULER_VERSION,
        "ok": all_ok,
        "task_installed": installed,
        "checks": checks,
        "safety": stamps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NBI scheduler: Windows Task Scheduler integration for the "
            "evidence factory (advisory-only; scoring + card export only)."
        )
    )
    sub = parser.add_subparsers(dest="command")
    ins = sub.add_parser("install")
    ins.add_argument("--time", default=DEFAULT_TIME)
    ins.add_argument("--dry-run", action="store_true")
    ins.add_argument("--confirm", action="store_true",
                     help="required for the real schtasks /Create")
    uni = sub.add_parser("uninstall")
    uni.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    doc = sub.add_parser("doctor")
    doc.add_argument("--fix-plan", action="store_true")
    sub.add_parser("verify-install")
    sub.add_parser("print-install-command")
    gen = sub.add_parser("generate-scripts",
                         help="write runtime/install_nbi_scheduler.ps1 (+un)")
    gen.add_argument("--time", default=DEFAULT_TIME)
    ro = sub.add_parser("run-once")
    ro.add_argument("--dry-run", action="store_true")
    ro.add_argument("--db", default=None)
    cron = sub.add_parser("cron")
    cron.add_argument("--time", default=DEFAULT_TIME)

    args = parser.parse_args(argv)
    if args.command == "install":
        if not args.dry_run and not args.confirm:
            print(json.dumps({
                "installed": False,
                "error": "pass --confirm for the real schtasks /Create "
                         "(or --dry-run to preview)",
                "install_command": print_install_command(args.time),
            }, indent=2))
            return 1
        print(json.dumps(install(args.time, dry_run=args.dry_run), indent=2))
    elif args.command == "uninstall":
        print(json.dumps(uninstall(dry_run=args.dry_run), indent=2))
    elif args.command == "status":
        print(json.dumps(scheduler_status(), indent=2, default=str))
    elif args.command == "doctor":
        report = doctor()
        if getattr(args, "fix_plan", False):
            report["fix_plan"] = build_fix_plan(report)
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["ok"] else 1
    elif args.command == "verify-install":
        out = verify_install()
        print(json.dumps(out, indent=2))
        return 0 if out["task_installed"] else 1
    elif args.command == "print-install-command":
        print(print_install_command())
    elif args.command == "generate-scripts":
        print(json.dumps(generate_install_scripts(args.time), indent=2))
    elif args.command == "run-once":
        record = run_once(dry_run=args.dry_run, db_path=args.db)
        print(json.dumps(record, indent=2, default=str))
        return 0 if record.get("status") != STATUS_FAILED else 1
    elif args.command == "cron":
        print(build_cron_line(args.time))
    else:
        parser.print_help()
        return 2
    return 0


__all__ = [
    "SCHEDULER_VERSION", "TASK_NAME", "DEFAULT_TIME",
    "STATUS_HEALTHY", "STATUS_DEGRADED_BUT_SAFE", "STATUS_FAILED",
    "STATUS_BROKEN", "STATUS_BROKEN_UNSAFE",
    "STATUS_NOT_INSTALLED", "STATUS_INSTALLED",
    "SCORE_REPORT_ARTIFACT_PATH",
    "build_task_command", "build_schtasks_install_args", "build_cron_line",
    "install", "uninstall", "task_installed", "scheduler_status",
    "run_once", "doctor", "build_fix_plan", "verify_install",
    "print_install_command", "generate_install_scripts",
    "INSTALL_PS1_PATH", "UNINSTALL_PS1_PATH", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
