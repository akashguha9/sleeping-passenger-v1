"""
Tests for the operator-visible CLI added to
scripts/check_live_signal_refresh_task.py.

The PowerShell-shelling helper is injected via the existing
``powershell_runner`` kwarg on ``check_live_signal_refresh_task`` so the
CLI runs cross-platform inside CI.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from contextlib import redirect_stdout

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def _registered_task_runner(monkeypatch):
    """Pretend Windows reports the task as installed and last-ran cleanly."""
    payload = json.dumps(
        {
            "State": "Ready",
            "LastRunTime": "2026-05-25T10:34:54Z",
            "NextRunTime": "2026-05-25T16:00:00Z",
            "LastTaskResult": 0,
        }
    )

    def _runner(args, timeout=10.0):
        return 0, payload, ""

    import scripts.check_live_signal_refresh_task as mod
    monkeypatch.setattr(mod, "_run_powershell", _runner)
    # platform.system returns "Windows" so the CLI doesn't short-circuit.
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    return mod


@pytest.fixture
def _missing_task_runner(monkeypatch):
    payload = json.dumps({"NotFound": True, "Error": "task not registered"})

    def _runner(args, timeout=10.0):
        return 0, payload, ""

    import scripts.check_live_signal_refresh_task as mod
    monkeypatch.setattr(mod, "_run_powershell", _runner)
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    return mod


@pytest.fixture
def _failing_task_runner(monkeypatch):
    payload = json.dumps(
        {
            "State": "Ready",
            "LastRunTime": "2026-05-25T04:34:54Z",
            "NextRunTime": "2026-05-25T10:00:00Z",
            "LastTaskResult": 1,
        }
    )

    def _runner(args, timeout=10.0):
        return 0, payload, ""

    import scripts.check_live_signal_refresh_task as mod
    monkeypatch.setattr(mod, "_run_powershell", _runner)
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    return mod


def test_cli_text_when_task_exists(_registered_task_runner) -> None:
    mod = _registered_task_runner
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod._cli([])
    out = buf.getvalue()
    assert rc == 0
    assert "Scheduled Task Diagnostic" in out
    assert "SleepingPassengerLiveSignalRefresh" in out
    assert "PASS" in out


def test_cli_json_when_task_exists(_registered_task_runner) -> None:
    mod = _registered_task_runner
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod._cli(["--json"])
    payload = json.loads(buf.getvalue())
    assert rc == 0
    assert payload["installed"] is True
    assert payload["status"] == "PASS"
    assert payload["advisory_only"] is True
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0


def test_cli_exits_nonzero_when_task_missing(_missing_task_runner) -> None:
    mod = _missing_task_runner
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod._cli([])
    out = buf.getvalue()
    assert rc == 1
    assert "NOT_INSTALLED" in out


def test_cli_warns_but_zero_when_last_task_result_nonzero_but_installed(_failing_task_runner) -> None:
    mod = _failing_task_runner
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod._cli([])
    out = buf.getvalue()
    assert "FAILING" in out
    # FAILING is a warning but the task is still installed; spec says exit
    # nonzero only for missing/broken-config.
    assert rc == 0


def test_cli_quiet_mode(_registered_task_runner) -> None:
    mod = _registered_task_runner
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod._cli(["--quiet"])
    out = buf.getvalue().strip()
    assert rc == 0
    assert "task=" in out
    assert "status=" in out
    assert "installed=" in out


def test_cli_respects_task_name_arg(_registered_task_runner) -> None:
    mod = _registered_task_runner
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod._cli(["--task-name", "SomeOtherTask", "--json"])
    payload = json.loads(buf.getvalue())
    assert rc == 0
    assert payload["task_name"] == "SomeOtherTask"
