"""UK/EU regulatory-filings provider wiring — advisory-only, honest status.

The US filings path (``build_today_filings_events``) already writes an honest
EMPTY fallback when no live source is wired. This module adds the *non-US*
provider surface the discovery sprint needs (UK Companies House / LSE-RNS / FCA
NSM, EU ESMA + national registers) WITHOUT pretending any of them is live.

Hard contract (pure / advisory):
    * no broker, no execution, no order endpoint, no network at import time
    * no provider is implemented as a live fetch yet, so this NEVER emits a row
      labelled ``is_live=true``; a placeholder/unavailable provider is reported
      as ``PROVIDER_NOT_CONFIGURED`` or ``NOT_ACTIVE`` and produces zero rows
    * an API-key-gated provider whose key is absent reports
      ``PROVIDER_NOT_CONFIGURED`` (key needed) — never a fake live status
    * fallbacks stay honest: zero fabricated filings, advisory stamps attached

When a real adapter is later implemented it should set ``implemented=True`` and
return freshly-fetched rows; only then may ``status`` become ``ACTIVE`` and
``is_live`` become True. Until then the truth is "not active".
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.entity_ticker_mapper import DEFAULT_THETA_MAP, map_event_to_tickers
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from entity_ticker_mapper import DEFAULT_THETA_MAP, map_event_to_tickers
    from runtime_common import utc_timestamp


# Honest provider lifecycle states. None of these is an execution instruction.
STATUS_ACTIVE = "ACTIVE"                              # implemented + fresh rows
STATUS_NOT_ACTIVE = "NOT_ACTIVE"                       # implemented-stub / no rows
STATUS_PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"  # needs an absent key
# Adapter-path states (UK RNS / Companies House) — only LIVE_VERIFIED is live.
STATUS_LIVE_VERIFIED = "LIVE_VERIFIED"                  # attempted + fresh rows present
STATUS_OK_EMPTY = "OK_EMPTY"                            # attempted, zero fresh rows
STATUS_DEGRADED_PROVIDER_ERROR = "DEGRADED_PROVIDER_ERROR"

FILINGS_TTL_HOURS = 72.0
# Mapping reason for a real but unlisted/private Companies House entity.
PRIVATE_UNLISTED_REASON = "PRIVATE_COMPANY_OR_UNLISTED"

# Provider registry. ``implemented`` is False for every entry today: we have
# wiring + honest status, not a live fetch. ``env_key`` names the credential a
# future live adapter would require (None = no key needed).
_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "provider": "companies_house",
        "region": "UK",
        "countries": ("United Kingdom",),
        "description": "UK Companies House filing history API",
        "env_key": "COMPANIES_HOUSE_API_KEY",
        "implemented": False,
    },
    {
        "provider": "lse_rns",
        "region": "UK",
        "countries": ("United Kingdom",),
        "description": "London Stock Exchange Regulatory News Service (RNS)",
        "env_key": "LSE_RNS_API_KEY",
        "implemented": False,
    },
    {
        "provider": "fca_nsm",
        "region": "UK",
        "countries": ("United Kingdom",),
        "description": "FCA National Storage Mechanism regulatory disclosures",
        "env_key": None,
        "implemented": False,
    },
    {
        "provider": "esma_register",
        "region": "EU",
        "countries": (
            "Germany", "France", "Netherlands", "Italy", "Spain",
        ),
        "description": "ESMA / EU transparency register (multi-jurisdiction)",
        "env_key": None,
        "implemented": False,
    },
    {
        "provider": "bundesanzeiger",
        "region": "EU",
        "countries": ("Germany",),
        "description": "German Federal Gazette (Bundesanzeiger) disclosures",
        "env_key": "BUNDESANZEIGER_API_KEY",
        "implemented": False,
    },
    {
        "provider": "amf_france",
        "region": "EU",
        "countries": ("France",),
        "description": "Autorité des marchés financiers (AMF) disclosures",
        "env_key": "AMF_API_KEY",
        "implemented": False,
    },
    {
        "provider": "afm_netherlands",
        "region": "EU",
        "countries": ("Netherlands",),
        "description": "Autoriteit Financiële Markten (AFM) disclosures",
        "env_key": "AFM_API_KEY",
        "implemented": False,
    },
)

_PROVIDER_INDEX = {p["provider"]: p for p in _PROVIDERS}


def _api_key_present(env_key: str | None) -> bool:
    if not env_key:
        return False
    return bool(str(os.environ.get(env_key) or "").strip())


def describe_filings_provider(provider: str) -> dict[str, Any]:
    """Return the honest status of one UK/EU filings provider.

    Unknown provider names resolve to ``PROVIDER_NOT_CONFIGURED`` rather than
    raising, so callers iterating a config never crash on a typo.
    """
    spec = _PROVIDER_INDEX.get(provider)
    if spec is None:
        return {
            "provider": provider,
            "region": "UNKNOWN",
            "countries": [],
            "requires_api_key": False,
            "api_key_present": False,
            "implemented": False,
            "status": STATUS_PROVIDER_NOT_CONFIGURED,
            "is_live": False,
            "reason": "unknown provider — not registered",
            "safety": advisory_safety_stamps(),
        }

    requires_key = spec["env_key"] is not None
    key_present = _api_key_present(spec["env_key"])
    implemented = bool(spec["implemented"])

    if not implemented:
        if requires_key and not key_present:
            status = STATUS_PROVIDER_NOT_CONFIGURED
            reason = (
                f"live adapter not implemented and credential {spec['env_key']} "
                "is not set"
            )
        else:
            status = STATUS_NOT_ACTIVE
            reason = "provider registered but live adapter not implemented yet"
    else:  # pragma: no cover - no provider is implemented today
        if requires_key and not key_present:
            status = STATUS_PROVIDER_NOT_CONFIGURED
            reason = f"credential {spec['env_key']} is required but not set"
        else:
            status = STATUS_NOT_ACTIVE
            reason = "implemented but no fresh rows returned this run"

    return {
        "provider": spec["provider"],
        "region": spec["region"],
        "countries": list(spec["countries"]),
        "description": spec["description"],
        "requires_api_key": requires_key,
        "api_key_present": key_present,
        "implemented": implemented,
        "status": status,
        # is_live can only be True for an implemented provider that actually
        # returned fresh rows — never for a placeholder.
        "is_live": False,
        "reason": reason,
        "safety": advisory_safety_stamps(),
    }


def available_filings_providers(region: str | None = None) -> list[dict[str, Any]]:
    """Describe all registered providers, optionally filtered by region (UK/EU)."""
    out: list[dict[str, Any]] = []
    for spec in _PROVIDERS:
        if region and spec["region"].upper() != region.upper():
            continue
        out.append(describe_filings_provider(spec["provider"]))
    return out


def load_uk_eu_filings(region: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attempt to load UK/EU filings; return ``(events, meta)`` honestly.

    No provider is implemented as a live fetch, so ``events`` is always ``[]``
    and ``meta`` records each provider's status. ``is_live`` is False and
    ``executable_allowed`` is False. This shape plugs into
    :func:`build_today_filings_events` via its ``live_meta`` argument.
    """
    provider_states = available_filings_providers(region=region)
    events: list[dict[str, Any]] = []  # never fabricated

    any_active = any(p["status"] == STATUS_ACTIVE for p in provider_states)
    any_configured = any(
        p["status"] != STATUS_PROVIDER_NOT_CONFIGURED for p in provider_states
    )

    if any_active and events:  # pragma: no cover - unreachable until implemented
        source_health = "DEGRADED_WITH_FRESH_ROWS"
        is_live = True
        fallback_reason = None
    elif any_configured:
        source_health = STATUS_NOT_ACTIVE
        is_live = False
        fallback_reason = "UK/EU filing adapters registered but not implemented"
    else:
        source_health = STATUS_PROVIDER_NOT_CONFIGURED
        is_live = False
        fallback_reason = "no UK/EU filing provider configured (missing credentials)"

    meta = {
        "provider": "GLOBAL_FILINGS_UK_EU",
        "source_health": source_health,
        "is_live": is_live,
        "executable_allowed": False,
        "fallback_reason": fallback_reason,
        "providers": provider_states,
        "diagnostics": {
            "region_filter": region,
            "provider_count": len(provider_states),
            "active_count": sum(1 for p in provider_states if p["status"] == STATUS_ACTIVE),
            "fresh_row_count": len(events),
        },
        "generated_at_utc": utc_timestamp(),
        "safety": advisory_safety_stamps(),
    }
    return events, meta


