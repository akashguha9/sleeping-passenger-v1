"""H4: scheduled DB backups with retention, inside the API server process.

Sprint 1 left backups operator-initiated (plus the automatic pre-migration
snapshots).  This module adds a daily in-process schedule built on a plain
asyncio task — no new dependency — calling the existing
:func:`scripts.backup_db.perform_backup` native API.

Retention: keep the newest 7 DAILY scheduled backups (one per calendar
day) plus the newest 4 WEEKLY ones (one per ISO week, beyond the daily
window).  Pre-migration and operator-labelled backups are NEVER pruned —
retention only manages files this scheduler created (label
``scheduled``).

Enable/disable with ``MVP_SCHEDULED_BACKUPS_ENABLED`` (default: on, but
auto-disabled under pytest — mirrors the rate limiter's pattern — so the
test suite's hundreds of TestClient startups don't write backups).

Advisory invariants: backups are read-only copies; no broker call, no
execution permission, stamps carried on every result dict.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.backup_db import perform_backup
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from backup_db import perform_backup  # type: ignore[no-redef]

_logger = logging.getLogger("scripts.backup_scheduler")

SCHEDULED_LABEL = "scheduled"
BACKUP_INTERVAL_SECONDS = 24 * 60 * 60
KEEP_DAILY = 7
KEEP_WEEKLY = 4

# Matches the backup_db filename for scheduler-created files:
#   {stem}-{YYYYMMDD-HHMMSS}-scheduled.db
_SCHEDULED_RE = re.compile(
    r"^(?P<stem>.+)-(?P<stamp>\d{8}-\d{6})-" + SCHEDULED_LABEL + r"\.db$"
)


def scheduled_backups_enabled() -> bool:
    raw = os.environ.get("MVP_SCHEDULED_BACKUPS_ENABLED", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _parse_stamp(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def prune_backups(
    backup_dir: Path,
    *,
    keep_daily: int = KEEP_DAILY,
    keep_weekly: int = KEEP_WEEKLY,
) -> dict[str, Any]:
    """Apply daily+weekly retention to SCHEDULER-created backups only.

    Keeps the newest backup per calendar day for the most recent
    ``keep_daily`` days, plus the newest backup per ISO week for
    ``keep_weekly`` further weeks.  Everything else this scheduler created
    is deleted.  Files without the ``-scheduled.db`` suffix are untouched.
    """
    candidates: list[tuple[datetime, Path]] = []
    if backup_dir.exists():
        for f in backup_dir.iterdir():
            m = _SCHEDULED_RE.match(f.name)
            if not m:
                continue
            ts = _parse_stamp(m.group("stamp"))
            if ts is not None:
                candidates.append((ts, f))
    candidates.sort(reverse=True)  # newest first

    keep: set[Path] = set()
    # Pass 1 — daily window: newest backup per calendar day, newest
    # keep_daily distinct days.
    daily_days: list[str] = []
    for ts, f in candidates:
        day_key = ts.strftime("%Y%m%d")
        if day_key in daily_days:
            continue
        if len(daily_days) >= keep_daily:
            break
        daily_days.append(day_key)
        keep.add(f)
    # Pass 2 — weekly window: among the rest, newest backup per ISO week
    # for keep_weekly weeks not already represented by a daily keep.
    daily_weeks = {
        f"{ts.isocalendar().year}-W{ts.isocalendar().week:02d}"
        for ts, f in candidates
        if f in keep
    }
    weekly_kept: list[str] = []
    for ts, f in candidates:
        if f in keep:
            continue
        week_key = f"{ts.isocalendar().year}-W{ts.isocalendar().week:02d}"
        if week_key in daily_weeks or week_key in weekly_kept:
            continue
        if len(weekly_kept) >= keep_weekly:
            continue
        weekly_kept.append(week_key)
        keep.add(f)

    deleted: list[str] = []
    for ts, f in candidates:
        if f in keep:
            continue
        try:
            f.unlink()
            deleted.append(f.name)
        except OSError as exc:
            _logger.error("retention could not delete %s: %s", f, exc)
    return {
        "kept": sorted(p.name for p in keep),
        "deleted": deleted,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def run_scheduled_backup(
    db_path: Path, backup_dir: Path | None = None
) -> dict[str, Any]:
    """One backup + retention pass.  Fail-loud: errors are logged at ERROR
    and reported in the result, never swallowed."""
    target_dir = backup_dir if backup_dir is not None else db_path.parent / "backups"
    result = perform_backup(db_path, target_dir, label=SCHEDULED_LABEL)
    if not result.get("ok"):
        _logger.error("scheduled backup FAILED: %s", result.get("error"))
        result["retention"] = None
        return result
    retention = prune_backups(target_dir)
    result["retention"] = retention
    _logger.info(
        "scheduled backup ok: %s (kept %d, pruned %d)",
        result.get("backup_path"),
        len(retention["kept"]),
        len(retention["deleted"]),
    )
    return result


async def _backup_loop(db_path: Path) -> None:  # pragma: no cover - timing loop
    while True:
        try:
            run_scheduled_backup(db_path)
        except Exception:
            # Defensive: the loop must survive any one failure; the failure
            # itself was already logged at ERROR by run_scheduled_backup,
            # this catches unexpected faults (e.g. fs disappearing).
            _logger.exception("scheduled backup loop iteration failed")
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)


def start_backup_scheduler(db_path: Path) -> "asyncio.Task | None":
    """Start the daily loop on the running event loop (API server startup)."""
    if not scheduled_backups_enabled():
        _logger.info("scheduled backups disabled (env/pytest)")
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - no loop (sync caller)
        _logger.error("no running event loop; scheduled backups not started")
        return None
    task = loop.create_task(_backup_loop(db_path), name="mvp-backup-scheduler")
    _logger.info("scheduled daily backups started for %s", db_path)
    return task
