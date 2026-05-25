"""
Scheduler-status diagnostic for the 6-hour live-signal refresh.

Reports whether the Windows Scheduled Task that drives
``scripts/refresh_live_signals.py --write`` is installed, enabled,
failing, or absent.  Used by the API at ``/live-sources/auto-refresh``
to power the Live Signals "Auto-refresh" panel.

Pure read-only.  Never registers, modifies, or deletes a scheduled
task — the operator runs the PowerShell registration script
manually.  Never calls a broker; never increments
``ai_execution_count``.  Safe to run on non-Windows machines (returns
``status = UNSUPPORTED_PLATFORM`` with a clear suggestion).
"""
from __future__ import annotations

import datetime as _dt
import json
import platform
import shutil
import subprocess
from typing import Any


DEFAULT_TASK_NAME: str = "SleepingPassengerLiveSignalRefresh"
DEFAULT_CADENCE_HOURS: int = 6

# Stable status enum the frontend pattern-matches.
STATUS_PASS = "PASS"
STATUS_NOT_INSTALLED = "NOT_INSTALLED"
STATUS_DISABLED = "DISABLED"
STATUS_FAILING = "FAILING"
STATUS_STALE = "STALE"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_UNSUPPORTED = "UNSUPPORTED_PLATFORM"

_REGISTER_PS_PATH = (
    ".\\scripts\\windows\\register_live_signal_refresh_task.ps1"
)
_MANUAL_REFRESH_CMD = "python scripts/refresh_live_signals.py --write"


def _safety_stamps() -> dict[str, Any]:
    return {
        "advisory_only": True,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
    }


def _empty_payload(
    *,
    task_name: str,
    status: str,
    reason: str,
    suggested_command: str | None = None,
) -> dict[str, Any]:
    return {
        "task_name": task_name,
        "installed": False,
        "enabled": False,
        "cadence_hours": DEFAULT_CADENCE_HOURS,
        "last_run_time": None,
        "next_run_time": None,
        "last_task_result": None,
        "last_successful_refresh_utc": None,
        "last_attempted_refresh_utc": None,
        "stale_sources": [],
        "stale_threshold_hours": DEFAULT_CADENCE_HOURS,
        "status": status,
        "status_reason": reason,
        "suggested_command": suggested_command,
        "manual_refresh_command": _MANUAL_REFRESH_CMD,
        **_safety_stamps(),
    }


