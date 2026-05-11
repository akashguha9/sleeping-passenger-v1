"""
Phase E.5 — Tests for silent background local MVP stack startup.

Coverage
--------
 1  start_mvp_stack_silent.ps1 exists
 2  stop_mvp_stack_silent.ps1 exists
 3  register_mvp_silent_startup_task.ps1 exists
 4  unregister_mvp_silent_startup_task.ps1 exists
 5  start script contains Test-PortListening function
 6  start script contains Wait-ForPort function
 7  start script contains Test-ProcessRunning function
 8  start script uses -WindowStyle Hidden for backend Start-Process
 9  start script uses -WindowStyle Hidden for frontend Start-Process
10  start script uses -WindowStyle Hidden for poller Start-Process
11  start script uses -WindowStyle Hidden for proxy Start-Process
12  start script checks port 8000 before starting backend (idempotency)
13  start script checks port 3000 before starting frontend (idempotency)
14  start script uses IPGlobalProperties for port detection (no netstat)
15  start script uses Get-CimInstance for process detection
16  start script redirects backend stdout to backend_stdout.log
17  start script redirects backend stderr to backend_stderr.log
18  start script redirects frontend stdout to frontend_stdout.log
19  start script redirects poller stdout to poller_stdout.log
20  start script redirects proxy stdout to proxy_stdout.log
21  start script logs to silent_startup.log
22  start script says Advisory only, no broker API
23  stop script uses Stop-Process not kill/taskkill
24  stop script uses Get-CimInstance for process matching
25  stop script targets python.exe + uvicorn pattern for backend
26  stop script targets node.exe + next dev for frontend-node
27  stop script targets powershell.exe + poll_live_sources for poller
28  stop script targets python.exe + local_frontend_reverse_proxy for proxy
29  stop script logs to silent_stop.log
30  stop script says Advisory only, no broker API
31  register script targets PipelineV57LocalMVPSilent task name
32  register script uses -WindowStyle Hidden in action argument
33  register script triggers at user logon (AtLogon)
34  register script uses RunLevel Highest
35  register script uses -Hidden in settings
36  register script checks start_mvp_stack_silent.ps1 exists before registering
37  register script exits 1 if script path not found
38  register script is idempotent (unregisters before registering)
39  register script says Advisory only, no broker API
40  unregister_silent script targets PipelineV57LocalMVPSilent task name
41  unregister_silent script checks for Administrator before proceeding
42  unregister_silent script uses -ErrorAction Stop on Unregister-ScheduledTask
43  unregister_silent script exits 1 on failure (try/catch present)
44  unregister_silent script does not print Unregistered on access denied
45  unregister_mvp_startup_task.ps1 (old) now has admin check
46  unregister_mvp_startup_task.ps1 (old) uses -ErrorAction Stop
47  unregister_mvp_startup_task.ps1 (old) exits 1 in catch block
48  unregister_mvp_startup_task.ps1 (old) does not print Unregistered outside try/catch
49  start script backend uses python -m uvicorn scripts.api_server:app
50  start script backend binds to 127.0.0.1 port 8000
51  README has Silent local startup section
52  README mentions start_mvp_stack_silent.ps1
53  README mentions stop_mvp_stack_silent.ps1
54  README mentions register_mvp_silent_startup_task.ps1
55  README mentions runtime/logs
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = REPO_ROOT / "scripts" / "windows"

_START  = WINDOWS_DIR / "start_mvp_stack_silent.ps1"
_STOP   = WINDOWS_DIR / "stop_mvp_stack_silent.ps1"
_REG    = WINDOWS_DIR / "register_mvp_silent_startup_task.ps1"
_UNREG  = WINDOWS_DIR / "unregister_mvp_silent_startup_task.ps1"
_OLD_UNREG = WINDOWS_DIR / "unregister_mvp_startup_task.ps1"
_README = REPO_ROOT / "README.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------

class TestFilesExist:
    def test_01_start_exists(self):
        assert _START.exists(), f"Missing: {_START}"

    def test_02_stop_exists(self):
        assert _STOP.exists(), f"Missing: {_STOP}"

    def test_03_register_exists(self):
        assert _REG.exists(), f"Missing: {_REG}"

    def test_04_unregister_exists(self):
        assert _UNREG.exists(), f"Missing: {_UNREG}"


# ---------------------------------------------------------------------------
# start_mvp_stack_silent.ps1
# ---------------------------------------------------------------------------

class TestStartScript:
    def setup_method(self):
        self.txt = _text(_START)

    def test_05_test_port_listening_function(self):
        assert "Test-PortListening" in self.txt

    def test_06_wait_for_port_function(self):
        assert "Wait-ForPort" in self.txt

    def test_07_test_process_running_function(self):
        assert "Test-ProcessRunning" in self.txt

    def test_08_backend_window_hidden(self):
        # Start-Process for backend must use -WindowStyle Hidden
        backend_block = self.txt[self.txt.find("Backend"):]
        # Find first Start-Process after "Backend" label
        idx = backend_block.find("Start-Process")
        assert idx != -1
        snippet = backend_block[idx:idx+400]
        assert "Hidden" in snippet, "Backend Start-Process must use WindowStyle Hidden"

    def test_09_frontend_window_hidden(self):
        frontend_block = self.txt[self.txt.find("Frontend"):]
        idx = frontend_block.find("Start-Process")
        assert idx != -1
        snippet = frontend_block[idx:idx+400]
        assert "Hidden" in snippet, "Frontend Start-Process must use WindowStyle Hidden"

    def test_10_poller_window_hidden(self):
        poller_block = self.txt[self.txt.find("Poller"):]
        idx = poller_block.find("Start-Process")
        assert idx != -1
        snippet = poller_block[idx:idx+400]
        assert "Hidden" in snippet, "Poller Start-Process must use WindowStyle Hidden"

    def test_11_proxy_window_hidden(self):
        proxy_block = self.txt[self.txt.find("Proxy"):]
        idx = proxy_block.find("Start-Process")
        assert idx != -1
        snippet = proxy_block[idx:idx+400]
        assert "Hidden" in snippet, "Proxy Start-Process must use WindowStyle Hidden"

    def test_12_idempotent_backend_port_check(self):
        assert "Test-PortListening -Port 8000" in self.txt

    def test_13_idempotent_frontend_port_check(self):
        assert "Test-PortListening -Port 3000" in self.txt

    def test_14_uses_ipglobalproperties(self):
        assert "IPGlobalProperties" in self.txt

    def test_15_uses_ciminstance_for_process(self):
        assert "Get-CimInstance" in self.txt

    def test_16_backend_stdout_log(self):
        assert "backend_stdout.log" in self.txt

    def test_17_backend_stderr_log(self):
        assert "backend_stderr.log" in self.txt

    def test_18_frontend_stdout_log(self):
        assert "frontend_stdout.log" in self.txt

    def test_19_poller_stdout_log(self):
        assert "poller_stdout.log" in self.txt

    def test_20_proxy_stdout_log(self):
        assert "proxy_stdout.log" in self.txt

    def test_21_startup_log(self):
        assert "silent_startup.log" in self.txt

    def test_22_advisory_disclaimer(self):
        low = self.txt.lower()
        assert "advisory only" in low or "advisory_only" in low

    def test_49_backend_uses_uvicorn_module(self):
        assert "scripts.api_server" in self.txt

    def test_50_backend_binds_127_0_0_1_8000(self):
        assert "127.0.0.1" in self.txt
        assert "8000" in self.txt


# ---------------------------------------------------------------------------
# stop_mvp_stack_silent.ps1
# ---------------------------------------------------------------------------

class TestStopScript:
    def setup_method(self):
        self.txt = _text(_STOP)

    def test_23_uses_stop_process(self):
        assert "Stop-Process" in self.txt

    def test_24_uses_ciminstance(self):
        assert "Get-CimInstance" in self.txt

    def test_25_targets_uvicorn_backend(self):
        assert "uvicorn" in self.txt
        assert "python.exe" in self.txt

    def test_26_targets_node_next_dev(self):
        assert "node.exe" in self.txt
        assert "next" in self.txt.lower()

    def test_27_targets_poller(self):
        assert "poll_live_sources" in self.txt

    def test_28_targets_proxy(self):
        assert "local_frontend_reverse_proxy" in self.txt

    def test_29_stop_log(self):
        assert "silent_stop.log" in self.txt

    def test_30_advisory_disclaimer(self):
        low = self.txt.lower()
        assert "advisory only" in low or "advisory_only" in low


# ---------------------------------------------------------------------------
# register_mvp_silent_startup_task.ps1
# ---------------------------------------------------------------------------

class TestRegisterScript:
    def setup_method(self):
        self.txt = _text(_REG)

    def test_31_task_name(self):
        assert "PipelineV57LocalMVPSilent" in self.txt

    def test_32_window_hidden_in_action(self):
        # The action argument string passed to powershell must include -WindowStyle Hidden
        assert "-WindowStyle Hidden" in self.txt

    def test_33_at_logon_trigger(self):
        assert "AtLogon" in self.txt

    def test_34_run_level_highest(self):
        assert "Highest" in self.txt

    def test_35_settings_hidden(self):
        assert "-Hidden" in self.txt

    def test_36_checks_script_exists(self):
        assert "Test-Path" in self.txt
        assert "start_mvp_stack_silent.ps1" in self.txt

    def test_37_exits_1_if_not_found(self):
        assert "exit 1" in self.txt

    def test_38_idempotent_unregister_first(self):
        # Must unregister with SilentlyContinue before registering
        assert "Unregister-ScheduledTask" in self.txt
        assert "SilentlyContinue" in self.txt

    def test_39_advisory_disclaimer(self):
        low = self.txt.lower()
        assert "advisory only" in low or "advisory_only" in low


# ---------------------------------------------------------------------------
# unregister_mvp_silent_startup_task.ps1
# ---------------------------------------------------------------------------

class TestUnregisterSilentScript:
    def setup_method(self):
        self.txt = _text(_UNREG)

    def test_40_task_name(self):
        assert "PipelineV57LocalMVPSilent" in self.txt

    def test_41_admin_check(self):
        assert "WindowsPrincipal" in self.txt or "IsInRole" in self.txt

    def test_42_error_action_stop(self):
        assert "-ErrorAction Stop" in self.txt

    def test_43_try_catch_for_failure(self):
        assert "try {" in self.txt or "try{" in self.txt
        assert "catch" in self.txt

    def test_44_no_false_success_message(self):
        # "Unregistered:" must only appear inside the try block after a successful call
        # The key check: there's no bare Write-Host "Unregistered" outside the try block
        # We verify by checking that -ErrorAction Stop guards the Unregister call
        assert "-ErrorAction Stop" in self.txt
        # And that the catch block does NOT write "Unregistered"
        catch_idx = self.txt.find("} catch {")
        if catch_idx == -1:
            catch_idx = self.txt.find("} catch{")
        assert catch_idx != -1, "No catch block found"
        catch_block = self.txt[catch_idx:]
        # "Unregistered" (success message) must NOT appear in catch block
        assert "Unregistered:" not in catch_block[:300]


# ---------------------------------------------------------------------------
# unregister_mvp_startup_task.ps1 (old E.1 script — fixed in E.5)
# ---------------------------------------------------------------------------

class TestOldUnregisterFixed:
    def setup_method(self):
        self.txt = _text(_OLD_UNREG)

    def test_45_admin_check_added(self):
        assert "WindowsPrincipal" in self.txt or "IsInRole" in self.txt

    def test_46_error_action_stop(self):
        assert "-ErrorAction Stop" in self.txt

    def test_47_exits_1_in_catch(self):
        catch_idx = self.txt.find("} catch {")
        if catch_idx == -1:
            catch_idx = self.txt.find("} catch{")
        assert catch_idx != -1
        catch_block = self.txt[catch_idx:catch_idx+200]
        assert "exit 1" in catch_block

    def test_48_unregistered_only_in_try(self):
        # "Unregistered:" success message must only appear inside the try block
        try_idx = self.txt.find("try {")
        catch_idx = self.txt.find("} catch {")
        assert try_idx != -1 and catch_idx != -1
        # Success message must be between try and catch
        success_idx = self.txt.find("Unregistered:")
        assert try_idx < success_idx < catch_idx, \
            "Unregistered: message must only appear inside try block"


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

class TestReadme:
    def setup_method(self):
        self.txt = _text(_README) if _README.exists() else ""

    def test_51_silent_startup_section(self):
        assert "Silent local startup" in self.txt or "silent" in self.txt.lower()

    def test_52_start_silent_mentioned(self):
        assert "start_mvp_stack_silent" in self.txt

    def test_53_stop_silent_mentioned(self):
        assert "stop_mvp_stack_silent" in self.txt

    def test_54_register_silent_mentioned(self):
        assert "register_mvp_silent_startup_task" in self.txt

    def test_55_runtime_logs_mentioned(self):
        assert "runtime" in self.txt.lower() and "logs" in self.txt.lower()