# ---------------------------------------------------------------------------
# Real adapter interfaces — UK RNS + Companies House (injectable, no-key tests)
# ---------------------------------------------------------------------------
# These adapters accept *injected* deterministic rows (``fixture_rows``) so the
# parse/normalize/map path is exercised with NO network and NO API key. A live
# fetch implementation can later replace the ``fixture_rows`` source; the honest
# status contract below is unchanged. A provider is only ``LIVE_VERIFIED`` when
# it was actually attempted AND returned at least one fresh row — a missing key
# or an empty response is never reported as live.


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _row_freshness_score(row: dict[str, Any], now_utc: datetime | None) -> float:
    """Deterministic freshness in [0,1].

    Honors an explicit ``freshness_score`` on the row (test-deterministic);
    otherwise derives it from ``published_at_utc`` vs ``now_utc`` over the
    filings TTL. Never raises.
    """
    explicit = row.get("freshness_score")
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        return max(0.0, min(1.0, float(explicit)))
    published = _parse_iso(row.get("published_at_utc") or row.get("published_at"))
    if published is None:
        return 0.0
    now = now_utc or datetime.now(timezone.utc)
    age_hours = (now - published).total_seconds() / 3600.0
    if age_hours < 0:
        age_hours = 0.0
    if age_hours > FILINGS_TTL_HOURS:
        return 0.0
    return round(max(0.0, 1.0 - age_hours / FILINGS_TTL_HOURS), 4)


