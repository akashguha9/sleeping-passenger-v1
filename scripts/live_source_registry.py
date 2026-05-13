"""
Canonical live source registry for the sleeping-passenger MVP.

This module is the single, source-agnostic surface that answers:

  - which live source families exist?
  - is the adapter implemented, partial, planned, or placeholder?
  - which environment variables does it need?
  - are those credentials configured right now (without exposing values)?
  - what is the canonical refresh cadence (6 hours)?
  - what safety stamps does a refresh run carry?

It deliberately does **not** call any live API. It introspects existing
adapters (phase1 + phase2 runners under ``scripts/live_source_runner*.py``
and the ingestion modules under ``scripts/ingestion/``) and the operator's
environment to surface a redacted, frontend-safe status object.

Safety
------
- Read-only. No outbound network, no DB writes.
- Credential values are NEVER returned — only ``configured: true/false``.
- All output carries ``advisory_status="ADVISORY_ONLY"`` and
  ``execution_gate="LOCKED"``.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"
DEFAULT_REFRESH_HOURS = 6

# Adapter status taxonomy.
ADAPTER_IMPLEMENTED = "implemented"
ADAPTER_PARTIAL = "partial"
ADAPTER_PLANNED = "planned"
ADAPTER_NOT_CONFIGURED = "not_configured"


_SOURCE_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "source_key": "polymarket",
        "display_name": "Polymarket",
        "category": "event_market",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": False,
        "env_keys": (),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": (
            "Public Polymarket Gamma API. Domain-gated to "
            "politics / finance / geopolitics / economy."
        ),
        "tos_warning": (
            "Polymarket attribution recommended; no CLOB order calls are used."
        ),
        "implementation_file": "scripts/ingestion/polymarket_loader.py",
        "health_check_supported": True,
        "phase": "phase1",
    },
    {
        "source_key": "gdelt",
        "display_name": "GDELT",
        "category": "narrative",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": False,
        "env_keys": (),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": "Public GDELT DOC API; query frequency self-limited.",
        "tos_warning": "Attribute 'Data provided by GDELT Project' if displayed.",
        "implementation_file": "scripts/ingestion/gdelt_loader.py",
        "health_check_supported": True,
        "phase": "phase1",
    },
    {
        "source_key": "sec_edgar",
        "display_name": "SEC EDGAR",
        "category": "filings",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": False,
        "env_keys": ("SEC_USER_AGENT",),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": (
            "Public EDGAR filings JSON. Requires a descriptive "
            "SEC_USER_AGENT (RFC: 'AppName contact@example.com')."
        ),
        "tos_warning": (
            "SEC enforces a 10 req/sec hard cap and a descriptive UA."
        ),
        "implementation_file": "scripts/ingestion/sec_edgar_loader.py",
        "health_check_supported": True,
        "phase": "phase1",
    },
    {
        "source_key": "newsapi",
        "display_name": "NewsAPI",
        "category": "news",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": True,
        "env_keys": ("NEWS_API_KEY",),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": "Free tier ~100/day. Article bodies not redistributed.",
        "tos_warning": (
            "Free tier is developer-only; commercial display requires paid plan."
        ),
        "implementation_file": "scripts/ingestion/newsapi_loader.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
    {
        "source_key": "event_registry",
        "display_name": "Event Registry",
        "category": "news",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": True,
        "env_keys": ("EVENT_REGISTRY_API_KEY",),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": "Free tier limited; check current plan before showing externally.",
        "tos_warning": "Attribution required.",
        "implementation_file": "scripts/ingestion/event_registry_loader.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
    {
        "source_key": "etherscan",
        "display_name": "Etherscan",
        "category": "onchain",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": True,
        "env_keys": ("ETHERSCAN_API_KEY",),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": "Read-only transaction list. No wallet signing, no transactions.",
        "tos_warning": "Free tier non-commercial; 5 calls/sec.",
        "implementation_file": "scripts/ingestion/etherscan_loader.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
    {
        "source_key": "grok_xai",
        "display_name": "Grok/xAI",
        "category": "ai_interpretation",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": True,
        "env_keys": ("XAI_API_KEY",),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "ai_interpretation",
        "notes": (
            "Hypothesis/interpretation only. Outputs flow through "
            "scripts/ai_output_schema.py for advisory-safety stamps."
        ),
        "tos_warning": "xAI provider ToS applies; do not persist others' data.",
        "implementation_file": "scripts/grok_xai_adapter.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
    {
        "source_key": "market_data",
        "display_name": "Market Data (Yahoo via yfinance)",
        "category": "market_data",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": False,
        "env_keys": (),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "market_data",
        "notes": "Read-only OHLCV via yfinance. Skips cleanly if package missing.",
        "tos_warning": "Yahoo ToS limits redistribution; local single-operator only.",
        "implementation_file": "scripts/ingestion/market_data_loader.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
    {
        "source_key": "india",
        "display_name": "India (NSE / RBI / SEBI)",
        "category": "regional_filings",
        "adapter_status": ADAPTER_IMPLEMENTED,
        "requires_api_key": False,
        "env_keys": (),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": "Public NSE / RBI / SEBI endpoints; skips cleanly on failure.",
        "tos_warning": "Per-source attribution required when displayed.",
        "implementation_file": "scripts/ingestion/india_loader.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
    {
        "source_key": "global_filings",
        "display_name": "Global Filings (ASX live; HKEX/SGX/UK-RNS/ESMA/SEDAR/TDNet planned)",
        "category": "regional_filings",
        "adapter_status": ADAPTER_PARTIAL,
        "requires_api_key": False,
        "env_keys": (),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": (
            "ASX is implemented and key-free. HKEX / SGX / UK-RNS / ESMA / "
            "SEDAR / TDNet are placeholders that skip cleanly."
        ),
        "tos_warning": (
            "Per-provider attribution required; placeholders must not be "
            "claimed implemented."
        ),
        "implementation_file": "scripts/ingestion/global_filings_loader.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
    {
        "source_key": "asia_disclosure",
        "display_name": "Asia Disclosure (SSE/SZSE/HKEX/TDNet/SGX/DART)",
        "category": "regional_filings",
        "adapter_status": ADAPTER_PLANNED,
        "requires_api_key": False,
        "env_keys": (),
        "default_refresh_hours": DEFAULT_REFRESH_HOURS,
        "advisory_only": True,
        "can_execute": False,
        "expected_output": "signal_events",
        "notes": (
            "All providers are placeholders; the adapter skips cleanly. "
            "SGX and DART will require API keys when implemented."
        ),
        "tos_warning": "All targets are exchange-disclosure sites with attribution rules.",
        "implementation_file": "scripts/ingestion/asia_disclosure_loader.py",
        "health_check_supported": True,
        "phase": "phase2",
    },
)


_SOURCE_BY_KEY: dict[str, dict[str, Any]] = {
    src["source_key"]: src for src in _SOURCE_REGISTRY
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_live_source_families() -> list[dict[str, Any]]:
    """Return a fresh copy of the canonical source registry.

    The copy preserves order, which is the order Day 26–35 documentation
    consistently uses. Each entry's ``env_keys`` is a tuple in the registry
    and is materialised as a list in the copy for JSON-friendly output.
    """
    out: list[dict[str, Any]] = []
    for entry in _SOURCE_REGISTRY:
        clean = dict(entry)
        clean["env_keys"] = list(entry["env_keys"])
        out.append(clean)
    return out


def get_source_family(source_key: str) -> dict[str, Any]:
    """Return the registry entry for ``source_key``.

    Raises ``KeyError`` (not ValueError) on unknown source — callers that
    want a soft failure should catch it explicitly. The hard failure is
    deliberate: silent shrugging is how phantom sources get into UI.
    """
    if not isinstance(source_key, str) or not source_key.strip():
        raise KeyError("source_key_must_be_nonempty_string")
    key = source_key.strip().lower()
    if key not in _SOURCE_BY_KEY:
        raise KeyError(f"unknown_source: {key}")
    entry = dict(_SOURCE_BY_KEY[key])
    entry["env_keys"] = list(entry["env_keys"])
    return entry


def detect_source_credential_state(
    env: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Inspect ``env`` (defaulting to ``os.environ``) and report, *per source*,
    whether every required env key is present.

    The returned shape is::

        {
          "<source_key>": {
            "source_key":       str,
            "configured":       bool,
            "requires_api_key": bool,
            "env_keys":         list[str],
            "missing_env_keys": list[str],
            "redacted_env_keys": list[str],
          },
          ...
        }

    Values are NEVER copied — only presence and a redacted placeholder list.
    """
    env_map = env if env is not None else os.environ
    out: dict[str, dict[str, Any]] = {}
    for src in _SOURCE_REGISTRY:
        keys = list(src["env_keys"])
        missing = [k for k in keys if not str(env_map.get(k, "")).strip()]
        redacted = ["<redacted>" if k not in missing else "<unset>" for k in keys]
        out[src["source_key"]] = {
            "source_key": src["source_key"],
            "configured": (not src["requires_api_key"]) or (
                src["requires_api_key"] and not missing
            ),
            "requires_api_key": src["requires_api_key"],
            "env_keys": keys,
            "missing_env_keys": missing,
            "redacted_env_keys": redacted,
        }
    return out


