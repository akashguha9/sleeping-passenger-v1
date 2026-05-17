"""
Phase 2 Live Source Runner — read-only ingestion for NewsAPI, Event Registry,
Etherscan, Grok/xAI interpretation, Market Data, India, Global Filings,
and Asia Disclosure.

Safety contract
---------------
- READ-ONLY. No write to any external system.
- No broker API calls. No order placement. No CLOB trading.
- No private keys, wallet signing, transaction broadcasting, or token approvals.
- All signals carry advisory_status="ADVISORY_ONLY" and human_review_required=True.
- execution_gate="LOCKED" on every record.
- AI execution count is always 0.
- broker_api_called is always False.
- broker_order_id is always "NONE".
- Dry-run mode fetches and normalizes but does NOT persist anything.
- NewsAPI skips cleanly when NEWS_API_KEY env var is unset.
- Event Registry skips cleanly when EVENT_REGISTRY_API_KEY env var is unset.
- Etherscan skips cleanly when ETHERSCAN_API_KEY env var is unset or no address given.
- Grok/xAI skips cleanly when XAI_API_KEY env var is unset.
- Grok/xAI output is hypothesis/interpretation only, never truth.
- Global Filings skips cleanly when no active providers reachable.
- Asia Disclosure skips cleanly when no active providers reachable (all are placeholders).

Rate-limit-safe defaults
------------------------
- NewsAPI: 20 articles per call, 15 s timeout
- Event Registry: 20 articles per call, 15 s timeout
- Etherscan: 25 transactions per call, 15 s timeout
- Grok/xAI: 1 interpretation per call, 30 s timeout
- Global Filings: 50 records per call, 15 s timeout
- Asia Disclosure: 50 records per call, 15 s timeout
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
    from scripts.ingestion.grok_interpreter import GrokInterpreter
    from scripts.ingestion.market_data_loader import MarketDataLoader
    from scripts.ingestion.india_loader import IndiaLoader
    from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
    from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
    from scripts.ingestion.base_loader import LoaderResult, SkipLoader
except ModuleNotFoundError:
    from runtime_common import utc_timestamp  # type: ignore[no-redef]
    from ingestion.newsapi_loader import NewsAPILoader  # type: ignore[no-redef]
    from ingestion.event_registry_loader import EventRegistryLoader  # type: ignore[no-redef]
    from ingestion.etherscan_loader import EtherscanLoader  # type: ignore[no-redef]
    from ingestion.grok_interpreter import GrokInterpreter  # type: ignore[no-redef]
    from ingestion.market_data_loader import MarketDataLoader  # type: ignore[no-redef]
    from ingestion.india_loader import IndiaLoader  # type: ignore[no-redef]
    from ingestion.global_filings_loader import GlobalFilingsLoader  # type: ignore[no-redef]
    from ingestion.asia_disclosure_loader import AsiaDisclosureLoader  # type: ignore[no-redef]
    from ingestion.base_loader import LoaderResult, SkipLoader  # type: ignore[no-redef]

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0
_BROKER_API_CALLED = False

_NEWSAPI_MAX_ARTICLES = 20
_ER_MAX_ARTICLES = 20
_ETHERSCAN_MAX_TRANSACTIONS = 25
_GROK_MAX_ITEMS = 1
_DEFAULT_TIMEOUT = 15
_GROK_TIMEOUT = 30
_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 2.0

_ETHERSCAN_CHAIN_URLS: dict[str, str] = {
    # Etherscan deprecated v1 in 2024; v2 is the supported endpoint and
    # requires the chainid parameter, which EtherscanLoader sends by default.
    "ethereum": "https://api.etherscan.io/v2/api",
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


def _normalize_market_data_record(rec: dict[str, Any]) -> dict[str, Any]:
    symbol = str(rec.get("symbol") or rec.get("ticker") or "").upper()
    ts = str(rec.get("timestamp", ""))
    provider = str(rec.get("provider") or "yahoo")
    latest_price = rec.get("latest_price") if rec.get("latest_price") is not None else rec.get("close")

    title_parts = [symbol or "MARKET"]
    if latest_price is not None:
        try:
            title_parts.append(f"@ {float(latest_price):.4f}")
        except (TypeError, ValueError):
            pass
    if provider:
        title_parts.append(f"({provider})")

    return {
        "event_id": _stable_event_id("market_data", symbol, ts),
        "source_name": "market_data",
        "signal_type": "market_price",
        "title": " ".join(title_parts),
        "symbol": symbol,
        "provider": provider,
        "period": rec.get("period"),
        "interval": rec.get("interval"),
        "latest_price": latest_price,
        "previous_close": rec.get("previous_close"),
        "price_change": rec.get("price_change"),
        "price_change_pct": rec.get("price_change_pct"),
        "volume": rec.get("volume"),
        "average_volume": rec.get("average_volume"),
        "volume_change_ratio": rec.get("volume_change_ratio"),
        "high": rec.get("high"),
        "low": rec.get("low"),
        "open": rec.get("open"),
        "close": rec.get("close"),
        "timestamp": ts,
        "market_confirmation_score": rec.get("market_confirmation_score", 0.0),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
    }


def _normalize_grok_record(rec: dict[str, Any]) -> dict[str, Any]:
    created_at = str(rec.get("created_at", ""))
    prompt = str(rec.get("source_prompt", ""))
    topic = str(rec.get("interpreted_topic", ""))
    return {
        "event_id": _stable_event_id("grok_xai", prompt, created_at),
        "source_name": "grok_xai",
        "signal_type": "ai_interpretation",
        "title": topic or "Grok Market Interpretation",
        "model_name": str(rec.get("model_name", "")),
        "source_prompt": prompt,
        "interpreted_topic": topic,
        "narrative_frame": str(rec.get("narrative_frame", "")),
        "contradiction_flags": rec.get("contradiction_flags", []),
        "confidence_score": rec.get("confidence_score"),
        "summary_text": str(rec.get("summary_text", "")),
        "grok_response": str(rec.get("grok_response", "")),
        "created_at": created_at,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
    }


def _normalize_india_record(rec: dict[str, Any]) -> dict[str, Any]:
    regulatory_source = str(rec.get("regulatory_source") or rec.get("source") or "india")
    index_name = str(rec.get("index_name", ""))
    url = str(rec.get("regulatory_url", ""))
    last_price = rec.get("last_price")
    pct = rec.get("percent_change")

    title_parts = [index_name or "India Signal"]
    if last_price is not None:
        try:
            title_parts.append(f"@ {float(last_price):.2f}")
        except (TypeError, ValueError):
            pass
    if pct is not None:
        try:
            pct_f = float(pct)
            sign = "+" if pct_f >= 0 else ""
            title_parts.append(f"({sign}{pct_f:.2f}%)")
        except (TypeError, ValueError):
            pass

    return {
        "event_id": _stable_event_id("india", regulatory_source, index_name or url),
        "source_name": "india",
        "signal_type": "india_market_signal",
        "title": " ".join(title_parts),
        "index_name": index_name,
        "last_price": last_price,
        "change": rec.get("change"),
        "percent_change": pct,
        "regulatory_source": regulatory_source,
        "regulatory_url": url,
        "regulatory_note": rec.get("regulatory_note"),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
    }


def _normalize_global_filings_record(rec: dict[str, Any]) -> dict[str, Any]:
    provider = str(rec.get("provider") or "global_filings")
    issuer_name = str(rec.get("issuer_name") or "")
    ticker = str(rec.get("ticker_or_identifier") or "")
    exchange = str(rec.get("exchange_or_regulator") or "")
    jurisdiction = str(rec.get("jurisdiction") or "")
    # Keep raw value for title (don't apply fallback label to empty input)
    _raw_disclosure_type = rec.get("disclosure_type") or ""
    disclosure_type = _raw_disclosure_type or "regulatory_disclosure"
    published_at = str(rec.get("published_at") or "")
    url = str(rec.get("url") or "")
    summary = str(rec.get("summary") or "")

    title_parts: list[str] = []
    if issuer_name:
        title_parts.append(issuer_name)
    if ticker and ticker != issuer_name:
        title_parts.append(f"({ticker})")
    if _raw_disclosure_type:
        title_parts.append(f"— {_raw_disclosure_type.replace('_', ' ').title()}")
    title = " ".join(title_parts) if title_parts else summary or "Global Regulatory Filing"

    return {
        "event_id": _stable_event_id(
            "global_filings", provider, ticker or issuer_name, published_at, url
        ),
        "source_name": "global_filings",
        "signal_type": "regulatory_disclosure",
        "title": title,
        "issuer_name": issuer_name,
        "ticker_or_identifier": ticker,
        "exchange_or_regulator": exchange,
        "jurisdiction": jurisdiction,
        "disclosure_type": disclosure_type,
        "published_at": published_at,
        "url": url,
        "summary": summary,
        "provider": provider,
        "raw_payload": rec.get("raw_payload") or {},
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
        "broker_order_id": "NONE",
    }


def _normalize_asia_disclosure_record(rec: dict[str, Any]) -> dict[str, Any]:
    provider = str(rec.get("provider") or "asia_disclosure")
    issuer_name = str(rec.get("issuer_name") or "")
    ticker = str(rec.get("ticker_or_identifier") or "")
    exchange = str(rec.get("exchange_or_regulator") or "")
    jurisdiction = str(rec.get("jurisdiction") or "")
    country = str(rec.get("country") or "")
    disclosure_system = str(rec.get("disclosure_system") or "")
    source_class = str(rec.get("source_class") or "")
    doc_id = str(rec.get("doc_id") or "")
    receipt_no = str(rec.get("receipt_no") or "")
    _raw_disclosure_type = rec.get("disclosure_type") or ""
    disclosure_type = _raw_disclosure_type or "asia_regulatory_disclosure"
    published_at = str(rec.get("published_at") or "")
    url = str(rec.get("url") or "")
    title_raw = str(rec.get("title") or "")
    summary = str(rec.get("summary") or "")
    language = str(rec.get("language") or "")

    title_parts: list[str] = []
    if issuer_name:
        title_parts.append(issuer_name)
    if ticker and ticker != issuer_name:
        title_parts.append(f"({ticker})")
    if _raw_disclosure_type:
        title_parts.append(f"— {_raw_disclosure_type.replace('_', ' ').title()}")
    title = (
        " ".join(title_parts) if title_parts
        else title_raw or summary or "Asia Regulatory Disclosure"
    )

    return {
        "event_id": _stable_event_id(
            "asia_disclosure",
            provider,
            ticker or issuer_name or doc_id or receipt_no,
            published_at,
            url,
        ),
        "source_name": "asia_disclosure",
        "signal_type": "asia_regulatory_disclosure",
        "title": title,
        "issuer_name": issuer_name,
        "ticker_or_identifier": ticker,
        "exchange_or_regulator": exchange,
        "jurisdiction": jurisdiction,
        "country": country,
        "disclosure_system": disclosure_system,
        "source_class": source_class,
        "doc_id": doc_id,
        "receipt_no": receipt_no,
        "disclosure_type": disclosure_type,
        "published_at": published_at,
        "url": url,
        "summary": summary,
        "provider": provider,
        "language": language,
        "raw_payload": rec.get("raw_payload") or {},
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": _BROKER_API_CALLED,
        "broker_order_id": "NONE",
        "execution_permission": False,
        "can_execute": False,
    }


_NORMALIZERS: dict[str, Any] = {
    "newsapi": _normalize_newsapi_record,
    "event_registry": _normalize_event_registry_record,
    "etherscan": _normalize_etherscan_record,
    "grok_xai": _normalize_grok_record,
    "market_data": _normalize_market_data_record,
    "india": _normalize_india_record,
    "global_filings": _normalize_global_filings_record,
    "asia_disclosure": _normalize_asia_disclosure_record,
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
    grok_query: str | None = None,
    grok_max_items: int = _GROK_MAX_ITEMS,
    grok_model: str = "grok-3-mini",
    market_data_tickers: list[str] | None = None,
    market_data_period: str = "5d",
    market_data_interval: str = "1d",
    market_data_provider: str = "yahoo",
    india_symbols: list[str] | None = None,
    india_date: str | None = None,
    india_max_items: int = 50,
    global_filings_providers: list[str] | None = None,
    global_filings_query: str | None = None,
    global_filings_region: str | None = None,
    global_filings_max_items: int = 50,
    asia_disclosure_providers: list[str] | None = None,
    asia_disclosure_query: str | None = None,
    asia_disclosure_jurisdiction: str | None = None,
    asia_disclosure_max_items: int = 50,
    sources: list[str] | None = None,
) -> Phase2RunReport:
    """
    Run Phase 2 live source ingestion: NewsAPI, Event Registry, Etherscan, Grok/xAI,
    Market Data (Phase C.5), India sources (Phase C.6), Global Filings (Phase C.7),
    and Asia Disclosure (Phase C.8).

    Parameters
    ----------
    dry_run:
        When True, fetch and normalize signals but do NOT persist to SQLite
        and do NOT write source_run_log entries.
    etherscan_address:
        Ethereum address to fetch transactions for. If None, Etherscan skips cleanly.
    grok_query:
        Custom prompt for Grok/xAI. Uses GrokInterpreter default if None.
    grok_max_items:
        Maximum interpretation items to request per call (default 1).
    grok_model:
        xAI model name (default "grok-beta").
    market_data_tickers:
        List of ticker symbols (e.g. ["SPY", "AAPL", "BTC-USD"]). Defaults to
        ["SPY", "QQQ", "GLD", "TLT"] when None.
    market_data_period:
        yfinance history period (default "5d").
    market_data_interval:
        yfinance bar interval (default "1d").
    market_data_provider:
        Data provider — only "yahoo" is active; paid-provider names skip cleanly.
    india_symbols:
        NSE index names to fetch (e.g. ["NIFTY 50", "NIFTY BANK"]). Defaults to
        ["NIFTY 50", "NIFTY BANK", "INDIA VIX"] when None.
    india_date:
        Informational date filter (ISO string). NSE API always returns latest data.
    india_max_items:
        Maximum India records to return (default 50).
    global_filings_providers:
        Specific provider names to use (e.g. ["asx"]). Defaults to all configured
        providers. Unsupported or inactive providers skip cleanly.
    global_filings_query:
        Filter string applied to issuer name and disclosure description.
    global_filings_region:
        Jurisdiction code to filter providers (e.g. "AU", "HK", "SG"). Defaults to all.
    global_filings_max_items:
        Maximum global filings records to return (default 50).
    asia_disclosure_providers:
        Specific Asia provider names (e.g. ["hkex", "sse"]). Defaults to all configured.
        All are currently placeholders; any active provider would be used automatically.
    asia_disclosure_query:
        Filter string applied to issuer name, ticker, title, and disclosure description.
    asia_disclosure_jurisdiction:
        Jurisdiction code to filter providers (e.g. "CN", "HK", "JP", "SG", "KR").
    asia_disclosure_max_items:
        Maximum Asia disclosure records to return (default 50).
    sources:
        Subset of Phase 2 sources to run. Defaults to ["newsapi"].
        Missing API keys / unavailable dependencies skip cleanly.
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
        "grok_xai": GrokInterpreter(
            prompt=grok_query,
            model=grok_model,
            max_items=grok_max_items,
            timeout=_GROK_TIMEOUT,
        ),
        "market_data": MarketDataLoader(
            tickers=market_data_tickers,
            period=market_data_period,
            interval=market_data_interval,
            provider=market_data_provider,
        ),
        "india": IndiaLoader(
            symbols=india_symbols,
            date=india_date,
            max_items=india_max_items,
        ),
        "global_filings": GlobalFilingsLoader(
            providers=global_filings_providers,
            query=global_filings_query,
            region=global_filings_region,
            max_items=global_filings_max_items,
        ),
        "asia_disclosure": AsiaDisclosureLoader(
            providers=asia_disclosure_providers,
            query=asia_disclosure_query,
            jurisdiction=asia_disclosure_jurisdiction,
            max_items=asia_disclosure_max_items,
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
            reason = loader_result.skip_reason
            reason_lower = reason.lower()
            if "[rate_limited]" in reason_lower:
                run_status = "rate_limited"
            elif "[timeout]" in reason_lower:
                run_status = "timeout"
            elif "[placeholder]" in reason_lower:
                run_status = "placeholder"
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
    "_normalize_grok_record",
    "_normalize_market_data_record",
    "_normalize_india_record",
    "_normalize_global_filings_record",
    "_normalize_asia_disclosure_record",
    "_persist_events",
    "_log_run",
]
