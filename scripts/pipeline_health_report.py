from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.attention_proxy_engine import build_attention_proxy_report
    from scripts.action_engine import build_action_report
    from scripts.archetype_profile import build_archetype_profile_report
    from scripts.asset_durability_filter import build_asset_durability_report
    from scripts.baines_engine import build_baines_engine_report
    from scripts.blocker_cost_engine import build_blocker_cost_report
    from scripts.busquets_pre_execution_audit import evaluate_busquets_pre_execution_audit
    from scripts.closure_deficit_monitor import build_closure_deficit_report
    from scripts.execution_integrity_audit import evaluate_execution_integrity_audit
    from scripts.external_data_runtime_sync import apply_external_observation_report
    from scripts.governance_feedback_report import build_governance_feedback_report
    from scripts.football_portfolio_archetype_engine import (
        build_football_portfolio_archetype_report,
    )
    from scripts.integrity_diagnostics import (
        build_reproducibility_summary,
        build_signal_segmentation_summary,
        build_stable_health_snapshot,
        build_temporal_integrity_summary,
        build_truth_metrics_summary,
        compute_stable_health_snapshot_hash,
    )
    from scripts.moltbook_feedback import build_moltbook_feedback_report
    from scripts.narrative_operator_wisdom_filter import (
        evaluate_narrative_operator_wisdom_filter,
    )
    from scripts.optical_operating_system import evaluate_optical_operating_system
    from scripts.operator_control import build_operator_control_report
    from scripts.perception_control import build_perception_control_report
    from scripts.position_truth_resolver import (
        build_position_truth_summary,
        format_position_truth_summary,
    )
    from scripts.snapshot_logger import build_snapshot_row
    from scripts.runtime_common import (
        COMPLEXITY_LADDER_CONTROLLER_PATH,
        EXTREME_STATE_REPORT_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        FOOTBALL_PORTFOLIO_ARCHETYPE_REPORT_PATH,
        HEALTH_REPORT_PATH,
        SNAPSHOT_LOG_PATH,
        build_runtime_state_from_scm_report_payload,
        resolve_bridge_mode,
        build_truth_context,
        classify_operating_mode,
        load_json_file,
        load_open_positions,
        normalize_active_blockers,
        normalize_per_signal_rows,
        persist_current_runtime_state,
        repo_relative,
        set_source_mode,
        stamp_payload,
        write_json_atomic,
    )
    from scripts.signal_refinery import build_signal_refinery_report
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.trend_engine import build_trend_report
except ModuleNotFoundError:
    from attention_proxy_engine import build_attention_proxy_report
    from action_engine import build_action_report
    from archetype_profile import build_archetype_profile_report
    from asset_durability_filter import build_asset_durability_report
    from baines_engine import build_baines_engine_report
    from blocker_cost_engine import build_blocker_cost_report
    from busquets_pre_execution_audit import evaluate_busquets_pre_execution_audit
    from closure_deficit_monitor import build_closure_deficit_report
    from execution_integrity_audit import evaluate_execution_integrity_audit
    from external_data_runtime_sync import apply_external_observation_report
    from governance_feedback_report import build_governance_feedback_report
    from football_portfolio_archetype_engine import (
        build_football_portfolio_archetype_report,
    )
    from integrity_diagnostics import (
        build_reproducibility_summary,
        build_signal_segmentation_summary,
        build_stable_health_snapshot,
        build_temporal_integrity_summary,
        build_truth_metrics_summary,
        compute_stable_health_snapshot_hash,
    )
    from moltbook_feedback import build_moltbook_feedback_report
    from narrative_operator_wisdom_filter import (
        evaluate_narrative_operator_wisdom_filter,
    )
    from optical_operating_system import evaluate_optical_operating_system
    from operator_control import build_operator_control_report
    from perception_control import build_perception_control_report
    from position_truth_resolver import (
        build_position_truth_summary,
        format_position_truth_summary,
    )
    from snapshot_logger import build_snapshot_row
    from runtime_common import (
        COMPLEXITY_LADDER_CONTROLLER_PATH,
        EXTREME_STATE_REPORT_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        FOOTBALL_PORTFOLIO_ARCHETYPE_REPORT_PATH,
        HEALTH_REPORT_PATH,
        SNAPSHOT_LOG_PATH,
        build_runtime_state_from_scm_report_payload,
        resolve_bridge_mode,
        build_truth_context,
        classify_operating_mode,
        load_json_file,
        load_open_positions,
        normalize_active_blockers,
        normalize_per_signal_rows,
        persist_current_runtime_state,
        repo_relative,
        set_source_mode,
        stamp_payload,
        write_json_atomic,
    )
    from signal_refinery import build_signal_refinery_report
    from signal_conversion_monitor import build_signal_conversion_report
    from trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SEEDED_SNAPSHOT_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"
TARGET_TEST_COMMAND = [
    sys.executable,
    "-m",
    "pytest",
    str(Path("tests") / "test_moltbook_schema.py"),
    str(Path("tests") / "test_moltbook_loader.py"),
    str(Path("tests") / "test_action_engine.py"),
    str(Path("tests") / "test_blocker_cost_engine.py"),
    str(Path("tests") / "test_trend_engine.py"),
    str(Path("tests") / "test_signal_refinery.py"),
    "-q",
]

SCORECARD_RULES = {
    "logging_quality": [
        "+2 if Moltbook summary is present",
        "+2 if signal_summary is present",
        "+2 if per-signal action summary is present",
        "+2 if blocker cost report is present",
        "+2 if trend report is present",
    ],
    "schema_reliability": [
        "+3 if open_positions validation passes",
        "+3 if SCM signal summary is coherent",
        "+2 if blocker weights config loaded",
        "+2 if targeted tests were invoked and passed",
    ],
    "end_to_end_wiring": [
        "+2 if SCM report is live",
        "+2 if action engine is live",
        "+2 if blocker cost engine is live",
        "+2 if trend engine is live",
        "+2 if health report persists runtime outputs",
    ],
    "self_correction_maturity": [
        "+3 if snapshot history contains 2 or more rows",
        "+3 if per-signal attribution exists",
        "+2 if minimum conditions to improve are explicit",
        "+2 if next operational action is explicit",
    ],
    "execution_readiness": [
        "Starts at 10 and is bounded between 0 and 10",
        "-1 to -2 for blocked promotable candidate backlog",
        "-1 to -3 for persistent promotable blockage",
        "-1 to -2 for chaos contamination",
        "-1 if policy_state remains RESTRICTED",
        "Final score is 10 minus the active readiness penalties",
    ],
}


def _last_non_empty_line(*blocks: str) -> str | None:
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return None


def _bounded_score(value: int) -> int:
    return max(0, min(value, 10))


def _coerce_optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_surface_recommendation(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"trainer", "utility", "jet"}:
        return text
    return "trainer"


def _load_optional_runtime_artifact(path: Path | None, default_path: Path) -> dict[str, Any]:
    payload = load_json_file(path or default_path, default={}) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _deterministic_trend_log_path(
    *,
    state: dict[str, Any],
    write_runtime: bool,
    simulation_context: dict[str, Any],
) -> Path | None:
    if write_runtime or simulation_context.get("is_simulated", False):
        return None
    operating_mode = str(classify_operating_mode(state) or "").strip().lower()
    truth_origin = str(build_truth_context(state).get("truth_origin") or "").strip().lower()
    if operating_mode == "seeded" and truth_origin == "seeded" and SEEDED_SNAPSHOT_FIXTURE_PATH.exists():
        return SEEDED_SNAPSHOT_FIXTURE_PATH
    return None


def build_experience_mode_summary(
    *,
    experience_mode_report: dict[str, Any] | None = None,
    complexity_ladder_controller: dict[str, Any] | None = None,
) -> dict[str, Any]:
    experience = experience_mode_report if isinstance(experience_mode_report, dict) else {}
    controller = (
        complexity_ladder_controller if isinstance(complexity_ladder_controller, dict) else {}
    )

    report_present = bool(experience)
    controller_present = bool(controller)
    trainer_metadata = experience.get("trainer_mode_metadata", {})
    readiness = experience.get("readiness_ladder", {})
    utility = experience.get("utility_resilience_layer", {})
    premium = experience.get("premium_compression_layer", {})

    recommended_surface_profile = _normalize_surface_recommendation(
        controller.get("operator_surface_recommendation")
        or trainer_metadata.get("recommended_surface_profile")
        or readiness.get("recommended_surface_profile")
    )
    trainer_mode_active = (
        recommended_surface_profile == "trainer"
        or bool(trainer_metadata.get("trainer_mode_active"))
    )
    degraded_mode_required = bool(utility.get("degraded_mode_required"))
    if controller_present:
        degraded_mode_required = (
            degraded_mode_required
            or bool(controller.get("degraded_mode_annotations_required"))
        )
    elif not report_present:
        degraded_mode_required = True

    premium_surface_eligible = bool(premium.get("premium_surface_eligible"))
    premium_surface_allowed = bool(controller.get("premium_surface_allowed")) if controller_present else False

    return {
        "experience_mode_report_present": report_present,
        "complexity_ladder_controller_present": controller_present,
        "recommended_surface_profile": recommended_surface_profile,
        "trainer_mode_active": trainer_mode_active,
        "degraded_mode_required": degraded_mode_required,
        "premium_surface_eligible": premium_surface_eligible,
        "premium_surface_allowed": premium_surface_allowed,
    }


