"""
Pure source-health classification and summary helpers.

This module is intentionally dependency-light: it has no FastAPI, Pydantic,
or uvicorn imports.  It can be unit-tested without any web framework and is
re-exported by ``scripts.api_server`` to back the /source-health/summary
endpoint.

Rules (carried through to the API surface):
  - ALL outputs are ADVISORY_ONLY.
  - Execution is HUMAN_ONLY.
  - ai_execution_count is always 0.
  - No broker API connections, no order placement.
"""
from __future__ import annotations

import re
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_MODE = "HUMAN_ONLY"
AI_EXECUTION_COUNT = 0

# Human labels for each known source key.  Keep in sync with the live source
# runner module names.
SOURCE_LABELS: dict[str, str] = {
    "polymarket": "Polymarket",
    "kalshi": "Kalshi",
    "prediction_market_disagreement": "Prediction Market Disagreement",
    "gdelt": "GDELT",
    "sec_edgar": "SEC EDGAR",
    "newsapi": "NewsAPI",
    "event_registry": "Event Registry",
    "etherscan": "Etherscan",
    "grok_xai": "Grok/xAI",
    "market_data": "Market Data",
    "india": "India (NSE/RBI/SEBI)",
    "global_filings": "Global Filings",
    "asia_disclosure": "Asia Disclosure",
}

# Phase 1 sources are run via run_live_sources_phase1.py; everything else
# routes through run_live_sources_phase2.py.  Used to build accurate
# "no runs yet" hints for the frontend.
_PHASE_1_SOURCES: set[str] = {"polymarket", "gdelt", "sec_edgar"}


def _phase_command_for(source_name: str) -> str:
    # The disagreement scanner is a derived signal — it doesn't route
    # through phase1/phase2 ingestion.  Surface its own CLI so the
    # operator copy-pastes the right command from the empty-state card.
    if source_name == "prediction_market_disagreement":
        return (
            "python scripts/prediction_market_disagreement_scanner.py "
            "--dry-run --limit 50 --embedding-provider deterministic"
        )
    if source_name in _PHASE_1_SOURCES:
        return (
            f"python scripts/run_live_sources_phase1.py "
            f"--source {source_name} --dry-run"
        )
    return (
        f"python scripts/run_live_sources_phase2.py "
        f"--source {source_name} --dry-run"
    )


def classify_source_status(
    status: str, skipped_reason: str, error_message: str
) -> dict[str, str]:
    """Return ``{severity, category, human_message}`` for a run row.

    Severity is one of ``ok | info | warning | error``.
    Category is a short machine code (CREDITS_EXHAUSTED, RATE_LIMITED, ...).
    human_message is short, secret-free, and user-friendly.
    """
    s = (status or "").upper().strip()
    reason = (skipped_reason or "").lower()
    err = (error_message or "").lower()

    if s == "OK":
        return {"severity": "ok", "category": "OK", "human_message": "Source healthy."}
    if s == "OK_FILTERED":
        return {
            "severity": "ok",
            "category": "OK_FILTERED",
            "human_message": "Source healthy (filtered out off-domain rows).",
        }
    if s == "PLACEHOLDER":
        return {
            "severity": "info",
            "category": "PLACEHOLDER",
            "human_message": "Not implemented yet — placeholder source.",
        }
    if s == "SKIPPED":
        if "api_key" in reason or "api key" in reason or "missing key" in reason:
            return {
                "severity": "warning",
                "category": "MISSING_API_KEY",
                "human_message": "Source skipped: API key not configured.",
            }
        if "license" in reason or "credits" in reason or "quota" in reason:
            return {
                "severity": "warning",
                "category": "CREDITS_EXHAUSTED",
                "human_message": "Source skipped: credits/license appear exhausted.",
            }
        return {
            "severity": "info",
            "category": "SKIPPED",
            "human_message": "Source skipped this run.",
        }
    if s == "RATE_LIMITED":
        return {
            "severity": "warning",
            "category": "RATE_LIMITED",
            "human_message": "Source rate-limited — try again later.",
        }
    if s == "TIMEOUT":
        return {
            "severity": "warning",
            "category": "TIMEOUT",
            "human_message": "Source timed out — likely transient.",
        }
    if s == "HTTP_ERROR":
        if "402" in err or "credit" in err or "credits" in err:
            return {
                "severity": "warning",
                "category": "CREDITS_EXHAUSTED",
                "human_message": "Source unavailable: credits/license exhausted.",
            }
        if "401" in err or "403" in err or "unauthorized" in err:
            return {
                "severity": "warning",
                "category": "AUTH_ERROR",
                "human_message": "Source unavailable: authentication/authorization issue.",
            }
        if "429" in err:
            return {
                "severity": "warning",
                "category": "RATE_LIMITED",
                "human_message": "Source rate-limited (HTTP 429).",
            }
        return {
            "severity": "warning",
            "category": "HTTP_ERROR",
            "human_message": "Source returned an HTTP error.",
        }
    if s == "ERROR":
        if "credit" in err or "credits" in err:
            return {
                "severity": "warning",
                "category": "CREDITS_EXHAUSTED",
                "human_message": "Source unavailable: credits/license exhausted.",
            }
        return {
            "severity": "error",
            "category": "ERROR",
            "human_message": "Source error during last run.",
        }
    return {
        "severity": "info",
        "category": s or "UNKNOWN",
        "human_message": "Source status unknown.",
    }


