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
- Polymarket markets are domain-gated: only politics/finance/geopolitics/economy
  markets are accepted; sports/entertainment/meme/gaming markets are rejected.

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
import os
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
    accepted_count: int = 0
    rejected_count: int = 0
    skipped_reason: str = ""
    error_message: str = ""
    timestamp_utc: str = ""
    duration_ms: int = 0
    events_persisted: int = 0
    advisory_status: str = _ADVISORY_STATUS
    status_detail: str = ""
    missing_env_var: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "fetched_count": self.fetched_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "skipped_reason": self.skipped_reason,
            "error_message": self.error_message,
            "timestamp_utc": self.timestamp_utc,
            "duration_ms": self.duration_ms,
            "events_persisted": self.events_persisted,
            "advisory_status": self.advisory_status,
            "status_detail": self.status_detail,
            "missing_env_var": self.missing_env_var,
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


def _normalize_polymarket_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    """
    Normalize a raw Polymarket record.

    Returns None when the market is rejected by the domain classifier.
    Rejected records are never written to SQLite.
    Accepted records carry domain, matched_terms, and full advisory-lock fields.
    """
    try:
        from scripts.live_signal_filters import classify_market_domain
    except ModuleNotFoundError:
        from live_signal_filters import classify_market_domain  # type: ignore[no-redef]

    title = str(rec.get("question", ""))
    category = str(rec.get("category", "") or "")
    tags: list[str] = rec.get("tags") or []
    market_id = str(rec.get("market_id", ""))

    classification = classify_market_domain(title, category or None, tags or None)

    if not classification["allowed"]:
        import logging
        logging.getLogger(__name__).debug(
            "REJECTED_POLYMARKET_DOMAIN market_id=%s title=%r category=%r "
            "tags=%r blocked_terms=%r reason=%s",
            market_id,
            title,
            category,
            tags,
            classification["blocked_terms"],
            classification["reason"],
        )
        return None

    return {
        "event_id": _stable_event_id("polymarket", market_id),
        "source_name": "polymarket",
        "signal_type": "prediction_market",
        "title": title,
        "market_id": market_id,
        "volume": rec.get("volume"),
        "liquidity": rec.get("liquidity"),
        "end_date": rec.get("end_date"),
        "active": rec.get("active"),
        "domain": classification["domain"],
        "matched_terms": classification["matched_terms"],
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


def _cleanup_rejected_polymarket_events() -> int:
    """
    Delete persisted Polymarket signal_events that fail the current domain classifier.
    Returns the number of rows deleted.  Fail-safe — never raises.
    """
    try:
        try:
            from scripts.persistence import get_signal_events, delete_signal_events_by_ids
            from scripts.live_signal_filters import classify_market_domain
        except ModuleNotFoundError:
            from persistence import get_signal_events, delete_signal_events_by_ids  # type: ignore[no-redef]
            from live_signal_filters import classify_market_domain  # type: ignore[no-redef]
    except Exception:
        return 0

    try:
        rows = get_signal_events(source_name="polymarket", limit=5000)
    except Exception:
        return 0

    bad_ids: list[int] = []
    for row in rows:
        try:
            payload = row.get("raw_payload") or {}
            if isinstance(payload, str):
                import json as _json
                payload = _json.loads(payload)
            title = str(payload.get("title", "") or payload.get("question", ""))
            category = str(payload.get("category", "") or "")
            tags = payload.get("matched_terms") or []
            result = classify_market_domain(title, category or None, tags or None)
            if not result["allowed"]:
                bad_ids.append(row["id"])
        except Exception:
            pass

    if not bad_ids:
        return 0

    try:
        return delete_signal_events_by_ids(bad_ids)
    except Exception:
        return 0


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
    sec_default_watchlist: bool = False,
    sources: list[str] | None = None,
) -> Phase1RunReport:
    """
    Run Phase 1 live source ingestion: Polymarket, GDELT, SEC EDGAR.

    Parameters
    ----------
    dry_run:
        When True, fetch and normalize signals but do NOT persist to SQLite
        and do NOT write source_run_log entries.
    sec_default_watchlist:
        When True and no sec_cik supplied, iterate over the built-in default
        watchlist (Apple, Microsoft, Nvidia, Tesla, Amazon, Meta, Alphabet).
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
            use_default_watchlist=sec_default_watchlist,
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
            reason = loader_result.skip_reason
            reason_lower = reason.lower()
            # Classify the skip reason into a semantic status
            missing_var = ""
            if "[rate_limited]" in reason_lower:
                run_status = "rate_limited"
            elif "[timeout]" in reason_lower:
                run_status = "timeout"
            elif "[placeholder]" in reason_lower:
                run_status = "placeholder"
            elif "SEC_USER_AGENT" in reason or "no cik provided" in reason_lower:
                run_status = "skipped"
                if "SEC_USER_AGENT" in reason:
                    missing_var = "SEC_USER_AGENT"
            elif (
                "unreachable" in reason_lower
                or "http error" in reason_lower
                or "httperror" in reason_lower
            ):
                run_status = "http_error"
            else:
                run_status = "skipped"
            src_result = SourceRunResult(
                source_name=source_name,
                status=run_status,
                fetched_count=0,
                skipped_reason=reason,
                timestamp_utc=ts,
                duration_ms=duration_ms,
                status_detail=reason,
                missing_env_var=missing_var,
            )
        else:
            raw_count = len(loader_result.records)
            normalized = [normalizer(rec) for rec in loader_result.records]
            # Filter out None (domain-rejected) records — only applies to Polymarket
            events = [e for e in normalized if e is not None]
            rejected_count = raw_count - len(events)
            persisted = 0
            if not dry_run:
                # Purge existing bad Polymarket rows before inserting new ones
                if source_name == "polymarket":
                    _cleanup_rejected_polymarket_events()
                persisted = _persist_events(events, source_name, ts)
            # Set OK_FILTERED when source responded but all records were domain-rejected
            if source_name == "polymarket" and raw_count > 0 and len(events) == 0:
                run_status = "ok_filtered"
            else:
                run_status = "ok"
            detail = ""
            if source_name == "polymarket":
                detail = (
                    f"domain gate active — accepted {len(events)}/{raw_count}"
                )
            src_result = SourceRunResult(
                source_name=source_name,
                status=run_status,
                fetched_count=raw_count,
                accepted_count=len(events),
                rejected_count=rejected_count,
                timestamp_utc=ts,
                duration_ms=duration_ms,
                events_persisted=persisted,
                status_detail=detail,
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


# ---------------------------------------------------------------------------
# Standalone diagnostic CLI  (python scripts/live_source_runner.py)
# ---------------------------------------------------------------------------

_PHASE2_ENV_REQS: dict[str, str] = {
    "newsapi": "NEWS_API_KEY or NEWSAPI_KEY",
    "event_registry": "EVENT_REGISTRY_API_KEY",
    "etherscan": "ETHERSCAN_API_KEY",
    "grok_xai": "XAI_API_KEY or GROK_API_KEY",
    "sec_edgar": "SEC_USER_AGENT",
    "market_data": "",   # no key — uses yfinance
    "india": "",         # no key — public NSE endpoints
    "global_filings": "", # no key (ASX only active provider)
    "asia_disclosure": "", # all placeholder — no key
}

_PHASE2_IMPLEMENTED: set[str] = {"newsapi", "event_registry", "etherscan", "grok_xai", "market_data", "india", "global_filings", "asia_disclosure"}


def _check_env_key(env_spec: str) -> tuple[bool, str]:
    """Return (present, label) for an env var spec like 'FOO or BAR'."""
    if not env_spec:
        return True, ""
    for var in [v.strip() for v in env_spec.replace(" or ", "|").split("|")]:
        if os.environ.get(var):
            return True, var
    # None present
    return False, env_spec


def _build_diag_rows(phase1_report: "Phase1RunReport") -> list[dict]:
    """Build a combined row list for all 11 sources."""
    rows: list[dict] = []

    # Phase 1 sources from live run
    p1_map = {s.source_name: s for s in phase1_report.sources}

    for src_name in _PHASE1_SOURCES:
        if src_name not in p1_map:
            rows.append({
                "source": src_name,
                "raw": 0, "accepted": 0, "rejected": 0,
                "status": "NOT_RUN", "detail": "",
            })
            continue
        sr = p1_map[src_name]
        if sr.status == "skipped":
            reason = sr.skipped_reason or ""
            if "SEC_USER_AGENT" in reason or "sec_user_agent" in reason.lower():
                st = "MISSING_CONFIG"
                detail = "SEC_USER_AGENT missing"
            elif "unreachable" in reason.lower():
                st = "HTTP_ERROR"
                detail = reason[:60]
            else:
                st = "SKIPPED"
                detail = reason[:60]
        else:
            accepted = sr.accepted_count if sr.accepted_count or sr.rejected_count else sr.fetched_count
            rejected = sr.rejected_count
            st = "OK"
            detail = sr.status_detail or "wrote live signals"
            rows.append({
                "source": src_name,
                "raw": sr.fetched_count,
                "accepted": accepted,
                "rejected": rejected,
                "status": st, "detail": detail,
            })
            continue
        rows.append({
            "source": src_name,
            "raw": 0, "accepted": 0, "rejected": 0,
            "status": st, "detail": detail,
        })

    # Phase 2 sources — diagnostic only (no live fetch in this mode)
    p2_sources = ["newsapi", "event_registry", "etherscan", "grok_xai",
                  "market_data", "india", "global_filings", "asia_disclosure"]
    for src_name in p2_sources:
        env_spec = _PHASE2_ENV_REQS.get(src_name, "")
        present, _var = _check_env_key(env_spec)
        if not present:
            rows.append({
                "source": src_name,
                "raw": 0, "accepted": 0, "rejected": 0,
                "status": "MISSING_API_KEY",
                "detail": f"{env_spec} missing",
            })
        elif src_name not in _PHASE2_IMPLEMENTED:
            rows.append({
                "source": src_name,
                "raw": 0, "accepted": 0, "rejected": 0,
                "status": "NOT_IMPLEMENTED",
                "detail": "fetcher not implemented",
            })
        else:
            rows.append({
                "source": src_name,
                "raw": 0, "accepted": 0, "rejected": 0,
                "status": "OK_KEY_PRESENT",
                "detail": "API key present — run phase2 CLI to ingest",
            })
    return rows


_DISPLAY_NAMES: dict[str, str] = {
    "polymarket": "Polymarket",
    "gdelt": "GDELT",
    "sec_edgar": "SEC EDGAR",
    "newsapi": "NewsAPI",
    "event_registry": "Event Registry",
    "etherscan": "Etherscan",
    "grok_xai": "Grok/xAI",
    "market_data": "Market Data",
    "india": "India",
    "global_filings": "Global Filings",
    "asia_disclosure": "Asia Disclosure",
}


def _print_diag_table(rows: list[dict]) -> None:
    header = f"{'Source':<18} {'Raw':>5} {'Accepted':>8} {'Rejected':>8}  {'Status':<25} {'Detail'}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for r in rows:
        name = _DISPLAY_NAMES.get(r["source"], r["source"])
        print(
            f"{name:<18} {r['raw']:>5} {r['accepted']:>8} {r['rejected']:>8}  "
            f"{r['status']:<25} {r['detail']}"
        )
    print(sep)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    _REPO_ROOT = Path(__file__).resolve().parents[1]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    print("=" * 70)
    print("Live Source Runner — Diagnostic Mode")
    print("Advisory policy: ADVISORY_ONLY | HUMAN_REVIEW_REQUIRED |"
          " execution_gate=LOCKED | ai_executions=0")
    print("=" * 70)
    print()

    # Env-var presence summary (no values printed)
    env_checks = {
        "NEWS_API_KEY": os.environ.get("NEWS_API_KEY") or os.environ.get("NEWSAPI_KEY"),
        "EVENT_REGISTRY_API_KEY": os.environ.get("EVENT_REGISTRY_API_KEY"),
        "ETHERSCAN_API_KEY": os.environ.get("ETHERSCAN_API_KEY"),
        "XAI_API_KEY": os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"),
        "SEC_USER_AGENT": os.environ.get("SEC_USER_AGENT"),
    }
    print("Env-var presence:")
    for var, val in env_checks.items():
        print(f"  {var:<28} {'present' if val else 'MISSING'}")
    print()

    print("Running Phase 1 (Polymarket, GDELT, SEC EDGAR) in dry-run mode…")
    phase1_report = run_phase1(dry_run=True)
    print()

    rows = _build_diag_rows(phase1_report)
    _print_diag_table(rows)
    print()
    print(f"Phase 1 total fetched:   {phase1_report.total_fetched}")
    print(f"Phase 1 advisory_status: {phase1_report.advisory_status}")
    print(f"Phase 1 execution_gate:  {phase1_report.execution_gate}")
    print(f"Phase 1 ai_executions:   {phase1_report.ai_execution_count}")
    print()
    print("To run Phase 2 sources:")
    print("  python scripts/run_live_sources_phase2.py --source newsapi --dry-run")
    print("  python scripts/run_live_sources_phase2.py --source market_data --dry-run")
    print("  python scripts/run_live_sources_phase2.py --source india --dry-run")
