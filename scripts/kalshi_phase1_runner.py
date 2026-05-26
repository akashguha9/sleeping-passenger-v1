"""Kalshi phase-1 refresh runner.

Wraps the existing read-only loaders into a single function the parent
orchestrator (``scripts/refresh_live_signals.py`` and its phase1 entry
``scripts/live_source_runner.run_phase1``) can use to:

1. Choose between the live API path (``src/ingestion/kalshi_live_loader``)
   and the legacy public-read path (``scripts/ingestion/kalshi_loader``).
2. Upsert accepted markets into ``signal_events`` so canonical freshness
   is refreshed even when the same market id is re-observed.
3. Apply a bounded semantic retry when the first attempt returns nothing
   actionable (empty / filtered / accepted-but-zero-canonical).
4. Return a single dict carrying the metrics the freshness classifier
   needs: records_seen_total, records_allowed, records_quarantined,
   rows_added, rows_refreshed, source_freshness_status, health_path.

Safety
------
Read-only end-to-end.  Never calls a non-GET endpoint.  Never logs
secrets.  Every persisted row gets the canonical advisory-safety stamps
(advisory_status=ADVISORY_ONLY, execution_gate=LOCKED,
broker_api_called=False, ai_execution_count=0, human_review_required=1).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.runtime_common import REPO_ROOT, utc_timestamp
    from scripts.ingestion.kalshi_loader import KalshiLoader, partition_kalshi_records
    from scripts.ingestion.base_loader import LoaderResult
    from scripts.kalshi_normalizer import CANONICAL_SOURCE, normalize_kalshi_market
except ModuleNotFoundError:  # pragma: no cover
    from runtime_common import REPO_ROOT, utc_timestamp  # type: ignore[no-redef]
    from ingestion.kalshi_loader import KalshiLoader, partition_kalshi_records  # type: ignore[no-redef]
    from ingestion.base_loader import LoaderResult  # type: ignore[no-redef]
    from kalshi_normalizer import CANONICAL_SOURCE, normalize_kalshi_market  # type: ignore[no-redef]

_LOG = logging.getLogger(__name__)

_DEFAULT_MAX_ATTEMPTS = 2
_DEFAULT_BACKOFF_SECONDS = (0.5, 1.0, 2.0)

# Retry-reason taxonomy — surfaced in the per-attempt log block.
RETRY_EMPTY_RESPONSE = "EMPTY_RESPONSE"
RETRY_FILTERED_NO_ALLOWED = "FILTERED_NO_ALLOWED"
RETRY_ACCEPTED_BUT_ZERO_CANONICAL = "ACCEPTED_BUT_ZERO_CANONICAL_WRITE"
RETRY_HTTP_ERROR = "HTTP_ERROR"
RETRY_TIMEOUT = "TIMEOUT"
RETRY_AUTH_TRANSIENT = "AUTH_TRANSIENT"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _live_config_ready() -> bool:
    """Return True iff the live Kalshi auth config can be loaded.

    Never echoes secrets — we only check presence of env vars.
    """
    if _env_truthy("KALSHI_REFRESH_USE_LIVE"):
        return True
    if _env_truthy("KALSHI_ENABLE_AUTH"):
        try:
            from src.ingestion.kalshi_live_config import (  # noqa: WPS433
                KalshiConfigError,
                load_kalshi_live_config,
            )
        except ImportError:  # pragma: no cover
            return False
        try:
            load_kalshi_live_config()
            return True
        except KalshiConfigError:
            return False
        except Exception:  # noqa: BLE001
            return False
    return False


def _upsert(
    event_payload: dict[str, Any],
    fetched_at: str,
    *,
    db_path: Path | None,
) -> tuple[int, int]:
    """Upsert one accepted Kalshi market.  Returns ``(added, refreshed)``."""
    try:
        try:
            from scripts.persistence import upsert_signal_event_observation
        except ModuleNotFoundError:  # pragma: no cover
            from persistence import upsert_signal_event_observation  # type: ignore[no-redef]
    except Exception:
        return (0, 0)
    try:
        return upsert_signal_event_observation(
            event_id=event_payload["event_id"],
            source_name=CANONICAL_SOURCE,
            raw_payload=event_payload,
            fetched_at=fetched_at,
            db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "kalshi upsert failed event=%s err=%s",
            event_payload.get("event_id"),
            type(exc).__name__,
        )
        return (0, 0)


def _persist_accepted(
    accepted: list[dict[str, Any]],
    fetched_at: str,
    *,
    db_path: Path | None,
) -> tuple[int, int]:
    rows_added = 0
    rows_refreshed = 0
    for payload in accepted:
        added, refreshed = _upsert(payload, fetched_at, db_path=db_path)
        rows_added += added
        rows_refreshed += refreshed
    return rows_added, rows_refreshed


def _attempt_legacy(
    *,
    limit: int,
    timeout: int,
    use_mock: bool | None,
    loader: KalshiLoader | None = None,
) -> dict[str, Any]:
    """One legacy public-read attempt — used when live auth is not configured."""
    if loader is None:
        loader = KalshiLoader(limit=limit, timeout=timeout, use_mock_fixtures=use_mock)
    fetched_at = utc_timestamp()
    result: LoaderResult = loader.safe_fetch()
    if result.skipped:
        return {
            "skipped": True,
            "skip_reason": result.skip_reason,
            "records_seen_total": 0,
            "records_allowed": 0,
            "records_quarantined": 0,
            "accepted": [],
            "fetched_at": fetched_at,
            "source_freshness_status": "",
            "health_path": "",
            "auth_used": False,
            "error_present": False,
            "error_message": result.skip_reason,
            "http_error": False,
            "timeout_error": False,
        }
    event_lookup = getattr(loader, "last_event_lookup", None) or {}
    accepted, quarantined = partition_kalshi_records(
        result.records, fetched_at_utc=fetched_at, event_lookup=event_lookup
    )
    return {
        "skipped": False,
        "skip_reason": "",
        "records_seen_total": len(result.records),
        "records_allowed": len(accepted),
        "records_quarantined": len(quarantined),
        "accepted": accepted,
        "fetched_at": fetched_at,
        # Legacy path does not write a source-health artifact — leave blank
        # and let the classifier fall back to the canonical artifact on disk.
        "source_freshness_status": "",
        "health_path": "",
        "auth_used": False,
        "error_present": False,
        "error_message": "",
        "http_error": False,
        "timeout_error": False,
    }


def _attempt_live(
    *,
    limit: int,
    max_pages: int,
    seek_allowed: bool,
    min_allowed: int,
    health_path: Path | None,
    quarantine_path: Path | None,
) -> dict[str, Any]:
    """One live read-only smoke attempt.

    Returns an outcome dict equivalent to ``_attempt_legacy`` plus the
    health-path / freshness fields populated from the artifact write.
    """
    try:
        from src.ingestion.kalshi_live_config import load_kalshi_live_config
        from src.ingestion.kalshi_live_loader import run_live_kalshi_smoke
    except ImportError as exc:  # pragma: no cover
        return {
            "skipped": True,
            "skip_reason": f"live_loader_import_failed: {type(exc).__name__}",
            "records_seen_total": 0,
            "records_allowed": 0,
            "records_quarantined": 0,
            "accepted": [],
            "fetched_at": utc_timestamp(),
            "source_freshness_status": "",
            "health_path": "",
            "auth_used": False,
            "error_present": True,
            "error_message": "live_loader_unavailable",
            "http_error": False,
            "timeout_error": False,
        }

    fetched_at = utc_timestamp()
    try:
        cfg = load_kalshi_live_config()
    except Exception as exc:  # noqa: BLE001
        return {
            "skipped": True,
            "skip_reason": f"live_config_unavailable: {type(exc).__name__}",
            "records_seen_total": 0,
            "records_allowed": 0,
            "records_quarantined": 0,
            "accepted": [],
            "fetched_at": fetched_at,
            "source_freshness_status": "",
            "health_path": "",
            "auth_used": False,
            "error_present": True,
            "error_message": "live_config_failed",
            "http_error": False,
            "timeout_error": False,
        }
    try:
        smoke = run_live_kalshi_smoke(
            config=cfg,
            max_pages=int(max_pages),
            limit=int(limit),
            dry_run=True,  # smoke never persists; we persist below from `accepted`.
            seek_allowed=bool(seek_allowed),
            min_allowed=int(min_allowed),
            health_path=health_path,
            quarantine_path=quarantine_path,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "skipped": False,
            "skip_reason": "",
            "records_seen_total": 0,
            "records_allowed": 0,
            "records_quarantined": 0,
            "accepted": [],
            "fetched_at": fetched_at,
            "source_freshness_status": "SOURCE_ERROR",
            "health_path": "",
            "auth_used": False,
            "error_present": True,
            "error_message": f"{type(exc).__name__}",
            "http_error": True,
            "timeout_error": "timeout" in type(exc).__name__.lower(),
        }

    # The smoke wrote the source-health artifact; pull accepted markets out
    # of the loader's internal partitioner so we can persist canonically.
    # ``run_live_kalshi_smoke`` keeps the accepted list internal — we
    # re-derive it from the smoke result's category counts plus a second,
    # cheap partition pass over the loader's collected pages.  Easier:
    # re-call partition over the LoaderResult-equivalent stream.  Since
    # the smoke already counted accepted markets via partition, we re-run
    # via the legacy public client only when accepted_count > 0 *and*
    # the operator wants persistence.
    #
    # To avoid a second HTTP call, we read the markets back from the
    # KalshiLiveClient cache attached to the smoke result if present.
    # When not present (current implementation), we accept the smoke
    # counts as authoritative and persist via a tiny re-partition pass
    # over the smoke result's accepted_sample_titles? — but those are
    # only titles, not full payloads.
    #
    # The pragmatic solution: when live auth is configured, also write a
    # canonical signal_events row PER ACCEPTED MARKET by calling the
    # smoke loader with a small helper that returns the accepted payloads.
    # That helper is added below.
    accepted = _collect_accepted_via_live_client(
        cfg=cfg, limit=limit, max_pages=max_pages, seek_allowed=seek_allowed,
        min_allowed=min_allowed,
    )
    return {
        "skipped": False,
        "skip_reason": "",
        "records_seen_total": int(smoke.records_seen_total or 0),
        "records_allowed": int(smoke.records_allowed or 0),
        "records_quarantined": int(smoke.records_quarantined or 0),
        "accepted": accepted,
        "fetched_at": fetched_at,
        "source_freshness_status": str(smoke.source_freshness_status or ""),
        "health_path": str(smoke.health_path or ""),
        "auth_used": bool(smoke.auth_used),
        "error_present": smoke.status != "ok",
        "error_message": smoke.error_type or "",
        "http_error": smoke.error_type.lower() == "httperror" if smoke.error_type else False,
        "timeout_error": "timeout" in (smoke.error_type or "").lower(),
    }


def _collect_accepted_via_live_client(
    *,
    cfg: Any,
    limit: int,
    max_pages: int,
    seek_allowed: bool,
    min_allowed: int,
) -> list[dict[str, Any]]:
    """Walk the live client a second time and return accepted payloads.

    The smoke wrote the audit artifact; this small follow-up call collects
    the canonical payloads we need to upsert.  Keeping it isolated keeps
    the smoke loader's signature unchanged and makes the persistence path
    trivially testable in isolation.

    Failure here is non-fatal — accepted=[] returns to the caller and the
    classifier maps it to ZERO_FRESH_ROWS / FILTERED / etc.
    """
    try:
        from src.ingestion.kalshi_live_client import KalshiLiveClient
        from src.ingestion.kalshi_live_loader import (
            _extract_markets_page,
            _market_to_loader_record,
            _partition,
        )
    except ImportError:  # pragma: no cover
        return []
    try:
        client = KalshiLiveClient(cfg)
    except Exception:  # noqa: BLE001
        return []

    fetched_at = utc_timestamp()
    accepted_total: list[dict[str, Any]] = []
    cursor: str | None = None
    pages_done = 0
    try:
        events_payload = client.get_events(limit=max(50, int(limit) * 2))
        events_raw = (
            events_payload.get("events", [])
            if isinstance(events_payload, dict)
            else []
        )
        event_lookup: dict[str, dict[str, Any]] = {}
        for ev in events_raw:
            if not isinstance(ev, dict):
                continue
            ticker = str(ev.get("event_ticker") or ev.get("ticker") or "").strip()
            if ticker:
                event_lookup[ticker] = ev
    except Exception:  # noqa: BLE001
        event_lookup = {}

    while pages_done < max(1, int(max_pages)):
        try:
            payload = client.get_markets(limit=limit, cursor=cursor)
        except Exception:  # noqa: BLE001
            break
        page_markets, next_cursor = _extract_markets_page(payload)
        page_records: list[dict[str, Any]] = []
        for market in page_markets:
            rec = _market_to_loader_record(market)
            if rec is None:
                continue
            page_records.append(rec)
        page_accepted, _q = _partition(
            page_records, fetched_at, event_lookup=event_lookup
        )
        accepted_total.extend(page_accepted)
        pages_done += 1
        if not next_cursor:
            break
        cursor = next_cursor
        if seek_allowed and min_allowed > 0 and len(accepted_total) >= min_allowed:
            break
    return accepted_total


def _retry_reason(attempt: dict[str, Any], rows_added: int, rows_refreshed: int) -> str | None:
    if attempt.get("error_present"):
        if attempt.get("timeout_error"):
            return RETRY_TIMEOUT
        if attempt.get("http_error"):
            return RETRY_HTTP_ERROR
        if "auth" in str(attempt.get("error_message") or "").lower():
            return RETRY_AUTH_TRANSIENT
        return RETRY_HTTP_ERROR
    if attempt.get("records_seen_total", 0) == 0:
        return RETRY_EMPTY_RESPONSE
    if (
        attempt.get("records_allowed", 0) == 0
        and attempt.get("records_quarantined", 0) > 0
    ):
        return RETRY_FILTERED_NO_ALLOWED
    if (
        attempt.get("records_allowed", 0) > 0
        and rows_added + rows_refreshed == 0
    ):
        return RETRY_ACCEPTED_BUT_ZERO_CANONICAL
    return None


def run_kalshi_phase1(
    *,
    dry_run: bool,
    limit: int = 25,
    timeout: int = 12,
    max_pages: int = 1,
    seek_allowed: bool = False,
    min_allowed: int = 0,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: tuple[float, ...] = _DEFAULT_BACKOFF_SECONDS,
    use_mock: bool | None = None,
    legacy_loader: KalshiLoader | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    force_live: bool | None = None,
    health_path: Path | None = None,
    quarantine_path: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Run the Kalshi phase-1 refresh.

    Returns a dict the caller can map directly into ``SourceRunResult``
    plus the metrics needed by ``kalshi_semantic_freshness.build_kalshi_truth``.
    """
    sleep = sleep_fn or time.sleep
    live = bool(force_live) if force_live is not None else _live_config_ready()

    attempts_log: list[dict[str, Any]] = []
    last_outcome: dict[str, Any] = {}
    rows_added_total = 0
    rows_refreshed_total = 0
    attempt_count = 0
    final_retry_reason: str | None = None

    while attempt_count < max(1, int(max_attempts)):
        attempt_count += 1
        if live:
            outcome = _attempt_live(
                limit=limit,
                max_pages=max_pages,
                seek_allowed=seek_allowed,
                min_allowed=min_allowed,
                health_path=health_path,
                quarantine_path=quarantine_path,
            )
        else:
            outcome = _attempt_legacy(
                limit=limit,
                timeout=timeout,
                use_mock=use_mock,
                loader=legacy_loader,
            )

        rows_added = 0
        rows_refreshed = 0
        if not dry_run and outcome["accepted"]:
            rows_added, rows_refreshed = _persist_accepted(
                outcome["accepted"], outcome["fetched_at"], db_path=db_path
            )
        rows_added_total += rows_added
        rows_refreshed_total += rows_refreshed

        attempts_log.append(
            {
                "attempt_number": attempt_count,
                "live": bool(live),
                "records_seen_total": outcome["records_seen_total"],
                "records_allowed": outcome["records_allowed"],
                "records_quarantined": outcome["records_quarantined"],
                "rows_added": rows_added,
                "rows_refreshed": rows_refreshed,
                "error_present": outcome["error_present"],
                "error_message": outcome["error_message"],
                "skipped": outcome["skipped"],
                "skip_reason": outcome["skip_reason"],
                "source_freshness_status": outcome["source_freshness_status"],
            }
        )
        last_outcome = outcome

        if outcome["skipped"]:
            break

        reason = _retry_reason(outcome, rows_added, rows_refreshed)
        attempts_log[-1]["retry_reason"] = reason
        if reason is None:
            final_retry_reason = None
            break
        final_retry_reason = reason
        if attempt_count >= int(max_attempts):
            break
        backoff = backoff_seconds[min(attempt_count - 1, len(backoff_seconds) - 1)]
        if backoff > 0:
            sleep(float(backoff))

    return {
        "live": bool(live),
        "skipped": bool(last_outcome.get("skipped", False)),
        "skipped_reason": str(last_outcome.get("skip_reason", "") or ""),
        "error_present": bool(last_outcome.get("error_present", False)),
        "error_message": str(last_outcome.get("error_message", "") or ""),
        "records_seen_total": int(last_outcome.get("records_seen_total", 0) or 0),
        "records_allowed": int(last_outcome.get("records_allowed", 0) or 0),
        "records_quarantined": int(last_outcome.get("records_quarantined", 0) or 0),
        "rows_added": int(rows_added_total),
        "rows_refreshed": int(rows_refreshed_total),
        "source_freshness_status": str(last_outcome.get("source_freshness_status", "") or ""),
        "health_path": str(last_outcome.get("health_path", "") or ""),
        "auth_used": bool(last_outcome.get("auth_used", False)),
        "retry_count": max(0, attempt_count - 1),
        "max_attempts": int(max_attempts),
        "final_retry_reason": final_retry_reason,
        "attempts": attempts_log,
        "fetched_at": str(last_outcome.get("fetched_at", "") or utc_timestamp()),
    }


__all__ = [
    "run_kalshi_phase1",
    "RETRY_EMPTY_RESPONSE",
    "RETRY_FILTERED_NO_ALLOWED",
    "RETRY_ACCEPTED_BUT_ZERO_CANONICAL",
    "RETRY_HTTP_ERROR",
    "RETRY_TIMEOUT",
    "RETRY_AUTH_TRANSIENT",
]
