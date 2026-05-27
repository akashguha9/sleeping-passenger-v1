"""Provider edge-case matrix.

proof_loop_hardening_sprint, Phase 10.

Pins the classification contract for every (provider, error_class)
combination.  This module is *spec-as-code*: it does not call live
providers; it asserts that the sprint's taxonomy can never overclaim
``LIVE_VERIFIED`` when an error class is in play.

If a future adapter wants to map its own classes onto these labels, it
should use ``map_adapter_status_to_sprint_label`` so the canonical
sprint vocabulary stays the single source of truth.
"""
from __future__ import annotations

from typing import Any

PROVIDERS: tuple[str, ...] = (
    "Kalshi",
    "Polymarket",
    "GDELT",
    "SEC_EDGAR",
    "NewsAPI",
    "EventRegistry",
    "yfinance",
    "IndiaSources",
    "Etherscan",
    "GlobalFilings",
    "AsiaDisclosure",
)

ERROR_CLASSES: tuple[str, ...] = (
    "timeout",
    "http_429",
    "http_5xx",
    "malformed_payload",
    "empty_response",
    "filtered_zero_rows",
    "stale_timestamp",
    "missing_credentials",
    "partial_adapter",
    "fresh_canonical_rows",
)


# Canonical sprint labels.  These are intentionally narrower than the
# existing live_source_registry taxonomy so the contract is easy to
# reason about.
LABEL_LIVE_VERIFIED = "LIVE_VERIFIED"
LABEL_NOT_CONFIGURED = "NOT_CONFIGURED"
LABEL_ADAPTER_PARTIAL = "ADAPTER_PARTIAL"
LABEL_DEGRADED = "DEGRADED"
LABEL_RATE_LIMITED = "RATE_LIMITED"
LABEL_ERROR = "ERROR"
LABEL_ZERO_FRESH_ROWS = "ZERO_FRESH_ROWS"
LABEL_FILTERED = "FILTERED"
LABEL_STALE = "STALE"


ALL_LABELS: frozenset[str] = frozenset(
    {
        LABEL_LIVE_VERIFIED,
        LABEL_NOT_CONFIGURED,
        LABEL_ADAPTER_PARTIAL,
        LABEL_DEGRADED,
        LABEL_RATE_LIMITED,
        LABEL_ERROR,
        LABEL_ZERO_FRESH_ROWS,
        LABEL_FILTERED,
        LABEL_STALE,
    }
)


def classify(error_class: str, *, canonical_ttl_passes: bool = False) -> str:
    """Classify a single (error_class) observation.

    Parameters
    ----------
    error_class:
        One of :data:`ERROR_CLASSES`.
    canonical_ttl_passes:
        For ``fresh_canonical_rows`` only — only mark ``LIVE_VERIFIED``
        when the canonical-store TTL also passes.  When False, even a
        fresh-rows event drops to ``ZERO_FRESH_ROWS``.

    Returns
    -------
    str
        One of :data:`ALL_LABELS`.
    """
    ec = str(error_class).strip().lower()
    if ec == "missing_credentials":
        return LABEL_NOT_CONFIGURED
    if ec == "partial_adapter":
        return LABEL_ADAPTER_PARTIAL
    if ec == "http_429":
        return LABEL_RATE_LIMITED
    if ec in ("timeout", "http_5xx"):
        return LABEL_DEGRADED
    if ec == "malformed_payload":
        return LABEL_ERROR
    if ec == "empty_response":
        return LABEL_ZERO_FRESH_ROWS
    if ec == "filtered_zero_rows":
        return LABEL_FILTERED
    if ec == "stale_timestamp":
        return LABEL_STALE
    if ec == "fresh_canonical_rows":
        return LABEL_LIVE_VERIFIED if canonical_ttl_passes else LABEL_ZERO_FRESH_ROWS
    return LABEL_ERROR


# Mapping from live_source_registry adapter-status strings → sprint labels.
# Keeps the wider repo's existing taxonomy compatible with the sprint's
# canonical vocabulary.
ADAPTER_STATUS_TO_SPRINT_LABEL: dict[str, str] = {
    "implemented": LABEL_LIVE_VERIFIED,
    "partial": LABEL_ADAPTER_PARTIAL,
    "planned": LABEL_ADAPTER_PARTIAL,
    "not_configured": LABEL_NOT_CONFIGURED,
}


def map_adapter_status_to_sprint_label(status: str) -> str:
    """Translate a live_source_registry adapter status into a sprint label.

    Unknown statuses degrade to :data:`LABEL_ERROR` rather than silently
    accepting a string the matrix cannot reason about.
    """
    return ADAPTER_STATUS_TO_SPRINT_LABEL.get(
        str(status or "").strip().lower(), LABEL_ERROR
    )


def matrix_report() -> dict[str, Any]:
    """Pure-Python matrix dump for documentation / audit."""
    rows: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        for ec in ERROR_CLASSES:
            rows.append(
                {
                    "provider": provider,
                    "error_class": ec,
                    "classification": classify(ec, canonical_ttl_passes=False),
                    "classification_when_ttl_passes": classify(
                        ec, canonical_ttl_passes=True
                    ),
                }
            )
    return {
        "providers": list(PROVIDERS),
        "error_classes": list(ERROR_CLASSES),
        "labels": sorted(ALL_LABELS),
        "rows": rows,
    }


__all__ = [
    "ADAPTER_STATUS_TO_SPRINT_LABEL",
    "ALL_LABELS",
    "ERROR_CLASSES",
    "LABEL_ADAPTER_PARTIAL",
    "LABEL_DEGRADED",
    "LABEL_ERROR",
    "LABEL_FILTERED",
    "LABEL_LIVE_VERIFIED",
    "LABEL_NOT_CONFIGURED",
    "LABEL_RATE_LIMITED",
    "LABEL_STALE",
    "LABEL_ZERO_FRESH_ROWS",
    "PROVIDERS",
    "classify",
    "map_adapter_status_to_sprint_label",
    "matrix_report",
]
