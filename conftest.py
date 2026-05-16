"""Root-level pytest bootstrap.

Three jobs, all idempotent:

1. Guarantee logs/system_snapshots.jsonl exists with at least the committed
   seed rows, so snapshot-memory tests produce deterministic numbers across
   platforms. If the live file already exists with content, it is left
   untouched.

2. Provide a Windows-safe scratch fixture rooted under
   ``~/.codex/memories/pipeline_pytest_scratch`` so tests that need temporary
   files do not depend on pytest's tmp_path cleanup behavior on this checkout.

3. Redirect the live-refresh summary path to a per-session tmp file for
   the entire pytest run.  Without this, any test that calls
   ``refresh_live_signals.run_refresh`` (directly or indirectly) would
   clobber the operator's real ``logs/live_signal_refresh_summary.json``,
   destroying observability across the next live refresh.  Tests can
   still monkeypatch the env var or pass ``summary_path=...`` explicitly.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent
_SCRATCH_ROOT = Path.home() / ".codex" / "memories" / "pipeline_pytest_scratch"

(_REPO_ROOT / "logs").mkdir(parents=True, exist_ok=True)
_SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

_SEED = _REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"
_LIVE = _REPO_ROOT / "logs" / "system_snapshots.jsonl"
if _SEED.exists() and (not _LIVE.exists() or _LIVE.stat().st_size == 0):
    _LIVE.write_bytes(_SEED.read_bytes())


# Session-wide isolation for the live-refresh summary file.  This runs at
# import time (before any test), so even tests that forget to monkeypatch
# the path cannot corrupt the operator's real summary file.  The chosen
# path lives under the platform temp dir and is wiped at process exit.
_REFRESH_SUMMARY_TMP_DIR = Path(tempfile.mkdtemp(prefix="mvp-refresh-summary-"))
_REFRESH_SUMMARY_TMP_PATH = (
    _REFRESH_SUMMARY_TMP_DIR / "live_signal_refresh_summary.json"
)
os.environ.setdefault(
    "MVP_LIVE_REFRESH_SUMMARY_PATH", str(_REFRESH_SUMMARY_TMP_PATH)
)


@pytest.fixture
def scratch_path():
    path = _SCRATCH_ROOT / f"codex-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def refresh_summary_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tests that explicitly want a per-test summary path use this fixture.

    The conftest already redirects the session-wide default to a temp
    dir; this fixture narrows that further to a per-test file so the
    test can assert on its own writes without interference from other
    tests that ran in the same session.
    """
    path = tmp_path / "live_signal_refresh_summary.json"
    monkeypatch.setenv("MVP_LIVE_REFRESH_SUMMARY_PATH", str(path))
    return path