def _run_powershell(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Invoke powershell.exe and return (returncode, stdout, stderr).

    Returns rc=-1 on any error so callers can branch on "could not query".
    """
    exe = shutil.which("powershell.exe") or shutil.which("pwsh")
    if exe is None:
        return -1, "", "powershell not found on PATH"
    try:
        result = subprocess.run(  # noqa: S603 - trusted command, no shell
            [exe, "-NoProfile", "-NonInteractive", "-Command", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except Exception as exc:  # pragma: no cover - defensive
        return -1, "", f"{type(exc).__name__}: {exc}"


def _parse_task_info(raw: str) -> dict[str, Any] | None:
    """Parse the JSON output of a Get-ScheduledTask | Get-ScheduledTaskInfo
    pipeline.  Returns None on parse failure."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def check_live_signal_refresh_task(
    *,
    task_name: str = DEFAULT_TASK_NAME,
    cadence_hours: int = DEFAULT_CADENCE_HOURS,
    powershell_runner=None,
) -> dict[str, Any]:
    """Best-effort scheduler-status probe.

    ``powershell_runner`` lets tests inject a fake PowerShell — when
    omitted we shell out to ``powershell.exe``.  Never raises.
    """
    runner = powershell_runner or _run_powershell

    if platform.system() != "Windows" and powershell_runner is None:
        return _empty_payload(
            task_name=task_name,
            status=STATUS_UNSUPPORTED,
            reason=(
                f"scheduler probe only implemented for Windows; "
                f"platform={platform.system()}"
            ),
            suggested_command=_MANUAL_REFRESH_CMD,
        )

    ps_script = (
        f"try {{ "
        f"  $t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction Stop; "
        f"  $info = $t | Get-ScheduledTaskInfo; "
        f"  $payload = @{{ "
        f"    State = [string]$t.State; "
        f"    LastRunTime = if ($info.LastRunTime) {{ $info.LastRunTime.ToUniversalTime().ToString('o') }} else {{ $null }}; "
        f"    NextRunTime = if ($info.NextRunTime) {{ $info.NextRunTime.ToUniversalTime().ToString('o') }} else {{ $null }}; "
        f"    LastTaskResult = $info.LastTaskResult "
        f"  }}; "
        f"  $payload | ConvertTo-Json -Compress "
        f"}} catch {{ "
        f"  ConvertTo-Json @{{ NotFound = $true; Error = $_.Exception.Message }} -Compress "
        f"}}"
    )

    rc, stdout, stderr = runner([ps_script])
    if rc == -1:
        return _empty_payload(
            task_name=task_name,
            status=STATUS_UNKNOWN,
            reason=f"could not invoke powershell: {stderr.strip() or 'unknown error'}",
            suggested_command=_MANUAL_REFRESH_CMD,
        )

    info = _parse_task_info(stdout) or {}
    if info.get("NotFound") or (not info and rc != 0):
        return _empty_payload(
            task_name=task_name,
            status=STATUS_NOT_INSTALLED,
            reason=(
                f"Scheduled task '{task_name}' is not registered. "
                "Run the one-time PowerShell registration script."
            ),
            suggested_command=(
                f"powershell -ExecutionPolicy Bypass -File {_REGISTER_PS_PATH}"
            ),
        )

    state = str(info.get("State") or "Unknown")
    last_run_time = info.get("LastRunTime")
    next_run_time = info.get("NextRunTime")
    last_task_result = info.get("LastTaskResult")

    enabled = state.lower() in {"ready", "running", "queued"}

    if state.lower() == "disabled":
        status = STATUS_DISABLED
        reason = f"Scheduled task '{task_name}' is currently disabled."
        suggested = (
            f"Enable-ScheduledTask -TaskName {task_name}"
        )
    elif isinstance(last_task_result, int) and last_task_result not in (0, 267009):
        # 267009 == "task is currently running" — not a failure.
        status = STATUS_FAILING
        reason = (
            f"Last task result {last_task_result} (non-zero exit). "
            "Investigate the wrapper log."
        )
        suggested = (
            "powershell -ExecutionPolicy Bypass -File "
            f"{_REGISTER_PS_PATH} -Force"
        )
    else:
        status = STATUS_PASS
        reason = "Scheduled task is registered and last ran cleanly."
        suggested = None

    return {
        "task_name": task_name,
        "installed": True,
        "enabled": enabled,
        "cadence_hours": cadence_hours,
        "last_run_time": last_run_time,
        "next_run_time": next_run_time,
        "last_task_result": last_task_result,
        "last_successful_refresh_utc": None,
        "last_attempted_refresh_utc": last_run_time,
        "stale_sources": [],
        "stale_threshold_hours": cadence_hours,
        "status": status,
        "status_reason": reason,
        "suggested_command": suggested,
        "manual_refresh_command": _MANUAL_REFRESH_CMD,
        **_safety_stamps(),
    }


__all__ = [
    "DEFAULT_TASK_NAME",
    "DEFAULT_CADENCE_HOURS",
    "STATUS_PASS",
    "STATUS_NOT_INSTALLED",
    "STATUS_DISABLED",
    "STATUS_FAILING",
    "STATUS_STALE",
    "STATUS_UNKNOWN",
    "STATUS_UNSUPPORTED",
    "check_live_signal_refresh_task",
]


