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

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.ingestion.kalshi_loader import KalshiLoader, normalize_kalshi_records
    from scripts.kalshi_normalizer import CANONICAL_SOURCE
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from ingestion.kalshi_loader import KalshiLoader, normalize_kalshi_records  # type: ignore[no-redef]
    from kalshi_normalizer import CANONICAL_SOURCE  # type: ignore[no-redef]
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


_log = logging.getLogger(__name__)


@dataclass
class KalshiRunResult:
    """Outcome of a single Kalshi run.  Read-only, advisory-only."""

    source_name: str = CANONICAL_SOURCE
    status: str = "ok"               # ok | skipped | error
    fetched_count: int = 0           # raw records returned by loader
    accepted_count: int = 0          # passed allowlist + required fields
    rejected_count: int = 0          # dropped by allowlist or missing fields
    events_persisted: int = 0
    skipped_reason: str = ""
    error_message: str = ""
    timestamp_utc: str = ""
    advisory_status: str = "ADVISORY_ONLY"
    execution_gate: str = "LOCKED"
    broker_api_called: bool = False
    ai_execution_count: int = 0
    is_mock_run: bool = False
    samples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "fetched_count": self.fetched_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "events_persisted": self.events_persisted,
            "skipped_reason": self.skipped_reason,
            "error_message": self.error_message,
            "timestamp_utc": self.timestamp_utc,
            "advisory_status": self.advisory_status,
            "execution_gate": self.execution_gate,
            "broker_api_called": self.broker_api_called,
            "ai_execution_count": self.ai_execution_count,
            "is_mock_run": self.is_mock_run,
            "samples": list(self.samples),
        }


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
    """
    ts = utc_timestamp()
    result = KalshiRunResult(timestamp_utc=ts)

    if loader is None:
        loader = KalshiLoader(use_mock_fixtures=use_mock_fixtures)

    loader_result = loader.safe_fetch()
    if loader_result.skipped:
        result.status = "skipped"
        result.skipped_reason = loader_result.skip_reason
        return result

    raw_records = loader_result.records
    result.fetched_count = len(raw_records)
    normalized = normalize_kalshi_records(raw_records, fetched_at_utc=ts)
    result.accepted_count = len(normalized)
    result.rejected_count = result.fetched_count - result.accepted_count
    result.is_mock_run = any(rec.get("is_mock_fixture") for rec in raw_records)

    if not dry_run:
        result.events_persisted = _persist(normalized, ts, db_path=db_path)

    # Record a small sample for diagnostics (no PII; titles + category only).
    for rec in normalized[:5]:
        result.samples.append(
            {
                "event_id": rec.get("event_id"),
                "category": rec.get("category"),
                "title": rec.get("title"),
                "source": rec.get("source"),
                "advisory_status": rec.get("advisory_status"),
                "execution_gate": rec.get("execution_gate"),
                "broker_api_called": rec.get("broker_api_called"),
                "ai_execution_count": rec.get("ai_execution_count"),
            }
        )
    return result


__all__ = ["KalshiRunResult", "run_kalshi_ingest"]
