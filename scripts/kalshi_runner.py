"""
Kalshi runner — drives the Kalshi scaffold loader + normalizer through to
canonical SQLite persistence.

Safety
------
- READ-ONLY end-to-end.  No broker, no order placement, no execution.
- The category allowlist (Elections / Politics / Crypto / Commodities /
  Economics / Finance / Tech & Science) is enforced BEFORE persistence:
  rejected categories are never inserted into ``signal_events``.
- Live Kalshi API is intentionally deferred.  ``KalshiLoader`` raises
  ``SkipLoader`` unless ``KALSHI_USE_MOCK_FIXTURES=1`` is set; in mock
  mode every fixture row is explicitly tagged ``is_mock_fixture=True`` so
  it cannot be confused with live data.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.ingestion.kalshi_loader import (
        KalshiLoader,
        normalize_kalshi_records,
        partition_kalshi_records,
    )
    from scripts.kalshi_category_governance import (
        ALLOWED_KALSHI_CATEGORIES,
        DISPLAY_LABELS,
    )
    from scripts.kalshi_normalizer import (
        CANONICAL_SOURCE,
        DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
        SOURCE_ERROR,
        SOURCE_LIVE_VERIFIED,
        SOURCE_STALE,
        SOURCE_UNVERIFIED,
        compute_source_freshness,
    )
    from scripts.runtime_common import REPO_ROOT, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from ingestion.kalshi_loader import (  # type: ignore[no-redef]
        KalshiLoader,
        normalize_kalshi_records,
        partition_kalshi_records,
    )
    from kalshi_category_governance import (  # type: ignore[no-redef]
        ALLOWED_KALSHI_CATEGORIES,
        DISPLAY_LABELS,
    )
    from kalshi_normalizer import (  # type: ignore[no-redef]
        CANONICAL_SOURCE,
        DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
        SOURCE_ERROR,
        SOURCE_LIVE_VERIFIED,
        SOURCE_STALE,
        SOURCE_UNVERIFIED,
        compute_source_freshness,
    )
    from runtime_common import REPO_ROOT, utc_timestamp  # type: ignore[no-redef]


DEFAULT_KALSHI_HEALTH_PATH = REPO_ROOT / "runtime" / "release" / "kalshi_source_health.json"
DEFAULT_KALSHI_QUARANTINE_PATH = REPO_ROOT / "runtime" / "release" / "kalshi_quarantine.jsonl"
DEFAULT_KALSHI_HEALTH_HISTORY_PATH = (
    REPO_ROOT / "runtime" / "release" / "kalshi_source_health_history.jsonl"
)
DEFAULT_KALSHI_QUARANTINE_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB rolling cap
DEFAULT_KALSHI_HEALTH_HISTORY_MAX_LINES = 500

# Keys that must never reach the sanitized history ledger.  Defence in
# depth against accidental upstream changes that start carrying auth
# material in source-health.
_HISTORY_FORBIDDEN_KEYS = frozenset(
    {
        "api_key_id",
        "private_key_path",
        "authorization",
        "kalshi-access-key",
        "kalshi-access-signature",
        "kalshi-access-timestamp",
    }
)


_log = logging.getLogger(__name__)


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``target`` atomically via tmp + os.replace.

    Used so a crashed interpreter / power loss mid-write cannot leave
    half-written JSON behind for the next operator to chase.
    """
    import os as _os

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    data = json.dumps(payload, indent=2)
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        try:
            _os.fsync(fh.fileno())
        except (OSError, AttributeError):  # pragma: no cover - non-POSIX fs
            pass
    _os.replace(tmp, target)