def build_external_data_summary(
    external_data_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = external_data_report if isinstance(external_data_report, dict) else {}
    active_sources = report.get("active_sources", [])
    if not isinstance(active_sources, list):
        active_sources = []
    return {
        "external_data_report_present": bool(report),
        "external_observation_active": bool(report.get("external_observation_active")),
        "active_sources": [str(value) for value in active_sources if str(value).strip()],
        "success_source_count": int(report.get("success_source_count", 0)),
        "failure_source_count": int(report.get("failure_source_count", 0)),
        "note": report.get("note"),
    }


def build_external_observation_summary(
    external_observation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten the external observation lane report for health-report consumption.

    Always returns the same shape. When the lane was not run, all counts are
    zero and ``external_observation_active=False``. This keeps the
    diagnostics schema stable across seeded-fallback and external-active
    runs, and makes the lane's presence independently visible alongside the
    broader ``external_data_summary`` block.
    """
    report = external_observation_report if isinstance(external_observation_report, dict) else {}
    symbols = report.get("external_observation_symbols") or []
    if not isinstance(symbols, list):
        symbols = []
    providers = report.get("external_observation_providers") or []
    if not isinstance(providers, list):
        providers = []
    quality_counts = report.get("external_observation_data_quality_counts") or {}
    if not isinstance(quality_counts, dict):
        quality_counts = {}

    active = bool(report.get("external_observation_active"))
    valid = int(report.get("external_observation_valid_count", 0) or 0)
    stale = int(report.get("external_observation_stale_count", 0) or 0)
    return {
        "external_observation_active": active,
        "external_observation_count": int(report.get("external_observation_count", 0) or 0),
        "external_observation_valid_count": valid,
        "external_observation_stale_count": stale,
        "external_observation_error_count": int(
            report.get("external_observation_error_count", 0) or 0
        ),
        "external_observation_active_count": int(
            report.get("external_observation_active_count", valid + stale) or (valid + stale)
        ),
        "external_observation_provider": report.get("external_observation_provider"),
        "external_observation_providers": [str(p) for p in providers if str(p).strip()],
        "external_observation_symbols": [str(s) for s in symbols if str(s).strip()],
        "external_observation_data_quality_counts": {
            str(k): int(v or 0) for k, v in quality_counts.items()
        },
        "external_observation_temporal_rejection_count": int(
            report.get("external_observation_temporal_rejection_count", 0) or 0
        ),
        "external_observation_temporal_rejections": list(
            report.get("external_observation_temporal_rejections") or []
        ),
        "observations": list(report.get("observations") or []),
        "external_observation_report_path": report.get("external_observation_report_path"),
        "live_quotes_available": active,
    }


def build_signal_source_summary(
    per_signal_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = per_signal_rows if isinstance(per_signal_rows, list) else []
    summary = {
        "total_signal_count": 0,
        "seeded_signal_count": 0,
        "external_signal_count": 0,
        "unknown_signal_count": 0,
        "source_counts": {},
        "external_signal_tickers": [],
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        summary["total_signal_count"] += 1
        ticker = str(row.get("ticker") or "").strip().upper()
        source_name = str(row.get("source_name") or "signal_ledger").strip().lower() or "signal_ledger"
        signal_origin = str(row.get("signal_origin") or "seeded_runtime").strip().lower()
        summary["source_counts"][source_name] = summary["source_counts"].get(source_name, 0) + 1

        is_external = source_name.startswith("polymarket") or signal_origin == "external"
        is_seeded = source_name == "signal_ledger" or signal_origin in {
            "seeded_runtime",
            "seeded",
            "synthetic_runtime_fallback",
        }
        if is_external:
            summary["external_signal_count"] += 1
            if ticker:
                summary["external_signal_tickers"].append(ticker)
        elif is_seeded:
            summary["seeded_signal_count"] += 1
        else:
            summary["unknown_signal_count"] += 1
    return summary


def build_intelligence_summary(
    grok_xai_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = grok_xai_report if isinstance(grok_xai_report, dict) else {}
    extracted_output = report.get("extracted_output", {})
    if not isinstance(extracted_output, dict):
        extracted_output = {}
    return {
        "grok_report_present": bool(report),
        "request_attempted": bool(report.get("request_attempted")),
        "request_success": bool(report.get("request_success")),
        "use_case": report.get("use_case"),
        "model_used": report.get("model_used"),
        "recommended_operator_action": extracted_output.get("recommended_operator_action"),
        "operator_focus": extracted_output.get("operator_focus"),
        "top_item": extracted_output.get("top_item"),
        "error_kind": report.get("error_kind"),
        "note": report.get("note"),
    }


def build_extreme_state_logic_summary(
    extreme_state_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = extreme_state_report if isinstance(extreme_state_report, dict) else {}
    counts = report.get("extreme_state_logic", {}) if isinstance(report, dict) else {}
    if not isinstance(counts, dict):
        counts = {}
    return {
        "report_present": bool(report),
        "extreme_state": str(report.get("extreme_state") or "UNAVAILABLE"),
        "signals_evaluated": int(report.get("signals_evaluated", 0) or 0),
        "termination_required_count": int(counts.get("termination_required_count", 0) or 0),
        "silent_chaos_count": int(counts.get("silent_chaos_count", 0) or 0),
        "valid_but_non_executable_count": int(
            counts.get("valid_but_non_executable_count", 0) or 0
        ),
        "non_converting_equilibrium_count": int(
            counts.get("non_converting_equilibrium_count", 0) or 0
        ),
        "promoted_count": int(counts.get("promoted_count", 0) or 0),
        "downgraded_count": int(counts.get("downgraded_count", 0) or 0),
        "recommended_action": str(report.get("recommended_action") or "WAIT"),
    }


def _health_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _blocked_backlog_penalty(blocked_count: int) -> int:
    if blocked_count <= 0:
        return 0
    if blocked_count <= 2:
        return 1
    return 2


def _persistent_blockage_penalty(max_consecutive_snapshots: int) -> int:
    if max_consecutive_snapshots >= 6:
        return 3
    if max_consecutive_snapshots >= 4:
        return 2
    if max_consecutive_snapshots >= 2:
        return 1
    return 0


def _chaos_contamination_penalty(chaos_count: int) -> int:
    if chaos_count <= 0:
        return 0
    if chaos_count == 1:
        return 1
    return 2


def _load_latest_snapshot_row(path: Path | None = None) -> dict[str, Any] | None:
    target = path or SNAPSHOT_LOG_PATH
    if not target.exists():
        return None

    lines = [line for line in target.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not lines:
        return None

    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_latest_snapshot_timestamp(path: Path | None = None) -> str | None:
    row = _load_latest_snapshot_row(path)
    if not isinstance(row, dict):
        return None
    timestamp = row.get("timestamp")
    if isinstance(timestamp, str) and timestamp.strip():
        return timestamp
    return None


def build_runtime_state_from_scm_report(scm_report: dict[str, Any]) -> dict[str, Any]:
    return build_runtime_state_from_scm_report_payload(scm_report)


def get_git_status(repo_root: Path | None = None) -> dict[str, Any]:
    base = repo_root or REPO_ROOT

    try:
        head = subprocess.run(
            ["git", "--no-pager", "rev-parse", "--short", "HEAD"],
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "--no-pager", "status", "--short"],
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "head": None,
            "is_clean": None,
            "changed_paths": [],
            "error": "git executable not available",
        }

    if head.returncode != 0 or status.returncode != 0:
        return {
            "available": False,
            "head": None,
            "is_clean": None,
            "changed_paths": [],
            "error": _last_non_empty_line(head.stderr, status.stderr),
        }

    changed_paths = []
    for line in status.stdout.splitlines():
        entry = line.strip()
        if not entry:
            continue
        parts = entry.split(maxsplit=1)
        changed_paths.append(parts[1] if len(parts) > 1 else parts[0])

    return {
        "available": True,
        "head": head.stdout.strip(),
        "is_clean": len(changed_paths) == 0,
        "changed_paths": changed_paths,
        "error": None,
    }


def run_targeted_tests(repo_root: Path | None = None) -> dict[str, Any]:
    base = repo_root or REPO_ROOT
    result = subprocess.run(
        TARGET_TEST_COMMAND,
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "invoked": True,
        "command": TARGET_TEST_COMMAND,
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "summary_line": _last_non_empty_line(result.stdout, result.stderr),
    }


def determine_system_readiness(
    scm_review: dict[str, Any],
    execution_policy: dict[str, Any],
    friction_report: dict[str, Any],
    open_positions_summary: dict[str, Any],
    active_blockers: list[str],
) -> tuple[str, bool]:
    critical_blockers = {"GSCE_PHASE_LOCK", "REALM_BIS"}
    friction_band = friction_report.get("friction_band", "HIGH_FRICTION")
    scm_rate = float(scm_review.get("scm_rate", 0.0))
    policy_state = str(execution_policy.get("policy_state", "UNKNOWN")).upper()

    if not open_positions_summary.get("valid", False):
        return "NOT_READY", False

    if (
        policy_state in {"RESTRICTED", "BLOCKED", "DO_NOT_DEPLOY", "NOT_READY"}
        and (
            friction_band == "HIGH_FRICTION"
            or scm_rate < 0.30
            or bool(critical_blockers.intersection(active_blockers))
        )
    ):
        return "DO_NOT_DEPLOY", False

    if friction_band == "HIGH_FRICTION" or policy_state in {"RESTRICTED", "BLOCKED"}:
        return "NOT_READY", False

    if (
        not execution_policy.get("allow_new_risk", False)
        or friction_band == "MEDIUM_FRICTION"
        or scm_review.get("scm_state") == "LOW_CONVERSION"
    ):
        return "LIMITED_DEPLOY", False

    return "READY", True


def summarize_watchlist_intelligence(watchlist_diagnostics: dict[str, Any]) -> dict[str, Any]:
    diagnostics = watchlist_diagnostics if isinstance(watchlist_diagnostics, dict) else {}
    source_rows = diagnostics.get("watchlist_signals", [])
    if not isinstance(source_rows, list):
        source_rows = []

    promotable_names: list[str] = []
    standard_names: list[str] = []
    blocked_promotable_names: list[str] = []

    for row in source_rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        watchlist_tier = str(row.get("watchlist_tier") or "").upper()
        pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()

        if watchlist_tier == "PROMOTABLE" and ticker not in promotable_names:
            promotable_names.append(ticker)
        elif watchlist_tier == "STANDARD" and ticker not in standard_names:
            standard_names.append(ticker)

        if pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE" and ticker not in blocked_promotable_names:
            blocked_promotable_names.append(ticker)

    return {
        "promotion_threshold_ce_score": float(diagnostics.get("promotion_threshold_ce_score", 0.0)),
        "promotable_watchlist_count": len(promotable_names),
        "standard_watchlist_count": len(standard_names),
        "promotable_watchlist_names": promotable_names,
        "standard_watchlist_names": standard_names,
        "blocked_promotable_clean_candidate_count": len(blocked_promotable_names),
        "blocked_promotable_clean_candidate_names": blocked_promotable_names,
    }


def _persistent_block_count_map(trend_report: dict[str, Any] | None = None) -> dict[str, int]:
    report = trend_report if isinstance(trend_report, dict) else {}
    persistence = report.get("blocked_promotable_persistence", {})
    rows = persistence.get("persistent_names", []) if isinstance(persistence, dict) else []
    if not isinstance(rows, list):
        rows = []

    mapping: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        try:
            consecutive_snapshots = int(row.get("consecutive_snapshots", 0))
        except (TypeError, ValueError):
            consecutive_snapshots = 0
        mapping[ticker] = max(0, consecutive_snapshots)
    return mapping


def build_blocked_promotable_candidate_queue(
    watchlist_diagnostics: dict[str, Any],
    per_signal_rows: list[dict[str, Any]] | None = None,
    trend_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    diagnostics = watchlist_diagnostics if isinstance(watchlist_diagnostics, dict) else {}
    source_rows = diagnostics.get("watchlist_signals", [])
    if not isinstance(source_rows, list):
        source_rows = []

    per_signal_rows = per_signal_rows or []
    priority_by_ticker = {
        str(row.get("ticker") or "").upper(): _coerce_optional_number(row.get("priority_score"))
        for row in per_signal_rows
        if isinstance(row, dict)
    }
    persistent_block_counts = _persistent_block_count_map(trend_report)

    queue: list[dict[str, Any]] = []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("pre_entry_state") or "NONE").upper() != "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE":
            continue

        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue

        priority_score = priority_by_ticker.get(ticker)
        if priority_score is None:
            priority_score = _coerce_optional_number(row.get("priority_score"))

        queue.append(
            {
                "signal_id": str(row.get("signal_id") or ""),
                "ticker": ticker,
                "ce_score": float(row.get("ce_score", 0.0)),
                "priority_score": priority_score,
                "watchlist_tier": str(row.get("watchlist_tier") or "").upper(),
                "candidate_conversion_state": str(row.get("candidate_conversion_state") or "").upper(),
                "pre_entry_state": str(row.get("pre_entry_state") or "NONE").upper(),
                "blocker_attribution": str(row.get("blocker_attribution") or "").upper(),
                "gate_needed_to_clear": "GSCE_PHASE_LOCK",
                "persistent_block_count": max(1, persistent_block_counts.get(ticker, 1)),
            }
        )

    queue.sort(
        key=lambda item: (
            item["priority_score"] is None,
            -(item["priority_score"] or 0.0),
            -item["ce_score"],
            item["ticker"],
        )
    )

    for index, item in enumerate(queue, start=1):
        item["queue_rank"] = index
        if index == 1:
            item["recommended_clearance_order"] = "CLEAR_FIRST"
        elif index == 2:
            item["recommended_clearance_order"] = "CLEAR_SECOND"
        else:
            item["recommended_clearance_order"] = "CLEAR_LATER"

    return queue


def _unique_tickers(rows: list[dict[str, Any]], predicate) -> list[str]:
    tickers = []
    for row in rows:
        if not isinstance(row, dict) or not predicate(row):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def build_operator_policy_view(
    execution_policy: dict[str, Any],
    watchlist_diagnostics: dict[str, Any],
    per_signal_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    policy = {
        key: (list(value) if isinstance(value, list) else value)
        for key, value in execution_policy.items()
    }

    watchlist_intelligence = summarize_watchlist_intelligence(watchlist_diagnostics)
    promotable_names = watchlist_intelligence["promotable_watchlist_names"]
    chaos_names = _unique_tickers(
        per_signal_rows,
        lambda row: str(row.get("status") or "").upper() == "EXECUTED_CHAOS"
        or str(row.get("blocker_attribution") or "").upper() == "REALM_BIS",
    )

    precise_conditions = []
    for condition in policy.get("minimum_conditions_to_improve", []):
        if (
            condition == "GSCE_PHASE_LOCK clears for above-threshold WATCHLIST names"
            and promotable_names
        ):
            precise_conditions.append(
                "GSCE_PHASE_LOCK clears for promotable watchlist names: "
                + ", ".join(promotable_names)
            )
            continue
        if condition == "REALM_BIS clears by eliminating chaos conversions" and chaos_names:
            precise_conditions.append(
                "REALM_BIS clears by eliminating chaos conversions tied to "
                + ", ".join(chaos_names)
            )
            continue
        precise_conditions.append(condition)

    operator_rationale = list(policy.get("rationale", []))
    if promotable_names:
        operator_rationale.append(
            "Promotable clean candidate backlog remains blocked: "
            + ", ".join(promotable_names)
        )
    if chaos_names:
        operator_rationale.append(
            "Chaos contamination remains active in: " + ", ".join(chaos_names)
        )

    policy["minimum_conditions_to_improve"] = precise_conditions
    policy["operator_rationale"] = operator_rationale
    return policy


def build_readiness_context(
    state: dict[str, Any],
    blocked_promotable_candidate_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    chaos_names = _unique_tickers(
        state.get("per_signal_attribution", []),
        lambda row: str(row.get("status") or "").upper() == "EXECUTED_CHAOS"
        or str(row.get("blocker_attribution") or "").upper() == "REALM_BIS",
    )
    blocked_names = [item["ticker"] for item in blocked_promotable_candidate_queue]
    active_blockers = state.get("active_blockers", [])
    return {
        "blocked_promotable_candidate_count": len(blocked_names),
        "blocked_promotable_candidate_names": blocked_names,
        "promotable_queue_backlog": len(blocked_promotable_candidate_queue),
        "chaos_contamination_count": len(chaos_names),
        "chaos_contamination_names": chaos_names,
        "active_critical_blockers": [
            blocker for blocker in active_blockers if blocker in {"GSCE_PHASE_LOCK", "REALM_BIS"}
        ],
        "restrictive_policy_active": str(state.get("execution_policy", {}).get("policy_state", "")).upper()
        == "RESTRICTED",
    }


def derive_performance_leak_summary(
    friction_report: dict[str, Any],
    watchlist_intelligence: dict[str, Any] | None = None,
) -> list[str]:
    components = [
        component
        for component in friction_report.get("components", [])
        if component.get("score", 0) > 0
    ]
    components.sort(key=lambda item: (-item["score"], item["name"]))
    leaks = []
    for component in components:
        leaks.append(f"{component['name']} (score={component['score']}, count={component['count']})")

    watchlist_intelligence = watchlist_intelligence or {}
    promotable_names = watchlist_intelligence.get("promotable_watchlist_names", [])
    standard_names = watchlist_intelligence.get("standard_watchlist_names", [])
    blocked_promotable_names = watchlist_intelligence.get(
        "blocked_promotable_clean_candidate_names", []
    )
    if promotable_names:
        leaks.append(
            "PROMOTABLE_WATCHLIST_STAGNATION "
            f"(count={len(promotable_names)}, names={', '.join(promotable_names)})"
        )
    if standard_names:
        leaks.append(
            "STANDARD_WATCHLIST_STAGNATION "
            f"(count={len(standard_names)}, names={', '.join(standard_names)})"
        )
    if blocked_promotable_names:
        leaks.append(
            "BLOCKED_PROMOTABLE_CLEAN_CANDIDATES "
            f"(count={len(blocked_promotable_names)}, names={', '.join(blocked_promotable_names)})"
        )
    return leaks


def derive_next_operational_action(
    execution_policy: dict[str, Any],
    action_report: dict[str, Any],
    blocked_promotable_candidate_queue: list[dict[str, Any]] | None = None,
) -> str:
    blocked_promotable_candidate_queue = blocked_promotable_candidate_queue or []
    parts: list[str] = []

    exit_now = [row["ticker"] for row in action_report["actions"] if row["action"] == "EXIT_NOW"]
    if exit_now:
        parts.append(f"EXIT_NOW: {', '.join(exit_now)}")
    else:
        reduce_positions = [row["ticker"] for row in action_report["actions"] if row["action"] == "REDUCE"]
        if reduce_positions:
            parts.append(f"REDUCE: {', '.join(reduce_positions)}")

    blocked_names = [item["ticker"] for item in blocked_promotable_candidate_queue]
    if blocked_names:
        parts.append(f"CLEAR_GSCE_PHASE_LOCK_FOR: {', '.join(blocked_names)}")
    else:
        review_for_entry = [
            row["ticker"]
            for row in action_report["actions"]
            if row["action"] == "REVIEW_FOR_ENTRY"
        ]
        if review_for_entry:
            parts.append(f"REVIEW_FOR_ENTRY: {', '.join(review_for_entry)}")
        elif execution_policy.get("next_priority_action"):
            parts.append(str(execution_policy["next_priority_action"]))

    if not execution_policy.get("allow_new_risk", False):
        parts.append("DO NOT ADD NEW RISK")
    elif (
        execution_policy.get("next_priority_action")
        and str(execution_policy["next_priority_action"]) not in parts
    ):
        parts.append(str(execution_policy["next_priority_action"]))
    elif not parts and execution_policy.get("next_priority_action"):
        parts.append(str(execution_policy["next_priority_action"]))

    return " | ".join(parts)


def build_execution_readiness_breakdown(
    state: dict[str, Any],
    friction_report: dict[str, Any],
    trend_report: dict[str, Any],
    blocked_promotable_candidate_queue: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocked_promotable_candidate_queue = blocked_promotable_candidate_queue or []
    blocked_promotable_candidate_count = len(blocked_promotable_candidate_queue)
    max_persistent_block_count = max(
        (
            int(item.get("persistent_block_count", 0))
            for item in blocked_promotable_candidate_queue
            if isinstance(item, dict)
        ),
        default=0,
    )
    if max_persistent_block_count == 0:
        max_persistent_block_count = max(
            _persistent_block_count_map(trend_report).values(),
            default=0,
        )

    chaos_contamination_count = max(
        (
            int(component.get("count", 0))
            for component in friction_report.get("components", [])
            if isinstance(component, dict) and component.get("name") == "CHAOS_ENTRY"
        ),
        default=0,
    )

    restrictive_policy_penalty = (
        1
        if str(state.get("execution_policy", {}).get("policy_state", "UNKNOWN")).upper() == "RESTRICTED"
        else 0
    )
    backlog_penalty = _blocked_backlog_penalty(blocked_promotable_candidate_count)
    persistence_penalty = _persistent_blockage_penalty(max_persistent_block_count)
    chaos_penalty = _chaos_contamination_penalty(chaos_contamination_count)

    base_score = 10
    final_score = _bounded_score(
        base_score
        - backlog_penalty
        - persistence_penalty
        - chaos_penalty
        - restrictive_policy_penalty
    )
    return {
        "base_score": base_score,
        "blocked_promotable_candidate_count": blocked_promotable_candidate_count,
        "max_persistent_block_count": max_persistent_block_count,
        "chaos_contamination_count": chaos_contamination_count,
        "blocked_promotable_backlog_penalty": backlog_penalty,
        "persistent_blockage_penalty": persistence_penalty,
        "chaos_contamination_penalty": chaos_penalty,
        "restrictive_policy_penalty": restrictive_policy_penalty,
        "final_score": final_score,
    }


def derive_queue_pressure_state(
    blocked_promotable_candidate_queue: list[dict[str, Any]] | None = None,
) -> str:
    queue = blocked_promotable_candidate_queue or []
    blocked_count = len(queue)
    if blocked_count == 0:
        return "LOW"

    max_persistent_block_count = max(
        (int(item.get("persistent_block_count", 0)) for item in queue if isinstance(item, dict)),
        default=0,
    )
    if blocked_count >= 2 and max_persistent_block_count >= 3:
        return "HIGH"
    return "MEDIUM"


def derive_queue_sync_state(
    blocked_promotable_candidate_queue: list[dict[str, Any]],
    trend_report: dict[str, Any] | None = None,
) -> str:
    trend_map = _persistent_block_count_map(trend_report)
    queue_map = {
        str(item.get("ticker") or "").upper(): int(item.get("persistent_block_count", 0))
        for item in blocked_promotable_candidate_queue
        if isinstance(item, dict) and str(item.get("ticker") or "").strip()
    }

    if not queue_map and not trend_map:
        return "IN_SYNC"
    if not isinstance(trend_report, dict) or "blocked_promotable_persistence" not in trend_report:
        return "UNKNOWN"
    if queue_map == trend_map:
        return "IN_SYNC"
    return "OUT_OF_SYNC"


def derive_blockage_severity(
    blocked_promotable_candidate_queue: list[dict[str, Any]],
    readiness_context: dict[str, Any],
    active_blockers: list[str],
) -> str:
    blocked_count = len(blocked_promotable_candidate_queue)
    max_persistent_block_count = max(
        (
            int(item.get("persistent_block_count", 0))
            for item in blocked_promotable_candidate_queue
            if isinstance(item, dict)
        ),
        default=0,
    )
    chaos_count = int(readiness_context.get("chaos_contamination_count", 0))
    critical_blockers = {blocker for blocker in active_blockers if blocker in {"GSCE_PHASE_LOCK", "REALM_BIS"}}

    if blocked_count >= 2 and max_persistent_block_count >= 3:
        return "HIGH"
    if chaos_count >= 2 or len(critical_blockers) >= 2:
        return "HIGH"
    if blocked_count > 0 or chaos_count > 0 or critical_blockers:
        return "MEDIUM"
    return "LOW"


def derive_operator_pressure_state(
    system_readiness_state: str,
    queue_pressure_state: str,
    readiness_breakdown: dict[str, Any],
    readiness_context: dict[str, Any],
) -> str:
    if (
        system_readiness_state == "DO_NOT_DEPLOY"
        and queue_pressure_state == "HIGH"
        and readiness_breakdown.get("persistent_blockage_penalty", 0) >= 2
    ):
        return "CHRONIC"
    if (
        system_readiness_state == "DO_NOT_DEPLOY"
        or readiness_context.get("chaos_contamination_count", 0) > 0
        or queue_pressure_state in {"HIGH", "MEDIUM"}
    ):
        return "ACUTE"
    return "CONTAINED"


def build_clean_ready_candidates_if_gsce_clears(
    gsce_clear_transition_preview: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "signal_id": item.get("signal_id", ""),
            "ticker": item["ticker"],
            "priority_score": item.get("priority_score"),
            "watchlist_tier": item.get("watchlist_tier"),
            "current_pre_entry_state": item.get("current_pre_entry_state"),
            "simulated_pre_entry_state": item.get("simulated_pre_entry_state"),
            "gate_to_clear": item.get("gate_required_to_flip"),
        }
        for item in gsce_clear_transition_preview
    ]


def _build_transition_preview_candidates(
    live_state: dict[str, Any],
    scenario_state: dict[str, Any],
    scenario_action_report: dict[str, Any],
    live_queue: list[dict[str, Any]],
    gate_required_to_flip: str,
) -> list[dict[str, Any]]:
    live_watchlist_rows = {
        str(row.get("ticker") or "").upper(): row
        for row in live_state.get("watchlist_diagnostics", {}).get("watchlist_signals", [])
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }
    scenario_watchlist_rows = {
        str(row.get("ticker") or "").upper(): row
        for row in scenario_state.get("watchlist_diagnostics", {}).get("watchlist_signals", [])
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }
    queue_rows = {
        str(row.get("ticker") or "").upper(): row
        for row in live_queue
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }
    scenario_actions = {
        str(row.get("ticker") or "").upper(): row
        for row in scenario_action_report.get("actions", [])
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }

    preview: list[dict[str, Any]] = []
    for ticker in sorted(queue_rows):
        live_row = live_watchlist_rows.get(ticker, {})
        scenario_row = scenario_watchlist_rows.get(ticker, {})
        queue_row = queue_rows[ticker]
        scenario_action = scenario_actions.get(ticker, {})
        preview.append(
            {
                "signal_id": str(
                    live_row.get("signal_id")
                    or scenario_row.get("signal_id")
                    or queue_row.get("signal_id")
                    or ""
                ),
                "ticker": ticker,
                "priority_score": queue_row.get("priority_score"),
                "watchlist_tier": str(
                    scenario_row.get("watchlist_tier")
                    or live_row.get("watchlist_tier")
                    or queue_row.get("watchlist_tier")
                    or ""
                ).upper(),
                "current_pre_entry_state": str(
                    live_row.get("pre_entry_state")
                    or queue_row.get("pre_entry_state")
                    or "NONE"
                ).upper(),
                "simulated_pre_entry_state": str(
                    scenario_row.get("pre_entry_state")
                    or live_row.get("pre_entry_state")
                    or "NONE"
                ).upper(),
                "current_candidate_conversion_state": str(
                    live_row.get("candidate_conversion_state")
                    or queue_row.get("candidate_conversion_state")
                    or "UNKNOWN"
                ).upper(),
                "simulated_candidate_conversion_state": str(
                    scenario_row.get("candidate_conversion_state")
                    or live_row.get("candidate_conversion_state")
                    or "UNKNOWN"
                ).upper(),
                "gate_required_to_flip": gate_required_to_flip,
                "would_still_allow_new_risk": bool(
                    scenario_state.get("execution_policy", {}).get("allow_new_risk", False)
                ),
                "policy_state": scenario_state.get("execution_policy", {}).get("policy_state"),
                "active_blockers": list(scenario_state.get("active_blockers", [])),
                "simulated_action": scenario_action.get("action"),
                "simulated_action_reasons": scenario_action.get("reasons", []),
            }
        )
    return preview


def build_gate_resolution_preview(
    live_state: dict[str, Any],
    live_action_report: dict[str, Any],
    live_queue: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    open_positions_path: Path | None = None,
) -> dict[str, Any]:
    scenarios = {
        "live": {},
        "gsce_clear": {"simulate_gsce_clear": True},
        "realm_bis_clear": {"simulate_realm_bis_clear": True},
        "all_clear": {"simulate_all_clear": True},
    }
    gate_resolution_preview: dict[str, Any] = {}

    for scenario_name, scenario_flags in scenarios.items():
        if scenario_name == "live":
            scenario_state = live_state
            scenario_action_report = live_action_report
            scenario_scm_report = {
                "simulation_context": live_state.get("simulation_context", {}),
            }
        else:
            scenario_scm_report = build_signal_conversion_report(**scenario_flags)
            scenario_state = build_runtime_state_from_scm_report(scenario_scm_report)
            scenario_signal_refinery_report = build_signal_refinery_report(
                runtime_state=scenario_state,
                open_positions_path=open_positions_path,
                write_runtime=False,
            )
            scenario_state["signal_refinery"] = scenario_signal_refinery_report
            scenario_perception_control_report = build_perception_control_report(
                runtime_state=scenario_state,
                signal_refinery_report=scenario_signal_refinery_report,
                write_runtime=False,
            )
            scenario_state["perception_control"] = scenario_perception_control_report
            scenario_action_report = build_action_report(
                runtime_state=scenario_state,
                signal_refinery_report=scenario_signal_refinery_report,
                perception_control_report=scenario_perception_control_report,
                write_runtime=False,
                open_positions_path=open_positions_path,
            )

        scenario_transition_review_packets = build_transition_review_packets(
            live_state=live_state,
            scenario_state=scenario_state,
            scenario_action_report=scenario_action_report,
            open_positions=open_positions,
        )
        scenario_entry_review_packets = build_entry_review_packets(
            live_state=live_state,
            scenario_state=scenario_state,
            scenario_action_report=scenario_action_report,
            open_positions=open_positions,
        )
        decision_review_state = _derive_decision_review_state(
            scenario_entry_review_packets,
            scenario_transition_review_packets,
        )

        gate_resolution_preview[scenario_name] = {
            "scenario": scenario_scm_report.get("simulation_context", {}).get(
                "scenario",
                "LIVE",
            ),
            "policy_state": scenario_state.get("execution_policy", {}).get("policy_state"),
            "allow_new_risk": bool(
                scenario_state.get("execution_policy", {}).get("allow_new_risk", False)
            ),
            "active_blockers": list(scenario_state.get("active_blockers", [])),
            "what_should_i_do_next": derive_next_operational_action(
                scenario_state.get("execution_policy", {}),
                scenario_action_report,
                blocked_promotable_candidate_queue=build_blocked_promotable_candidate_queue(
                    scenario_state.get("watchlist_diagnostics", {}),
                    per_signal_rows=scenario_state.get("per_signal_attribution", []),
                ),
            ),
            "candidates": _build_transition_preview_candidates(
                live_state=live_state,
                scenario_state=scenario_state,
                scenario_action_report=scenario_action_report,
                live_queue=live_queue,
                gate_required_to_flip=(
                    "GSCE_PHASE_LOCK"
                    if scenario_name != "all_clear"
                    else "GSCE_PHASE_LOCK+REALM_BIS"
                ),
            ),
            "packet_summary": _packet_summary(
                scenario_entry_review_packets,
                scenario_transition_review_packets,
            ),
            "decision_review_state": decision_review_state,
            "entry_review_packets": scenario_entry_review_packets,
            "transition_review_packets": scenario_transition_review_packets,
        }

    return gate_resolution_preview


def build_next_state_if_all_clear(
    gate_resolution_preview: dict[str, Any],
) -> dict[str, Any]:
    all_clear_preview = gate_resolution_preview.get("all_clear", {})
    all_clear_candidates = all_clear_preview.get("candidates", [])
    return {
        "tickers": [item["ticker"] for item in all_clear_candidates],
        "pre_entry_state": "CLEAN_ENTRY_ELIGIBLE",
        "candidate_conversion_state": "CLEAN_ENTRY_ELIGIBLE",
        "action": "REVIEW_FOR_ENTRY",
        "policy_state": all_clear_preview.get("policy_state"),
        "allow_new_risk": all_clear_preview.get("allow_new_risk"),
        "active_blockers": all_clear_preview.get("active_blockers", []),
    }


def _watchlist_rows_by_ticker(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("ticker") or "").upper(): row
        for row in state.get("watchlist_diagnostics", {}).get("watchlist_signals", [])
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }


def _action_rows_by_ticker(action_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("ticker") or "").upper(): row
        for row in action_report.get("actions", [])
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }


def _position_is_open_like(position: dict[str, Any]) -> bool:
    return str(position.get("state") or "").upper() in {"OPEN", "REDUCED", "EXIT_PENDING"}


def _open_positions_by_ticker(open_positions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = {}
    for position in open_positions:
        if not isinstance(position, dict):
            continue
        ticker = str(position.get("ticker") or "").upper()
        if not ticker:
            continue
        mapping.setdefault(ticker, []).append(position)
    return mapping


def _required_blockers_for_target_state(target_pre_entry_state: str) -> list[str]:
    normalized_target = str(target_pre_entry_state or "NONE").upper()
    if normalized_target == "CLEAN_READY_PENDING_TRIGGER":
        return ["GSCE_PHASE_LOCK"]
    if normalized_target == "CLEAN_ENTRY_ELIGIBLE":
        return ["GSCE_PHASE_LOCK", "REALM_BIS"]
    return []


def _signal_above_threshold(
    state: dict[str, Any],
    signal_id: str,
    ticker: str,
) -> bool:
    qualifying_ids = {
        str(item).strip()
        for item in state.get("signal_summary", {}).get("qualifying_signal_ids", [])
        if str(item).strip()
    }
    if signal_id and signal_id in qualifying_ids:
        return True

    qualifying_signals = state.get("signal_summary", {}).get("qualifying_signals", [])
    for item in qualifying_signals:
        if not isinstance(item, dict):
            continue
        if str(item.get("ticker") or "").upper() == str(ticker or "").upper():
            return True
    return False


def _field_is_populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _build_blocker_clearance_path(
    live_state: dict[str, Any],
    scenario_state: dict[str, Any],
    target_pre_entry_state: str,
) -> dict[str, Any]:
    tracked_blockers = ["GSCE_PHASE_LOCK", "REALM_BIS"]
    required_for_target_state = _required_blockers_for_target_state(target_pre_entry_state)
    live_active = set(live_state.get("active_blockers", []))
    scenario_active = set(scenario_state.get("active_blockers", []))
    return {
        "required_for_target_state": required_for_target_state,
        "cleared_for_target_state": [
            blocker for blocker in required_for_target_state if blocker not in scenario_active
        ],
        "remaining_for_target_state": [
            blocker for blocker in required_for_target_state if blocker in scenario_active
        ],
        "live_active_blockers": [
            blocker for blocker in tracked_blockers if blocker in live_active
        ],
        "remaining_blockers": [
            blocker for blocker in tracked_blockers if blocker in scenario_active
        ],
    }


def _build_scm_context(
    state: dict[str, Any],
    signal_id: str,
    ticker: str,
) -> dict[str, Any]:
    scm_review = state.get("scm_review", {})
    return {
        "scm_state": scm_review.get("scm_state"),
        "scm_rate": scm_review.get("scm_rate"),
        "diagnosis": list(scm_review.get("diagnosis", [])),
        "signal_above_threshold": _signal_above_threshold(state, signal_id, ticker),
    }


def _build_execution_policy_context(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_state": policy.get("policy_state"),
        "allow_new_risk": bool(policy.get("allow_new_risk", False)),
        "position_sizing_cap": policy.get("position_sizing_cap"),
        "required_clearance_gates": list(policy.get("required_clearance_gates", [])),
        "next_priority_action": policy.get("next_priority_action"),
    }


def _build_review_checklist(
    packet_type: str,
    *,
    watchlist_tier: str,
    signal_above_threshold: bool,
    open_position_conflict: bool,
    existing_exposure_conflict: bool,
    sizing_allowed_now: bool,
    blocker_clearance_path: dict[str, Any],
    packet_fields_populated: bool,
) -> dict[str, Any]:
    checklist_items = [
        {
            "name": "signal_still_promotable",
            "passed": watchlist_tier == "PROMOTABLE",
            "detail": (
                "Watchlist row remains PROMOTABLE."
                if watchlist_tier == "PROMOTABLE"
                else f"Watchlist tier is {watchlist_tier or 'UNKNOWN'}."
            ),
        },
        {
            "name": "signal_above_threshold",
            "passed": signal_above_threshold,
            "detail": (
                "Signal is still present in the above-threshold set."
                if signal_above_threshold
                else "Signal is no longer present in the above-threshold set."
            ),
        },
        {
            "name": "no_open_position_conflict",
            "passed": not open_position_conflict,
            "detail": (
                "No same-ticker open position is live."
                if not open_position_conflict
                else "Same-ticker open position already exists."
            ),
        },
        {
            "name": "no_existing_exposure_conflict",
            "passed": not existing_exposure_conflict,
            "detail": (
                "No same-ticker exposure conflict is active."
                if not existing_exposure_conflict
                else "Same-ticker exposure conflict is active."
            ),
        },
        {
            "name": "policy_allows_sizing_now",
            "passed": sizing_allowed_now,
            "detail": (
                "Policy currently permits sizing."
                if sizing_allowed_now
                else "Policy does not currently permit sizing."
            ),
        },
        {
            "name": "required_blockers_cleared",
            "passed": not blocker_clearance_path["remaining_for_target_state"],
            "detail": (
                "All blockers required for the target state are cleared."
                if not blocker_clearance_path["remaining_for_target_state"]
                else "Remaining blockers for target state: "
                + ", ".join(blocker_clearance_path["remaining_for_target_state"])
            ),
        },
        {
            "name": "packet_fields_populated",
            "passed": packet_fields_populated,
            "detail": (
                "All required packet fields are populated."
                if packet_fields_populated
                else "Packet has missing required fields."
            ),
        },
    ]
    review_checklist_missing_items = [
        item["name"] for item in checklist_items if not item["passed"]
    ]

    if open_position_conflict or existing_exposure_conflict:
        review_checklist_status = "BLOCKED"
        operator_decision_state = "BLOCKED_BY_CONFLICT"
    elif not review_checklist_missing_items:
        review_checklist_status = "COMPLETE"
        operator_decision_state = (
            "READY_FOR_OPERATOR_DECISION"
            if packet_type == "ENTRY"
            else "NOT_REVIEWED"
        )
    else:
        review_checklist_status = "INCOMPLETE"
        operator_decision_state = "NEEDS_CHECKLIST"

    return {
        "checklist_items": checklist_items,
        "review_checklist_status": review_checklist_status,
        "review_checklist_missing_items": review_checklist_missing_items,
        "operator_decision_state": operator_decision_state,
    }


def _derive_decision_review_state(
    entry_review_packets: list[dict[str, Any]],
    transition_review_packets: list[dict[str, Any]],
) -> str:
    packet_states = [
        packet.get("operator_decision_state")
        for packet in [*entry_review_packets, *transition_review_packets]
        if isinstance(packet, dict)
    ]
    if "BLOCKED_BY_CONFLICT" in packet_states:
        return "BLOCKED_BY_CONFLICT"
    if entry_review_packets:
        return "ENTRY_REVIEW_READY"
    if transition_review_packets:
        return "TRANSITION_REVIEW_READY"
    return "NONE"


def _packet_summary(
    entry_review_packets: list[dict[str, Any]],
    transition_review_packets: list[dict[str, Any]],
) -> dict[str, Any]:
    entry_names = [packet["ticker"] for packet in entry_review_packets]
    transition_names = [packet["ticker"] for packet in transition_review_packets]
    if entry_names:
        packet_state = "ENTRY_REVIEW_READY"
    elif transition_names:
        packet_state = "TRANSITION_REVIEW_READY"
    else:
        packet_state = "NONE"
    return {
        "entry_review_candidate_count": len(entry_names),
        "transition_review_candidate_count": len(transition_names),
        "entry_review_candidate_names": entry_names,
        "transition_review_candidate_names": transition_names,
        "packet_state": packet_state,
    }


def _first_matching_row(
    rows: list[dict[str, Any]] | None,
    ticker: str,
) -> dict[str, Any]:
    for row in rows or []:
        if isinstance(row, dict) and str(row.get("ticker") or "").upper() == ticker.upper():
            return row
    return {}


def _build_execution_packet_from_review_packet(
    packet: dict[str, Any] | None,
    *,
    policy: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool, list[str]]:
    review_packet = packet if isinstance(packet, dict) else {}
    if not review_packet:
        return None, False, ["review_packet_missing"]

    execution_packet = {
        "entry": {
            "ticker": review_packet.get("ticker"),
            "signal_id": review_packet.get("signal_id"),
            "trigger_state": review_packet.get("target_pre_entry_state"),
        },
        "size": {
            "position_sizing_cap": review_packet.get("sizing_cap_now")
            or review_packet.get("position_sizing_cap"),
            "sizing_allowed_now": bool(review_packet.get("sizing_allowed_now", False)),
        },
        "invalidation": {
            "remaining_blockers": list(review_packet.get("remaining_blockers", [])),
            "open_position_conflict": bool(review_packet.get("open_position_conflict", False)),
            "existing_exposure_conflict": bool(
                review_packet.get("existing_exposure_conflict", False)
            ),
        },
        "exit_logic": {
            "recommended_action": review_packet.get("recommended_action"),
            "policy_state": policy.get("policy_state"),
            "review_checklist_status": review_packet.get("review_checklist_status"),
        },
    }
    missing_fields: list[str] = []
    for section_name, section in execution_packet.items():
        if not isinstance(section, dict):
            missing_fields.append(section_name)
            continue
        for field_name, value in section.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_fields.append(f"{section_name}.{field_name}")
    locked = (
        review_packet.get("review_checklist_status") == "COMPLETE"
        and review_packet.get("operator_decision_state") != "BLOCKED_BY_CONFLICT"
        and not missing_fields
    )
    return execution_packet, locked, missing_fields


def build_reflection_context(
    *,
    state: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    attention_proxy_report: dict[str, Any],
    action_report: dict[str, Any],
    entry_review_packets: list[dict[str, Any]],
    transition_review_packets: list[dict[str, Any]],
    operator_control_report: dict[str, Any],
    open_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    validation_rows = signal_refinery_report.get("validation_engine", {}).get("signals", [])
    launch_rows = signal_refinery_report.get("launch_control", {}).get("launch_rows", [])
    action_rows = action_report.get("actions", [])
    primary_packet = (
        (entry_review_packets[0] if entry_review_packets else None)
        or (transition_review_packets[0] if transition_review_packets else None)
    )
    primary_ticker = str((primary_packet or {}).get("ticker") or "").upper()
    if not primary_ticker and isinstance(validation_rows, list) and validation_rows:
        primary_ticker = str(validation_rows[0].get("ticker") or "").upper()

    validation_row = _first_matching_row(validation_rows, primary_ticker) if primary_ticker else {}
    launch_row = _first_matching_row(launch_rows, primary_ticker) if primary_ticker else {}
    action_row = _first_matching_row(action_rows, primary_ticker) if primary_ticker else {}
    open_position = {}
    for position in open_positions:
        if isinstance(position, dict) and str(position.get("ticker") or "").upper() == primary_ticker:
            open_position = position
            break

    policy = state.get("execution_policy", {})
    execution_packet, execution_packet_locked, packet_missing_fields = (
        _build_execution_packet_from_review_packet(primary_packet, policy=policy)
    )
    chaos_veto_active = bool(
        str((validation_row or {}).get("status") or "").upper() == "EXECUTED_CHAOS"
        or ("REALM_BIS" in state.get("active_blockers", []) and state.get("moltbook_summary", {}).get("chaos_entries", 0) > 0)
    )
    evidence_strength = float((validation_row or {}).get("validation_score") or 0.0)
    narrative_confidence = float(
        attention_proxy_report.get("narrative_cohesion_score")
        or attention_proxy_report.get("attention_capture_score")
        or 0.0
    )
    emotional_resonance = float(attention_proxy_report.get("narrative_heat_score") or 0.0)
    operator_state_payload = signal_refinery_report.get("manual_operator_state", {})
    raw_operator_mode = str(operator_state_payload.get("operator_mode") or "UNKNOWN").upper()
    operator_state = {
        "CALM": "CALM",
        "NEUTRAL": "NEUTRAL",
        "STRESSED": "STRESSED",
        "STRESS": "STRESSED",
        "EUPHORIC": "EUPHORIC",
        "FATIGUED": "FATIGUED",
        "INTOXICATED": "INTOXICATED",
    }.get(raw_operator_mode, "UNKNOWN")
    context_switch_count = int(operator_state_payload.get("context_switch_count", 0) or 0)
    reopen_count = int(operator_control_report.get("active_work_block", {}).get("reopened_decision_count", 0) or 0)

    return {
        "primary_ticker": primary_ticker or None,
        "validation_row": validation_row,
        "launch_row": launch_row,
        "action_row": action_row,
        "primary_packet": primary_packet or {},
        "open_position": open_position,
        "execution_packet": execution_packet,
        "execution_packet_locked": execution_packet_locked,
        "execution_packet_missing_fields": packet_missing_fields,
        "chaos_veto_active": chaos_veto_active,
        "policy": policy,
        "evidence_strength": evidence_strength,
        "narrative_confidence": narrative_confidence,
        "emotional_resonance": emotional_resonance,
        "operator_state": operator_state,
        "operator_stability_score": float(
            operator_state_payload.get("current_score")
            or operator_state_payload.get("baseline_score")
            or 0.0
        ),
        "context_switch_count": context_switch_count,
        "reopen_count": reopen_count,
    }


def _historical_conversion_score_for_baines(status: str) -> float:
    normalized = str(status or "").upper()
    if normalized == "EXECUTED_CLEAN":
        return 0.8
    if normalized == "WATCHLIST":
        return 0.55
    if normalized == "EXECUTED_CHAOS":
        return 0.2
    return 0.35


def _build_baines_inputs(
    *,
    state: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    operator_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    validation_rows = signal_refinery_report.get("validation_engine", {}).get("signals", [])
    validation_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in validation_rows
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }
    active_blockers = set(normalize_active_blockers(state.get("active_blockers")))
    policy_veto = not bool(operator_policy.get("allow_new_risk", False))

    inputs: list[dict[str, Any]] = []
    for row in state.get("per_signal_attribution", []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        validation_row = validation_by_ticker.get(ticker, {})
        ce_score = float(row.get("ce_score", 0.0) or 0.0)
        output_score = float(validation_row.get("validation_score", 0.0) or 0.0)
        attention_score = float(validation_row.get("light_score", 0.0) or 0.0)
        first_order_score = float(validation_row.get("first_order_score", 0.0) or 0.0)
        source_quality_score = float(validation_row.get("source_quality_score", 0.0) or 0.0)
        cross_source_confirmation = float(
            validation_row.get("cross_source_confirmation_score", 0.0) or 0.0
        )
        repricing_headroom = float(validation_row.get("repricing_headroom_score", 0.0) or 0.0)
        blocker_clearance = float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)
        novelty_score = float(validation_row.get("novelty_score", 0.0) or 0.0)
        price_lead_score = float(validation_row.get("price_lead_score", 0.0) or 0.0)
        crowding_state = str(validation_row.get("crowding_state") or "").upper()
        chaos_veto = (
            str(row.get("status") or "").upper() == "EXECUTED_CHAOS"
            or str(row.get("conversion_state") or "").upper() == "CHAOS_ENTRY"
            or "REALM_BIS" in active_blockers
        )
        price_expectation_percentile = max(
            0.0,
            min(
                1.0,
                (ce_score * 0.65)
                + (attention_score * 0.20)
                + (0.15 if crowding_state in {"CROWDED", "ALREADY_EXTENDED"} else 0.0),
            ),
        )
        risk_adjusted_cost = max(
            0.05,
            (1.0 - blocker_clearance)
            + max(0.0, novelty_score - (first_order_score * 0.5))
            + (1.0 - source_quality_score)
            + (0.10 if chaos_veto else 0.0),
        )
        inputs.append(
            {
                "asset_id": ticker,
                "asset_class": "unknown",
                "listed_role": str(row.get("conversion_state") or "unknown").lower(),
                "observed_function": str(validation_row.get("validation_state") or "unknown").lower(),
                "price_score": max(0.0, min(1.0, ce_score)),
                "output_score": max(0.0, min(1.0, output_score)),
                "output_percentile": max(0.0, min(1.0, output_score)),
                "price_expectation_percentile": round(price_expectation_percentile, 3),
                "attention_score": max(0.0, min(1.0, attention_score)),
                "payoff_channels": {
                    "confirmation": cross_source_confirmation,
                    "repricing": repricing_headroom,
                    "source_quality": source_quality_score,
                    "price_lead": price_lead_score,
                },
                "persistence_score": max(0.0, min(1.0, first_order_score)),
                "stability_score": max(0.0, min(1.0, 1.0 - novelty_score)),
                "historical_conversion_score": _historical_conversion_score_for_baines(
                    str(row.get("status") or "")
                ),
                "performance_before_stress": max(output_score, 0.05),
                "performance_after_stress": max(output_score * repricing_headroom, 0.0),
                "risk_adjusted_cost": risk_adjusted_cost,
                "volatility_penalty": max(0.0, min(1.0, novelty_score)),
                "liquidity_penalty": max(0.0, min(1.0, 1.0 - source_quality_score)),
                "reality_gap_penalty": max(
                    0.0,
                    min(1.0, 1.0 - cross_source_confirmation),
                ),
                "policy_veto": policy_veto,
                "chaos_veto": chaos_veto,
            }
        )
    return inputs


def _build_football_portfolio_archetype_inputs(
    *,
    state: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    operator_policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    validation_rows = signal_refinery_report.get("validation_engine", {}).get("signals", [])
    validation_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in validation_rows
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }
    active_blockers = set(normalize_active_blockers(state.get("active_blockers")))
    chaos_state = "REALM_BIS" in active_blockers or int(
        state.get("moltbook_summary", {}).get("chaos_entries", 0) or 0
    ) > 0
    policy_veto = not bool(operator_policy.get("allow_new_risk", False))

    inputs: list[dict[str, Any]] = []
    for row in state.get("per_signal_attribution", []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        validation_row = validation_by_ticker.get(ticker, {})
        status = str(row.get("status") or "").upper()
        conversion_state = str(row.get("conversion_state") or "").upper()
        primary_role_score = float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)
        secondary_output_score = float(validation_row.get("validation_score", 0.0) or 0.0)
        multi_channel_output_score = min(
            1.0,
            (
                float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0)
                + float(validation_row.get("repricing_headroom_score", 0.0) or 0.0)
                + float(validation_row.get("source_quality_score", 0.0) or 0.0)
            )
            / 2.2,
        )
        repeatability_score = float(validation_row.get("first_order_score", 0.0) or 0.0)
        catalyst_score = float(validation_row.get("novelty_score", 0.0) or 0.0)
        attention_score = float(validation_row.get("light_score", 0.0) or 0.0)
        relative_cost_score = min(
            1.0,
            (
                float(row.get("ce_score", 0.0) or 0.0) * 0.55
                + attention_score * 0.20
                + (0.25 if status == "WATCHLIST" else 0.0)
            ),
        )
        system_dependency_score = min(
            1.0,
            max(
                0.0,
                float(validation_row.get("novelty_score", 0.0) or 0.0)
                + (0.35 if status == "WATCHLIST" else 0.0)
                + (0.25 if conversion_state == "CHAOS_ENTRY" else 0.0)
                - (0.20 * float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0)),
            ),
        )
        structural_compromise_score = min(
            1.0,
            max(
                0.0,
                (1.0 - primary_role_score) * 0.55
                + system_dependency_score * 0.30
                + (1.0 - float(validation_row.get("source_quality_score", 0.0) or 0.0)) * 0.15,
            ),
        )
        risk_adjusted_cost = max(
            0.05,
            relative_cost_score
            + structural_compromise_score
            + max(0.0, float(validation_row.get("novelty_score", 0.0) or 0.0) - repeatability_score * 0.4),
        )
        defense_score = min(
            1.0,
            (primary_role_score * 0.60)
            + (float(validation_row.get("source_quality_score", 0.0) or 0.0) * 0.25)
            + (float(validation_row.get("blocker_clearance_score", 0.0) or 0.0) * 0.15),
        )
        survival_score = min(
            1.0,
            (repeatability_score * 0.45)
            + (float(validation_row.get("repricing_headroom_score", 0.0) or 0.0) * 0.30)
            + (float(validation_row.get("source_quality_score", 0.0) or 0.0) * 0.25),
        )
        inputs.append(
            {
                "candidate_id": ticker,
                "asset_symbol": ticker,
                "asset_name": ticker,
                "primary_role_score": primary_role_score,
                "secondary_output_score": secondary_output_score,
                "output_percentile": secondary_output_score,
                "price_percentile": relative_cost_score,
                "multi_channel_output_score": multi_channel_output_score,
                "repeatability_score": repeatability_score,
                "catalyst_score": catalyst_score,
                "attention_score": attention_score,
                "relative_cost_score": relative_cost_score,
                "risk_adjusted_cost": risk_adjusted_cost,
                "defense_score": defense_score,
                "survival_score": survival_score,
                "catalyst_probability": catalyst_score,
                "impact_magnitude": float(validation_row.get("repricing_headroom_score", 0.0) or 0.0),
                "structural_safety_score": max(0.0, 1.0 - structural_compromise_score),
                "system_dependency_score": system_dependency_score,
                "structural_compromise_score": structural_compromise_score,
                "validated_output_score": secondary_output_score,
                "policy_veto": policy_veto,
                "chaos_state": chaos_state,
                "heat_state": attention_score >= 0.75,
                "run_id": state.get("run_id"),
                "generated_at": state.get("artifact_written_at") or state.get("run_started_at"),
            }
        )
    return inputs, chaos_state


def build_entry_review_packets(
    live_state: dict[str, Any],
    scenario_state: dict[str, Any],
    scenario_action_report: dict[str, Any],
    open_positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    policy = scenario_state.get("execution_policy", {})
    live_watchlist_rows = _watchlist_rows_by_ticker(live_state)
    scenario_watchlist_rows = _watchlist_rows_by_ticker(scenario_state)
    action_rows = _action_rows_by_ticker(scenario_action_report)
    positions_by_ticker = _open_positions_by_ticker(open_positions)
    tracked_blockers = {"GSCE_PHASE_LOCK", "REALM_BIS"}
    live_active_blockers = tracked_blockers.intersection(live_state.get("active_blockers", []))
    current_active_blockers = set(scenario_state.get("active_blockers", []))

    packets: list[dict[str, Any]] = []
    for ticker, scenario_watchlist_row in sorted(scenario_watchlist_rows.items()):
        if str(scenario_watchlist_row.get("pre_entry_state") or "").upper() != "CLEAN_ENTRY_ELIGIBLE":
            continue
        action_row = action_rows.get(ticker, {})
        if action_row.get("action") != "REVIEW_FOR_ENTRY":
            continue
        live_watchlist_row = live_watchlist_rows.get(ticker, {})
        remaining_blockers = sorted(tracked_blockers.intersection(current_active_blockers))
        open_position_conflict = any(
            _position_is_open_like(position)
            for position in positions_by_ticker.get(ticker, [])
        )
        existing_exposure_conflict = open_position_conflict
        signal_id = str(
            scenario_watchlist_row.get("signal_id")
            or live_watchlist_row.get("signal_id")
            or ""
        )
        watchlist_tier = str(scenario_watchlist_row.get("watchlist_tier") or "").upper()
        blocker_clearance_path = _build_blocker_clearance_path(
            live_state=live_state,
            scenario_state=scenario_state,
            target_pre_entry_state="CLEAN_ENTRY_ELIGIBLE",
        )
        scm_context = _build_scm_context(scenario_state, signal_id, ticker)
        execution_policy_context = _build_execution_policy_context(policy)
        sizing_allowed_now = bool(policy.get("allow_new_risk", False)) and not (
            open_position_conflict or existing_exposure_conflict
        )
        sizing_cap_now = policy.get("position_sizing_cap") if sizing_allowed_now else "NONE"

        packet = {
            "ticker": ticker,
            "signal_id": signal_id,
            "priority_score": action_row.get("priority_score"),
            "ce_score": float(scenario_watchlist_row.get("ce_score", 0.0)),
            "watchlist_tier": watchlist_tier,
            "current_pre_entry_state": str(
                live_watchlist_row.get("pre_entry_state") or "NONE"
            ).upper(),
            "target_pre_entry_state": "CLEAN_ENTRY_ELIGIBLE",
            "current_candidate_conversion_state": str(
                live_watchlist_row.get("candidate_conversion_state") or "UNKNOWN"
            ).upper(),
            "target_candidate_conversion_state": str(
                scenario_watchlist_row.get("candidate_conversion_state") or "UNKNOWN"
            ).upper(),
            "thesis_tag": "PROMOTABLE_CLEAN_CANDIDATE",
            "why_eligible_now": "GSCE_PHASE_LOCK and REALM_BIS cleared; promotable candidate advanced to review-ready state.",
            "blockers_cleared": sorted(live_active_blockers - current_active_blockers),
            "remaining_blockers": remaining_blockers,
            "blocker_clearance_path": blocker_clearance_path,
            "scm_context": scm_context,
            "execution_policy_context": execution_policy_context,
            "policy_state": policy.get("policy_state"),
            "allow_new_risk": bool(policy.get("allow_new_risk", False)),
            "position_sizing_cap": policy.get("position_sizing_cap"),
            "sizing_allowed_now": sizing_allowed_now,
            "sizing_cap_now": sizing_cap_now,
            "open_position_conflict": open_position_conflict,
            "existing_exposure_conflict": existing_exposure_conflict,
            "recommended_action": action_row.get("action"),
            "action_reasons": action_row.get("reasons", []),
        }
        checklist = _build_review_checklist(
            "ENTRY",
            watchlist_tier=watchlist_tier,
            signal_above_threshold=scm_context["signal_above_threshold"],
            open_position_conflict=open_position_conflict,
            existing_exposure_conflict=existing_exposure_conflict,
            sizing_allowed_now=sizing_allowed_now,
            blocker_clearance_path=blocker_clearance_path,
            packet_fields_populated=all(
                _field_is_populated(packet.get(field))
                for field in (
                    "ticker",
                    "signal_id",
                    "priority_score",
                    "ce_score",
                    "watchlist_tier",
                    "current_pre_entry_state",
                    "target_pre_entry_state",
                    "current_candidate_conversion_state",
                    "target_candidate_conversion_state",
                    "recommended_action",
                )
            ),
        )
        packet.update(checklist)
        packet["operator_note"] = (
            "Existing open position or exposure conflict blocks operator review."
            if packet["operator_decision_state"] == "BLOCKED_BY_CONFLICT"
            else "Promotable clean candidate is fully gate-cleared and ready for operator entry review."
        )

        packets.append(packet)
    return packets


def build_transition_review_packets(
    live_state: dict[str, Any],
    scenario_state: dict[str, Any],
    scenario_action_report: dict[str, Any],
    open_positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    policy = scenario_state.get("execution_policy", {})
    live_watchlist_rows = _watchlist_rows_by_ticker(live_state)
    scenario_watchlist_rows = _watchlist_rows_by_ticker(scenario_state)
    action_rows = _action_rows_by_ticker(scenario_action_report)
    positions_by_ticker = _open_positions_by_ticker(open_positions)
    tracked_blockers = {"GSCE_PHASE_LOCK", "REALM_BIS"}
    current_active_blockers = set(scenario_state.get("active_blockers", []))

    packets: list[dict[str, Any]] = []
    for ticker, scenario_watchlist_row in sorted(scenario_watchlist_rows.items()):
        if str(scenario_watchlist_row.get("pre_entry_state") or "").upper() != "CLEAN_READY_PENDING_TRIGGER":
            continue
        action_row = action_rows.get(ticker, {})
        if action_row.get("action") != "MONITOR":
            continue
        live_watchlist_row = live_watchlist_rows.get(ticker, {})
        remaining_blockers = sorted(tracked_blockers.intersection(current_active_blockers))
        next_gate_to_clear = remaining_blockers[0] if remaining_blockers else None
        open_position_conflict = any(
            _position_is_open_like(position)
            for position in positions_by_ticker.get(ticker, [])
        )
        existing_exposure_conflict = open_position_conflict
        signal_id = str(
            scenario_watchlist_row.get("signal_id")
            or live_watchlist_row.get("signal_id")
            or ""
        )
        watchlist_tier = str(scenario_watchlist_row.get("watchlist_tier") or "").upper()
        blocker_clearance_path = _build_blocker_clearance_path(
            live_state=live_state,
            scenario_state=scenario_state,
            target_pre_entry_state="CLEAN_READY_PENDING_TRIGGER",
        )
        scm_context = _build_scm_context(scenario_state, signal_id, ticker)
        execution_policy_context = _build_execution_policy_context(policy)
        sizing_allowed_now = bool(policy.get("allow_new_risk", False)) and not (
            open_position_conflict or existing_exposure_conflict
        )
        sizing_cap_now = policy.get("position_sizing_cap") if sizing_allowed_now else "NONE"
        blockers_cleared = blocker_clearance_path["cleared_for_target_state"]

        packet = {
            "ticker": ticker,
            "signal_id": signal_id,
            "priority_score": action_row.get("priority_score"),
            "ce_score": float(scenario_watchlist_row.get("ce_score", 0.0)),
            "watchlist_tier": watchlist_tier,
            "current_pre_entry_state": str(
                live_watchlist_row.get("pre_entry_state") or "NONE"
            ).upper(),
            "target_pre_entry_state": "CLEAN_READY_PENDING_TRIGGER",
            "current_candidate_conversion_state": str(
                live_watchlist_row.get("candidate_conversion_state") or "UNKNOWN"
            ).upper(),
            "target_candidate_conversion_state": str(
                scenario_watchlist_row.get("candidate_conversion_state") or "UNKNOWN"
            ).upper(),
            "thesis_tag": "PROMOTABLE_CLEAN_CANDIDATE",
            "advanced_because": "GSCE_PHASE_LOCK cleared and the promotable candidate advanced into the clean-ready pending path.",
            "blockers_cleared": blockers_cleared,
            "remaining_blockers": remaining_blockers,
            "blocker_clearance_path": blocker_clearance_path,
            "next_gate_to_clear": next_gate_to_clear,
            "scm_context": scm_context,
            "execution_policy_context": execution_policy_context,
            "policy_state": policy.get("policy_state"),
            "allow_new_risk": bool(policy.get("allow_new_risk", False)),
            "sizing_allowed_now": sizing_allowed_now,
            "sizing_cap_now": sizing_cap_now,
            "open_position_conflict": open_position_conflict,
            "existing_exposure_conflict": existing_exposure_conflict,
            "recommended_action": action_row.get("action"),
            "action_reasons": action_row.get("reasons", []),
        }
        checklist = _build_review_checklist(
            "TRANSITION",
            watchlist_tier=watchlist_tier,
            signal_above_threshold=scm_context["signal_above_threshold"],
            open_position_conflict=open_position_conflict,
            existing_exposure_conflict=existing_exposure_conflict,
            sizing_allowed_now=sizing_allowed_now,
            blocker_clearance_path=blocker_clearance_path,
            packet_fields_populated=all(
                _field_is_populated(packet.get(field))
                for field in (
                    "ticker",
                    "signal_id",
                    "priority_score",
                    "ce_score",
                    "watchlist_tier",
                    "current_pre_entry_state",
                    "target_pre_entry_state",
                    "current_candidate_conversion_state",
                    "target_candidate_conversion_state",
                    "recommended_action",
                )
            ),
        )
        packet.update(checklist)
        packet["operator_note"] = (
            "Existing open position or exposure conflict blocks transition review."
            if packet["operator_decision_state"] == "BLOCKED_BY_CONFLICT"
            else "Candidate advanced into CLEAN_READY_PENDING_TRIGGER but REALM_BIS still forbids new risk."
        )

        packets.append(packet)
    return packets


def build_health_scorecard(
    state: dict[str, Any],
    action_report: dict[str, Any],
    friction_report: dict[str, Any],
    trend_report: dict[str, Any],
    open_positions_summary: dict[str, Any],
    test_status: dict[str, Any],
    execution_readiness_breakdown: dict[str, Any],
) -> dict[str, Any]:
    logging_quality = 0
    if state["moltbook_summary"]:
        logging_quality += 2
    if state["signal_summary"]:
        logging_quality += 2
    if action_report["summary_by_action"]:
        logging_quality += 2
    if friction_report["components"]:
        logging_quality += 2
    if trend_report["snapshot_count"] >= 0:
        logging_quality += 2

    schema_reliability = 0
    if open_positions_summary["valid"]:
        schema_reliability += 3
    if state["signal_summary"]["signal_count_total"] >= state["signal_summary"]["signals_above_ce_threshold"]:
        schema_reliability += 3
    if friction_report["weights"]:
        schema_reliability += 2
    if test_status.get("invoked") and test_status.get("passed"):
        schema_reliability += 2

    end_to_end_wiring = 0
    if state["scm_review"]["scm_state"] != "UNKNOWN":
        end_to_end_wiring += 2
    if action_report["actions"]:
        end_to_end_wiring += 2
    if friction_report["components"]:
        end_to_end_wiring += 2
    if trend_report["snapshot_count"] >= 0:
        end_to_end_wiring += 2
    if state["execution_policy"]:
        end_to_end_wiring += 2

    self_correction_maturity = 0
    if trend_report["snapshot_count"] >= 2:
        self_correction_maturity += 3
    if state["per_signal_attribution"]:
        self_correction_maturity += 3
    if state["execution_policy"]["minimum_conditions_to_improve"]:
        self_correction_maturity += 2
    if state["execution_policy"]["next_priority_action"]:
        self_correction_maturity += 2

    return {
        "logging_quality": {"score": _bounded_score(logging_quality), "max_score": 10},
        "schema_reliability": {"score": _bounded_score(schema_reliability), "max_score": 10},
        "end_to_end_wiring": {"score": _bounded_score(end_to_end_wiring), "max_score": 10},
        "self_correction_maturity": {
            "score": _bounded_score(self_correction_maturity),
            "max_score": 10,
        },
        "execution_readiness": {
            "score": _bounded_score(int(execution_readiness_breakdown.get("final_score", 0))),
            "max_score": 10,
        },
    }


def build_pipeline_health_report(
    include_tests: bool = False,
    repo_root: Path | None = None,
    write_runtime: bool = True,
    open_positions_path: Path | None = None,
    experience_mode_report_path: Path | None = None,
    complexity_ladder_controller_path: Path | None = None,
    runtime_state: dict[str, Any] | None = None,
    action_report: dict[str, Any] | None = None,
    attention_proxy_report: dict[str, Any] | None = None,
    moltbook_feedback_report: dict[str, Any] | None = None,
    friction_report: dict[str, Any] | None = None,
    trend_report: dict[str, Any] | None = None,
    signal_refinery_report: dict[str, Any] | None = None,
    perception_control_report: dict[str, Any] | None = None,
    external_data_report: dict[str, Any] | None = None,
    external_observation_report: dict[str, Any] | None = None,
    grok_xai_report: dict[str, Any] | None = None,
    latest_snapshot_timestamp: str | None = None,
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict:
    base = repo_root or REPO_ROOT
    if runtime_state is None:
        scm_report = build_signal_conversion_report(
            simulate_gsce_clear=simulate_gsce_clear,
            simulate_realm_bis_clear=simulate_realm_bis_clear,
            simulate_all_clear=simulate_all_clear,
        )
        state = build_runtime_state_from_scm_report(scm_report)
    else:
        state = runtime_state
    loaded_external_data_report = (
        external_data_report if isinstance(external_data_report, dict) else {}
    )
    if loaded_external_data_report.get("external_observation_active"):
        state = apply_external_observation_report(state, loaded_external_data_report)
    simulation_context = state.get("simulation_context", {})
    effective_write_runtime = write_runtime and not simulation_context.get("is_simulated", False)

    if effective_write_runtime:
        persist_current_runtime_state(state)

    open_positions, open_positions_summary = load_open_positions(open_positions_path)
    current_snapshot_row = (
        build_snapshot_row(runtime_state=state)
        if simulation_context.get("is_simulated", False) or not effective_write_runtime
        else None
    )
    friction_report = friction_report or build_blocker_cost_report(
        runtime_state=state,
        write_runtime=effective_write_runtime,
    )
    trend_report = trend_report or build_trend_report(
        log_path=_deterministic_trend_log_path(
            state=state,
            write_runtime=effective_write_runtime,
            simulation_context=simulation_context,
        ),
        write_runtime=effective_write_runtime,
        current_snapshot_row=current_snapshot_row,
    )
    attention_proxy_report = attention_proxy_report or state.get("attention_proxy")
    if not isinstance(attention_proxy_report, dict) or not attention_proxy_report:
        attention_proxy_report = build_attention_proxy_report(
            runtime_state=state,
            trend_report=trend_report,
            write_runtime=effective_write_runtime,
        )
    state["attention_proxy"] = attention_proxy_report
    moltbook_feedback_report = moltbook_feedback_report or state.get("moltbook_feedback")
    if not isinstance(moltbook_feedback_report, dict) or not moltbook_feedback_report:
        moltbook_feedback_report = build_moltbook_feedback_report(
            runtime_state=state,
            write_runtime=effective_write_runtime,
        )
    state["moltbook_feedback"] = moltbook_feedback_report
    signal_refinery_report = signal_refinery_report or build_signal_refinery_report(
        runtime_state=state,
        trend_report=trend_report,
        open_positions_path=open_positions_path,
        write_runtime=effective_write_runtime,
    )
    state["signal_refinery"] = signal_refinery_report
    perception_control_report = perception_control_report or build_perception_control_report(
        runtime_state=state,
        signal_refinery_report=signal_refinery_report,
        trend_report=trend_report,
        write_runtime=effective_write_runtime,
    )
    state["perception_control"] = perception_control_report
    action_report = action_report or build_action_report(
        runtime_state=state,
        open_positions_path=open_positions_path,
        signal_refinery_report=signal_refinery_report,
        perception_control_report=perception_control_report,
        write_runtime=effective_write_runtime,
    )
    test_status = (
        run_targeted_tests(base)
        if include_tests
        else {
            "invoked": False,
            "command": TARGET_TEST_COMMAND,
            "exit_code": None,
            "passed": None,
            "summary_line": None,
        }
    )

    blocked_promotable_candidate_queue = build_blocked_promotable_candidate_queue(
        state["watchlist_diagnostics"],
        per_signal_rows=state["per_signal_attribution"],
        trend_report=trend_report,
    )
    live_baseline_report = build_signal_conversion_report()
    live_baseline_state = build_runtime_state_from_scm_report(live_baseline_report)
    live_baseline_queue = build_blocked_promotable_candidate_queue(
        live_baseline_state["watchlist_diagnostics"],
        per_signal_rows=live_baseline_state["per_signal_attribution"],
        trend_report=trend_report,
    )
    live_baseline_action_report = build_action_report(
        runtime_state=live_baseline_state,
        open_positions_path=open_positions_path,
        write_runtime=False,
    )
    gate_resolution_preview = build_gate_resolution_preview(
        live_state=live_baseline_state,
        live_action_report=live_baseline_action_report,
        live_queue=live_baseline_queue,
        open_positions=open_positions,
        open_positions_path=open_positions_path,
    )
    gsce_clear_transition_preview = gate_resolution_preview["gsce_clear"]["candidates"]
    queue_pressure_state = derive_queue_pressure_state(blocked_promotable_candidate_queue)
    operator_policy = build_operator_policy_view(
        state["execution_policy"],
        state["watchlist_diagnostics"],
        state["per_signal_attribution"],
    )
    system_readiness_state, can_deploy_capital = determine_system_readiness(
        scm_review=state["scm_review"],
        execution_policy=state["execution_policy"],
        friction_report=friction_report,
        open_positions_summary=open_positions_summary,
        active_blockers=state["active_blockers"],
    )
    watchlist_intelligence = summarize_watchlist_intelligence(state["watchlist_diagnostics"])
    where_am_i_leaking_performance = derive_performance_leak_summary(
        friction_report,
        watchlist_intelligence=watchlist_intelligence,
    )
    what_should_i_do_next = derive_next_operational_action(
        operator_policy,
        action_report,
        blocked_promotable_candidate_queue=blocked_promotable_candidate_queue,
    )
    readiness_context = build_readiness_context(state, blocked_promotable_candidate_queue)
    execution_readiness_breakdown = build_execution_readiness_breakdown(
        state=state,
        friction_report=friction_report,
        trend_report=trend_report,
        blocked_promotable_candidate_queue=blocked_promotable_candidate_queue,
    )
    scorecard = build_health_scorecard(
        state=state,
        action_report=action_report,
        friction_report=friction_report,
        trend_report=trend_report,
        open_positions_summary=open_positions_summary,
        test_status=test_status,
        execution_readiness_breakdown=execution_readiness_breakdown,
    )

    highest_priority_actions = [
        {
            "ticker": row["ticker"],
            "action": row["action"],
            "priority_score": row["priority_score"],
        }
        for row in action_report["actions"][:5]
    ]

    resolved_latest_snapshot_timestamp = latest_snapshot_timestamp or _load_latest_snapshot_timestamp()
    latest_trend_timestamp_or_window_end = trend_report.get("window", {}).get("last_timestamp")
    if not latest_trend_timestamp_or_window_end:
        latest_trend_timestamp_or_window_end = resolved_latest_snapshot_timestamp

    queue_sync_state = (
        "UNKNOWN"
        if simulation_context.get("is_simulated", False)
        else derive_queue_sync_state(
            blocked_promotable_candidate_queue,
            trend_report=trend_report,
        )
    )
    blockage_severity = derive_blockage_severity(
        blocked_promotable_candidate_queue,
        readiness_context=readiness_context,
        active_blockers=state["active_blockers"],
    )
    operator_pressure_state = derive_operator_pressure_state(
        system_readiness_state=system_readiness_state,
        queue_pressure_state=queue_pressure_state,
        readiness_breakdown=execution_readiness_breakdown,
        readiness_context=readiness_context,
    )
    preview_key_by_scenario = {
        "LIVE": "live",
        "GSCE_CLEAR": "gsce_clear",
        "REALM_BIS_CLEAR": "realm_bis_clear",
        "ALL_CLEAR": "all_clear",
    }
    current_preview_key = preview_key_by_scenario.get(
        simulation_context.get("scenario", "LIVE"),
        "live",
    )
    current_scenario_preview = gate_resolution_preview[current_preview_key]
    clean_ready_candidates_if_gsce_clears = build_clean_ready_candidates_if_gsce_clears(
        gsce_clear_transition_preview
    )
    next_state_if_all_clear = build_next_state_if_all_clear(gate_resolution_preview)
    entry_review_packets = current_scenario_preview["entry_review_packets"]
    transition_review_packets = current_scenario_preview["transition_review_packets"]
    packet_summary = current_scenario_preview["packet_summary"]
    decision_review_state = current_scenario_preview["decision_review_state"]
    truth_context = build_truth_context(state)
    experience_mode_report = _load_optional_runtime_artifact(
        experience_mode_report_path,
        EXPERIENCE_MODE_REPORT_PATH,
    )
    complexity_ladder_controller = _load_optional_runtime_artifact(
        complexity_ladder_controller_path,
        COMPLEXITY_LADDER_CONTROLLER_PATH,
    )
    experience_mode_summary = build_experience_mode_summary(
        experience_mode_report=experience_mode_report,
        complexity_ladder_controller=complexity_ladder_controller,
    )
    external_data_summary = build_external_data_summary(loaded_external_data_report)
    external_observation_summary = build_external_observation_summary(external_observation_report)
    bridge_mode_context = resolve_bridge_mode(
        include_external_observations=bool(
            state.get("external_observation_requested", False)
            or external_observation_report is not None
        ),
        external_candidate_bridge_enabled=bool(
            state.get("external_candidate_bridge_enabled", False)
        ),
        external_observation_active=bool(
            external_observation_summary.get("external_observation_active", False)
        ),
        external_observation_valid_count=int(
            external_observation_summary.get("external_observation_valid_count", 0) or 0
        ),
        external_candidate_count=int(state.get("external_candidate_count", 0) or 0),
        scm_external_row_count=int(state.get("scm_external_row_count", 0) or 0),
        paper_candidate_count=int(
            state.get("external_paper_candidate_count", 0) or 0
        ),
        provider_error_count=int(
            external_observation_summary.get("external_observation_error_count", 0) or 0
        ),
    )
    position_truth_summary = build_position_truth_summary(curated_path=open_positions_path)
    external_candidate_rows = state.get("external_candidate_rows", [])
    signal_source_rows = list(state["per_signal_attribution"])
    if isinstance(external_candidate_rows, list) and external_candidate_rows:
        signal_source_rows = signal_source_rows + [
            row for row in external_candidate_rows if isinstance(row, dict)
        ]
    signal_source_summary = build_signal_source_summary(signal_source_rows)
    signal_segmentation = build_signal_segmentation_summary(
        per_signal_rows=signal_source_rows,
        external_candidate_count=int(state.get("external_candidate_count", 0) or 0),
        external_observation_valid_count=int(
            external_observation_summary.get("external_observation_valid_count", 0) or 0
        ),
        scm_external_row_count=int(state.get("scm_external_row_count", 0) or 0),
        scm_seeded_row_count=int(state.get("scm_seeded_row_count", 0) or 0),
    )
    temporal_integrity = build_temporal_integrity_summary(
        decision_timestamp=state.get("decision_timestamp"),
        reconciliation_timestamp=state.get("reconciliation_timestamp"),
        observations=external_observation_summary.get("observations", []),
        feature_rows=signal_source_rows,
    )
    truth_metrics = build_truth_metrics_summary(
        signal_summary=state.get("signal_summary"),
        per_signal_rows=signal_source_rows,
        feedback_report=moltbook_feedback_report,
        signal_segmentation=signal_segmentation,
    )
    intelligence_summary = build_intelligence_summary(grok_xai_report)
    extreme_state_report = _load_optional_runtime_artifact(
        None,
        EXTREME_STATE_REPORT_PATH,
    )
    extreme_state_logic = build_extreme_state_logic_summary(extreme_state_report)
    operator_control_report = build_operator_control_report(
        gate_summary=signal_refinery_report.get("signal_admission_gate", {}),
        test_status=test_status,
        write_runtime=effective_write_runtime,
    )
    reflection_context = build_reflection_context(
        state=state,
        signal_refinery_report=signal_refinery_report,
        attention_proxy_report=attention_proxy_report,
        action_report=action_report,
        entry_review_packets=entry_review_packets,
        transition_review_packets=transition_review_packets,
        operator_control_report=operator_control_report,
        open_positions=open_positions,
    )
    narrative_filter_report = evaluate_narrative_operator_wisdom_filter(
        {
            "evidence_strength": reflection_context["evidence_strength"],
            "narrative_confidence": reflection_context["narrative_confidence"],
            "emotional_resonance": reflection_context["emotional_resonance"],
            "interpretation_width": 1.0
            - float(
                reflection_context["validation_row"].get("cross_source_confirmation_score") or 0.0
            ),
            "falsifiable": bool(reflection_context["validation_row"]),
            "operator_state": reflection_context["operator_state"],
            "operator_stability_score": reflection_context["operator_stability_score"],
            "cross_state_validated": bool(reflection_context["validation_row"])
            and reflection_context["operator_state"] not in {"UNKNOWN", "STRESSED", "EUPHORIC", "FATIGUED", "INTOXICATED"},
            "passing_state_tag": False,
            "urgency_spike": reflection_context["context_switch_count"] > 1,
            "confidence_surge": reflection_context["narrative_confidence"] >= 0.75,
            "selected_feeling_match": reflection_context["operator_state"] in {"CALM", "NEUTRAL"},
        }
    )
    busquets_audit_report = evaluate_busquets_pre_execution_audit(
        {
            "signal_validated": (
                str(reflection_context["validation_row"].get("validation_state") or "").upper()
                == "VALIDATED"
            ),
            "commitment_detected": bool(reflection_context["primary_packet"])
            and bool(reflection_context["launch_row"]),
            "space_created": str(
                reflection_context["primary_packet"].get("target_pre_entry_state") or ""
            ).upper()
            == "CLEAN_ENTRY_ELIGIBLE",
            "timing_quality": reflection_context["validation_row"].get(
                "cross_source_confirmation_score",
                reflection_context["evidence_strength"],
            ),
            "space_quality": reflection_context["validation_row"].get(
                "repricing_headroom_score",
                0.0,
            ),
            "risk_clearance": bool(reflection_context["policy"].get("allow_new_risk", False))
            and not bool(reflection_context["primary_packet"].get("open_position_conflict", False))
            and not narrative_filter_report["action_authority"] == "REVOKED",
            "chaos_veto_active": reflection_context["chaos_veto_active"],
            "execution_packet": reflection_context["execution_packet"],
            "execution_packet_locked": reflection_context["execution_packet_locked"],
            "policy_state": reflection_context["policy"].get("policy_state"),
        }
    )
    execution_integrity_report = evaluate_execution_integrity_audit(
        {
            "rhythm_integrity_score": reflection_context["validation_row"].get(
                "novelty_score",
                reflection_context["evidence_strength"],
            ),
            "pattern_fidelity_score": reflection_context["validation_row"].get(
                "first_order_score",
                reflection_context["evidence_strength"],
            ),
            "visible_reopen": reflection_context["reopen_count"] > 0
            and reflection_context["context_switch_count"] > 0,
            "mid_execution_reopen_detected": reflection_context["reopen_count"] > 0,
            "hidden_adaptation_detected": reflection_context["reopen_count"] > 0
            and reflection_context["context_switch_count"] == 0,
            "concealment_score": 1.0 if reflection_context["context_switch_count"] == 0 else 0.0,
            "operator_uncertainty_score": 1.0 - narrative_filter_report["operator_stability_score"],
            "delay_cost": min(
                1.0,
                float(reflection_context["context_switch_count"] + reflection_context["reopen_count"])
                * 0.15,
            ),
            "information_gain": reflection_context["narrative_confidence"],
            "policy_aligned": bool(reflection_context["policy"].get("allow_new_risk", False)),
            "execution_packet_valid": reflection_context["execution_packet_locked"],
        }
    )
    asset_durability_report = build_asset_durability_report(
        {
            "durability": reflection_context["evidence_strength"],
            "recovery": reflection_context["validation_row"].get("first_order_score", 0.0),
            "adaptation": reflection_context["validation_row"].get("novelty_score", 0.0),
            "liquidity": reflection_context["validation_row"].get("source_quality_score", 0.0),
            "low_fragility": reflection_context["validation_row"].get(
                "blocker_clearance_score",
                0.0,
            ),
            "performance_before_stress": max(reflection_context["evidence_strength"], 0.01),
            "performance_after_stress": max(
                float(reflection_context["validation_row"].get("repricing_headroom_score", 0.0)) * max(reflection_context["evidence_strength"], 0.01),
                0.0,
            ),
            "cash_flow_quality": reflection_context["validation_row"].get("source_quality_score", 0.0),
            "margin_quality": reflection_context["validation_row"].get("price_lead_score", 0.0),
            "debt_burden": 1.0 - float(
                reflection_context["validation_row"].get("blocker_clearance_score", 0.0)
            ),
            "pricing_power": reflection_context["validation_row"].get(
                "repricing_headroom_score",
                0.0,
            ),
            "revenue_recurrence": reflection_context["validation_row"].get("first_order_score", 0.0),
            "fundamental_durability_value": max(reflection_context["evidence_strength"], 0.01),
            "market_price": max(
                float(reflection_context["validation_row"].get("validation_score", 0.0)) + 0.1,
                0.01,
            ),
            "dependency_importance": reflection_context["validation_row"].get(
                "source_quality_score",
                0.0,
            ),
            "low_visibility": 1.0 - float(reflection_context["narrative_confidence"]),
            "high_recurrence": reflection_context["validation_row"].get("first_order_score", 0.0),
            "simple_mechanism": reflection_context["validation_row"].get(
                "cross_source_confirmation_score",
                0.0,
            ),
            "universal_need": reflection_context["validation_row"].get("source_quality_score", 0.0),
            "repeat_demand": reflection_context["validation_row"].get("first_order_score", 0.0),
            "unrelated_business_lines": 0.0,
            "single_founder_dependency": 0.0,
            "single_regulation_dependency": 0.2 if reflection_context["chaos_veto_active"] else 0.0,
            "single_liquidity_dependency": 1.0
            - float(reflection_context["validation_row"].get("source_quality_score", 0.0)),
            "single_narrative_dependency": reflection_context["narrative_confidence"],
            "unclear_core_mechanism": 1.0
            - float(reflection_context["validation_row"].get("cross_source_confirmation_score", 0.0)),
        }
    )
    baines_engine_report = build_baines_engine_report(
        _build_baines_inputs(
            state=state,
            signal_refinery_report=signal_refinery_report,
            operator_policy=operator_policy,
        )
    )
    football_archetype_inputs, football_chaos_state = _build_football_portfolio_archetype_inputs(
        state=state,
        signal_refinery_report=signal_refinery_report,
        operator_policy=operator_policy,
    )
    football_portfolio_archetype_report = build_football_portfolio_archetype_report(
        football_archetype_inputs,
        policy_state=operator_policy.get("policy_state", "RESTRICTED"),
        chaos_state=football_chaos_state,
        run_id=state.get("run_id"),
        generated_at=state.get("artifact_written_at") or state.get("run_started_at"),
    )
    primary_packet = reflection_context.get("primary_packet", {})
    current_lens_mode = "WIDE"
    if primary_packet:
        current_lens_mode = "TELEPHOTO"
    if str(primary_packet.get("target_pre_entry_state") or "").upper() == "CLEAN_ENTRY_ELIGIBLE":
        current_lens_mode = "MACRO"
    if reflection_context["execution_packet_locked"]:
        current_lens_mode = "LEICA"
    opportunity_half_life = float(
        reflection_context["validation_row"].get(
            "repricing_headroom_score",
            reflection_context["evidence_strength"],
        )
        or 0.0
    )
    validation_time = float(
        signal_refinery_report.get("time_to_valid_signal_kpi", {}).get(
            "median_time_to_valid_signal_hours",
            0.0,
        )
        or 0.0
    )
    if validation_time > 1.0:
        validation_time = 1.0
    candidate_count = max(
        len(entry_review_packets),
        len(transition_review_packets),
        int(state.get("signal_summary", {}).get("signals_above_ce_threshold", 0) or 0),
    )
    optical_operating_system_report = evaluate_optical_operating_system(
        {
            "timestamp": state.get("artifact_written_at") or state.get("run_started_at"),
            "run_id": state.get("run_id"),
            "asset": reflection_context["primary_ticker"],
            "ticker": reflection_context["primary_ticker"],
            "signal_id": reflection_context["primary_packet"].get("signal_id"),
            "detection_strength": reflection_context["evidence_strength"],
            "validation_quality": reflection_context["validation_row"].get(
                "cross_source_confirmation_score",
                reflection_context["evidence_strength"],
            ),
            "durability_score": asset_durability_report["adjusted_score"],
            "execution_survivability": min(
                float(busquets_audit_report["audit_score"]),
                float(execution_integrity_report["execution_integrity_score"]),
            ),
            "source_quality": reflection_context["validation_row"].get(
                "source_quality_score",
                reflection_context["evidence_strength"],
            ),
            "signal_strength": reflection_context["validation_row"].get(
                "validation_score",
                reflection_context["evidence_strength"],
            ),
            "evidence_strength": reflection_context["evidence_strength"],
            "narrative_confidence": reflection_context["narrative_confidence"],
            "opportunity_half_life": opportunity_half_life,
            "validation_time": validation_time,
            "information_gain": reflection_context["narrative_confidence"],
            "delay_cost": min(
                1.0,
                float(reflection_context["context_switch_count"] + reflection_context["reopen_count"])
                * 0.15,
            ),
            "current_lens_mode": current_lens_mode,
            "momentum_score": reflection_context["validation_row"].get(
                "first_order_score",
                0.0,
            ),
            "persistence": min(
                1.0,
                float(trend_report.get("snapshot_count", 0) or 0) / 10.0,
            ),
            "convergence": reflection_context["validation_row"].get(
                "cross_source_confirmation_score",
                0.0,
            ),
            "volatility": max(
                float(attention_proxy_report.get("narrative_heat_score") or 0.0),
                1.0 if reflection_context["chaos_veto_active"] else 0.0,
            ),
            "risk_score": 0.0
            if (
                busquets_audit_report["risk_clearance"]
                and not reflection_context["primary_packet"].get("open_position_conflict", False)
            )
            else 1.0,
            "regime_stress": 1.0 if reflection_context["chaos_veto_active"] else 0.35,
            "candidate_count": candidate_count,
            "active_blockers": state.get("active_blockers", []),
            "chaos_veto_active": reflection_context["chaos_veto_active"],
            "shock_override_active": temporal_integrity["temporal_integrity_state"] == "FAILED"
            or position_truth_summary.get("divergence_severity") == "CRITICAL",
            "policy_clear": bool(reflection_context["policy"].get("allow_new_risk", False)),
            "policy_state": reflection_context["policy"].get("policy_state"),
            "risk_clear": busquets_audit_report["risk_clearance"],
            "signal_valid": (
                str(reflection_context["validation_row"].get("validation_state") or "").upper()
                == "VALIDATED"
            ),
            "minimum_validation_passed": bool(reflection_context["validation_row"])
            and float(reflection_context["evidence_strength"]) >= 0.55,
            "urgency_spike": reflection_context["context_switch_count"] > 1,
            "confidence_surge": reflection_context["narrative_confidence"] >= 0.75,
            "cognitive_load": min(
                1.0,
                float(reflection_context["context_switch_count"] + reflection_context["reopen_count"])
                * 0.2,
            ),
            "requested_lens_change": reflection_context["reopen_count"] > 0,
            "operator_state": narrative_filter_report["operator_state"],
            "operator_state_fit": narrative_filter_report["operator_stability_score"],
            "lens_lock_active": reflection_context["execution_packet_locked"]
            and execution_integrity_report["execution_integrity_state"]
            in {"LOCKED_EXECUTION", "ADAPTIVE_EXECUTION_ALLOWED"},
            "data_integrity_failure": temporal_integrity["temporal_integrity_state"] == "FAILED",
        }
    )
    reflection_allowed_to_execute = bool(
        busquets_audit_report["allowed_to_execute"]
        and execution_integrity_report["allowed_to_execute"]
        and narrative_filter_report["allowed_to_execute"]
        and optical_operating_system_report["action_allowed"]
        and not reflection_context["chaos_veto_active"]
        and bool(reflection_context["policy"].get("allow_new_risk", False))
    )
    governance_feedback_report = build_governance_feedback_report(
        runtime_state=state,
        action_report=action_report,
        write_runtime=effective_write_runtime,
    )
    closure_deficit_report = build_closure_deficit_report(
        runtime_state=state,
        action_report=action_report,
        signal_refinery_report=signal_refinery_report,
        packet_summary=packet_summary,
        operator_control_report=operator_control_report,
        write_runtime=effective_write_runtime,
    )
    archetype_profile_report = build_archetype_profile_report(
        runtime_state=state,
        action_report=action_report,
        signal_refinery_report=signal_refinery_report,
        friction_report=friction_report,
        trend_report=trend_report,
        governance_feedback_report=governance_feedback_report,
        closure_deficit_report=closure_deficit_report,
        operator_control_report=operator_control_report,
        blocked_promotable_candidate_queue=blocked_promotable_candidate_queue,
        gate_resolution_preview=gate_resolution_preview,
        entry_review_packets=entry_review_packets,
        transition_review_packets=transition_review_packets,
        packet_summary=packet_summary,
        open_positions_path=open_positions_path,
        write_runtime=effective_write_runtime,
    )

    report = {
        "health_generated_at": _health_timestamp(),
        "latest_snapshot_timestamp": resolved_latest_snapshot_timestamp,
        "latest_trend_timestamp_or_window_end": latest_trend_timestamp_or_window_end,
        "simulation_context": simulation_context,
        "simulation_mode": simulation_context.get("scenario", "LIVE"),
        "simulation_writes_runtime": effective_write_runtime,
        "operating_mode": classify_operating_mode(state),
        "truth_origin": truth_context["truth_origin"],
        "truth_origin_tags": truth_context["truth_origin_tags"],
        "queue_sync_state": queue_sync_state,
        "system_readiness_state": system_readiness_state,
        "can_deploy_capital": can_deploy_capital,
        "experience_mode_summary": experience_mode_summary,
        "external_data_summary": external_data_summary,
        "external_observation_summary": external_observation_summary,
        "external_observation_active": external_observation_summary["external_observation_active"],
        "external_observation_count": external_observation_summary["external_observation_count"],
        "external_observation_valid_count": external_observation_summary["external_observation_valid_count"],
        "external_observation_error_count": external_observation_summary["external_observation_error_count"],
        "external_observation_provider": external_observation_summary["external_observation_provider"],
        "external_observation_symbols": external_observation_summary["external_observation_symbols"],
        "external_observation_data_quality_counts": external_observation_summary["external_observation_data_quality_counts"],
        "external_observation_report_path": external_observation_summary["external_observation_report_path"],
        "live_quotes_available": external_observation_summary["live_quotes_available"],
        "bridge_mode": bridge_mode_context["bridge_mode"],
        "bridge_mode_reason": bridge_mode_context["bridge_mode_reason"],
        "bridge_mode_safety_state": bridge_mode_context["bridge_mode_safety_state"],
        "position_truth_summary": position_truth_summary,
        "position_truth_source": position_truth_summary["canonical_position_source"],
        "position_source_divergence_detected": position_truth_summary["position_source_divergence_detected"],
        "position_integrity_state": position_truth_summary.get("position_integrity_state", "UNKNOWN"),
        "curated_positions_count": position_truth_summary["curated_moltbook_positions_count"],
        "runtime_paper_positions_count": position_truth_summary["runtime_paper_positions_count"],
        "position_truth_warning": position_truth_summary["position_truth_warning"],
        "position_truth_recommended_canonical_source": position_truth_summary.get(
            "recommended_canonical_source",
            position_truth_summary["canonical_position_source"],
        ),
        "position_truth_divergence_severity": position_truth_summary.get(
            "divergence_severity",
            "NONE",
        ),
        "position_truth_safe_next_action": position_truth_summary.get(
            "safe_next_action",
            "",
        ),
        "canonical_position_source": position_truth_summary.get("canonical_position_source"),
        "canonical_position_count": position_truth_summary.get("canonical_position_count"),
        "advisory_position_sources": position_truth_summary.get("advisory_position_sources", []),
        "curated_only_symbols": position_truth_summary.get("curated_only_symbols", []),
        "runtime_only_symbols": position_truth_summary.get("runtime_only_symbols", []),
        "overlapping_symbols": position_truth_summary.get("overlapping_symbols", []),
        "canonical_position_checksum": position_truth_summary.get("canonical_position_checksum"),
        "advisory_position_checksum": position_truth_summary.get("advisory_position_checksum"),
        "signal_source_summary": signal_source_summary,
        "signal_segmentation": signal_segmentation,
        "seeded_signal_count": signal_segmentation["seeded_signal_count"],
        "external_signal_count": signal_segmentation["external_signal_count"],
        "mixed_signal_metric_warning": signal_segmentation["mixed_signal_metric_warning"],
        "evidence_contamination_risk": signal_segmentation["evidence_contamination_risk"],
        "external_candidate_count": int(state.get("external_candidate_count", 0) or 0),
        "external_paper_candidate_count": int(
            state.get("external_paper_candidate_count", 0) or 0
        ),
        "temporal_integrity": temporal_integrity,
        "temporal_integrity_state": temporal_integrity["temporal_integrity_state"],
        "temporal_integrity_violation_count": temporal_integrity[
            "temporal_integrity_violation_count"
        ],
        "temporal_integrity_warnings": temporal_integrity["temporal_integrity_warnings"],
        "truth_metrics": truth_metrics,
        "allowed_to_execute": reflection_allowed_to_execute,
        "busquets_audit": busquets_audit_report,
        "busquets_audit_state": busquets_audit_report["busquets_state"],
        "busquets_allowed_to_execute": busquets_audit_report["allowed_to_execute"],
        "busquets_audit_score": busquets_audit_report["audit_score"],
        "execution_integrity_audit": execution_integrity_report,
        "execution_integrity_state": execution_integrity_report["execution_integrity_state"],
        "execution_integrity_score": execution_integrity_report["execution_integrity_score"],
        "hesitation_leak_score": execution_integrity_report["hesitation_leak_score"],
        "mid_execution_reopen_detected": execution_integrity_report[
            "mid_execution_reopen_detected"
        ],
        "narrative_operator_wisdom": narrative_filter_report,
        "narrative_signal_class": narrative_filter_report["narrative_signal_class"],
        "hallucination_risk": narrative_filter_report["hallucination_risk"],
        "operator_state": narrative_filter_report["operator_state"],
        "operator_stability_score": narrative_filter_report["operator_stability_score"],
        "action_authority": narrative_filter_report["action_authority"],
        "asset_durability_report": asset_durability_report,
        "hundred_wash_score": asset_durability_report["hundred_wash_score"],
        "paracetamol_score": asset_durability_report["paracetamol_score"],
        "durability_class": asset_durability_report["durability_class"],
        "positive_adaptation_score": asset_durability_report["positive_adaptation_score"],
        "baines_engine": baines_engine_report,
        "baines_engine_available": baines_engine_report["baines_engine_available"],
        "baines_engine_state": baines_engine_report["baines_engine_state"],
        "baines_candidates_detected": baines_engine_report["baines_candidates_detected"],
        "baines_durable_candidates": baines_engine_report["baines_durable_candidates"],
        "baines_policy_vetoed": baines_engine_report["baines_policy_vetoed"],
        "baines_chaos_vetoed": baines_engine_report["baines_chaos_vetoed"],
        "top_baines_candidate": baines_engine_report["top_baines_candidate"],
        "top_baines_score": baines_engine_report["top_baines_score"],
        "football_portfolio_archetypes": football_portfolio_archetype_report,
        "football_portfolio_archetype_engine_available": football_portfolio_archetype_report[
            "football_portfolio_archetype_engine_available"
        ],
        "football_portfolio_archetype_engine_state": football_portfolio_archetype_report[
            "football_portfolio_archetype_engine_state"
        ],
        "football_baines_candidates_count": football_portfolio_archetype_report[
            "baines_candidates_count"
        ],
        "football_tarkowski_candidates_count": football_portfolio_archetype_report[
            "tarkowski_candidates_count"
        ],
        "football_alonso_variant_count": football_portfolio_archetype_report[
            "alonso_variant_count"
        ],
        "football_trent_risk_count": football_portfolio_archetype_report[
            "trent_risk_count"
        ],
        "football_primary_role_rejections_count": football_portfolio_archetype_report[
            "primary_role_rejections_count"
        ],
        "football_chaos_rejections_count": football_portfolio_archetype_report[
            "chaos_rejections_count"
        ],
        "football_top_baines_candidate": football_portfolio_archetype_report[
            "top_baines_candidate"
        ],
        "football_top_tarkowski_candidate": football_portfolio_archetype_report[
            "top_tarkowski_candidate"
        ],
        "football_portfolio_mode": football_portfolio_archetype_report["portfolio_mode"],
        "football_allocation_recommendation": football_portfolio_archetype_report[
            "allocation_recommendation"
        ],
        "football_policy_veto_applied": football_portfolio_archetype_report[
            "policy_veto_applied"
        ],
        "football_portfolio_archetype_report_path": repo_relative(
            FOOTBALL_PORTFOLIO_ARCHETYPE_REPORT_PATH
        ),
        "optical_operating_system": optical_operating_system_report,
        "optical_bull_state": optical_operating_system_report["optical_bull_state"],
        "optical_lens_mode": optical_operating_system_report["lens_mode"],
        "optical_target_lens_mode": optical_operating_system_report["target_lens_mode"],
        "optical_lens_transition_state": optical_operating_system_report[
            "lens_transition_state"
        ],
        "optical_mirror_mode": optical_operating_system_report["mirror_mode"],
        "optical_opacity_state": optical_operating_system_report["opacity_state"],
        "optical_opacity_score": optical_operating_system_report["opacity_score"],
        "optical_aperture_state": optical_operating_system_report["aperture_state"],
        "optical_shutter_state": optical_operating_system_report["shutter_state"],
        "optical_valve_state": optical_operating_system_report["valve_state"],
        "optical_operator_band": optical_operating_system_report["operator_band"],
        "optical_macro_pass": optical_operating_system_report["macro_pass"],
        "optical_leica_clearance": optical_operating_system_report["leica_clearance"],
        "optical_lens_lock": optical_operating_system_report["lens_lock"],
        "optical_action_allowed": optical_operating_system_report["action_allowed"],
        "optical_final_recommendation": optical_operating_system_report[
            "final_recommendation"
        ],
        "optical_blocking_reason": optical_operating_system_report["blocking_reason"],
        "optical_state_log": optical_operating_system_report["optical_state_log"],
        "intelligence_summary": intelligence_summary,
        "extreme_state_logic": extreme_state_logic,
        "where_am_i_leaking_performance": where_am_i_leaking_performance,
        "what_should_i_do_next": what_should_i_do_next,
        "scm": state["scm_review"],
        "scm_input_origin": state.get("scm_input_origin", "seeded"),
        "scm_external_row_count": int(state.get("scm_external_row_count", 0) or 0),
        "scm_seeded_row_count": int(state.get("scm_seeded_row_count", 0) or 0),
        "attention_proxy": attention_proxy_report,
        "attention_proxy_state": attention_proxy_report.get(
            "attention_proxy_state",
            "UNAVAILABLE",
        ),
        "attention_proxy_score": attention_proxy_report.get("attention_proxy_score"),
        "attention_proxy_confidence": attention_proxy_report.get(
            "attention_proxy_confidence",
            "LOW",
        ),
        "narrative_proxy_advisory": attention_proxy_report.get(
            "narrative_proxy_advisory",
            "no_attention_inputs_scored",
        ),
        "moltbook_feedback": moltbook_feedback_report,
        "moltbook_feedback_available": bool(
            moltbook_feedback_report.get("moltbook_feedback_available", False)
        ),
        "feedback_learning_state": moltbook_feedback_report.get(
            "feedback_learning_state",
            "NO_FEEDBACK",
        ),
        "feedback_cases_total": int(moltbook_feedback_report.get("feedback_cases_total", 0) or 0),
        "feedback_success_rate": moltbook_feedback_report.get("feedback_success_rate", 0.0),
        "feedback_top_failure_mode": moltbook_feedback_report.get(
            "feedback_top_failure_mode",
            "NONE",
        ),
        "feedback_readiness_penalty": moltbook_feedback_report.get(
            "feedback_readiness_penalty",
            0.0,
        ),
        "suggested_feedback_adjustments": moltbook_feedback_report.get(
            "suggested_feedback_adjustments",
            [],
        ),
        "policy": operator_policy,
        "friction": friction_report,
        "governance_feedback": governance_feedback_report,
        "closure_deficit": closure_deficit_report,
        "archetype_profile": archetype_profile_report,
        "trends": trend_report,
        "signal_refinery": signal_refinery_report,
        "perception_control": perception_control_report,
        "perception_control_state": perception_control_report.get(
            "perception_control_state",
            "UNKNOWN",
        ),
        "gravity_pressure_state": perception_control_report.get(
            "gravity_pressure_state",
            "UNKNOWN",
        ),
        "resurfacing_load_state": perception_control_report.get(
            "resurfacing_load_state",
            "UNKNOWN",
        ),
        "dominant_spectrum_class": perception_control_report.get(
            "dominant_spectrum_class",
            "unknown",
        ),
        "visibility_timing_context": signal_refinery_report.get(
            "visibility_timing_context",
            {},
        ),
        "operator_control": operator_control_report,
        "watchlist_intelligence": watchlist_intelligence,
        "blocked_promotable_candidate_queue": blocked_promotable_candidate_queue,
        "queue_pressure_state": queue_pressure_state,
        "blockage_severity": blockage_severity,
        "operator_pressure_state": operator_pressure_state,
        "operator_pressure_note": (
            "This is a derived blockage/readiness pressure label, not an inferred psychological state."
        ),
        "execution_readiness_breakdown": execution_readiness_breakdown,
        "gate_resolution_preview": gate_resolution_preview,
        "gsce_clear_transition_preview": gsce_clear_transition_preview,
        "gsce_clear_action_preview": gate_resolution_preview["gsce_clear"],
        "clean_ready_candidates_if_gsce_clears": clean_ready_candidates_if_gsce_clears,
        "next_state_if_all_clear": next_state_if_all_clear,
        "blocked_promotable_transition_streak": trend_report.get(
            "blocked_promotable_transition_streak",
            {},
        ),
        "clean_ready_pending_transition_streak": trend_report.get(
            "clean_ready_pending_transition_streak",
            {},
        ),
        "clean_entry_eligible_transition_streak": trend_report.get(
            "clean_entry_eligible_transition_streak",
            {},
        ),
        "scenario_transition_trends": trend_report.get("scenario_transition_trends", {}),
        "transition_pressure_state": trend_report.get("transition_pressure_state"),
        "transition_readiness_state": trend_report.get("transition_readiness_state"),
        "packet_transition_state": trend_report.get("packet_transition_state"),
        "packet_entry_state": trend_report.get("packet_entry_state"),
        "entry_review_candidate_streak": trend_report.get("entry_review_candidate_streak", {}),
        "transition_review_candidate_streak": trend_report.get(
            "transition_review_candidate_streak",
            {},
        ),
        "decision_review_state": decision_review_state,
        "entry_review_packets": entry_review_packets,
        "transition_review_packets": transition_review_packets,
        "packet_summary": packet_summary,
        "readiness_context": readiness_context,
        "per_ticker_action_summary": {
            "summary_by_action": action_report["summary_by_action"],
            "highest_priority_actions": highest_priority_actions,
        },
        "open_positions_validation_summary": open_positions_summary,
        "git_status": get_git_status(base),
        "test_status": test_status,
        "moltbook_summary": state["moltbook_summary"],
        "signal_summary": state["signal_summary"],
        "active_blockers": state["active_blockers"],
        "scorecard": scorecard,
        "scorecard_rules": SCORECARD_RULES,
        "note": (
            "Health report integrates the local SCM runtime, signal refinery gating, "
            "action policy, blocker cost, paper-feedback learning, memory trends, and open-position validation. "
            "It is a local decision shell report, not a live execution report."
        ),
    }
    report = stamp_payload(report, runtime_state=state)
    state["reconciliation_timestamp"] = report.get("artifact_written_at")
    temporal_integrity = build_temporal_integrity_summary(
        decision_timestamp=state.get("decision_timestamp"),
        reconciliation_timestamp=state.get("reconciliation_timestamp"),
        observations=external_observation_summary.get("observations", []),
        feature_rows=signal_source_rows,
    )
    report["temporal_integrity"] = temporal_integrity
    report["temporal_integrity_state"] = temporal_integrity["temporal_integrity_state"]
    report["temporal_integrity_violation_count"] = temporal_integrity[
        "temporal_integrity_violation_count"
    ]
    report["temporal_integrity_warnings"] = temporal_integrity["temporal_integrity_warnings"]
    reproducibility_summary = build_reproducibility_summary(repo_root=base, report=report)
    report["reproducibility_summary"] = reproducibility_summary
    report["golden_health_snapshot"] = build_stable_health_snapshot(report)
    report["golden_health_snapshot_hash"] = compute_stable_health_snapshot_hash(report)

    if effective_write_runtime:
        write_json_atomic(HEALTH_REPORT_PATH, report, stamp=False)
        write_json_atomic(
            FOOTBALL_PORTFOLIO_ARCHETYPE_REPORT_PATH,
            football_portfolio_archetype_report,
            stamp=True,
        )

    return report


def format_pipeline_health_summary(report: dict[str, Any]) -> str:
    git_clean = report["git_status"]["is_clean"]
    tests_invoked = report["test_status"]["invoked"]
    tests_passed = report["test_status"]["passed"]
    lines = ["Pipeline Health Report"]
    if report.get("simulation_mode") and report.get("simulation_mode") != "LIVE":
        lines.append(f"simulation_mode={report['simulation_mode']}")
    lines.extend(
        [
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"git_clean={str(git_clean).lower() if isinstance(git_clean, bool) else git_clean}",
            f"tests_invoked={str(tests_invoked).lower() if isinstance(tests_invoked, bool) else tests_invoked}",
            f"tests_passed={str(tests_passed).lower() if isinstance(tests_passed, bool) else tests_passed}",
            f"system_readiness_state={report['system_readiness_state']}",
            f"can_deploy_capital={str(report['can_deploy_capital']).lower()}",
            f"scm_state={report['scm']['scm_state']}",
            f"policy_state={report['policy']['policy_state']}",
            f"friction_band={report['friction']['friction_band']}",
            f"perception_control_state={report.get('perception_control_state', 'UNKNOWN')}",
            (
                "attention_proxy="
                f"state={report.get('attention_proxy_state', 'UNAVAILABLE')}, "
                f"score={report.get('attention_proxy_score')}, "
                f"confidence={report.get('attention_proxy_confidence', 'LOW')}"
            ),
            f"narrative_proxy_advisory={report.get('narrative_proxy_advisory', 'no_attention_inputs_scored')}",
            f"feedback_learning_state={report.get('feedback_learning_state', 'NO_FEEDBACK')}",
            f"feedback_cases_total={report.get('feedback_cases_total', 0)}",
            f"feedback_success_rate={report.get('feedback_success_rate', 0.0)}",
            f"feedback_top_failure_mode={report.get('feedback_top_failure_mode', 'NONE')}",
            f"feedback_readiness_penalty={report.get('feedback_readiness_penalty', 0.0)}",
            "moltbook_feedback_available="
            f"{str(bool(report.get('moltbook_feedback_available', False))).lower()}",
            f"bridge_mode={report.get('bridge_mode', 'seeded')}",
            f"bridge_mode_reason={report.get('bridge_mode_reason', 'no external observation mode requested')}",
            f"bridge_mode_safety_state={report.get('bridge_mode_safety_state', 'paper_safe_only')}",
            f"position_integrity_state={report.get('position_integrity_state', 'UNKNOWN')}",
            f"temporal_integrity_state={report.get('temporal_integrity_state', 'UNKNOWN')}",
            f"temporal_integrity_violation_count={int(report.get('temporal_integrity_violation_count', 0) or 0)}",
            f"seeded_signal_count={int(report.get('seeded_signal_count', 0) or 0)}",
            f"external_signal_count={int(report.get('external_signal_count', 0) or 0)}",
            f"evidence_contamination_risk={report.get('evidence_contamination_risk', 'UNKNOWN')}",
            f"golden_health_snapshot_hash={report.get('golden_health_snapshot_hash')}",
            f"busquets_audit_state={report.get('busquets_audit_state', 'UNKNOWN')}",
            f"allowed_to_execute={str(bool(report.get('allowed_to_execute', False))).lower()}",
            "busquets_allowed_to_execute="
            f"{str(bool(report.get('busquets_allowed_to_execute', False))).lower()}",
            f"busquets_audit_score={report.get('busquets_audit_score')}",
            f"execution_integrity_state={report.get('execution_integrity_state', 'UNKNOWN')}",
            f"execution_integrity_score={report.get('execution_integrity_score')}",
            f"hesitation_leak_score={report.get('hesitation_leak_score')}",
            "mid_execution_reopen_detected="
            f"{str(bool(report.get('mid_execution_reopen_detected', False))).lower()}",
            f"narrative_signal_class={report.get('narrative_signal_class', 'UNKNOWN')}",
            f"hallucination_risk={report.get('hallucination_risk')}",
            f"operator_state={report.get('operator_state', 'UNKNOWN')}",
            f"operator_stability_score={report.get('operator_stability_score')}",
            f"action_authority={report.get('action_authority', 'UNKNOWN')}",
            f"hundred_wash_score={report.get('hundred_wash_score')}",
            f"paracetamol_score={report.get('paracetamol_score')}",
            f"durability_class={report.get('durability_class', 'UNKNOWN')}",
            f"positive_adaptation_score={report.get('positive_adaptation_score')}",
            "baines_engine_available="
            f"{str(bool(report.get('baines_engine_available', False))).lower()}",
            f"baines_engine_state={report.get('baines_engine_state', 'EMPTY')}",
            f"baines_candidates_detected={int(report.get('baines_candidates_detected', 0) or 0)}",
            f"baines_durable_candidates={int(report.get('baines_durable_candidates', 0) or 0)}",
            f"baines_policy_vetoed={int(report.get('baines_policy_vetoed', 0) or 0)}",
            f"baines_chaos_vetoed={int(report.get('baines_chaos_vetoed', 0) or 0)}",
            f"top_baines_candidate={report.get('top_baines_candidate')}",
            f"top_baines_score={report.get('top_baines_score')}",
            "football_portfolio_archetype_engine_available="
            f"{str(bool(report.get('football_portfolio_archetype_engine_available', False))).lower()}",
            "football_portfolio_archetype_engine_state="
            f"{report.get('football_portfolio_archetype_engine_state', 'EMPTY')}",
            "football_baines_candidates_count="
            f"{int(report.get('football_baines_candidates_count', 0) or 0)}",
            "football_tarkowski_candidates_count="
            f"{int(report.get('football_tarkowski_candidates_count', 0) or 0)}",
            "football_alonso_variant_count="
            f"{int(report.get('football_alonso_variant_count', 0) or 0)}",
            f"football_trent_risk_count={int(report.get('football_trent_risk_count', 0) or 0)}",
            "football_primary_role_rejections_count="
            f"{int(report.get('football_primary_role_rejections_count', 0) or 0)}",
            "football_chaos_rejections_count="
            f"{int(report.get('football_chaos_rejections_count', 0) or 0)}",
            f"football_top_baines_candidate={report.get('football_top_baines_candidate')}",
            f"football_top_tarkowski_candidate={report.get('football_top_tarkowski_candidate')}",
            f"football_portfolio_mode={report.get('football_portfolio_mode', 'UNKNOWN')}",
            "football_policy_veto_applied="
            f"{str(bool(report.get('football_policy_veto_applied', False))).lower()}",
            "football_portfolio_archetype_report_path="
            f"{report.get('football_portfolio_archetype_report_path')}",
            f"optical_bull_state={report.get('optical_bull_state', 'UNKNOWN')}",
            f"optical_lens_mode={report.get('optical_lens_mode', 'UNKNOWN')}",
            f"optical_mirror_mode={report.get('optical_mirror_mode', 'UNKNOWN')}",
            f"optical_opacity_state={report.get('optical_opacity_state', 'UNKNOWN')}",
            f"optical_aperture_state={report.get('optical_aperture_state', 'UNKNOWN')}",
            f"optical_shutter_state={report.get('optical_shutter_state', 'UNKNOWN')}",
            f"optical_valve_state={report.get('optical_valve_state', 'UNKNOWN')}",
            f"optical_lens_lock={str(bool(report.get('optical_lens_lock', False))).lower()}",
            "optical_action_allowed="
            f"{str(bool(report.get('optical_action_allowed', False))).lower()}",
            "optical_final_recommendation="
            f"{report.get('optical_final_recommendation', 'UNKNOWN')}",
            f"what_should_i_do_next={report['what_should_i_do_next']}",
            (
                "scorecard="
                f"logging_quality={report['scorecard']['logging_quality']['score']}/10, "
                f"schema_reliability={report['scorecard']['schema_reliability']['score']}/10, "
                f"end_to_end_wiring={report['scorecard']['end_to_end_wiring']['score']}/10, "
                f"self_correction_maturity={report['scorecard']['self_correction_maturity']['score']}/10, "
                f"execution_readiness={report['scorecard']['execution_readiness']['score']}/10"
            ),
        ]
    )
    attention_proxy = report.get("attention_proxy", {})
    observability = (
        attention_proxy.get("observability", {})
        if isinstance(attention_proxy, dict)
        else {}
    )
    if isinstance(observability, dict) and observability:
        lines.append(
            "attention_proxy_inputs="
            f"telemetry_backed={observability.get('telemetry_backed_signal_count', 0)}/"
            f"{attention_proxy.get('scored_signal_count', 0)}, "
            f"inferred={observability.get('inferred_signal_count', 0)}, "
            f"state_overlap={observability.get('state_overlap_signal_count', 0)}"
        )
    football_allocation = report.get("football_allocation_recommendation", {})
    if isinstance(football_allocation, dict) and football_allocation:
        allocation_bands = football_allocation.get("allocation_bands", {})
        if isinstance(allocation_bands, dict):
            lines.append(
                "football_allocation_recommendation="
                f"tarkowski_core={allocation_bands.get('tarkowski_core')}, "
                f"baines_expansion={allocation_bands.get('baines_expansion')}, "
                f"optional_spikes={allocation_bands.get('optional_spikes')}"
            )
    feedback_adjustments = report.get("suggested_feedback_adjustments", [])
    if isinstance(feedback_adjustments, list) and feedback_adjustments:
        lines.append(
            "suggested_feedback_adjustments="
            + " | ".join(str(value) for value in feedback_adjustments[:2])
        )
    perception_control = report.get("perception_control", {})
    if isinstance(perception_control, dict):
        lines.append(
            "perception_metrics="
            f"noise_suppression_ratio={perception_control.get('noise_suppression_ratio')}, "
            f"signal_survival_rate={perception_control.get('signal_survival_rate')}, "
            f"average_signal_lux={perception_control.get('average_signal_lux')}"
        )
        advisories = perception_control.get("advisories", [])
        if isinstance(advisories, list) and advisories:
            lines.append(f"perception_advisory={advisories[0]}")
    entry_review_names = report.get("packet_summary", {}).get("entry_review_candidate_names", [])
    transition_review_names = report.get("packet_summary", {}).get(
        "transition_review_candidate_names",
        [],
    )
    if entry_review_names:
        lines.append(f"entry_review_candidates={', '.join(entry_review_names)}")
    if transition_review_names:
        lines.append(f"transition_review_candidates={', '.join(transition_review_names)}")
    external_summary = report.get("external_data_summary", {})
    if external_summary.get("external_observation_active"):
        lines.append(
            "external_data_active="
            f"{str(external_summary.get('external_observation_active')).lower()}"
        )
        if external_summary.get("active_sources"):
            lines.append(
                "external_data_sources="
                + ", ".join(external_summary.get("active_sources", []))
            )
    position_truth = report.get("position_truth_summary", {})
    if isinstance(position_truth, dict) and position_truth:
        lines.extend(format_position_truth_summary(position_truth))
    mixed_signal_metric_warning = report.get("mixed_signal_metric_warning")
    if mixed_signal_metric_warning:
        lines.append(f"mixed_signal_metric_warning={mixed_signal_metric_warning}")
    external_candidate_count = int(report.get("external_candidate_count", 0) or 0)
    if external_candidate_count > 0:
        lines.append(f"external_candidate_count={external_candidate_count}")
        lines.append(
            "external_paper_candidate_count="
            f"{int(report.get('external_paper_candidate_count', 0) or 0)}"
        )
    scm_input_origin = report.get("scm_input_origin")
    if scm_input_origin:
        lines.append(f"scm_input_origin={scm_input_origin}")
        lines.append(
            "scm_row_counts="
            f"seeded={int(report.get('scm_seeded_row_count', 0))}, "
            f"external={int(report.get('scm_external_row_count', 0))}"
        )
    observation_summary = report.get("external_observation_summary", {})
    if observation_summary.get("external_observation_active"):
        lines.append(
            "external_observation_active="
            f"{str(observation_summary.get('external_observation_active')).lower()}"
        )
        lines.append(
            "external_observation_count="
            f"valid={int(observation_summary.get('external_observation_valid_count', 0))}, "
            f"error={int(observation_summary.get('external_observation_error_count', 0))}, "
            f"total={int(observation_summary.get('external_observation_count', 0))}"
        )
        provider = observation_summary.get("external_observation_provider")
        if provider:
            lines.append(f"external_observation_provider={provider}")
        obs_symbols = observation_summary.get("external_observation_symbols", [])
        if obs_symbols:
            lines.append(
                "external_observation_symbols=" + ", ".join(obs_symbols)
            )
        lines.append(
            "live_quotes_available="
            f"{str(observation_summary.get('live_quotes_available', False)).lower()}"
        )
    temporal_warnings = report.get("temporal_integrity_warnings", [])
    if temporal_warnings:
        lines.append("temporal_integrity_warnings=" + " | ".join(temporal_warnings))
    signal_source_summary = report.get("signal_source_summary", {})
    if int(signal_source_summary.get("external_signal_count", 0)) > 0:
        lines.append(
            "signal_sources="
            f"seeded={int(signal_source_summary.get('seeded_signal_count', 0))}, "
            f"external={int(signal_source_summary.get('external_signal_count', 0))}"
        )
    reproducibility = report.get("reproducibility_summary", {})
    if isinstance(reproducibility, dict) and reproducibility:
        lines.append(
            "reproducibility="
            f"python={reproducibility.get('python_version')}, "
            f"requirements={str(bool(reproducibility.get('requirements_txt_exists'))).lower()}, "
            f"ci={str(bool(reproducibility.get('ci_workflow_exists'))).lower()}, "
            f"runtime_metadata={str(bool(reproducibility.get('runtime_metadata_exposed'))).lower()}"
        )
    truth_metrics = report.get("truth_metrics", {})
    if isinstance(truth_metrics, dict) and truth_metrics:
        lines.append(
            "truth_metrics="
            f"candidate_survival_rate={truth_metrics.get('candidate_survival_rate', {}).get('value')}, "
            f"governance_trip_rate={truth_metrics.get('governance_trip_rate', {}).get('value')}, "
            f"seeded_vs_external_delta={truth_metrics.get('seeded_vs_external_delta', {}).get('value')}, "
            f"feedback_information_gain={truth_metrics.get('feedback_information_gain', {}).get('value')}"
        )
    extreme_state_logic = report.get("extreme_state_logic", {})
    if isinstance(extreme_state_logic, dict) and extreme_state_logic.get("report_present"):
        lines.append(
            "extreme_state_logic="
            f"state={extreme_state_logic.get('extreme_state', 'UNAVAILABLE')}, "
            f"signals={extreme_state_logic.get('signals_evaluated', 0)}, "
            f"silent_chaos={extreme_state_logic.get('silent_chaos_count', 0)}, "
            f"terminations={extreme_state_logic.get('termination_required_count', 0)}, "
            f"recommended_action={extreme_state_logic.get('recommended_action', 'WAIT')}"
        )
    intelligence_summary = report.get("intelligence_summary", {})
    if intelligence_summary.get("request_success"):
        lines.append(
            "intelligence_use_case="
            f"{intelligence_summary.get('use_case')}"
        )
        operator_focus = (
            intelligence_summary.get("recommended_operator_action")
            or intelligence_summary.get("operator_focus")
        )
        if operator_focus:
            lines.append(f"intelligence_focus={operator_focus}")
    if report.get("decision_review_state") and report.get("decision_review_state") != "NONE":
        lines.append(f"decision_review_state={report['decision_review_state']}")
    if report.get("simulation_mode") and report.get("simulation_mode") != "LIVE":
        lines.append(f"transition_readiness_state={report['transition_readiness_state']}")
    return "\n".join(lines)


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a deterministic local pipeline health report.")
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Run the targeted test slice and include the result in the report.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not persist runtime/pipeline_health_report.json or dependent runtime files.",
    )
    simulation = parser.add_mutually_exclusive_group()
    simulation.add_argument(
        "--simulate-gsce-clear",
        action="store_true",
        help="Preview health after GSCE_PHASE_LOCK clears without overwriting live runtime output.",
    )
    simulation.add_argument(
        "--simulate-realm-bis-clear",
        action="store_true",
        help="Preview health after REALM_BIS clears without overwriting live runtime output.",
    )
    simulation.add_argument(
        "--simulate-all-clear",
        action="store_true",
        help="Preview health after GSCE_PHASE_LOCK and REALM_BIS both clear without overwriting live runtime output.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    set_source_mode("SYNTHETIC_RUNTIME_FALLBACK")

    report = build_pipeline_health_report(
        include_tests=args.include_tests,
        write_runtime=not args.no_write,
        simulate_gsce_clear=args.simulate_gsce_clear,
        simulate_realm_bis_clear=args.simulate_realm_bis_clear,
        simulate_all_clear=args.simulate_all_clear,
    )
    if args.summary:
        print(format_pipeline_health_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
