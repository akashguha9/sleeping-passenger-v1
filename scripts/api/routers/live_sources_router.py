"""Live source status router — read-only, advisory-only.

Calibration Corpus + Hosted Canary sprint, Phase 3.

Extracts ``GET /live-sources/status`` and its large pure builder
``_build_live_sources_status`` from ``scripts/api_server.py``.  The
helper is re-exported back to ``scripts.api_server`` so existing
imports and patches continue to bite.  The route handler resolves the
builder via ``scripts.api_server`` at request time so
``patch("scripts.api_server._build_live_sources_status", ...)`` works.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover — env-dependent
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def get(self, *_a: Any, **_kw: Any):
            def decorator(fn):
                return fn

            return decorator


_STALE_THRESHOLD_HOURS = 6
_SCHEDULER_HINT_PS = (
    ".\\scripts\\windows\\register_live_signal_refresh_task.ps1 "
    "(every 6h Scheduled Task)"
)
_SCHEDULER_HINT_MANUAL = (
    "python scripts/refresh_live_signals.py --write"
)

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0


def _build_live_sources_status(
    *,
    stale_threshold_hours: int = _STALE_THRESHOLD_HOURS,
    now_iso: str | None = None,
) -> dict:
    """Pure builder for ``GET /live-sources/status``.

    Behaviour and contract identical to the prior implementation that
    lived directly on ``scripts/api_server.py`` (Identity Collapse +
    earlier sprints).  Read-only — never refreshes, never writes, never
    triggers execution.
    """
    import datetime as _dt

    if now_iso:
        now_dt = _dt.datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)
    else:
        now_dt = _dt.datetime.now(_dt.timezone.utc)
    now_epoch = now_dt.timestamp()

    try:
        try:
            from scripts.live_source_registry import compute_source_freshness
            from scripts.persistence import (
                get_latest_source_run_per_source,
                get_latest_refresh_run_per_source,
                get_persisted_row_stats_per_source,
            )
        except ModuleNotFoundError:
            from live_source_registry import compute_source_freshness  # type: ignore[no-redef]
            from persistence import (  # type: ignore[no-redef]
                get_latest_source_run_per_source,
                get_latest_refresh_run_per_source,
                get_persisted_row_stats_per_source,
            )
        latest_runs = get_latest_source_run_per_source()
        freshness = compute_source_freshness(latest_runs, now_epoch=now_epoch)
        try:
            refresh_runs = get_latest_refresh_run_per_source()
        except Exception:
            refresh_runs = {}
        try:
            persisted_stats = get_persisted_row_stats_per_source()
        except Exception:
            persisted_stats = {}
    except Exception as exc:
        return {
            "operation": "get_live_sources_status",
            "sources": {},
            "source_count": 0,
            "freshness_distribution": {},
            "stale_sources": [],
            "excluded_from_stale": [],
            "source_errors": {},
            "refresh_configured": False,
            "stale_threshold_hours": int(stale_threshold_hours),
            "scheduler_hint": _SCHEDULER_HINT_PS,
            "manual_refresh_command": _SCHEDULER_HINT_MANUAL,
            "source_coverage_rows": {},
            "asia_disclosure_coverage_rows": [],
            "error": str(exc),
            "advisory_status": _ADVISORY_STATUS,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_permission": False,
            "can_execute": False,
            "human_review_required": True,
        }

    refresh_configured = bool(refresh_runs)
    stale_sources: list[str] = []
    excluded_from_stale: list[dict[str, str]] = []
    source_errors: dict[str, str] = {}
    latest_attempt_iso: str | None = None
    latest_success_iso: str | None = None

    for source_key, entry in freshness.items():
        refresh_row = refresh_runs.get(source_key, {})
        last_attempt_at = refresh_row.get("finished_at") or refresh_row.get("started_at")
        last_success_at = (
            refresh_row.get("finished_at")
            if int(refresh_row.get("success", 0) or 0)
            else None
        )
        refresh_age_hours: float | None = None
        if last_attempt_at:
            try:
                attempt_dt = _dt.datetime.fromisoformat(
                    str(last_attempt_at).replace("Z", "+00:00")
                )
                if attempt_dt.tzinfo is None:
                    attempt_dt = attempt_dt.replace(tzinfo=_dt.timezone.utc)
                refresh_age_hours = round(
                    (now_dt - attempt_dt).total_seconds() / 3600.0, 4
                )
            except ValueError:
                refresh_age_hours = None

        last_refresh_success = bool(int(refresh_row.get("success", 0) or 0))
        last_refresh_skipped = bool(int(refresh_row.get("skipped", 0) or 0))
        last_refresh_error = str(refresh_row.get("error_message") or "")
        last_refresh_skip_reason = str(refresh_row.get("skipped_reason") or "")

        freshness_state = entry.get("freshness_state", "unknown")
        hours_since_success = entry.get("hours_since_last_success")
        adapter_status = str(entry.get("adapter_status") or "").lower()
        source_tier = str(entry.get("tier") or "").lower()
        credential_configured = bool(entry.get("credential_configured", False))

        stale_excluded_reason: str | None = None
        if adapter_status == "planned" or source_tier == "planned":
            stale_excluded_reason = "planned_not_scored"
        elif source_tier == "optional" and not credential_configured:
            stale_excluded_reason = "optional_config_missing"

        if source_key == "asia_disclosure" and stale_excluded_reason is None:
            try:
                try:
                    from scripts.live_source_registry import (
                        asia_disclosure_subsource_state,
                    )
                except ModuleNotFoundError:  # pragma: no cover
                    from live_source_registry import (  # type: ignore[no-redef]
                        asia_disclosure_subsource_state,
                    )
                _asia_sub_state = asia_disclosure_subsource_state()
            except Exception:
                _asia_sub_state = {"any_configured": False, "sub_sources": {}}
            any_sub_configured = bool(_asia_sub_state.get("any_configured"))
            has_active_subsource_success = bool(
                freshness_state == "fresh" or last_refresh_success
            )
            if not any_sub_configured and not has_active_subsource_success:
                stale_excluded_reason = "optional_config_missing"
            _asia_sub_state["has_active_subsource_success"] = (
                has_active_subsource_success
            )
            entry["asia_disclosure_subsource_state"] = _asia_sub_state

        is_stale = False
        if stale_excluded_reason is None:
            if freshness_state in {"stale", "overdue", "never_run", "failed"}:
                is_stale = True
            if (
                isinstance(hours_since_success, (int, float))
                and hours_since_success > stale_threshold_hours
            ):
                is_stale = True
            if refresh_age_hours is not None and refresh_age_hours > stale_threshold_hours:
                is_stale = True
            if not refresh_configured and freshness_state != "skipped":
                is_stale = True

        if is_stale and freshness_state != "skipped":
            stale_sources.append(source_key)
        if stale_excluded_reason is not None:
            excluded_from_stale.append(
                {"source": source_key, "reason": stale_excluded_reason}
            )
        if last_refresh_error:
            source_errors[source_key] = last_refresh_error[:200]
        elif last_refresh_skip_reason and last_refresh_skipped:
            source_errors[source_key] = f"skipped: {last_refresh_skip_reason[:180]}"

        if stale_excluded_reason == "planned_not_scored":
            stale_reason = "planned adapter — not counted as stale"
        elif stale_excluded_reason == "optional_config_missing":
            stale_reason = "optional source not configured — not counted as stale"
        elif is_stale:
            if last_refresh_error:
                stale_reason = f"refresh error: {last_refresh_error[:120]}"
            elif freshness_state == "never_run":
                stale_reason = "no successful refresh recorded yet"
            elif freshness_state in {"stale", "overdue"}:
                stale_reason = (
                    f"source data older than {int(stale_threshold_hours)}h"
                )
            elif freshness_state == "failed":
                stale_reason = "last refresh failed"
            elif (
                refresh_age_hours is not None
                and refresh_age_hours > stale_threshold_hours
            ):
                stale_reason = (
                    f"last refresh attempt {refresh_age_hours:.1f}h ago "
                    f"(threshold {int(stale_threshold_hours)}h)"
                )
            else:
                stale_reason = "stale by refresh cadence"
        elif freshness_state == "skipped":
            if last_refresh_skip_reason:
                stale_reason = f"skipped: {last_refresh_skip_reason[:120]}"
            else:
                stale_reason = "skipped — refresh pending"
        elif freshness_state == "fresh":
            stale_reason = "fresh"
        else:
            stale_reason = f"state={freshness_state}"

        entry["last_refresh_attempt"] = last_attempt_at
        entry["last_refresh_success_at"] = last_success_at
        entry["last_refresh_success"] = last_refresh_success
        entry["last_refresh_skipped"] = last_refresh_skipped
        entry["refresh_age_hours"] = refresh_age_hours
        entry["stale_threshold_hours"] = int(stale_threshold_hours)
        entry["is_stale"] = bool(is_stale)
        entry["stale_reason"] = stale_reason
        if stale_excluded_reason is not None:
            entry["stale_excluded_reason"] = stale_excluded_reason
        if last_refresh_error:
            entry["last_refresh_error"] = last_refresh_error[:200]
        if last_refresh_skip_reason:
            entry["last_refresh_skipped_reason"] = last_refresh_skip_reason[:200]

        # Source display state — see truthfulness fix doc.
        stats = persisted_stats.get(source_key, {}) or {}
        persisted_row_count = int(stats.get("row_count") or 0)
        latest_persisted_row_at = stats.get("latest_fetched_at")

        is_optional_missing = stale_excluded_reason == "optional_config_missing"
        is_planned = stale_excluded_reason == "planned_not_scored"
        is_current_live = (
            not is_optional_missing
            and not is_planned
            and not is_stale
            and freshness_state == "fresh"
            and persisted_row_count > 0
        )

        coverage_row_count = 0
        if source_key == "asia_disclosure":
            try:
                try:
                    from scripts.ingestion.asia_disclosure_loader import (
                        get_asia_disclosure_country_rows,
                    )
                except ModuleNotFoundError:
                    from ingestion.asia_disclosure_loader import (  # type: ignore[no-redef]
                        get_asia_disclosure_country_rows,
                    )
                coverage_row_count = len(get_asia_disclosure_country_rows())
            except Exception:
                coverage_row_count = 0

        if is_current_live:
            display_state = "current_live"
            current_live_count = persisted_row_count
            archived_row_count = 0
            display_count_label = "Current live signals"
            display_timestamp_label = "Latest fetched"
            display_timestamp_value = latest_persisted_row_at
            source_display_warning = ""
            rows_display_reason = "current_live"
            rows_are_current_live = True
            rows_are_archived = False
            rows_are_stale = False
        elif is_optional_missing and source_key == "asia_disclosure":
            display_state = "optional_unconfigured_with_coverage"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = (
                "Coverage rows" if coverage_row_count > 0 else "Current live signals"
            )
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            source_display_warning = (
                "Asia Disclosure is optional and not configured. Set "
                "EDINET_API_KEY and/or OPENDART_API_KEY to enable live "
                "fetches; coverage list below is configuration only."
            )
            rows_display_reason = "optional_config_missing_coverage"
            rows_are_current_live = False
            rows_are_archived = persisted_row_count > 0
            rows_are_stale = False
        elif is_optional_missing and persisted_row_count > 0:
            display_state = "optional_unconfigured_with_archive"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = "Archived/persisted rows"
            display_timestamp_label = "Latest archived row"
            display_timestamp_value = latest_persisted_row_at
            display_name = source_key.replace("_", " ").title()
            source_display_warning = (
                f"{display_name} is optional and not configured. Rows "
                "below are archived/persisted records, not current live "
                "data."
            )
            rows_display_reason = "optional_config_missing_archive"
            rows_are_current_live = False
            rows_are_archived = True
            rows_are_stale = False
        elif is_optional_missing:
            display_state = "optional_unconfigured_empty"
            current_live_count = 0
            archived_row_count = 0
            display_count_label = "Current live signals"
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            display_name = source_key.replace("_", " ").title()
            source_display_warning = (
                f"{display_name} is optional and not configured. No "
                "current live data; set the required environment "
                "variable(s) to enable this source."
            )
            rows_display_reason = "optional_config_missing_empty"
            rows_are_current_live = False
            rows_are_archived = False
            rows_are_stale = False
        elif is_planned:
            display_state = "planned_coverage"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = (
                "Coverage rows" if coverage_row_count > 0 else "Current live signals"
            )
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            source_display_warning = (
                "This source is planned/not scored. Showing configured "
                "coverage only; no live source run has been recorded."
            )
            rows_display_reason = "planned_coverage"
            rows_are_current_live = False
            rows_are_archived = persisted_row_count > 0
            rows_are_stale = False
        elif is_stale:
            display_state = "stale_active"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = (
                "Stale persisted rows" if persisted_row_count > 0 else "Current live signals"
            )
            display_timestamp_label = (
                "Latest stale row" if persisted_row_count > 0 else "Latest attempted refresh"
            )
            display_timestamp_value = (
                latest_persisted_row_at if persisted_row_count > 0 else last_attempt_at
            )
            source_display_warning = (
                f"Stale active source — {stale_reason}. Retry the local "
                "refresh or reduce cadence."
            )
            rows_display_reason = "stale_active"
            rows_are_current_live = False
            rows_are_archived = False
            rows_are_stale = persisted_row_count > 0
        else:
            display_state = "never_run"
            current_live_count = 0
            archived_row_count = persisted_row_count
            display_count_label = "Current live signals"
            display_timestamp_label = "No live runs"
            display_timestamp_value = None
            source_display_warning = (
                "No successful refresh recorded yet for this source."
            )
            rows_display_reason = "never_run"
            rows_are_current_live = False
            rows_are_archived = persisted_row_count > 0
            rows_are_stale = False

        entry["display_state"] = display_state
        entry["is_current_live"] = bool(is_current_live)
        entry["is_configured"] = bool(credential_configured)
        entry["is_optional"] = source_tier == "optional"
        entry["is_planned"] = bool(is_planned)
        entry["is_active"] = adapter_status in {"implemented", "partial"} and not is_planned
        entry["is_scored"] = adapter_status in {"implemented", "partial"} and not is_planned
        entry["rows_are_current_live"] = bool(rows_are_current_live)
        entry["rows_are_archived"] = bool(rows_are_archived)
        entry["rows_are_stale"] = bool(rows_are_stale)
        entry["current_live_count"] = int(current_live_count)
        entry["archived_row_count"] = int(archived_row_count)
        entry["coverage_row_count"] = int(coverage_row_count)
        entry["total_persisted_count"] = int(persisted_row_count)
        entry["latest_persisted_row_at_utc"] = latest_persisted_row_at
        entry["latest_current_refresh_at_utc"] = (
            last_success_at if is_current_live else None
        )
        entry["latest_source_event_at_utc"] = (
            latest_persisted_row_at if is_current_live else None
        )
        entry["display_count_label"] = display_count_label
        entry["display_timestamp_label"] = display_timestamp_label
        entry["display_timestamp_value"] = display_timestamp_value
        entry["source_display_warning"] = source_display_warning
        entry["rows_display_reason"] = rows_display_reason
        entry["excluded_from_stale"] = stale_excluded_reason is not None
        entry["advisory_only"] = True

        if last_attempt_at and (latest_attempt_iso is None or str(last_attempt_at) > latest_attempt_iso):
            latest_attempt_iso = str(last_attempt_at)
        if last_success_at and (latest_success_iso is None or str(last_success_at) > latest_success_iso):
            latest_success_iso = str(last_success_at)

    dist: dict = {}
    for entry in freshness.values():
        state = entry.get("freshness_state", "unknown")
        dist[state] = dist.get(state, 0) + 1

    try:
        try:
            from scripts.source_health_score import score_source, aggregate_health
        except ModuleNotFoundError:
            from source_health_score import score_source, aggregate_health  # type: ignore[no-redef]
        for src_key, entry in freshness.items():
            try:
                scored = score_source(entry)
            except Exception:
                continue
            for k, v in scored.items():
                if k in {"tier", "advisory_status", "execution_gate",
                         "broker_api_called", "ai_execution_count",
                         "execution_permission", "can_execute"}:
                    continue
                entry[k] = v
        health_summary = aggregate_health(freshness)
    except Exception:
        health_summary = {
            "health_label_distribution": {},
            "core_health_label": "healthy",
            "average_scored_health": None,
            "scored_count": 0,
            "planned_count": 0,
            "optional_missing_config_count": 0,
        }

    try:
        try:
            from scripts.check_live_signal_refresh_task import (
                check_live_signal_refresh_task,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from check_live_signal_refresh_task import (  # type: ignore[no-redef]
                check_live_signal_refresh_task,
            )
        auto_refresh_status = check_live_signal_refresh_task()
        auto_refresh_status["last_successful_refresh_utc"] = latest_success_iso
        auto_refresh_status["last_attempted_refresh_utc"] = (
            auto_refresh_status.get("last_attempted_refresh_utc") or latest_attempt_iso
        )
        auto_refresh_status["stale_sources"] = list(stale_sources)
        auto_refresh_status["excluded_from_stale"] = list(excluded_from_stale)
        auto_refresh_status["stale_threshold_hours"] = int(stale_threshold_hours)
    except Exception as exc:  # pragma: no cover - defensive
        auto_refresh_status = {
            "status": "UNKNOWN",
            "status_reason": f"scheduler probe failed: {type(exc).__name__}",
            "installed": False,
            "enabled": False,
            "advisory_only": True,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "execution_gate": "LOCKED",
        }

    source_coverage_rows: dict[str, list[dict[str, str]]] = {}
    asia_disclosure_coverage_rows: list[dict[str, str]] = []
    try:
        try:
            from scripts.ingestion.asia_disclosure_loader import (
                get_asia_disclosure_country_rows,
            )
        except ModuleNotFoundError:
            from ingestion.asia_disclosure_loader import (  # type: ignore[no-redef]
                get_asia_disclosure_country_rows,
            )
        asia_disclosure_coverage_rows = get_asia_disclosure_country_rows()
        source_coverage_rows["asia_disclosure"] = asia_disclosure_coverage_rows
    except Exception:
        asia_disclosure_coverage_rows = []
        source_coverage_rows.setdefault("asia_disclosure", [])

    return {
        "operation": "get_live_sources_status",
        "sources": freshness,
        "source_count": len(freshness),
        "freshness_distribution": dist,
        "stale_sources": stale_sources,
        "excluded_from_stale": excluded_from_stale,
        "source_errors": source_errors,
        "refresh_configured": refresh_configured,
        "stale_threshold_hours": int(stale_threshold_hours),
        "last_refresh_attempt": latest_attempt_iso,
        "last_refresh_success": latest_success_iso,
        "scheduler_hint": _SCHEDULER_HINT_PS,
        "manual_refresh_command": _SCHEDULER_HINT_MANUAL,
        "auto_refresh_status": auto_refresh_status,
        "health_summary": health_summary,
        "source_coverage_rows": source_coverage_rows,
        "asia_disclosure_coverage_rows": asia_disclosure_coverage_rows,
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_permission": False,
        "can_execute": False,
        "human_review_required": True,
    }


def get_live_sources_status() -> dict:
    """Route handler — resolves the builder via ``scripts.api_server``
    at request time so test patches on
    ``scripts.api_server._build_live_sources_status`` still bite."""
    import scripts.api_server as _srv

    fn = getattr(_srv, "_build_live_sources_status", _build_live_sources_status)
    return fn()


def build_router():
    router = APIRouter()
    router.get("/live-sources/status")(get_live_sources_status)
    return router
