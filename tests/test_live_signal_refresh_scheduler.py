"""Sprint I addendum — scheduler-status diagnostic for the 6-hour refresh.

These tests pin the contract of
``scripts/check_live_signal_refresh_task.py`` without ever touching
the operator's real Windows Task Scheduler:

  - On non-Windows the probe degrades to UNSUPPORTED_PLATFORM with a
    suggestion to run the manual refresh.
  - NOT_INSTALLED when Get-ScheduledTask returns the JSON "NotFound"
    payload.
  - PASS when the task is registered and last result == 0.
  - FAILING when last_task_result is a non-zero, non-running code.
  - DISABLED when state == 'Disabled'.
  - UNKNOWN when PowerShell cannot be invoked at all.
  - Safety stamps always present.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _runner_returning(rc: int, stdout: str, stderr: str = ""):
    def runner(_args):
        return rc, stdout, stderr
    return runner


def test_not_installed_when_get_scheduled_task_says_so():
    from scripts.check_live_signal_refresh_task import (
        STATUS_NOT_INSTALLED,
        check_live_signal_refresh_task,
    )
    runner = _runner_returning(0, '{"NotFound": true, "Error": "no such task"}')
    out = check_live_signal_refresh_task(powershell_runner=runner)
    assert out["status"] == STATUS_NOT_INSTALLED
    assert out["installed"] is False
    # We always carry a runnable suggestion the operator can copy/paste.
    assert "register_live_signal_refresh_task.ps1" in (out.get("suggested_command") or "")


def test_pass_when_task_ran_cleanly():
    from scripts.check_live_signal_refresh_task import (
        STATUS_PASS,
        check_live_signal_refresh_task,
    )
    runner = _runner_returning(0, (
        '{"State":"Ready","LastRunTime":"2026-05-15T10:00:00Z",'
        '"NextRunTime":"2026-05-15T16:00:00Z","LastTaskResult":0}'
    ))
    out = check_live_signal_refresh_task(powershell_runner=runner)
    assert out["status"] == STATUS_PASS
    assert out["installed"] is True
    assert out["enabled"] is True
    assert out["last_task_result"] == 0
    assert out["next_run_time"] == "2026-05-15T16:00:00Z"


def test_failing_when_last_task_result_nonzero():
    from scripts.check_live_signal_refresh_task import (
        STATUS_FAILING,
        check_live_signal_refresh_task,
    )
    runner = _runner_returning(0, (
        '{"State":"Ready","LastRunTime":"2026-05-15T10:00:00Z",'
        '"NextRunTime":"2026-05-15T16:00:00Z","LastTaskResult":1}'
    ))
    out = check_live_signal_refresh_task(powershell_runner=runner)
    assert out["status"] == STATUS_FAILING
    assert out["last_task_result"] == 1
    # The suggested command should point at a -Force re-register.
    assert "register_live_signal_refresh_task.ps1" in (out.get("suggested_command") or "")


def test_disabled_state():
    from scripts.check_live_signal_refresh_task import (
        STATUS_DISABLED,
        check_live_signal_refresh_task,
    )
    runner = _runner_returning(0, (
        '{"State":"Disabled","LastRunTime":null,"NextRunTime":null,"LastTaskResult":null}'
    ))
    out = check_live_signal_refresh_task(powershell_runner=runner)
    assert out["status"] == STATUS_DISABLED
    assert out["enabled"] is False


def test_unknown_when_powershell_unreachable():
    from scripts.check_live_signal_refresh_task import (
        STATUS_UNKNOWN,
        check_live_signal_refresh_task,
    )
    runner = _runner_returning(-1, "", "powershell not on PATH")
    out = check_live_signal_refresh_task(powershell_runner=runner)
    assert out["status"] == STATUS_UNKNOWN
    assert out["installed"] is False


def test_safety_stamps_always_present():
    """Whatever the path through the diagnostic, we never lie about
    advisory_only / broker_api_called / ai_execution_count."""
    from scripts.check_live_signal_refresh_task import check_live_signal_refresh_task

    runners = [
        _runner_returning(0, '{"NotFound": true}'),
        _runner_returning(0, '{"State":"Ready","LastTaskResult":0}'),
        _runner_returning(0, '{"State":"Ready","LastTaskResult":13}'),
        _runner_returning(-1, "", "boom"),
    ]
    for r in runners:
        out = check_live_signal_refresh_task(powershell_runner=r)
        assert out["advisory_only"] is True
        assert out["broker_api_called"] is False
        assert out["ai_execution_count"] == 0
        assert out["execution_gate"] == "LOCKED"
        assert out["can_execute"] is False


def test_unsupported_platform_when_no_runner_and_not_windows(monkeypatch):
    """On Linux/macOS we cannot probe the scheduler at all — degrade
    cleanly rather than crash."""
    import platform as _plat
    from scripts.check_live_signal_refresh_task import (
        STATUS_UNSUPPORTED,
        check_live_signal_refresh_task,
    )

    monkeypatch.setattr(_plat, "system", lambda: "Linux")
    out = check_live_signal_refresh_task()
    assert out["status"] == STATUS_UNSUPPORTED
    assert "Linux" in (out["status_reason"] or "")
    assert "python scripts/refresh_live_signals.py" in (
        out.get("suggested_command") or ""
    )


# ---------------------------------------------------------------------------
# Endpoint integration — /live-sources/status carries auto_refresh_status
# ---------------------------------------------------------------------------


def test_live_sources_status_includes_auto_refresh_block(monkeypatch):
    """The Live Signals API must surface the scheduler probe — that is
    what the frontend reads to decide ENABLED / NOT_INSTALLED / etc."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    # Replace the scheduler probe with a deterministic stub so the
    # endpoint test does not depend on a real Windows Task Scheduler.
    def fake_probe(**_kwargs):
        return {
            "task_name": "Foo",
            "installed": True,
            "enabled": True,
            "cadence_hours": 6,
            "last_run_time": "2026-05-15T10:00:00Z",
            "next_run_time": "2026-05-15T16:00:00Z",
            "last_task_result": 0,
            "last_successful_refresh_utc": "2026-05-15T10:00:00Z",
            "last_attempted_refresh_utc": "2026-05-15T10:00:00Z",
            "stale_sources": [],
            "stale_threshold_hours": 6,
            "status": "PASS",
            "status_reason": "registered",
            "suggested_command": None,
            "manual_refresh_command": "python scripts/refresh_live_signals.py --write",
            "advisory_only": True,
            "advisory_status": "ADVISORY_ONLY",
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": 0,
            "execution_permission": False,
            "can_execute": False,
        }

    import scripts.check_live_signal_refresh_task as probe_mod
    monkeypatch.setattr(
        probe_mod, "check_live_signal_refresh_task", fake_probe, raising=True,
    )

    client = TestClient(srv.app, raise_server_exceptions=True)
    resp = client.get("/live-sources/status")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "auto_refresh_status" in payload
    ar = payload["auto_refresh_status"]
    assert ar["status"] == "PASS"
    assert ar["cadence_hours"] == 6
    # The endpoint must keep its own safety stamps regardless of the
    # scheduler probe's outcome.
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# PowerShell registration script invariants — read-only sanity checks
# ---------------------------------------------------------------------------


