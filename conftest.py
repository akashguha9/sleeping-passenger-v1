"""Root-level pytest bootstrap.

Two jobs, both idempotent:

1. Guarantee logs/system_snapshots.jsonl exists with at least the committed
   seed rows, so snapshot-memory tests produce deterministic numbers across
   platforms. If the live file already exists with content, it is left
   untouched.

2. Provide a Windows-safe scratch fixture rooted under
   ``~/.codex/memories/pipeline_pytest_scratch`` so tests that need temporary
   files do not depend on pytest's tmp_path cleanup behavior on this checkout.
"""
from __future__ import annotations

import shutil
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


@pytest.fixture
def scratch_path():
    path = _SCRATCH_ROOT / f"codex-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