def _sanitize_for_history(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip any forbidden keys from a source-health summary before logging."""

    def _scrub(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: _scrub(v)
                for k, v in obj.items()
                if str(k).lower() not in _HISTORY_FORBIDDEN_KEYS
            }
        if isinstance(obj, list):
            return [_scrub(x) for x in obj]
        return obj

    return _scrub(payload)


def append_kalshi_source_health_history(
    summary: dict[str, Any],
    *,
    base_path: Path | None = None,
    max_lines: int = DEFAULT_KALSHI_HEALTH_HISTORY_MAX_LINES,
) -> Path:
    """Append a sanitized one-line summary to the JSONL history ledger.

    Rotates by truncating to the last ``max_lines`` lines when the
    ledger crosses that threshold — keeps the operator-visible history
    bounded without losing recent runs.  Never persists secret material.
    """
    if base_path is None:
        target = DEFAULT_KALSHI_HEALTH_HISTORY_PATH
    else:
        target = Path(base_path) / "kalshi_source_health_history.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)

    line = _sanitize_for_history(
        {
            "timestamp_utc": summary.get(
                "completed_at_utc", summary.get("attempted_at_utc", "")
            ),
            "mode": summary.get("mode", "kalshi_run"),
            "env": summary.get("env", ""),
            "status": summary.get("status", ""),
            "source_freshness_status": summary.get("source_freshness_status", ""),
            "records_seen_total": summary.get("records_seen_total", 0),
            "records_allowed": summary.get("records_allowed", 0),
            "records_quarantined": summary.get("records_quarantined", 0),
            "auth_used": summary.get("auth_used", False),
            "api_base_url": summary.get("api_base_url", ""),
            "dry_run": summary.get("dry_run", True),
            "seek_allowed": summary.get("seek_allowed", False),
            "allowed_found": summary.get("allowed_found", False),
            "pages_scanned": summary.get("pages_scanned", 0),
            "advisory_only": True,
            "human_review_required": True,
            "execution_locked": True,
            "broker_api_called": False,
            "ai_execution_count": 0,
        }
    )
    try:
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError as exc:  # pragma: no cover - filesystem failure
        _log.warning("kalshi health history append failed: %s", exc)
        return target

    # Rotate by truncating to the most-recent ``max_lines``.
    try:
        text = target.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) > max_lines:
            kept = lines[-max_lines:]
            _atomic_write_text(target, "\n".join(kept) + "\n")
    except OSError:  # pragma: no cover
        pass
    return target


def _atomic_write_text(target: Path, text: str) -> None:
    import os as _os

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        try:
            _os.fsync(fh.fileno())
        except (OSError, AttributeError):  # pragma: no cover
            pass
    _os.replace(tmp, target)


def rotate_kalshi_quarantine(
    path: Path,
    *,
    max_bytes: int = DEFAULT_KALSHI_QUARANTINE_MAX_BYTES,
) -> dict[str, Any]:
    """Rotate the Kalshi quarantine jsonl when it exceeds ``max_bytes``.

    The current file is renamed to ``<path>.1`` (overwriting any prior
    rotation), a small summary is recorded next to it, and a fresh
    empty jsonl is left in its place.  Never deletes the audit without
    leaving the summary breadcrumb.
    """
    target = Path(path)
    if not target.exists():
        return {"rotated": False, "reason": "missing"}
    try:
        size = target.stat().st_size
    except OSError as exc:
        return {"rotated": False, "reason": f"stat_failed:{type(exc).__name__}"}
    if size <= int(max_bytes):
        return {"rotated": False, "reason": "under_cap", "size_bytes": size}
    backup = target.with_suffix(target.suffix + ".1")
    try:
        if backup.exists():
            backup.unlink()
        target.rename(backup)
        target.write_text("", encoding="utf-8")
    except OSError as exc:
        return {"rotated": False, "reason": f"rename_failed:{type(exc).__name__}"}
    rot_summary = target.with_suffix(target.suffix + ".rotation.json")
    payload = {
        "rotated_at_utc": utc_timestamp(),
        "previous_file": str(backup),
        "previous_size_bytes": int(size),
        "max_bytes": int(max_bytes),
        "advisory_only": True,
        "human_review_required": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }
    try:
        _atomic_write_json(rot_summary, payload)
    except OSError:  # pragma: no cover
        pass
    return {"rotated": True, **payload}


@dataclass
class KalshiRunResult:
    """Outcome of a single Kalshi run.  Read-only, advisory-only."""

    source_name: str = CANONICAL_SOURCE
    status: str = "ok"               # ok | skipped | error
    fetched_count: int = 0           # raw records returned by loader
    accepted_count: int = 0          # passed allowlist + required fields
    rejected_count: int = 0          # dropped by allowlist or missing fields
    quarantined_count: int = 0
    events_persisted: int = 0
    skipped_reason: str = ""
    error_message: str = ""
    timestamp_utc: str = ""
    source_freshness_status: str = SOURCE_UNVERIFIED
    advisory_status: str = "ADVISORY_ONLY"
    execution_gate: str = "LOCKED"
    broker_api_called: bool = False
    ai_execution_count: int = 0
    is_mock_run: bool = False
    samples: list[dict[str, Any]] = field(default_factory=list)
    category_allowed_counts: dict[str, int] = field(default_factory=dict)
    category_rejected_counts: dict[str, int] = field(default_factory=dict)
    health_path: str = ""
    quarantine_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "fetched_count": self.fetched_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "quarantined_count": self.quarantined_count,
            "events_persisted": self.events_persisted,
            "skipped_reason": self.skipped_reason,
            "error_message": self.error_message,
            "timestamp_utc": self.timestamp_utc,
            "source_freshness_status": self.source_freshness_status,
            "advisory_status": self.advisory_status,
            "execution_gate": self.execution_gate,
            "broker_api_called": self.broker_api_called,
            "ai_execution_count": self.ai_execution_count,
            "is_mock_run": self.is_mock_run,
            "samples": list(self.samples),
            "category_allowed_counts": dict(self.category_allowed_counts),
            "category_rejected_counts": dict(self.category_rejected_counts),
            "health_path": self.health_path,
            "quarantine_path": self.quarantine_path,
        }


def _safety_block() -> dict[str, Any]:
    return {
        "advisory_only": True,
        "human_review_required": True,
        "execution_locked": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def write_kalshi_source_health(
    *,
    attempted_at_utc: str,
    completed_at_utc: str,
    status: str,
    records_seen_total: int,
    accepted: list[dict[str, Any]],
    quarantined: list[dict[str, Any]],
    events_persisted: int,
    skipped_reason: str = "",
    error_type: str = "",
    error_message: str = "",
    http_status: int | None = None,
    last_successful_fetch_at_utc: str | None = None,
    freshness_ttl_seconds: int = DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
    is_mock_run: bool = False,
    health_path: Path | None = None,
    quarantine_path: Path | None = None,
) -> dict[str, Any]:
    """Write the parent Kalshi source-health evidence file (and the
    quarantine jsonl) and return the in-memory summary.

    Run summaries land at ``runtime/release/kalshi_source_health.json``
    by default.  Tests inject ``health_path`` / ``quarantine_path``
    under ``tmp_path``.

    All summaries carry the full advisory-safety block — failed runs
    included.
    """
    if health_path is None:
        health_path = DEFAULT_KALSHI_HEALTH_PATH
    if quarantine_path is None:
        quarantine_path = DEFAULT_KALSHI_QUARANTINE_PATH

    accepted_categories = Counter(
        str(rec.get("mvp_category") or rec.get("category") or "") for rec in accepted
    )
    quarantined_categories = Counter(
        str(rec.get("raw_category") or rec.get("category_decision", {}).get("kalshi_category_raw", "") or "<missing>")
        for rec in quarantined
    )
    quarantine_reason_counts = Counter(
        str(rec.get("quarantine_reason") or "")
        for rec in quarantined
    )

    close_times = [
        rec.get("close_time_utc") for rec in accepted if rec.get("close_time_utc")
    ]
    earliest_close = min(close_times) if close_times else None
    latest_close = max(close_times) if close_times else None

    # Source-freshness status — explicit error states override.
    if status.upper() in {"ERROR", "SOURCE_ERROR", "HTTP_ERROR"}:
        freshness = SOURCE_ERROR
    elif status.upper() in {"SKIPPED"} and not last_successful_fetch_at_utc:
        freshness = SOURCE_UNVERIFIED
    else:
        freshness = compute_source_freshness(
            last_successful_fetch_at_utc or completed_at_utc,
            completed_at_utc,
            freshness_ttl_seconds,
        )

    summary: dict[str, Any] = {
        "source_name": CANONICAL_SOURCE,
        "artifact_kind": "kalshi_source_health",
        "attempted_at_utc": attempted_at_utc,
        "completed_at_utc": completed_at_utc,
        "status": status,
        "http_status": http_status,
        "skipped_reason": skipped_reason,
        "error_type": error_type,
        "error_message": error_message,
        "records_seen_total": int(records_seen_total),
        "records_allowed": len(accepted),
        "records_quarantined": len(quarantined),
        "records_persisted": int(events_persisted),
        "records_dropped": max(
            0, int(records_seen_total) - len(accepted) - len(quarantined)
        ),
        "allowed_categories": sorted(ALLOWED_KALSHI_CATEGORIES),
        "display_labels": dict(DISPLAY_LABELS),
        "category_allowed_counts": dict(accepted_categories),
        "category_rejected_counts": dict(quarantined_categories),
        "quarantine_reason_counts": dict(quarantine_reason_counts),
        "earliest_close_time_utc": earliest_close,
        "latest_close_time_utc": latest_close,
        "last_successful_fetch_at_utc": last_successful_fetch_at_utc or completed_at_utc,
        "freshness_ttl_seconds": int(freshness_ttl_seconds),
        "source_freshness_status": freshness,
        "is_mock_run": bool(is_mock_run),
    }
    summary.update(_safety_block())

    # Write health summary atomically (tmp + replace).
    try:
        _atomic_write_json(health_path, summary)
    except OSError as exc:  # pragma: no cover - filesystem failure
        _log.warning("kalshi health summary write failed: %s", exc)

    # Append quarantine evidence (jsonl, one row per quarantined market).
    if quarantined:
        try:
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            with quarantine_path.open("a", encoding="utf-8") as fh:
                for rec in quarantined:
                    fh.write(json.dumps(rec) + "\n")
        except OSError as exc:  # pragma: no cover - filesystem failure
            _log.warning("kalshi quarantine append failed: %s", exc)

    # Rolling retention — bound the audit jsonl so unattended demo days
    # don't grow it without limit.  Rotation summary preserves a
    # breadcrumb pointing at the prior file.
    try:
        rotate_kalshi_quarantine(quarantine_path)
    except Exception:  # pragma: no cover
        pass

    # Sanitized append-only history ledger (one line per run).
    try:
        append_kalshi_source_health_history(summary, base_path=health_path.parent)
    except Exception:  # pragma: no cover
        pass

    return summary


def _persist(payloads: list[dict[str, Any]], fetched_at: str, *, db_path: Path | None) -> int:
    try:
        try:
            from scripts.persistence import insert_signal_event
        except ModuleNotFoundError:  # pragma: no cover
            from persistence import insert_signal_event  # type: ignore[no-redef]
    except Exception as exc:  # pragma: no cover - persistence import optional
        _log.warning("kalshi persistence import failed: %s", exc)
        return 0

    count = 0
    for ev in payloads:
        try:
            kwargs: dict[str, Any] = {
                "event_id": ev["event_id"],
                "source_name": CANONICAL_SOURCE,
                "raw_payload": ev,
                "fetched_at": fetched_at,
            }
            if db_path is not None:
                kwargs["db_path"] = db_path
            inserted = insert_signal_event(**kwargs)
            if inserted:
                count += 1
        except Exception as exc:  # noqa: BLE001
            _log.warning("kalshi insert failed for %s: %s", ev.get("event_id"), exc)
    return count


def run_kalshi_ingest(
    *,
    dry_run: bool = True,
    loader: KalshiLoader | None = None,
    db_path: Path | None = None,
    use_mock_fixtures: bool | None = None,
    health_path: Path | None = None,
    quarantine_path: Path | None = None,
    write_health: bool = True,
    last_successful_fetch_at_utc: str | None = None,
) -> KalshiRunResult:
    """Fetch → normalize → (optionally) persist Kalshi records.

    Parameters
    ----------
    dry_run:
        When True (default) records are fetched + normalized but NOT
        written to SQLite.
    loader:
        Inject a custom loader for tests.  Defaults to ``KalshiLoader``.
    db_path:
        Override the canonical SQLite path (tests).
    use_mock_fixtures:
        Forwarded to the default loader.  Ignored when ``loader`` is given.
    health_path / quarantine_path:
        Override the runtime/release artifact paths (tests use
        ``tmp_path`` to keep test runs isolated from real artifacts).
    write_health:
        When False, skip writing the health/quarantine artifacts (the
        in-memory summary on the result is still populated).
    last_successful_fetch_at_utc:
        Optional context for freshness computation.  Defaults to the
        current attempt timestamp on a successful run.
    """
    attempted_at = utc_timestamp()
    result = KalshiRunResult(timestamp_utc=attempted_at)

    if loader is None:
        loader = KalshiLoader(use_mock_fixtures=use_mock_fixtures)

    loader_result = loader.safe_fetch()
    if loader_result.skipped:
        result.status = "skipped"
        result.skipped_reason = loader_result.skip_reason
        completed_at = utc_timestamp()
        if write_health:
            summary = write_kalshi_source_health(
                attempted_at_utc=attempted_at,
                completed_at_utc=completed_at,
                status="SKIPPED",
                records_seen_total=0,
                accepted=[],
                quarantined=[],
                events_persisted=0,
                skipped_reason=loader_result.skip_reason,
                last_successful_fetch_at_utc=last_successful_fetch_at_utc,
                health_path=health_path,
                quarantine_path=quarantine_path,
            )
            result.source_freshness_status = summary["source_freshness_status"]
            result.health_path = str(health_path or DEFAULT_KALSHI_HEALTH_PATH)
            result.quarantine_path = str(quarantine_path or DEFAULT_KALSHI_QUARANTINE_PATH)
        return result

    raw_records = loader_result.records
    result.fetched_count = len(raw_records)
    event_lookup = getattr(loader, "last_event_lookup", None) or {}
    accepted, quarantined = partition_kalshi_records(
        raw_records, fetched_at_utc=attempted_at, event_lookup=event_lookup
    )
    result.accepted_count = len(accepted)
    result.quarantined_count = len(quarantined)
    result.rejected_count = result.fetched_count - result.accepted_count
    result.is_mock_run = any(rec.get("is_mock_fixture") for rec in raw_records)
    result.category_allowed_counts = dict(
        Counter(str(rec.get("mvp_category") or "") for rec in accepted)
    )
    result.category_rejected_counts = dict(
        Counter(str(rec.get("quarantine_reason") or "") for rec in quarantined)
    )

    if not dry_run:
        result.events_persisted = _persist(accepted, attempted_at, db_path=db_path)

    # Record a small sample for diagnostics (no PII; titles + category only).
    for rec in accepted[:5]:
        result.samples.append(
            {
                "event_id": rec.get("event_id"),
                "category": rec.get("category"),
                "mvp_category": rec.get("mvp_category"),
                "title": rec.get("title"),
                "source": rec.get("source"),
                "source_freshness_status": rec.get("source_freshness_status"),
                "market_activity_status": rec.get("market_activity_status"),
                "ui_badge_status": rec.get("ui_badge_status"),
                "advisory_status": rec.get("advisory_status"),
                "execution_gate": rec.get("execution_gate"),
                "broker_api_called": rec.get("broker_api_called"),
                "ai_execution_count": rec.get("ai_execution_count"),
            }
        )

    completed_at = utc_timestamp()
    if write_health:
        summary = write_kalshi_source_health(
            attempted_at_utc=attempted_at,
            completed_at_utc=completed_at,
            status="OK" if result.accepted_count else "OK_FILTERED",
            records_seen_total=result.fetched_count,
            accepted=accepted,
            quarantined=quarantined,
            events_persisted=result.events_persisted,
            is_mock_run=result.is_mock_run,
            last_successful_fetch_at_utc=last_successful_fetch_at_utc or completed_at,
            health_path=health_path,
            quarantine_path=quarantine_path,
        )
        result.source_freshness_status = summary["source_freshness_status"]
        result.health_path = str(health_path or DEFAULT_KALSHI_HEALTH_PATH)
        result.quarantine_path = str(quarantine_path or DEFAULT_KALSHI_QUARANTINE_PATH)

    return result


__all__ = [
    "KalshiRunResult",
    "run_kalshi_ingest",
    "write_kalshi_source_health",
    "DEFAULT_KALSHI_HEALTH_PATH",
    "DEFAULT_KALSHI_QUARANTINE_PATH",
    "DEFAULT_KALSHI_HEALTH_HISTORY_PATH",
    "DEFAULT_KALSHI_QUARANTINE_MAX_BYTES",
    "DEFAULT_KALSHI_HEALTH_HISTORY_MAX_LINES",
    "append_kalshi_source_health_history",
    "rotate_kalshi_quarantine",
    "_atomic_write_json",
]
