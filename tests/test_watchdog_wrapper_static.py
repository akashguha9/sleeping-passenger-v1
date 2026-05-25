"""
Static safety scan for the Windows wrapper at
``scripts/windows/run_refresh_watchdog_once.ps1``.

We cannot reliably exec PowerShell from cross-platform CI, so the
contract is pinned via source inspection:

  - Log rotation block present, parameterised, defaults documented.
  - Exit-code mapping covers rc=0, rc=2, rc=1, and an "unexpected" arm.
  - PASS_WITH_STALE_SOURCES string present so Task Scheduler logs
    show the distinction.
  - No execute/order/broker verbs sneaked into the wrapper.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WRAPPER = _REPO_ROOT / "scripts" / "windows" / "run_refresh_watchdog_once.ps1"


def _read():
    return _WRAPPER.read_text(encoding="utf-8")


def test_wrapper_file_exists():
    assert _WRAPPER.exists(), f"missing wrapper at {_WRAPPER}"


def test_log_rotation_params_present():
    src = _read()
    assert "[int]$LogMaxBytes" in src
    assert "[int]$LogBackupCount" in src
    # Default 5 MB and 5 backups documented in header AND in param defaults.
    assert "$LogMaxBytes = 5242880" in src
    assert "$LogBackupCount = 5" in src


def test_log_rotation_function_present():
    src = _read()
    assert "function Invoke-WatchdogLogRotation" in src
    # Rotation must compare size to threshold.
    assert "$size -lt $MaxBytes" in src
    # Must call the rotation helper before appending.
    assert (
        "Invoke-WatchdogLogRotation -ActivePath $LogPath" in src
    ), "rotation helper not invoked at top of script"


def test_exit_code_mapping_distinguishes_stale_unchanged():
    src = _read()
    # Three explicit arms: 0, 2, 1; plus a default else.
    assert re.search(r"if \(\$rc -eq 0\)", src)
    assert re.search(r"elseif \(\$rc -eq 2\)", src)
    assert re.search(r"elseif \(\$rc -eq 1\)", src)
    # PASS_WITH_STALE_SOURCES log+stdout line present.
    assert "PASS_WITH_STALE_SOURCES" in src
    # rc=2 path exits 0 (so Task Scheduler does not flag failure).
    rc2_block = src[src.index("elseif ($rc -eq 2)"):]
    rc2_block = rc2_block[: rc2_block.index("elseif ($rc -eq 1)")]
    assert "exit 0" in rc2_block, "rc=2 must map to wrapper exit 0"
    # rc=1 path must exit non-zero so real crashes are still flagged.
    rc1_block = src[src.index("elseif ($rc -eq 1)"):]
    assert "exit 1" in rc1_block


def test_wrapper_carries_advisory_only_safety_language():
    src = _read()
    lowered = src.lower()
    assert "advisory_only" in lowered or "advisory-only" in lowered
    assert "no broker contacted" in lowered or "no broker" in lowered
    # No execute/order/trade verbs introduced.
    for verb in ("place order", "execute trade", "submit order", "broker action"):
        assert verb not in lowered, f"forbidden verb in wrapper: {verb}"