_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|bearer)\s*[=:\s]\s*\S+"
)


def sanitize_error_text(text: str) -> str:
    """Trim and redact obvious secret-like tokens from error strings."""
    if not text:
        return ""
    out = str(text).strip()
    if len(out) > 240:
        out = out[:240] + "…"
    return _SECRET_PATTERN.sub(r"\1=<redacted>", out)


def _no_runs_message(source_name: str, label: str) -> str:
    """Source-specific 'no runs yet' message with the correct CLI hint.

    Asia Disclosure and other placeholder-leaning sources benefit from a
    concrete command, so the UI doesn't show a generic line.
    """
    cmd = _phase_command_for(source_name)
    return (
        f"No {label} run recorded yet. Run: {cmd}"
    )


def _placeholder_message(label: str) -> str:
    return (
        f"{label} is PLACEHOLDER / not implemented yet. "
        "No real provider is currently active."
    )


def build_source_health_summary(
    latest_rows: list[dict[str, Any]],
    event_counts: dict[str, int],
) -> dict[str, Any]:
    """Build the /source-health/summary payload from persisted rows.

    Pure function — no DB access here.  Callers fetch rows from persistence
    and feed them in; that makes the function trivially unit-testable.
    """
    sources: list[dict[str, Any]] = []
    warning_count = 0
    error_count = 0
    ok_count = 0

    seen: set[str] = set()
    for row in latest_rows:
        source_name = str(row.get("source_name", ""))
        if not source_name or source_name in seen:
            continue
        seen.add(source_name)
        status = str(row.get("status", ""))
        skipped_reason = str(row.get("skipped_reason", ""))
        error_message = sanitize_error_text(str(row.get("error_message", "")))
        classification = classify_source_status(status, skipped_reason, error_message)
        label = SOURCE_LABELS.get(source_name, source_name)

        human_message = classification["human_message"]
        if classification["category"] == "PLACEHOLDER":
            human_message = _placeholder_message(label)

        if classification["severity"] == "warning":
            warning_count += 1
        elif classification["severity"] == "error":
            error_count += 1
        elif classification["severity"] == "ok":
            ok_count += 1
        sources.append({
            "source_name": source_name,
            "label": label,
            "status": status,
            "severity": classification["severity"],
            "category": classification["category"],
            "human_message": human_message,
            "skipped_reason": skipped_reason,
            "error_message": error_message,
            "fetched_count": int(row.get("fetched_count", 0) or 0),
            "duration_ms": int(row.get("duration_ms", 0) or 0),
            "last_run_at": str(row.get("timestamp_utc", "")),
            "event_row_count": int(event_counts.get(source_name, 0)),
            "suggested_command": _phase_command_for(source_name),
        })

    for source_name, label in SOURCE_LABELS.items():
        if source_name in seen:
            continue
        sources.append({
            "source_name": source_name,
            "label": label,
            "status": "NO_RUNS",
            "severity": "info",
            "category": "NO_RUNS",
            "human_message": _no_runs_message(source_name, label),
            "skipped_reason": "",
            "error_message": "",
            "fetched_count": 0,
            "duration_ms": 0,
            "last_run_at": "",
            "event_row_count": int(event_counts.get(source_name, 0)),
            "suggested_command": _phase_command_for(source_name),
        })

    return {
        "sources": sources,
        "warning_count": warning_count,
        "error_count": error_count,
        "ok_count": ok_count,
        "total_count": len(sources),
        "advisory_status": ADVISORY_STATUS,
        "execution_mode": EXECUTION_MODE,
        "ai_execution_count": AI_EXECUTION_COUNT,
        "human_review_required": True,
        "broker_api_called": False,
    }


def empty_summary(error: str | None = None) -> dict[str, Any]:
    """Fallback payload when persistence is unreachable.  Keeps invariants."""
    payload: dict[str, Any] = {
        "sources": [],
        "warning_count": 0,
        "error_count": 0,
        "ok_count": 0,
        "total_count": 0,
        "advisory_status": ADVISORY_STATUS,
        "execution_mode": EXECUTION_MODE,
        "ai_execution_count": AI_EXECUTION_COUNT,
        "human_review_required": True,
        "broker_api_called": False,
    }
    if error:
        payload["error"] = error
    return payload
