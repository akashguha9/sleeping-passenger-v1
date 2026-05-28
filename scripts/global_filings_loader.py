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
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from runtime_common import utc_timestamp


# Honest provider lifecycle states. None of these is an execution instruction.
STATUS_ACTIVE = "ACTIVE"                              # implemented + fresh rows
STATUS_NOT_ACTIVE = "NOT_ACTIVE"                       # implemented-stub / no rows
STATUS_PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"  # needs an absent key

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


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_NOT_ACTIVE",
    "STATUS_PROVIDER_NOT_CONFIGURED",
    "describe_filings_provider",
    "available_filings_providers",
    "load_uk_eu_filings",
]
