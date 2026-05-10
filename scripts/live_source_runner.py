"""
Phase 1 Live Source Runner — read-only ingestion for Polymarket, GDELT, SEC EDGAR.

Safety contract
---------------
- READ-ONLY. No write to any external system.
- No broker API calls. No order placement. No CLOB trading.
- All signals carry advisory_status="ADVISORY_ONLY" and human_review_required=True.
- execution_gate="LOCKED" on every record.
- AI execution count is always 0.
- Dry-run mode fetches and normalizes but does NOT persist anything.
- SEC EDGAR skips cleanly when SEC_USER_AGENT env var is unset.
- Polymarket and GDELT require no secrets.

Rate-limit-safe defaults
------------------------
- Polymarket: 20 markets per call, 15 s timeout
- GDELT: 25 articles per call, 15 s timeout
- SEC EDGAR: 10 filings per call, 15 s timeout
- Up to 2 retries on transient network errors, 2 s back-off
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp
    from scripts.ingestion.polymarket_loader import PolymarketLoader
    from scripts.ingestion.gdelt_loader import GDELTLoader
    from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
    from scripts.ingestion.base_loader import LoaderResult, SkipLoader
except ModuleNotFoundError:
    from runtime_common import utc_timestamp  # type: ignore[no-redef]
    from ingestion.polymarket_loader import PolymarketLoader  # type: ignore[no-redef]
    from ingestion.gdelt_loader import GDELTLoader  # type: ignore[no-redef]
    from ingestion.sec_edgar_loader import SECEdgarLoader  # type: ignore[no-redef]
    from ingestion.base_loader import LoaderResult, SkipLoader  # type: ignore[no-redef]

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0

_POLYMARKET_LIMIT = 20
_GDELT_MAX_RECORDS = 25
_SEC_MAX_FILINGS = 10
_DEFAULT_TIMEOUT = 15
_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 2.0


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class SourceRunResult:
    """Result of running a single source."""

    source_name: str
    status: str  # "ok" | "skipped" | "error"
    fetched_count: int = 0
    skipped_reason: str = ""
    error_message: str = ""
    timestamp_utc: str = ""
    duration_ms: int = 0
    events_persisted: int = 0
    advisory_status: str = _ADVISORY_STATUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "fetched_count": self.fetched_count,
            "skipped_reason": self.skipped_reason,
            "error_message": self.error_message,
            "timestamp_utc": self.timestamp_utc,
            "duration_ms": self.duration_ms,
            "events_persisted": self.events_persisted,
            "advisory_status": self.advisory_status,
        }


@dataclass
class Phase1RunReport:
    """Aggregate report from a full Phase 1 run."""

    dry_run: bool
    sources: list[SourceRunResult] = field(default_factory=list)
    total_fetched: int = 0
    total_persisted: int = 0
    advisory_status: str = _ADVISORY_STATUS
    execution_gate: str = _EXECUTION_GATE
    ai_execution_count: int = _AI_EXECUTION_COUNT
    human_review_required: bool = True
    run_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "sources": [s.to_dict() for s in self.sources],
            "total_fetched": self.total_fetched,
            "total_persisted": self.total_persisted,
            "advisory_status": self.advisory_status,
            "execution_gate": self.execution_gate,
            "ai_execution_count": self.ai_execution_count,
            "human_review_required": self.human_review_required,
            "run_at": self.run_at,
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _stable_event_id(source_name: str, *key_parts: str) -> str:
    """Deterministic event_id derived from source name + key fields."""
    raw = f"{source_name}:" + "|".join(str(p) for p in key_parts)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{source_name}_{digest}"


def _normalize_polymarket_record(rec: dict[str, Any]) -> dict[str, Any]:
    market_id = str(rec.get("market_id", ""))
    return {
        "event_id": _stable_event_id("polymarket", market_id),
        "source_name": "polymarket",
        "signal_type": "prediction_market",
        "title": str(rec.get("question", "")),
        "market_id": market_id,
        "volume": rec.get("volume"),
        "liquidity": rec.get("liquidity"),
        "end_date": rec.get("end_date"),
        "active": rec.get("active"),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
    }


def _normalize_gdelt_record(rec: dict[str, Any]) -> dict[str, Any]:
    url = str(rec.get("url", ""))
    return {
        "event_id": _stable_event_id("gdelt", url),
        "source_name": "gdelt",
        "signal_type": "news_event",
        "title": str(rec.get("title", "")),
        "url": url,
        "seendate": rec.get("seendate"),
        "domain": rec.get("domain"),
        "language": rec.get("language"),
        "sourcecountry": rec.get("sourcecountry"),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
    }


def _normalize_sec_record(rec: dict[str, Any]) -> dict[str, Any]:
    cik = str(rec.get("cik", ""))
    accession = str(rec.get("accession_number", ""))
    note = str(rec.get("note", ""))
    return {
        "event_id": _stable_event_id("sec_edgar", cik, accession, note),
        "source_name": "sec_edgar",
        "signal_type": "sec_filing",
        "title": f"{rec.get('form_type', 'SEC Filing')} — CIK {cik}",
        "cik": cik,
        "form_type": rec.get("form_type"),
        "filing_date": rec.get("filing_date"),
        "accession_number": accession,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
    }


_NORMALIZERS: dict[str, Any] = {
    "polymarket": _normalize_polymarket_record,
    "gdelt": _normalize_gdelt_record,
    "sec_edgar": _normalize_sec_record,
}


# ---------------------------------------------------------------------------
# Fetch with retry
# ---------------------------------------------------------------------------


def _run_loader_with_retry(
    loader: Any,
    max_retries: int = _MAX_RETRIES,
    backoff: float = _RETRY_BACKOFF_S,
) -> LoaderResult:
    """Run loader.safe_fetch() with limited retries on transient network errors."""
    last_result: LoaderResult | None = None
    for attempt in range(max_retries + 1):
        result = loader.safe_fetch()
        # Return immediately if successful or if skip is non-transient (missing key etc.)
        if not result.skipped:
            return result
        if "unreachable" not in result.skip_reason.lower():
            return result
        last_result = result
        if attempt < max_retries:
            time.sleep(backoff)
    return last_result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Persistence helpers (optional, fail-safe)
# ---------------------------------------------------------------------------


def _persist_events(
    events: list[dict[str, Any]],
    source_name: str,
    fetched_at: str,
) -> int:
    """Persist normalized events to SQLite. Returns count of newly inserted rows."""
    try:
        try:
            from scripts.persistence import insert_signal_event
        except ModuleNotFoundError:
            from persistence import insert_signal_event  # type: ignore[no-redef]
    except Exception:
        return 0

    count = 0
    for ev in events:
        try:
            inserted = insert_signal_event(
                event_id=ev["event_id"],
                source_name=source_name,
                raw_payload=ev,
                fetched_at=fetched_at,
            )
            if inserted:
                count += 1
        except Exception:
            pass
    return count


def _log_run(result: SourceRunResult) -> None:
    """Write a SourceRunResult to the source_run_log table (fail-safe)."""
    try:
        try:
            from scripts.persistence import log_source_run
        except ModuleNotFoundError:
            from persistence import log_source_run  # type: ignore[no-redef]
        log_source_run(
            source_name=result.source_name,
            status=result.status,
            fetched_count=result.fetched_count,
            skipped_reason=result.skipped_reason,
            error_message=result.error_message,
            timestamp_utc=result.timestamp_utc,
            duration_ms=result.duration_ms,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_phase1(
    dry_run: bool = True,
    polymarket_limit: int = _POLYMARKET_LIMIT,
    gdelt_max_records: int = _GDELT_MAX_RECORDS,
    sec_cik: str | None = None,
    sec_form_type: str = "10-K",
    sec_max_filings: int = _SEC_MAX_FILINGS,
    sources: list[str] | None = None,
) -> Phase1RunReport:
    """
    Run Phase 1 live source ingestion: Polymarket, GDELT, SEC EDGAR.

    Parameters
    ----------
    dry_run:
        When True, fetch and normalize signals but do NOT persist to SQLite
        and do NOT write source_run_log entries.
    sources:
        Subset of Phase 1 sources to run. Defaults to all
        (["polymarket", "gdelt", "sec_edgar"]).
    """
    if sources is None:
        sources = ["polymarket", "gdelt", "sec_edgar"]

    report = Phase1RunReport(dry_run=dry_run, run_at=utc_timestamp())

    all_loaders: dict[str, Any] = {
        "polymarket": PolymarketLoader(limit=polymarket_limit, timeout=_DEFAULT_TIMEOUT),
        "gdelt": GDELTLoader(max_records=gdelt_max_records, timeout=_DEFAULT_TIMEOUT),
        "sec_edgar": SECEdgarLoader(
            cik=sec_cik,
            form_type=sec_form_type,
            max_filings=sec_max_filings,
            timeout=_DEFAULT_TIMEOUT,
        ),
    }

    loaders: list[tuple[str, Any]] = [
        (name, all_loaders[name]) for name in sources if name in all_loaders
    ]

    for source_name, loader in loaders:
        normalizer = _NORMALIZERS[source_name]
        ts = utc_timestamp()
        t0 = time.monotonic()

        loader_result = _run_loader_with_retry(loader)

        duration_ms = int((time.monotonic() - t0) * 1000)

        if loader_result.skipped:
            src_result = SourceRunResult(
                source_name=source_name,
                status="skipped",
                fetched_count=0,
                skipped_reason=loader_result.skip_reason,
                timestamp_utc=ts,
                duration_ms=duration_ms,
            )
        else:
            events = [normalizer(rec) for rec in loader_result.records]
            persisted = 0
            if not dry_run:
                persisted = _persist_events(events, source_name, ts)
            src_result = SourceRunResult(
                source_name=source_name,
                status="ok",
                fetched_count=len(events),
                timestamp_utc=ts,
                duration_ms=duration_ms,
                events_persisted=persisted,
            )

        if not dry_run:
            _log_run(src_result)

        report.sources.append(src_result)
        report.total_fetched += src_result.fetched_count
        report.total_persisted += src_result.events_persisted

    return report


_PHASE1_SOURCES = ["polymarket", "gdelt", "sec_edgar"]

__all__ = [
    "SourceRunResult",
    "Phase1RunReport",
    "run_phase1",
    "_stable_event_id",
    "_normalize_polymarket_record",
    "_normalize_gdelt_record",
    "_normalize_sec_record",
    "_persist_events",
    "_log_run",
    "_PHASE1_SOURCES",
]
