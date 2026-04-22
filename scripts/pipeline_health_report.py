from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.action_engine import build_action_report
    from scripts.blocker_cost_engine import build_blocker_cost_report
    from scripts.snapshot_logger import build_snapshot_row
    from scripts.runtime_common import (
        HEALTH_REPORT_PATH,
        SNAPSHOT_LOG_PATH,
        build_runtime_state_from_scm_report_payload,
        load_open_positions,
        normalize_active_blockers,
        normalize_per_signal_rows,
        persist_current_runtime_state,
        write_json_atomic,
    )
    from scripts.signal_refinery import build_signal_refinery_report
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.trend_engine import build_trend_report
except ModuleNotFoundError:
    from action_engine import build_action_report
    from blocker_cost_engine import build_blocker_cost_report
    from snapshot_logger import build_snapshot_row
    from runtime_common import (
        HEALTH_REPORT_PATH,
        SNAPSHOT_LOG_PATH,
        build_runtime_state_from_scm_report_payload,
        load_open_positions,
        normalize_active_blockers,
        normalize_per_signal_rows,
        persist_current_runtime_state,
        write_json_atomic,
    )
    from signal_refinery import build_signal_refinery_report
    from signal_conversion_monitor import build_signal_conversion_report
    from trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]
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


def derive_operator_state(
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
            scenario_action_report = build_action_report(
                runtime_state=scenario_state,
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
    runtime_state: dict[str, Any] | None = None,
    action_report: dict[str, Any] | None = None,
    friction_report: dict[str, Any] | None = None,
    trend_report: dict[str, Any] | None = None,
    signal_refinery_report: dict[str, Any] | None = None,
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
        write_runtime=effective_write_runtime,
        current_snapshot_row=current_snapshot_row,
    )
    signal_refinery_report = signal_refinery_report or build_signal_refinery_report(
        runtime_state=state,
        trend_report=trend_report,
        open_positions_path=open_positions_path,
        write_runtime=effective_write_runtime,
    )
    state["signal_refinery"] = signal_refinery_report
    action_report = action_report or build_action_report(
        runtime_state=state,
        open_positions_path=open_positions_path,
        signal_refinery_report=signal_refinery_report,
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
    operator_state = derive_operator_state(
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

    report = {
        "health_generated_at": _health_timestamp(),
        "latest_snapshot_timestamp": resolved_latest_snapshot_timestamp,
        "latest_trend_timestamp_or_window_end": latest_trend_timestamp_or_window_end,
        "simulation_context": simulation_context,
        "simulation_mode": simulation_context.get("scenario", "LIVE"),
        "simulation_writes_runtime": effective_write_runtime,
        "queue_sync_state": queue_sync_state,
        "system_readiness_state": system_readiness_state,
        "can_deploy_capital": can_deploy_capital,
        "where_am_i_leaking_performance": where_am_i_leaking_performance,
        "what_should_i_do_next": what_should_i_do_next,
        "scm": state["scm_review"],
        "policy": operator_policy,
        "friction": friction_report,
        "trends": trend_report,
        "signal_refinery": signal_refinery_report,
        "watchlist_intelligence": watchlist_intelligence,
        "blocked_promotable_candidate_queue": blocked_promotable_candidate_queue,
        "queue_pressure_state": queue_pressure_state,
        "blockage_severity": blockage_severity,
        "operator_state": operator_state,
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
        "note": "Health report integrates authoritative SCM state, signal refinery gating, action policy, blocker cost, memory trends, and open positions validation.",
    }

    if effective_write_runtime:
        write_json_atomic(HEALTH_REPORT_PATH, report)

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
            f"git_clean={str(git_clean).lower() if isinstance(git_clean, bool) else git_clean}",
            f"tests_invoked={str(tests_invoked).lower() if isinstance(tests_invoked, bool) else tests_invoked}",
            f"tests_passed={str(tests_passed).lower() if isinstance(tests_passed, bool) else tests_passed}",
            f"system_readiness_state={report['system_readiness_state']}",
            f"can_deploy_capital={str(report['can_deploy_capital']).lower()}",
            f"scm_state={report['scm']['scm_state']}",
            f"policy_state={report['policy']['policy_state']}",
            f"friction_band={report['friction']['friction_band']}",
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
    entry_review_names = report.get("packet_summary", {}).get("entry_review_candidate_names", [])
    transition_review_names = report.get("packet_summary", {}).get(
        "transition_review_candidate_names",
        [],
    )
    if entry_review_names:
        lines.append(f"entry_review_candidates={', '.join(entry_review_names)}")
    if transition_review_names:
        lines.append(f"transition_review_candidates={', '.join(transition_review_names)}")
    if report.get("decision_review_state") and report.get("decision_review_state") != "NONE":
        lines.append(f"decision_review_state={report['decision_review_state']}")
    if report.get("simulation_mode") and report.get("simulation_mode") != "LIVE":
        lines.append(f"transition_readiness_state={report['transition_readiness_state']}")
    return "\n".join(lines)


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a deterministic closed-loop pipeline health report.")
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
