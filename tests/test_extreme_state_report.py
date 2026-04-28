from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_run_extreme_state_report_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_extreme_state_report.py"), "--summary", "--no-write"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout
    assert "Extreme State Report" in output
    assert "extreme_state=" in output
    assert "signals_evaluated=" in output
    assert "Recommended Action=" in output