def build_refresh_plan(
    source_keys: list[str] | None = None,
    cadence_hours: int = DEFAULT_REFRESH_HOURS,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a dry-run refresh plan that callers (CLI, frontend, scheduler
    wrappers) can inspect before deciding whether to run anything.

    The plan never includes credential values, never calls any adapter, and
    every entry stamps the advisory-safety contract.
    """
    requested = _normalise_source_keys(source_keys)
    credential_state = detect_source_credential_state(env)

    implemented: list[str] = []
    partial: list[str] = []
    planned: list[str] = []
    skipped_missing_creds: list[str] = []

    entries: list[dict[str, Any]] = []
    for key in requested:
        entry = get_source_family(key)  # raises if unknown — fine here.
        cred = credential_state.get(key, {})
        status = entry["adapter_status"]
        if status == ADAPTER_IMPLEMENTED:
            implemented.append(key)
        elif status == ADAPTER_PARTIAL:
            partial.append(key)
        elif status == ADAPTER_PLANNED:
            planned.append(key)
        cred_configured = bool(cred.get("configured"))
        if entry["requires_api_key"] and not cred_configured:
            skipped_missing_creds.append(key)
        entries.append({
            "source_key": key,
            "display_name": entry["display_name"],
            "adapter_status": status,
            "phase": entry.get("phase", "unknown"),
            "default_refresh_hours": entry["default_refresh_hours"],
            "credential_configured": cred_configured,
            "missing_env_keys": list(cred.get("missing_env_keys", ())),
            "advisory_status": ADVISORY_STATUS,
            "execution_gate": EXECUTION_GATE_LOCKED,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "human_review_required": True,
        })

    safe_to_run_without_live_keys = all(
        not entry["requires_api_key"] or entry["adapter_status"] != ADAPTER_IMPLEMENTED
        for entry in (get_source_family(k) for k in requested)
        # the predicate above is *required-key-implementation*; in dry-run
        # mode no source is *forced* to run, so safe_to_run is always True
        # in dry-run. We compute the no-live-keys variant for documentation.
    )

    return {
        "cadence_hours": int(cadence_hours) if cadence_hours else DEFAULT_REFRESH_HOURS,
        "requested_source_keys": requested,
        "implemented": implemented,
        "partial": partial,
        "planned": planned,
        "skipped_missing_creds": skipped_missing_creds,
        "entries": entries,
        "safe_to_run_without_live_keys": bool(safe_to_run_without_live_keys),
        "dry_run_supported": True,
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
    }


def _normalise_source_keys(source_keys: Iterable[str] | None) -> list[str]:
    """Turn ``None`` into "all sources, in canonical order" and an iterable
    of keys into a validated, deduplicated, canonical-order list.
    """
    if source_keys is None:
        return [src["source_key"] for src in _SOURCE_REGISTRY]
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in source_keys:
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower()
        if not key or key in seen:
            continue
        if key not in _SOURCE_BY_KEY:
            raise KeyError(f"unknown_source: {key}")
        seen.add(key)
        cleaned.append(key)
    if not cleaned:
        # An explicit empty selection — return empty, do not silently expand.
        return []
    # Preserve canonical order.
    canonical = [src["source_key"] for src in _SOURCE_REGISTRY]
    return [k for k in canonical if k in seen]


# ---------------------------------------------------------------------------
# Source freshness state (added by Self-Test Hardening sprint)
# ---------------------------------------------------------------------------

FRESHNESS_FRESH = "fresh"
FRESHNESS_STALE = "stale"
FRESHNESS_OVERDUE = "overdue"
FRESHNESS_NEVER_RUN = "never_run"
FRESHNESS_SKIPPED = "skipped"
FRESHNESS_FAILED = "failed"


def _parse_iso8601(value: Any) -> float | None:
    """Parse an ISO8601 timestamp into a Unix epoch float. Returns ``None`` on
    failure rather than raising — the diagnostic must never crash on garbage.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    import datetime as _dt

    text = value.strip()
    # Normalise trailing "Z" to "+00:00" so fromisoformat accepts it.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.timestamp()


def compute_source_freshness(
    latest_runs: Iterable[Mapping[str, Any]] | None,
    *,
    cadence_hours: int = DEFAULT_REFRESH_HOURS,
    now_epoch: float | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute per-source freshness given the latest ``source_run_log`` rows.

    Parameters
    ----------
    latest_runs : iterable of mappings
        One row per source — usually the output of
        ``persistence.get_latest_source_run_per_source()``. Each row must
        carry at minimum ``source_name``, ``status``, ``timestamp_utc``.
        Recognised statuses: ``OK``, ``SKIP``/``SKIPPED``, ``FAIL``/``ERROR``.
    cadence_hours : int
        The expected refresh cadence. Defaults to 6h, matching the
        registry's ``default_refresh_hours``.
    now_epoch : float, optional
        Override the current time (seconds since epoch). Used by tests.
    env : mapping, optional
        Forwarded to credential detection so missing-key sources are
        reported as ``skipped`` rather than ``never_run``.

    Returns
    -------
    dict
        ``{source_key: {freshness_state, last_success_at, next_expected_refresh_at,
        hours_since_last_success, advisory_status, execution_gate,
        broker_api_called, ai_execution_count, can_execute,
        execution_permission, may_inform_human_review, may_execute,
        may_call_broker, credential_configured}}``

    No secrets are exposed. Sources that lack required credentials are
    explicitly marked ``skipped`` so the operator does not confuse
    "configured but stale" with "never configured".
    """
    import time as _time

    now = float(now_epoch) if now_epoch is not None else _time.time()
    cadence = max(1, int(cadence_hours or DEFAULT_REFRESH_HOURS))

    by_source: dict[str, Mapping[str, Any]] = {}
    if latest_runs:
        for row in latest_runs:
            if not isinstance(row, Mapping):
                continue
            key = row.get("source_name")
            if isinstance(key, str) and key:
                by_source[key] = row

    credential_state = detect_source_credential_state(env)
    out: dict[str, dict[str, Any]] = {}

    for src in _SOURCE_REGISTRY:
        key = src["source_key"]
        row = by_source.get(key)
        cred = credential_state.get(key, {})
        cred_configured = bool(cred.get("configured", False))

        last_success_at: str | None = None
        last_success_epoch: float | None = None
        status: str | None = None

        if row is not None:
            status = str(row.get("status") or "").upper() or None
            ts = row.get("timestamp_utc")
            epoch = _parse_iso8601(ts)
            if status == "OK" and epoch is not None:
                last_success_at = str(ts)
                last_success_epoch = epoch

        if not cred_configured and src["requires_api_key"]:
            freshness_state = FRESHNESS_SKIPPED
            hours_since = None
            next_expected_refresh_at = None
        elif last_success_epoch is None:
            if status in {"FAIL", "ERROR"}:
                freshness_state = FRESHNESS_FAILED
            elif status in {"SKIP", "SKIPPED"}:
                freshness_state = FRESHNESS_SKIPPED
            else:
                freshness_state = FRESHNESS_NEVER_RUN
            hours_since = None
            next_expected_refresh_at = None
        else:
            hours_since = (now - last_success_epoch) / 3600.0
            if hours_since <= cadence:
                freshness_state = FRESHNESS_FRESH
            elif hours_since <= cadence * 2:
                freshness_state = FRESHNESS_STALE
            else:
                freshness_state = FRESHNESS_OVERDUE
            next_expected_refresh_at = _format_epoch(last_success_epoch + cadence * 3600)

        out[key] = {
            "source_key": key,
            "freshness_state": freshness_state,
            "last_success_at": last_success_at,
            "hours_since_last_success": (
                round(hours_since, 4) if hours_since is not None else None
            ),
            "next_expected_refresh_at": next_expected_refresh_at,
            "cadence_hours": cadence,
            "credential_configured": cred_configured,
            "adapter_status": src["adapter_status"],
            "advisory_status": ADVISORY_STATUS,
            "execution_gate": EXECUTION_GATE_LOCKED,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "execution_permission": False,
            "can_execute": False,
            "may_inform_human_review": True,
            "may_execute": False,
            "may_call_broker": False,
        }
    return out


def _format_epoch(epoch: float) -> str:
    import datetime as _dt

    return (
        _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Convenience constants
# ---------------------------------------------------------------------------

ALL_SOURCE_KEYS: tuple[str, ...] = tuple(src["source_key"] for src in _SOURCE_REGISTRY)

__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "DEFAULT_REFRESH_HOURS",
    "ADAPTER_IMPLEMENTED",
    "ADAPTER_PARTIAL",
    "ADAPTER_PLANNED",
    "ADAPTER_NOT_CONFIGURED",
    "ALL_SOURCE_KEYS",
    "FRESHNESS_FRESH",
    "FRESHNESS_STALE",
    "FRESHNESS_OVERDUE",
    "FRESHNESS_NEVER_RUN",
    "FRESHNESS_SKIPPED",
    "FRESHNESS_FAILED",
    "build_refresh_plan",
    "compute_source_freshness",
    "detect_source_credential_state",
    "get_source_family",
    "list_live_source_families",
]