def _map_entity(entity_name: str, ticker: str, country_code: str) -> dict[str, Any]:
    """Resolve an entity/ticker to a mapping row (advisory, never drops)."""
    event = {"entity_name": entity_name, "ticker": ticker, "country": country_code}
    rows = map_event_to_tickers(event, theta_map=DEFAULT_THETA_MAP)
    return max(rows, key=lambda m: float(m.get("mapping_confidence") or 0.0))


def normalize_uk_rns_row(
    raw: dict[str, Any], *, now_utc: datetime | None = None
) -> dict[str, Any]:
    """Normalize one UK RNS row into a canonical filing SignalEvent-like row.

    Pure / null-safe. ``is_live`` reflects freshness only; a stale or
    timestamp-less row is honestly ``is_live=false``.
    """
    raw = raw or {}
    entity_name = str(raw.get("entity_name") or raw.get("company") or "").strip()
    ticker = str(raw.get("ticker") or "").strip().upper()
    mapping = _map_entity(entity_name, ticker, "GB")
    fresh = _row_freshness_score(raw, now_utc)
    return {
        "source_name": "UK_RNS",
        "provider": "lse_rns",
        "country": "United Kingdom",
        "jurisdiction": "UK",
        "event_type": str(raw.get("event_type") or "regulatory"),
        "entity_name": entity_name or (mapping.get("entity_name") or None),
        "ticker": mapping.get("ticker") or (ticker or None),
        "exchange": mapping.get("exchange") or "",
        "headline": str(raw.get("headline") or raw.get("title") or "").strip() or None,
        "summary": raw.get("summary"),
        "url": raw.get("url") or raw.get("source_url"),
        "published_at_utc": raw.get("published_at_utc") or raw.get("published_at"),
        "freshness": "FRESH_TODAY" if fresh > 0 else "STALE",
        "freshness_score": fresh,
        "is_live": fresh > 0,
        "mapping_status": mapping.get("mapping_status", "UNMAPPED"),
        "mapping_confidence": float(mapping.get("mapping_confidence") or 0.0),
        "mapping_failure_reason": mapping.get("mapping_failure_reason"),
        "provider_status": STATUS_LIVE_VERIFIED if fresh > 0 else STATUS_OK_EMPTY,
        "source_health": "DEGRADED_WITH_FRESH_ROWS" if fresh > 0 else STATUS_OK_EMPTY,
        "executable_allowed": False,
        "advisory_only": True,
        "human_review_required": True,
        "safety": advisory_safety_stamps(),
    }


