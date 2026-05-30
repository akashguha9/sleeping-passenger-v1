"""Read-only news provider fallback chain (Kanté P2).

Presses real read-only news providers in priority order::

    P_news = [GDELT_PUBLIC, NEWSAPI, EVENT_REGISTRY]

* GDELT's public DOC API needs no key (public read-only path).
* NewsAPI / Event Registry are gated on an env key whose *value* is NEVER
  logged (only ``api_key_present`` booleans appear in the report).
* Network is NEVER touched unless ``allow_network=True``. Tests inject a
  deterministic ``transports`` mapping so the fetch/normalize/enrich/map path
  runs with NO network and NO key.

For each provider we try a small set of conservative Rheinmetall-focused
queries, normalize every raw article into a SignalEvent-like row, run the
deterministic entity/country enrichment + entity->ticker mapping, and classify
the provider honestly. The chain falls through on failure/empty and stops at
the first provider that is genuinely ``LIVE_VERIFIED`` (>=1 fresh row).

Hard safety contract (mirrors the rest of the MVP):
    * Read-of-news only. NEVER trades, NEVER places an order, NEVER reaches a
      broker/execution endpoint.
    * A misbehaving / empty / timed-out / unauthorized provider degrades to an
      honest status. ``LIVE_VERIFIED`` is NEVER claimed without a fresh row.
    * Unmapped rows are RETAINED with an explicit mapping_failure_reason — they
      are never dropped (evidence / data-quality feedback).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.entity_ticker_mapper import DEFAULT_THETA_MAP, map_event_to_tickers
    from scripts.news_entity_country_enrichment import enrich_news_event
    from scripts.provider_secret_redaction import (
        assert_no_secret,
        collect_secret_values,
        key_present,
        provider_key_fields,
    )
    from scripts.signal_events_to_daily_payload import NEWS_TTL_HOURS, freshness
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from entity_ticker_mapper import DEFAULT_THETA_MAP, map_event_to_tickers
    from news_entity_country_enrichment import enrich_news_event
    from provider_secret_redaction import (
        assert_no_secret,
        collect_secret_values,
        key_present,
        provider_key_fields,
    )
    from signal_events_to_daily_payload import NEWS_TTL_HOURS, freshness


# Provider identifiers.
GDELT_PUBLIC = "gdelt"
NEWSAPI = "newsapi"
EVENT_REGISTRY = "event_registry"

NEWS_PROVIDER_PRIORITY: tuple[str, ...] = (GDELT_PUBLIC, NEWSAPI, EVENT_REGISTRY)

# Provider -> accepted env-var spellings (canonical first; None = public).
NEWS_PROVIDER_ENV: dict[str, tuple[str, ...] | None] = {
    GDELT_PUBLIC: None,
    NEWSAPI: ("NEWS_API_KEY", "NEWSAPI_KEY"),
    EVENT_REGISTRY: ("EVENT_REGISTRY_API_KEY", "EVENTREGISTRY_API_KEY"),
}

# News providers are READ_ONLY_NEWS_DATA — never broker/execution.
PROVIDER_CATEGORY = "READ_ONLY_NEWS_DATA"
BROKER_OR_EXECUTION_PROVIDERS: frozenset[str] = frozenset(
    {"alpaca", "broker", "ibkr", "interactive_brokers", "execute", "order"}
)

# Honest status vocabulary (verbatim from the sprint spec).
LIVE_VERIFIED = "LIVE_VERIFIED"
OK_EMPTY = "OK_EMPTY"
NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
PROVIDER_ERROR = "PROVIDER_ERROR"
PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
NETWORK_DISABLED = "NETWORK_DISABLED"
DEGRADED_EMPTY = "DEGRADED_EMPTY"

# Conservative Rheinmetall query set (read-only; small row caps).
RHEINMETALL_QUERIES: tuple[str, ...] = (
    "Rheinmetall",
    "Rheinmetall RHM",
    "Rheinmetall defense Germany",
    "Rheinmetall order contract earnings",
    "RHM.DE Rheinmetall",
)
MAX_ROWS_PER_PROVIDER = 20
HTTP_TIMEOUT_SECONDS = 8.0

# A transport fetches raw article dicts for one query string. It is read-only
# and may raise to signal a transport failure (mapped to an honest status).
NewsTransport = Callable[[str], "list[dict[str, Any]]"]


# ---------------------------------------------------------------------------
# Honest transport-failure signalling.
# ---------------------------------------------------------------------------
class NewsProviderTimeout(Exception):
    """Provider request timed out."""


class NewsProviderUnreachable(Exception):
    """Provider host unreachable / DNS / connection refused."""


class NewsProviderAuthFailed(Exception):
    """Provider rejected the credential (401/403)."""


class NewsProviderRateLimited(Exception):
    """Provider returned 429."""


def _status_for_exception(exc: Exception) -> str:
    if isinstance(exc, (NewsProviderTimeout, TimeoutError)):
        return PROVIDER_TIMEOUT
    if isinstance(exc, (NewsProviderUnreachable, ConnectionError)):
        return NETWORK_UNREACHABLE
    if isinstance(exc, (NewsProviderAuthFailed, PermissionError)):
        return PROVIDER_AUTH_FAILED
    if isinstance(exc, NewsProviderRateLimited):
        return PROVIDER_RATE_LIMITED
    return PROVIDER_ERROR


# ---------------------------------------------------------------------------
# Provider configuration (secret-safe).
# ---------------------------------------------------------------------------
def provider_env_names(provider: str) -> tuple[str, ...]:
    names = NEWS_PROVIDER_ENV.get(provider)
    return tuple(names) if names else ()


def provider_requires_key(provider: str) -> bool:
    return NEWS_PROVIDER_ENV.get(provider) is not None


def provider_configured(provider: str, env: Mapping[str, str] | None = None) -> bool:
    """Public providers are always configured; keyed providers need any alias."""
    if not provider_requires_key(provider):
        return provider in NEWS_PROVIDER_ENV
    return any(key_present(name, env) for name in provider_env_names(provider))


def provider_attempt_allowed(
    provider: str, *, allow_network: bool, env: Mapping[str, str] | None = None
) -> bool:
    return bool(
        allow_network
        and provider_configured(provider, env)
        and provider not in BROKER_OR_EXECUTION_PROVIDERS
    )


def describe_news_providers(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Secret-safe descriptor for every known news provider (priority order)."""
    out: list[dict[str, Any]] = []
    for name in NEWS_PROVIDER_PRIORITY:
        names = provider_env_names(name)
        canonical = names[0] if names else None
        fields = provider_key_fields(name, canonical, env)
        if len(names) > 1:
            fields["api_key_env_aliases"] = list(names)
            fields["api_key_present"] = any(key_present(a, env) for a in names)
        fields["configured"] = provider_configured(name, env)
        fields["category"] = PROVIDER_CATEGORY
        out.append(fields)
    return out


