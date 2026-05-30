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


def _build_kalshi_truth_response() -> dict:
    """Return the split-semantic Kalshi truth + sanitized health artifact.

    Read-only.  Never echoes secrets.  Falls back to MISSING / UNKNOWN
    when the artifact is absent so the UI can render the split state
    honestly.
    """
    try:
        try:
            from scripts.kalshi_semantic_freshness import (
                build_kalshi_truth,
                load_health_artifact,
            )
            from scripts.persistence import count_fresh_signal_events_by_source
        except ModuleNotFoundError:  # pragma: no cover
            from kalshi_semantic_freshness import (  # type: ignore[no-redef]
                build_kalshi_truth,
                load_health_artifact,
            )
            from persistence import count_fresh_signal_events_by_source  # type: ignore[no-redef]
        # Resolve runtime/release relative to repo root so a process started
        # from anywhere still finds the artifact.
        _repo_root = Path(__file__).resolve().parents[3]
        health_path = _repo_root / "runtime" / "release" / "kalshi_source_health.json"
        artifact = load_health_artifact(health_path)
        canonical_stats = count_fresh_signal_events_by_source(
            source_name="kalshi", ttl_hours=6.0
        )
        truth = build_kalshi_truth(
            health_path=health_path,
            canonical_stats=canonical_stats,
            ttl_hours=6.0,
        )

        sanitized_artifact: dict = {}
        if artifact.present and isinstance(artifact.raw, dict):
            forbidden = {
                "api_key_id",
                "private_key_path",
                "authorization",
                "kalshi-access-key",
                "kalshi-access-signature",
                "kalshi-access-timestamp",
            }
            sanitized_artifact = {
                k: v
                for k, v in artifact.raw.items()
                if str(k).lower() not in forbidden
            }
        # Surface both the truth block (for new UI components) and a
        # backwards-compatible "sanitized artifact" block so the existing
        # operator-truth panel keeps rendering.
        response: dict = {
            "kalshi_semantic_truth": truth,
            "artifact_present": artifact.present,
            "artifact": sanitized_artifact or None,
            **_watchdog_safety_payload(),
        }
        # Surface canonical fields at the top level so the existing
        # frontend client (which reads ``KalshiSourceHealthResponse``)
        # keeps working without renaming.
        if sanitized_artifact:
            response.update(sanitized_artifact)
        response["api_health_status"] = truth["api_health_status"]
        response["canonical_signal_status"] = truth["canonical_signal_status"]
        response["semantic_fresh"] = truth["semantic_fresh"]
        response["degraded"] = truth["degraded"]
        response["operator_message"] = truth["operator_message"]
        response["canonical_live_count"] = truth["canonical_live_count"]
        response["latest_canonical_fetched_at"] = truth["latest_canonical_fetched_at"]
        return response
    except Exception as exc:  # noqa: BLE001
        return {
            "kalshi_semantic_truth": None,
            "artifact_present": False,
            "artifact": None,
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "api_health_status": "UNKNOWN",
            "canonical_signal_status": "UNKNOWN",
            "semantic_fresh": False,
            "degraded": False,
            **_watchdog_safety_payload(),
        }


def get_kalshi_source_health() -> dict:
    """Route handler — resolves builder via ``scripts.api_server`` at
    request time so test patches still bite."""
    import scripts.api_server as _srv

    fn = getattr(_srv, "_build_kalshi_truth_response", _build_kalshi_truth_response)
    return fn()


# ---------------------------------------------------------------------------
# Wiring Sprint — canonical source-truth route.
#
# Surfaces the source_freshness_contract as the single canonical-status reducer
# so the API separates *provider API health* from *canonical fresh rows*.  A
# source with api_health_status == OK but rows_added == 0 is reported as
# ZERO_FRESH_ROWS (DEGRADED), never LIVE_CANONICAL — impossible to fake.
# ---------------------------------------------------------------------------


def _canonical_age_hours(created_at: Any, now_dt: Any) -> float | None:
    import datetime as _dt

    if not created_at:
        return None
    try:
        cdt = _dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if cdt.tzinfo is None:
        cdt = cdt.replace(tzinfo=_dt.timezone.utc)
    return round((now_dt - cdt).total_seconds() / 3600.0, 6)


def build_canonical_source_truth(
    source_run_rows: list,
    *,
    now_iso: str | None = None,
    ttl_hours: float = 24.0,
) -> dict:
    """Pure builder — classify each source's canonical truth.

    ``source_run_rows`` are rows shaped like ``persistence.get_source_run_log``
    output (``source``, ``status``, ``rows_added``, ``rows_filtered``,
    ``created_at`` ...).  Read-only; no DB or network access.
    """
    import datetime as _dt

    try:
        from scripts.source_freshness_contract import classify_canonical_status
    except ModuleNotFoundError:  # pragma: no cover
        from source_freshness_contract import classify_canonical_status  # type: ignore

    if now_iso:
        now_dt = _dt.datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)
    else:
        now_dt = _dt.datetime.now(_dt.timezone.utc)

    sources: list[dict] = []
    for row in source_run_rows or []:
        if not isinstance(row, dict):
            continue
        created_at = row.get("created_at") or row.get("fetched_at") or row.get("timestamp_utc")
        age_hours = _canonical_age_hours(created_at, now_dt)
        rows_added = int(row.get("rows_added") or 0)
        rows_filtered = int(row.get("rows_filtered") or 0)
        classified = classify_canonical_status(
            api_health_status=str(row.get("status") or row.get("api_health_status") or ""),
            rows_added=rows_added,
            age_hours=age_hours,
            ttl_hours=ttl_hours,
            mock_flag=bool(row.get("mock_flag", False)),
            backfill_only=bool(row.get("backfill_only", False)),
            filtered=rows_filtered > 0,
        )
        sources.append({
            "source": row.get("source") or row.get("source_name"),
            "api_health_status": classified["api_health_status"],
            "canonical_signal_status": classified["canonical_signal_status"],
            "rows_added": rows_added,
            "latest_canonical_signal_timestamp": created_at,
            "canonical_age_hours": age_hours,
            "is_live_canonical": classified["live_canonical"],
            "source_truth_score": classified["C_s"],
            "freshness_score": classified["freshness_score"],
        })

    live = [s for s in sources if s["is_live_canonical"]]
    return {
        "operation": "get_source_canonical_truth",
        "sources": sources,
        "live_canonical_count": len(live),
        "source_count": len(sources),
        **_watchdog_safety_payload(),
    }


def get_source_canonical_truth() -> dict:
    """Route handler — resolves the run-log via ``scripts.api_server`` at
    request time so test patches still bite."""
    import scripts.api_server as _srv

    run_log_fn = getattr(_srv, "_get_source_run_log", _get_source_run_log)
    return build_canonical_source_truth(run_log_fn(limit=50))


def build_router():
    router = APIRouter()
    router.get("/source-health")(get_source_health)
    router.get("/source-health/summary")(get_source_health_summary)
    router.get("/source-health/watchdog")(get_source_health_watchdog)
    router.get("/source-health/kalshi")(get_kalshi_source_health)
    router.get("/kalshi/source-health")(get_kalshi_source_health)
    router.get("/source-health/canonical-truth")(get_source_canonical_truth)
    return router
