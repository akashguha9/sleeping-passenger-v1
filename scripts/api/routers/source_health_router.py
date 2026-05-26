"""Source-health router — read-only, advisory-only.

Calibration Corpus + Hosted Canary sprint, Phase 3.

Extracts ``GET /source-health``, ``GET /source-health/summary`` and
``GET /source-health/watchdog`` from ``scripts/api_server.py``.  The
helpers are re-exported back so direct imports / patches in tests
continue to work.

Patch surface:
* ``scripts.api_server._get_source_health_summary``
* ``scripts.api_server._get_source_run_log``
* ``scripts.api_server.list_inbox_items``  (already a re-export)
* ``scripts.api_server._build_watchdog_summary_response``  (new)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def get(self, *_a: Any, **_kw: Any):
            def decorator(fn):
                return fn

            return decorator


_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0
_WATCHDOG_SUMMARY_STALE_AFTER_MINUTES = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_source_run_log(limit: int = 50) -> list:
    try:
        try:
            from scripts.persistence import get_source_run_log
        except ModuleNotFoundError:
            from persistence import get_source_run_log  # type: ignore
        return get_source_run_log(limit=limit)
    except Exception:
        return []


def _get_source_health_summary() -> dict:
    try:
        try:
            from scripts.source_health_summary import (
                build_source_health_summary,
                empty_summary as empty_source_health_summary,
            )
            from scripts.persistence import (
                get_latest_source_run_per_source,
                count_signal_events_by_source,
            )
        except ModuleNotFoundError:
            from source_health_summary import (  # type: ignore[no-redef]
                build_source_health_summary,
                empty_summary as empty_source_health_summary,
            )
            from persistence import (  # type: ignore[no-redef]
                get_latest_source_run_per_source,
                count_signal_events_by_source,
            )
        latest_rows = get_latest_source_run_per_source()
        event_counts = count_signal_events_by_source()
    except Exception as exc:
        try:
            from scripts.source_health_summary import empty_summary as empty_source_health_summary
        except ModuleNotFoundError:
            from source_health_summary import empty_summary as empty_source_health_summary  # type: ignore
        return empty_source_health_summary(error=str(exc))
    return build_source_health_summary(latest_rows, event_counts)


def _log_source_health(stats: dict, bull_state: str) -> None:
    try:
        try:
            from scripts.persistence import insert_source_health
        except ModuleNotFoundError:
            from persistence import insert_source_health  # type: ignore
        insert_source_health(
            snapshot_count=int(stats.get("total_snapshot_rows", 0)),
            signal_event_count=int(stats.get("total_signal_events", 0)),
            ticker_count=int(stats.get("total_tickers_observed", 0)),
            killed_count=int(stats.get("killed_signal_count", 0)),
            blocked_count=int(stats.get("blocked_signal_count", 0)),
            fabric_bull_state=str(bull_state),
        )
    except Exception:
        pass


def _watchdog_summary_path() -> Path:
    return Path(__file__).resolve().parents[3] / "runtime" / "refresh_watchdog_summary.json"


def _watchdog_safety_payload() -> dict:
    return {
        "advisory_status": "ADVISORY_ONLY",
        "advisory_only": True,
        "human_execution_required": True,
        "human_review_required": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "can_execute": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "broker_order_id": "NONE",
    }


def _build_watchdog_summary_response(
    *,
    summary_path: Path | None = None,
    now_iso: str | None = None,
) -> dict:
    """Pure builder for ``GET /source-health/watchdog`` — read-only.

    Behaviour and contract identical to the prior implementation that
    lived on ``scripts/api_server.py``.
    """
    import datetime as _dt
    import json as _json

    target = Path(summary_path) if summary_path else _watchdog_summary_path()
    safety = _watchdog_safety_payload()
    if now_iso:
        now_dt = _dt.datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)
    else:
        now_dt = _dt.datetime.now(_dt.timezone.utc)
    loaded_at_iso = now_dt.isoformat(timespec="seconds")

    if not target.exists():
        return {
            "present": False,
            "status": "MISSING",
            "reason": "refresh_watchdog_summary.json not found",
            "summary_path": str(target),
            "loaded_at_utc": loaded_at_iso,
            "age_seconds": None,
            "age_minutes": None,
            "stale": False,
            "summary": None,
            **safety,
        }
    try:
        text = target.read_text(encoding="utf-8")
        parsed = _json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("watchdog summary must be a JSON object")
    except Exception as exc:  # noqa: BLE001 - never crash the route
        return {
            "present": True,
            "status": "ERROR",
            "reason": f"failed_to_parse_summary: {type(exc).__name__}: {exc}",
            "summary_path": str(target),
            "loaded_at_utc": loaded_at_iso,
            "age_seconds": None,
            "age_minutes": None,
            "stale": False,
            "summary": None,
            **safety,
        }

    generated = parsed.get("generated_at_utc") or parsed.get("finished_at_utc")
    age_seconds: float | None = None
    age_minutes: float | None = None
    summary_stale = False
    if generated:
        try:
            gdt = _dt.datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            if gdt.tzinfo is None:
                gdt = gdt.replace(tzinfo=_dt.timezone.utc)
            age_seconds = round((now_dt - gdt).total_seconds(), 3)
            age_minutes = round(age_seconds / 60.0, 3)
            summary_stale = age_minutes is not None and age_minutes > _WATCHDOG_SUMMARY_STALE_AFTER_MINUTES
        except ValueError:
            age_seconds = None
            age_minutes = None
            summary_stale = False

    status = str(parsed.get("status") or "UNKNOWN")
    return {
        "present": True,
        "status": status,
        "reason": None,
        "summary_path": str(target),
        "loaded_at_utc": loaded_at_iso,
        "age_seconds": age_seconds,
        "age_minutes": age_minutes,
        "stale": bool(summary_stale),
        "summary_stale_after_minutes": _WATCHDOG_SUMMARY_STALE_AFTER_MINUTES,
        "summary": {
            "operation": parsed.get("operation"),
            "run_id": parsed.get("run_id"),
            "status": status,
            "ttl_hours": parsed.get("ttl_hours"),
            "max_retries": parsed.get("max_retries"),
            "retries_attempted": parsed.get("retries_attempted"),
            "freshness_improved": parsed.get("freshness_improved"),
            "improvement_reasons": parsed.get("improvement_reasons") or [],
            "backoff_seconds": parsed.get("backoff_seconds") or [],
            "backoff_jitter_pct": parsed.get("backoff_jitter_pct"),
            "jitter_enabled": parsed.get("jitter_enabled"),
            "planned_sleep_seconds_per_retry": parsed.get(
                "planned_sleep_seconds_per_retry"
            )
            or [],
            "actual_sleep_seconds_per_retry": parsed.get(
                "actual_sleep_seconds_per_retry"
            )
            or [],
            "stale_sources_before": parsed.get("stale_sources_before") or [],
            "stale_sources_after": parsed.get("stale_sources_after") or [],
            "excluded_optional_sources": parsed.get("excluded_optional_sources") or [],
            "parent_stale_derived_sources": parsed.get("parent_stale_derived_sources")
            or [],
            "derived_source_dependency_status": parsed.get(
                "derived_source_dependency_status"
            )
            or {},
            "dependency_critical_sources": parsed.get("dependency_critical_sources")
            or [],
            "kalshi_freshness_before": parsed.get("kalshi_freshness_before"),
            "kalshi_freshness_after": parsed.get("kalshi_freshness_after"),
            "prediction_market_disagreement_freshness_before": parsed.get(
                "prediction_market_disagreement_freshness_before"
            ),
            "prediction_market_disagreement_freshness_after": parsed.get(
                "prediction_market_disagreement_freshness_after"
            ),
            "kalshi_status_before": parsed.get("kalshi_status_before"),
            "kalshi_status_after": parsed.get("kalshi_status_after"),
            "gdelt_status_before": parsed.get("gdelt_status_before"),
            "gdelt_status_after": parsed.get("gdelt_status_after"),
            "prediction_market_disagreement_status_before": parsed.get(
                "prediction_market_disagreement_status_before"
            ),
            "prediction_market_disagreement_status_after": parsed.get(
                "prediction_market_disagreement_status_after"
            ),
            "started_at_utc": parsed.get("started_at_utc"),
            "finished_at_utc": parsed.get("finished_at_utc"),
            "generated_at_utc": parsed.get("generated_at_utc"),
        },
        **safety,
    }


# ---------------------------------------------------------------------------
# Route handlers — resolve helpers via scripts.api_server at request time
# so test patches on those symbols apply.
# ---------------------------------------------------------------------------


def get_source_health() -> dict:
    import scripts.api_server as _srv

    list_inbox = getattr(_srv, "list_inbox_items")
    result = list_inbox(write_runtime=False)
    stats = result.get("fabric_stats", {})
    bull_state = result.get("fabric_bull_state", "UNKNOWN")
    log_fn = getattr(_srv, "_log_source_health", _log_source_health)
    log_fn(stats, bull_state)
    run_log_fn = getattr(_srv, "_get_source_run_log", _get_source_run_log)
    return {
        "operation": "get_source_health",
        "fabric_stats": stats,
        "fabric_bull_state": bull_state,
        "source_run_log": run_log_fn(limit=20),
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
        "generated_at": result.get("generated_at", ""),
    }


def get_source_health_summary() -> dict:
    import scripts.api_server as _srv

    fn = getattr(_srv, "_get_source_health_summary", _get_source_health_summary)
    return fn()


def get_source_health_watchdog() -> dict:
    import scripts.api_server as _srv

    fn = getattr(_srv, "_build_watchdog_summary_response", _build_watchdog_summary_response)
    return fn()


def build_router():
    router = APIRouter()
    router.get("/source-health")(get_source_health)
    router.get("/source-health/summary")(get_source_health_summary)
    router.get("/source-health/watchdog")(get_source_health_watchdog)
    return router