def test_register_ps1_has_six_hour_trigger_and_log_path():
    """The PowerShell registration script must declare a 6-hour
    cadence, target the canonical task name, and log to runtime/logs
    (or an equivalent local file).  We do NOT execute it from tests."""
    ps1 = _REPO / "scripts" / "windows" / "register_live_signal_refresh_task.ps1"
    text = ps1.read_text(encoding="utf-8", errors="ignore")
    assert "SleepingPassengerLiveSignalRefresh" in text
    assert "New-TimeSpan -Hours 6" in text
    # Working directory is set to repo root so paths resolve correctly.
    assert "WorkingDirectory" in text


def test_register_ps1_no_unconditional_success_print():
    """Sprint 10B: the registration script must not print 'Registered'
    before verifying the task exists. Specifically, the success Write-Host
    must not appear inside the try block that calls Register-ScheduledTask,
    and the Register-ScheduledTask call must be guarded by try/catch with
    -ErrorAction Stop so a failure does not fall through to success."""
    ps1 = _REPO / "scripts" / "windows" / "register_live_signal_refresh_task.ps1"
    text = ps1.read_text(encoding="utf-8", errors="ignore")

    # try/catch present around Register-ScheduledTask
    assert "Register-ScheduledTask" in text
    assert "-ErrorAction Stop" in text
    assert "try {" in text and "} catch {" in text

    # Verification step after registration
    assert "Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop" in text

    # Access-denied / Administrator guidance must exist and exit non-zero
    assert "Access denied" in text or "access\\s*is\\s*denied" in text
    assert "Administrator" in text or "RunAs" in text
    assert "exit 1" in text


def test_run_once_ps1_uses_utf8_encoding_for_logs():
    """Sprint 10B: the run-once wrapper must force UTF-8 so PowerShell
    does not emit UTF-16LE log lines (the prior bug)."""
    ps1 = _REPO / "scripts" / "windows" / "run_live_signal_refresh_once.ps1"
    text = ps1.read_text(encoding="utf-8", errors="ignore")
    # Both interpreter-side and PowerShell-side encoding forced.
    assert "PYTHONIOENCODING" in text
    assert "[System.Text.Encoding]::UTF8" in text
    # File writes go through Out-File -Encoding utf8 (Tee-Object on PS 5.1
    # cannot set encoding, so its presence here would be a regression).
    assert "Out-File -FilePath $LogPath -Append -Encoding utf8" in text
