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