# ---------------------------------------------------------------------------
# Operator-visible CLI
# ---------------------------------------------------------------------------
#
# Adds a ``__main__`` block so ``python scripts/check_live_signal_refresh_task.py``
# prints a diagnostic table from PowerShell instead of exiting silently.
# Read-only — never registers/modifies/deletes a task.


def _format_task_diagnostic(payload: dict[str, Any]) -> str:
    import datetime as _dt
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Sleeping Passenger — Scheduled Task Diagnostic")
    lines.append("=" * 72)
    lines.append(f"generated_at_utc: {_dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')}")
    lines.append(
        f"advisory_only={payload.get('advisory_only')}  "
        f"execution_gate={payload.get('execution_gate')}  "
        f"broker_api_called={payload.get('broker_api_called')}  "
        f"ai_execution_count={payload.get('ai_execution_count')}"
    )
    lines.append("")
    lines.append(f"task_name:               {payload.get('task_name')}")
    lines.append(f"installed:               {payload.get('installed')}")
    lines.append(f"enabled:                 {payload.get('enabled')}")
    lines.append(f"status:                  {payload.get('status')}")
    lines.append(f"status_reason:           {payload.get('status_reason')}")
    lines.append(f"last_run_time:           {payload.get('last_run_time')}")
    lines.append(f"next_run_time:           {payload.get('next_run_time')}")
    ltr = payload.get("last_task_result")
    if isinstance(ltr, int):
        interp = "clean last run" if ltr == 0 else ("currently running" if ltr == 267009 else "prior nonzero/failed run")
        lines.append(f"last_task_result:        {ltr} ({interp})")
    else:
        lines.append(f"last_task_result:        {ltr}")
    lines.append(f"cadence_hours:           {payload.get('cadence_hours')}")
    lines.append(f"suggested_command:       {payload.get('suggested_command') or '-'}")
    lines.append(f"manual_refresh_command:  {payload.get('manual_refresh_command')}")

    wrapper_rel = "scripts/windows/run_live_signal_refresh_once.ps1"
    wrapper_abs = repo / "scripts" / "windows" / "run_live_signal_refresh_once.ps1"
    log = repo / "logs" / "live_signal_refresh.log"
    summary = repo / "logs" / "live_signal_refresh_summary.json"
    lines.append("")
    lines.append("Local artefacts:")
    lines.append(f"  wrapper_expected:     {wrapper_rel} (exists={wrapper_abs.exists()})")
    lines.append(f"  refresh_log:          {log} (exists={log.exists()})")
    lines.append(f"  refresh_summary_json: {summary} (exists={summary.exists()})")
    return "\n".join(lines)


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Print scheduled-task status for the 6-hour live refresh. "
            "Read-only diagnostic — never registers, modifies, or deletes "
            "a task. ADVISORY_ONLY."
        ),
    )
    parser.add_argument(
        "--task-name",
        default=DEFAULT_TASK_NAME,
        help=f"Scheduled task name. Default: {DEFAULT_TASK_NAME}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-line detail; print a single-line summary.",
    )
    args = parser.parse_args(argv)

    payload = check_live_signal_refresh_task(task_name=str(args.task_name))
    status = str(payload.get("status") or "")

    if args.json:
        sys.stdout.write(_json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    elif args.quiet:
        sys.stdout.write(
            f"task={payload.get('task_name')} status={status} "
            f"installed={payload.get('installed')} enabled={payload.get('enabled')} "
            f"last_run={payload.get('last_run_time')}\n"
        )
    else:
        sys.stdout.write(_format_task_diagnostic(payload) + "\n")

    # Exit-code rule per the watchdog spec: nonzero only when the task is
    # missing or broken in a way the operator must fix.  A prior FAILING
    # run with a now-valid registration is a warning, not a hard failure.
    if status in {STATUS_NOT_INSTALLED, STATUS_UNKNOWN, STATUS_DISABLED}:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via test_live_signal_refresh_task_cli
    raise SystemExit(_cli())