def normalize_companies_house_row(
    raw: dict[str, Any], *, now_utc: datetime | None = None
) -> dict[str, Any]:
    """Normalize one Companies House row into a canonical filing row.

    Many Companies House entities are private/unlisted: when the row has a
    company number but resolves to no listed ticker, it is RETAINED with
    ``mapping_failure_reason='PRIVATE_COMPANY_OR_UNLISTED'`` and is never a
    tradable candidate (``tradable_candidate=False``). We never overclaim
    listed-equity coverage.
    """
    raw = raw or {}
    entity_name = str(raw.get("entity_name") or raw.get("company_name") or "").strip()
    ticker = str(raw.get("ticker") or "").strip().upper()
    company_number = str(raw.get("company_number") or "").strip()
    mapping = _map_entity(entity_name, ticker, "GB")
    fresh = _row_freshness_score(raw, now_utc)

    mapped_ok = mapping.get("mapping_status") == "MAPPED" and mapping.get("ticker")
    failure_reason = mapping.get("mapping_failure_reason")
    tradable = False
    if mapped_ok:
        tradable = True
    elif company_number:
        # A real registered company that does not resolve to a listed ticker.
        failure_reason = PRIVATE_UNLISTED_REASON

    return {
        "source_name": "UK_COMPANIES_HOUSE",
        "provider": "companies_house",
        "country": "United Kingdom",
        "jurisdiction": "UK",
        "event_type": str(raw.get("event_type") or "filing"),
        "entity_name": entity_name or None,
        "company_number": company_number or None,
        "ticker": mapping.get("ticker") if mapped_ok else None,
        "exchange": mapping.get("exchange") if mapped_ok else "",
        "headline": str(raw.get("headline") or raw.get("description") or "").strip() or None,
        "url": raw.get("url"),
        "published_at_utc": raw.get("published_at_utc") or raw.get("published_at"),
        "freshness": "FRESH_TODAY" if fresh > 0 else "STALE",
        "freshness_score": fresh,
        "is_live": fresh > 0,
        "mapping_status": mapping.get("mapping_status", "UNMAPPED") if mapped_ok else "UNMAPPED",
        "mapping_confidence": float(mapping.get("mapping_confidence") or 0.0) if mapped_ok else 0.0,
        "mapping_failure_reason": failure_reason,
        "tradable_candidate": tradable,
        "provider_status": STATUS_LIVE_VERIFIED if fresh > 0 else STATUS_OK_EMPTY,
        "source_health": "DEGRADED_WITH_FRESH_ROWS" if fresh > 0 else STATUS_OK_EMPTY,
        "executable_allowed": False,
        "advisory_only": True,
        "human_review_required": True,
        "safety": advisory_safety_stamps(),
    }


