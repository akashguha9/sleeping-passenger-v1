"""Root-level pytest bootstrap.

Two jobs, both idempotent:

1. Guarantee the directories pytest uses for --basetemp and cache_dir
   (configured in pytest.ini as logs/.pytest_tmp and logs/.pytest_cache)
   exist before pytest tries to open them. On a fresh Windows clone,
   logs/ is gitignored so it doesn't exist, and pytest raises
   FileNotFoundError when --basetemp is resolved.

2. Guarantee logs/system_snapshots.jsonl exists with at least the
   committed seed rows, so tests that read the pipeline's snapshot
   memory (notably the health-report scorecard, which scores
   self_correction_maturity based on snapshot_count >= 2) produce
   deterministic numbers across platforms. If the file already exists
   with content, it is left untouched — appended runtime rows are fine
   and the seed rows at the top remain valid chronology data.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent

for _subdir in ("logs", "logs/.pytest_tmp", "logs/.pytest_cache"):
    (_REPO_ROOT / _subdir).mkdir(parents=True, exist_ok=True)

_SEED = _REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"
_LIVE = _REPO_ROOT / "logs" / "system_snapshots.jsonl"
if _SEED.exists() and (not _LIVE.exists() or _LIVE.stat().st_size == 0):
    _LIVE.write_bytes(_SEED.read_bytes())
