"""
Phase 2 Live Source Runner — read-only ingestion for NewsAPI, Event Registry, and Etherscan.

Safety contract
---------------
- READ-ONLY. No write to any external system.
- No broker API calls. No order placement. No CLOB trading.
- No private keys, wallet signing, transaction broadcasting, or token approvals.
- All signals carry advisory_status="ADVISORY_ONLY" and human_review_required=True.
- execution_gate="LOCKED" on every record.
- AI execution count is always 0.
- broker_api_called is always False.
- Dry-run mode fetches and normalizes but does NOT persist anything.
- NewsAPI skips cleanly when NEWS_API_KEY env var is unset.
- Event Registry skips cleanly when EVENT_REGISTRY_API_KEY env var is unset.
- Etherscan skips cleanly when ETHERSCAN_API_KEY env var is unset or no address given.

Rate-limit-safe defaults
------------------------
- NewsAPI: 20 articles per call, 15 s timeout
- Event Registry: 20 articles per call, 15 s timeout
- Etherscan: 25 transactions per call, 15 s timeout
- Up to 2 retries on transient network errors, 2 s back-off
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp
    from scripts.ingestion.newsapi_loader import NewsAPILoader
    from scripts.ingestion.event_registry_loader import EventRegistryLoader
    from scripts.ingestion.etherscan_loader import EtherscanLoader
    from scripts.ingestion.base_loader import LoaderResult, SkipLoader
except ModuleNotFoundError:
    from runtime_common import utc_timestamp  # type: ignore[no-redef]
    from ingestion.newsapi_loader import NewsAPILoader  # type: ignore[no-redef]
    from ingestion.event_registry_loader import EventRegistryLoader  # type: ignore[no-redef]
    from ingestion.etherscan_loader import EtherscanLoader  # type: ignore[no-redef]
    from ingestion.base_loader import LoaderResult, SkipLoader  # type: ignore[no-redef]

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0
_BROKER_API_CALLED = False

_NEWSAPI_MAX_ARTICLES = 20
_ER_MAX_ARTICLES = 20
_ETHERSCAN_MAX_TRANSACTIONS = 25
_DEFAULT_TIMEOUT = 15
_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 2.0

_ETHERSCAN_CHAIN_URLS: dict[str, str] = {
    "ethereum": "https://api.etherscan.io/api",
}


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
    broker_api_called: bool = _BROKER_API_CALLED

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
            "broker_api_called": self.broker_api_called,
        }


@dataclass
class Phase2RunReport:
    """Aggregate report from a full Phase 2 run."""

    dry_run: bool
    sources: list[SourceRunResult] = field(default_factory=list)
    total_fetched: int = 0
    total_persisted: int = 0
    advisory_status: str = _ADVISORY_STATUS
    execution_gate: str = _EXECUTION_GATE
    ai_execution_count: int = _AI_EXECUTION_COUNT
    human_review_required: bool = True
    broker_api_called: bool = _BROKER_API_CALLED
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
            "broker_api_called": self.broker_api_called,
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


def _normalize_newsapi_record(rec: dict[str, Any]) -> dict[str, Any]:
    url = str(rec.get("url", ""))
    return {
        "event_id": _stable_event_id("newsapi", url),
        "source_name": "newsapi",
        "signal_type": "news_article",
        "title": str(rec.get("title", "")),
        "url": url,
        "description": rec.get("description"),
        "published_at": rec.get("published_at"),
        "publisher": rec.get("source_name"),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
    }


def _normalize_event_registry_record(rec: dict[str, Any]) -> dict[str, Any]:
    url = str(rec.get("url", ""))
    return {
        "event_id": _stable_event_id("event_registry", url),
        "source_name": "event_registry",
        "signal_type": "news_article",
        "title": str(rec.get("title", "")),
        "url": url,
        "date_time": rec.get("date_time"),
        "publisher": rec.get("source_name"),
        "body": rec.get("body"),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
    }


def _normalize_etherscan_record(rec: dict[str, Any]) -> dict[str, Any]:
    tx_hash = str(rec.get("hash", ""))
    short_hash = (tx_hash[:12] + "...") if len(tx_hash) > 12 else tx_hash
    return {
        "event_id": _stable_event_id("etherscan", tx_hash),
        "source_name": "etherscan",
        "signal_type": "blockchain_transaction",
        "title": f"Tx {short_hash}" if tx_hash else "Ethereum Transaction",
        "hash": tx_hash,
        "from_address": str(rec.get("from_address", "")),
        "to_address": str(rec.get("to_address", "")),
        "value_wei": str(rec.get("value_wei", "0")),
        "block_number": str(rec.get("block_number", "")),
        "timestamp": str(rec.get("timestamp", "")),
        "gas_used": str(rec.get("gas_used", "")),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
    }


_NORMALIZERS: dict[str, Any] = {
    "newsapi": _normalize_newsapi_record,
    "event_registry": _normalize_event_registry_record,
    "etherscan": _normalize_etherscan_record,
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


def run_phase2(
    dry_run: bool = True,
    newsapi_query: str = "markets economy finance",
    newsapi_max_articles: int = _NEWSAPI_MAX_ARTICLES,
    newsapi_language: str = "en",
    event_registry_keywords: list[str] | None = None,
    event_registry_max_articles: int = _ER_MAX_ARTICLES,
    event_registry_language: str = "eng",
    etherscan_address: str | None = None,
    etherscan_max_transactions: int = _ETHERSCAN_MAX_TRANSACTIONS,
    etherscan_chain: str = "ethereum",
    sources: list[str] | None = None,
) -> Phase2RunReport:
    """
    Run Phase 2 live source ingestion: NewsAPI, Event Registry, and Etherscan.

    Parameters
    ----------
    dry_run:
        When True, fetch and normalize signals but do NOT persist to SQLite
        and do NOT write source_run_log entries.
    etherscan_address:
        Ethereum address to fetch transactions for. If None, Etherscan skips cleanly.
    etherscan_max_transactions:
        Maximum number of transactions to fetch (default 25).
    etherscan_chain:
        Chain name. Currently only "ethereum" is supported. Unknown chains fall back
        to ethereum URL.
    sources:
        Subset of Phase 2 sources to run. Defaults to ["newsapi"].
        Pass ["etherscan"] or any combination. Missing API keys skip cleanly.
    """
    if sources is None:
        sources = ["newsapi"]

    report = Phase2RunReport(dry_run=dry_run, run_at=utc_timestamp())

    etherscan_base_url = _ETHERSCAN_CHAIN_URLS.get(
        etherscan_chain, _ETHERSCAN_CHAIN_URLS["ethereum"]
    )

    all_loaders: dict[str, Any] = {
        "newsapi": NewsAPILoader(
            query=newsapi_query,
            max_articles=newsapi_max_articles,
            language=newsapi_language,
            timeout=_DEFAULT_TIMEOUT,
        ),
        "event_registry": EventRegistryLoader(
            keywords=event_registry_keywords,
            max_articles=event_registry_max_articles,
            language=event_registry_language,
            timeout=_DEFAULT_TIMEOUT,
        ),
        "etherscan": EtherscanLoader(
            address=etherscan_address,
            max_records=etherscan_max_transactions,
            base_url=etherscan_base_url,
        ),
    }

    for source_name in sources:
        if source_name not in all_loaders:
            continue
        loader = all_loaders[source_name]
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


__all__ = [
    "SourceRunResult",
    "Phase2RunReport",
    "run_phase2",
    "_stable_event_id",
    "_normalize_newsapi_record",
    "_normalize_event_registry_record",
    "_normalize_etherscan_record",
    "_persist_events",
    "_log_run",
]