def _load_adapter(
    provider: str,
    normalizer,
    *,
    fixture_rows: list[dict[str, Any]] | None,
    now_utc: datetime | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shared honest-status loader for an injectable filing adapter."""
    spec = describe_filings_provider(provider)
    configured = (not spec["requires_api_key"]) or spec["api_key_present"]

    # No injection AND not configured -> honest not-configured, no rows.
    if fixture_rows is None and not configured:
        meta = {
            "provider": provider,
            "status": STATUS_PROVIDER_NOT_CONFIGURED,
            "is_live": False,
            "attempted": False,
            "fresh_row_count": 0,
            "executable_allowed": False,
            "reason": spec["reason"],
            "safety": advisory_safety_stamps(),
        }
        return [], meta

    attempted = fixture_rows is not None
    events: list[dict[str, Any]] = []
    if attempted:
        for raw in fixture_rows or []:
            if isinstance(raw, dict):
                events.append(normalizer(raw, now_utc=now_utc))

    fresh_count = sum(1 for e in events if e.get("freshness_score", 0) > 0)
    if not attempted:
        status, is_live = STATUS_OK_EMPTY, False
    elif fresh_count > 0:
        status, is_live = STATUS_LIVE_VERIFIED, True
    else:
        status, is_live = STATUS_OK_EMPTY, False

    meta = {
        "provider": provider,
        "status": status,
        "is_live": is_live,
        "attempted": attempted,
        "fresh_row_count": fresh_count,
        "row_count": len(events),
        "executable_allowed": False,
        "safety": advisory_safety_stamps(),
    }
    return events, meta


def load_uk_rns_filings(
    fixture_rows: list[dict[str, Any]] | None = None,
    *,
    now_utc: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load UK RNS filing events (injectable). Honest live/empty/not-configured."""
    return _load_adapter(
        "lse_rns", normalize_uk_rns_row, fixture_rows=fixture_rows, now_utc=now_utc
    )


def load_companies_house_filings(
    fixture_rows: list[dict[str, Any]] | None = None,
    *,
    now_utc: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load Companies House filing events (injectable). Honest status; private/
    unlisted rows retained but never tradable."""
    return _load_adapter(
        "companies_house",
        normalize_companies_house_row,
        fixture_rows=fixture_rows,
        now_utc=now_utc,
    )


def build_uk_filing_events(
    *,
    rns_rows: list[dict[str, Any]] | None = None,
    companies_house_rows: list[dict[str, Any]] | None = None,
    now_utc: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate UK RNS + Companies House adapter rows into one honest payload.

    ``is_live`` is True iff at least one adapter is LIVE_VERIFIED. The combined
    payload plugs into ``build_today_filings_events`` via its ``live_meta``.
    """
    rns_events, rns_meta = load_uk_rns_filings(rns_rows, now_utc=now_utc)
    ch_events, ch_meta = load_companies_house_filings(
        companies_house_rows, now_utc=now_utc
    )
    events = rns_events + ch_events
    any_live = rns_meta["is_live"] or ch_meta["is_live"]
    fresh_total = rns_meta["fresh_row_count"] + ch_meta["fresh_row_count"]
    if any_live:
        source_health = "DEGRADED_WITH_FRESH_ROWS"
    elif rns_meta["attempted"] or ch_meta["attempted"]:
        source_health = STATUS_OK_EMPTY
    else:
        source_health = STATUS_PROVIDER_NOT_CONFIGURED
    meta = {
        "provider": "UK_FILINGS",
        "source_health": source_health,
        "is_live": any_live,
        "executable_allowed": False,
        "providers": [rns_meta, ch_meta],
        "diagnostics": {
            "fresh_row_count": fresh_total,
            "rns_rows": rns_meta.get("row_count", 0),
            "companies_house_rows": ch_meta.get("row_count", 0),
        },
        "generated_at_utc": utc_timestamp(),
        "safety": advisory_safety_stamps(),
    }
    return events, meta


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_NOT_ACTIVE",
    "STATUS_PROVIDER_NOT_CONFIGURED",
    "STATUS_LIVE_VERIFIED",
    "STATUS_OK_EMPTY",
    "STATUS_DEGRADED_PROVIDER_ERROR",
    "PRIVATE_UNLISTED_REASON",
    "describe_filings_provider",
    "available_filings_providers",
    "load_uk_eu_filings",
    "normalize_uk_rns_row",
    "normalize_companies_house_row",
    "load_uk_rns_filings",
    "load_companies_house_filings",
    "build_uk_filing_events",
]