# ---------------------------------------------------------------------------
# Raw record normalization.
# ---------------------------------------------------------------------------
def _first_non_null(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return None


def normalize_news_record(
    raw: dict[str, Any], provider: str, *, now_utc: datetime
) -> dict[str, Any]:
    """Map a provider's raw article into a SignalEvent-like news row.

    The row is shaped so it can be (a) enriched/mapped here and (b) persisted to
    the canonical SQLite ``signal_events`` table for the daily-payload bridge.
    Never fabricates a timestamp — a missing one yields freshness_score 0.
    """
    headline = _first_non_null(raw, "headline", "title")
    summary = _first_non_null(raw, "summary", "description", "body_snippet", "body", "snippet")
    url = _first_non_null(raw, "url", "source_url")
    published = _first_non_null(
        raw, "published_at", "seendate", "date_time", "datetime", "date", "timestamp_utc"
    )
    country = _first_non_null(raw, "country", "sourcecountry")
    ts_iso = _parse_published(published)
    age_hours, fresh_flag, score = freshness(now_utc, ts_iso, NEWS_TTL_HOURS)
    return {
        "headline": headline,
        "title": headline,
        "summary": summary,
        "description": summary,
        "url": url,
        "published_at": ts_iso,
        "published_at_utc": ts_iso,
        "country": country,
        "sourcecountry": raw.get("sourcecountry"),
        "language": raw.get("language"),
        "asset_tags": raw.get("asset_tags") or [],
        "provider_entities": raw.get("provider_entities") or [],
        "source": provider,
        "source_name": provider,
        "provider": provider,
        "provider_status": "OK",
        "freshness_age_hours": age_hours,
        "freshness_score": score,
        "is_live": bool(fresh_flag),
        "advisory_only": True,
        "human_review_required": True,
    }


def _parse_published(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    # GDELT seendate form: 20260530T101500Z
    if len(text) == 16 and text.endswith("Z") and "T" in text:
        try:
            dt = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _enrich_and_map(
    row: dict[str, Any],
    *,
    db_path: Path | None,
    securities_master_path: Path | None,
    theta_map: float,
) -> dict[str, Any]:
    """Run deterministic enrichment + mapping; retain unmapped with a reason."""
    enr = enrich_news_event(
        row,
        db_path=db_path,
        securities_master_path=securities_master_path,
        theta_map=theta_map,
    )
    # Resolve a ticker even when enrichment already injected entity_name.
    map_in = dict(row)
    if enr.get("entity_name"):
        map_in["entity_name"] = enr["entity_name"]
    if enr.get("country") and enr["country"] != "UNKNOWN":
        map_in.setdefault("country", enr["country"])
    mapped = map_event_to_tickers(
        map_in,
        db_path=db_path,
        securities_master_path=securities_master_path,
        theta_map=theta_map,
    )
    best = max(mapped, key=lambda m: float(m.get("mapping_confidence") or 0.0))
    mapping_conf = float(best.get("mapping_confidence") or 0.0)
    row.update(
        entity_name=enr.get("entity_name") or best.get("entity_name"),
        entity_extraction_confidence=enr.get("entity_extraction_confidence"),
        country=best.get("country") or (enr.get("country") if enr.get("country") != "UNKNOWN" else row.get("country")),
        country_confidence=enr.get("country_confidence"),
        country_method=enr.get("country_method"),
        ticker=best.get("ticker"),
        exchange=best.get("exchange", ""),
        mapping_status=best.get("mapping_status", "UNMAPPED"),
        mapping_confidence=round(mapping_conf, 4),
        mapping_failure_reason=best.get("mapping_failure_reason"),
        valid_news_mapping=bool(enr.get("valid_news_mapping")),
    )
    if best.get("mapping_status") != "MAPPED" and not row.get("mapping_failure_reason"):
        row["mapping_failure_reason"] = "NO_ENTITY"
    return row


def provider_live_verified(provider_result: dict[str, Any]) -> bool:
    """LIVE_VERIFIED iff attempted, response OK, >=1 fresh row, max freshness>0."""
    return bool(
        provider_result.get("attempted")
        and provider_result.get("response_ok")
        and provider_result.get("fresh_rows", 0) > 0
        and provider_result.get("max_freshness_score", 0.0) > 0
    )


# ---------------------------------------------------------------------------
# Real read-only transports (network path; tests inject deterministic ones).
# ---------------------------------------------------------------------------
def _http_get_json(url: str) -> Any:  # pragma: no cover - network
    import json as _json
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "sleeping-passenger-advisory/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if status == 429:
                raise NewsProviderRateLimited("429")
            if status in (401, 403):
                raise NewsProviderAuthFailed(str(status))
            if status != 200:
                raise NewsProviderUnreachable(f"http {status}")
            return _json.loads(resp.read().decode("utf-8"))
    except (NewsProviderRateLimited, NewsProviderAuthFailed, NewsProviderUnreachable):
        raise
    except TimeoutError as exc:
        raise NewsProviderTimeout(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise NewsProviderUnreachable(type(exc).__name__) from exc


def _gdelt_transport(query: str) -> list[dict[str, Any]]:  # pragma: no cover - network
    import urllib.parse

    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?query="
        f"{urllib.parse.quote(query)}&mode=artlist&maxrecords=10&format=json"
    )
    data = _http_get_json(url)
    arts = data.get("articles", []) if isinstance(data, dict) else []
    return [a for a in arts if isinstance(a, dict)]


def _newsapi_transport(query: str, env: Mapping[str, str] | None) -> list[dict[str, Any]]:  # pragma: no cover - network
    import os
    import urllib.parse

    key = None
    for name in provider_env_names(NEWSAPI):
        key = (env or os.environ).get(name)
        if key:
            break
    if not key:
        raise NewsProviderAuthFailed("no key")
    url = (
        "https://newsapi.org/v2/everything?q="
        f"{urllib.parse.quote(query)}&pageSize=10&language=en&sortBy=publishedAt"
        f"&apiKey={urllib.parse.quote(key)}"
    )
    data = _http_get_json(url)
    arts = data.get("articles", []) if isinstance(data, dict) else []
    return [a for a in arts if isinstance(a, dict)]


def _event_registry_transport(query: str, env: Mapping[str, str] | None) -> list[dict[str, Any]]:  # pragma: no cover - network
    import os
    import urllib.parse

    key = None
    for name in provider_env_names(EVENT_REGISTRY):
        key = (env or os.environ).get(name)
        if key:
            break
    if not key:
        raise NewsProviderAuthFailed("no key")
    url = (
        "https://eventregistry.org/api/v1/article/getArticles?action=getArticles"
        f"&keyword={urllib.parse.quote(query)}&articlesCount=10&lang=eng"
        f"&apiKey={urllib.parse.quote(key)}"
    )
    data = _http_get_json(url)
    if isinstance(data, dict):
        results = data.get("articles", {})
        if isinstance(results, dict):
            return [a for a in results.get("results", []) if isinstance(a, dict)]
    return []


def _default_transports(env: Mapping[str, str] | None) -> dict[str, NewsTransport]:  # pragma: no cover - network
    return {
        GDELT_PUBLIC: _gdelt_transport,
        NEWSAPI: lambda q: _newsapi_transport(q, env),
        EVENT_REGISTRY: lambda q: _event_registry_transport(q, env),
    }


# ---------------------------------------------------------------------------
# The fallback chain.
# ---------------------------------------------------------------------------
def fetch_news_chain(
    *,
    allow_network: bool = False,
    transports: Mapping[str, NewsTransport] | None = None,
    env: Mapping[str, str] | None = None,
    queries: tuple[str, ...] = RHEINMETALL_QUERIES,
    now_utc: datetime | None = None,
    db_path: Path | None = None,
    securities_master_path: Path | None = None,
    theta_map: float = DEFAULT_THETA_MAP,
    max_rows_per_provider: int = MAX_ROWS_PER_PROVIDER,
) -> dict[str, Any]:
    """Run GDELT -> NewsAPI -> Event Registry, returning an honest report.

    With neither network nor an injected transport, every keyed provider is
    PROVIDER_NOT_CONFIGURED / NETWORK_DISABLED and the chain returns no rows
    (honest, never fabricated). Injected transports run the full
    normalize/enrich/map path with no network.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    injected = dict(transports) if transports is not None else None

    provider_reports: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    first_live_provider: str | None = None

    for provider in NEWS_PROVIDER_PRIORITY:
        configured = provider_configured(provider, env)
        rep: dict[str, Any] = {
            "provider": provider,
            "configured": configured,
            "attempted": False,
            "response_ok": False,
            "status": PROVIDER_NOT_CONFIGURED if not configured else OK_EMPTY,
            "rows_fetched": 0,
            "fresh_rows": 0,
            "mapped_rows": 0,
            "unmapped_rows": 0,
            "max_freshness_score": 0.0,
            "failure_reason": None,
        }

        transport: NewsTransport | None = None
        if injected is not None and provider in injected:
            transport = injected[provider]
        elif allow_network and provider_attempt_allowed(
            provider, allow_network=allow_network, env=env
        ):
            transport = _default_transports(env).get(provider)  # pragma: no cover - network

        if transport is None:
            if not configured:
                rep["status"] = PROVIDER_NOT_CONFIGURED
            elif not allow_network and injected is None:
                rep["status"] = NETWORK_DISABLED
            else:
                rep["status"] = PROVIDER_NOT_CONFIGURED
            provider_reports.append(rep)
            continue

        rep["attempted"] = True
        raw_rows: list[dict[str, Any]] = []
        failure_status: str | None = None
        for query in queries:
            try:
                fetched = transport(query) or []
            except Exception as exc:  # noqa: BLE001 - classify, never crash
                failure_status = _status_for_exception(exc)
                rep["failure_reason"] = type(exc).__name__
                break
            for raw in fetched:
                if isinstance(raw, dict):
                    raw_rows.append(raw)
            if len(raw_rows) >= max_rows_per_provider:
                break

        if failure_status is not None:
            rep["status"] = failure_status
            provider_reports.append(rep)
            continue  # fall through to the next provider

        rep["response_ok"] = True
        raw_rows = raw_rows[:max_rows_per_provider]
        rep["rows_fetched"] = len(raw_rows)

        normalized: list[dict[str, Any]] = []
        for raw in raw_rows:
            row = normalize_news_record(raw, provider, now_utc=now_utc)
            row = _enrich_and_map(
                row,
                db_path=db_path,
                securities_master_path=securities_master_path,
                theta_map=theta_map,
            )
            normalized.append(row)

        fresh = [r for r in normalized if r.get("is_live")]
        mapped = [
            r for r in fresh
            if r.get("mapping_status") == "MAPPED"
            and float(r.get("mapping_confidence") or 0.0) >= theta_map
        ]
        rep["fresh_rows"] = len(fresh)
        rep["mapped_rows"] = len(mapped)
        rep["unmapped_rows"] = len(normalized) - len(mapped)
        rep["max_freshness_score"] = max((r.get("freshness_score") or 0.0) for r in normalized) if normalized else 0.0

        # ALL rows are retained (mapped + unmapped) for evidence feedback.
        all_rows.extend(normalized)

        if provider_live_verified(rep):
            rep["status"] = LIVE_VERIFIED
            if first_live_provider is None:
                first_live_provider = provider
            provider_reports.append(rep)
            break  # first live provider wins; chain stops here
        rep["status"] = OK_EMPTY if not normalized else DEGRADED_EMPTY
        provider_reports.append(rep)

    mapped_total = [
        r for r in all_rows
        if r.get("mapping_status") == "MAPPED"
        and float(r.get("mapping_confidence") or 0.0) >= theta_map
    ]
    news_layer_present = any(r.get("is_live") for r in all_rows)

    report = {
        "report": "news_provider_fallback_chain",
        "generated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "allow_network": bool(allow_network),
        "mode": "MOCK" if injected is not None else ("NETWORK" if allow_network else "SKIP_NETWORK"),
        "provider_priority": list(NEWS_PROVIDER_PRIORITY),
        "configured_providers": describe_news_providers(env),
        "provider_reports": provider_reports,
        "first_live_provider": first_live_provider,
        "rows": all_rows,
        "mapped_rows": mapped_total,
        "fresh_row_count": sum(1 for r in all_rows if r.get("is_live")),
        "mapped_row_count": len(mapped_total),
        "unmapped_row_count": len(all_rows) - len(mapped_total),
        "news_layer_present": news_layer_present,
        "missing_layers": [] if news_layer_present else ["news_support", "mapping_support"],
        "advisory_only": True,
        "human_review_required": True,
        "executable_allowed": False,
        **advisory_safety_stamps(),
        "safety": advisory_safety_stamps(),
    }
    secret_values = collect_secret_values(
        [n for names in NEWS_PROVIDER_ENV.values() if names for n in names], env=env
    )
    report["secret_leak_check_passed"] = assert_no_secret(report, secret_values)
    return report


__all__ = [
    "GDELT_PUBLIC",
    "NEWSAPI",
    "EVENT_REGISTRY",
    "NEWS_PROVIDER_PRIORITY",
    "NEWS_PROVIDER_ENV",
    "RHEINMETALL_QUERIES",
    "LIVE_VERIFIED",
    "OK_EMPTY",
    "NETWORK_UNREACHABLE",
    "PROVIDER_TIMEOUT",
    "PROVIDER_ERROR",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_NOT_CONFIGURED",
    "DEGRADED_EMPTY",
    "NewsProviderTimeout",
    "NewsProviderUnreachable",
    "NewsProviderAuthFailed",
    "NewsProviderRateLimited",
    "provider_configured",
    "provider_attempt_allowed",
    "describe_news_providers",
    "normalize_news_record",
    "provider_live_verified",
    "fetch_news_chain",
]
