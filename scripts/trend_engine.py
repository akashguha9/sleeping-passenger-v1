from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        SNAPSHOT_LOG_PATH,
        TREND_REPORT_PATH,
        policy_state_score,
        repo_relative,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        SNAPSHOT_LOG_PATH,
        TREND_REPORT_PATH,
        policy_state_score,
        repo_relative,
        write_json_atomic,
    )


SCENARIO_ORDER = ("LIVE", "GSCE_CLEAR", "REALM_BIS_CLEAR", "ALL_CLEAR")


def load_snapshot_rows(path: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    target = path or SNAPSHOT_LOG_PATH
    if not target.exists():
        return [], [f"Missing snapshot log: {repo_relative(target)}"]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, line in enumerate(target.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"Line {index}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(payload, dict):
            errors.append(f"Line {index}: snapshot row must be an object")
            continue
        rows.append(payload)

    return rows, errors


def linear_regression_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0

    n = float(len(values))
    x_values = list(range(len(values)))
    sum_x = sum(x_values)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(x_values, values))
    sum_x2 = sum(x * x for x in x_values)
    denominator = (n * sum_x2) - (sum_x * sum_x)
    if denominator == 0:
        return 0.0
    numerator = (n * sum_xy) - (sum_x * sum_y)
    return numerator / denominator


def classify_trend(slope: float, epsilon: float, positive_is_good: bool = True) -> str:
    if abs(slope) <= epsilon:
        return "FLAT"
    if positive_is_good:
        return "IMPROVING" if slope > 0 else "DETERIORATING"
    return "DETERIORATING" if slope > 0 else "IMPROVING"


def _numeric_series(rows: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for row in rows:
        value = row.get(key, 0.0)
        if isinstance(value, bool):
            values.append(0.0)
        elif isinstance(value, (int, float)):
            values.append(float(value))
        else:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                values.append(0.0)
    return values


def _string_list_from_row(row: dict[str, Any], key: str) -> list[str]:
    value = row.get(key, [])
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip().upper()
        if text and text not in names:
            names.append(text)
    return names


def _positive_name_streak(rows: list[dict[str, Any]], key: str) -> int:
    streak = 0
    for row in reversed(rows):
        if _string_list_from_row(row, key):
            streak += 1
        else:
            break
    return streak


def _scenario_from_row(row: dict[str, Any]) -> str:
    scenario = str(row.get("scenario") or "LIVE").upper().strip()
    if scenario in SCENARIO_ORDER:
        return scenario
    return "LIVE"


def _rows_for_scenario(rows: list[dict[str, Any]], scenario: str) -> list[dict[str, Any]]:
    target = str(scenario or "LIVE").upper()
    return [row for row in rows if _scenario_from_row(row) == target]


def _name_persistence(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    if not rows:
        return []
    current_names = _string_list_from_row(rows[-1], key)
    persistence = []
    for name in current_names:
        streak = 0
        for row in reversed(rows):
            if name in _string_list_from_row(row, key):
                streak += 1
            else:
                break
        persistence.append({"ticker": name, "consecutive_snapshots": streak})
    persistence.sort(key=lambda item: (-item["consecutive_snapshots"], item["ticker"]))
    return persistence


def _queue_trend_label(rows: list[dict[str, Any]], key: str, prefix: str) -> str:
    if len(rows) < 2:
        return f"{prefix}_FLAT"

    previous = int(rows[-2].get(key, 0) or 0)
    latest = int(rows[-1].get(key, 0) or 0)
    if latest > previous:
        return f"{prefix}_WORSENING"
    if latest < previous:
        return f"{prefix}_IMPROVING"
    return f"{prefix}_FLAT"


def _build_transition_streak(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    current_names = _string_list_from_row(rows[-1], key) if rows else []
    return {
        "current_count": len(current_names),
        "current_names": current_names,
        "persistent_names": _name_persistence(rows, key) if rows else [],
    }


def _build_candidate_streak(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    current_names = _string_list_from_row(rows[-1], key) if rows else []
    return {
        "current_count": len(current_names),
        "current_names": current_names,
        "consecutive_snapshots": _positive_name_streak(rows, key) if rows else 0,
    }


def _derive_transition_pressure_state(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "CLEAR"

    latest = rows[-1]
    blocked_count = int(latest.get("blocked_promotable_candidate_count", 0) or 0)
    clean_ready_count = int(latest.get("clean_ready_pending_trigger_count", 0) or 0)
    clean_entry_eligible_count = int(latest.get("clean_entry_eligible_count", 0) or 0)

    if clean_entry_eligible_count > 0:
        return "READY_BUT_UNTRIGGERED"
    if clean_ready_count > 0:
        return "TRANSITIONING"
    if blocked_count > 0:
        return "STUCK_BLOCKED"
    return "CLEAR"


def _derive_transition_readiness_state(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "BLOCKED"

    latest = rows[-1]
    blocked_count = int(latest.get("blocked_promotable_candidate_count", 0) or 0)
    clean_ready_count = int(latest.get("clean_ready_pending_trigger_count", 0) or 0)
    clean_entry_eligible_count = int(latest.get("clean_entry_eligible_count", 0) or 0)
    allow_new_risk = bool(latest.get("allow_new_risk", False))
    policy_state = str(latest.get("policy_state", "UNKNOWN")).upper()

    if clean_entry_eligible_count > 0:
        if allow_new_risk or policy_state in {"REVIEW_READY", "READY", "UNRESTRICTED"}:
            return "ENTRY_REVIEW_READY"
        return "READY_PENDING_REVIEW"
    if clean_ready_count > 0:
        return "ADVANCING"
    if blocked_count > 0:
        return "BLOCKED"
    return "BLOCKED"


def _derive_packet_transition_state(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "NONE"
    latest = rows[-1]
    transition_count = int(latest.get("transition_review_candidate_count", 0) or 0)
    entry_count = int(latest.get("entry_review_candidate_count", 0) or 0)
    if transition_count > 0 and entry_count > 0:
        return "MIXED"
    if transition_count > 0:
        return "TRANSITION_REVIEW_READY"
    return "NONE"


def _derive_packet_entry_state(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "NONE"
    latest = rows[-1]
    transition_count = int(latest.get("transition_review_candidate_count", 0) or 0)
    entry_count = int(latest.get("entry_review_candidate_count", 0) or 0)
    if transition_count > 0 and entry_count > 0:
        return "MIXED"
    if entry_count > 0:
        return "ENTRY_REVIEW_READY"
    return "NONE"


def _empty_transition_summary(scenario: str) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "snapshot_count": 0,
        "window": {
            "first_timestamp": None,
            "last_timestamp": None,
        },
        "blocked_promotable_transition_streak": {
            "current_count": 0,
            "current_names": [],
            "persistent_names": [],
        },
        "clean_ready_pending_transition_streak": {
            "current_count": 0,
            "current_names": [],
            "persistent_names": [],
        },
        "clean_entry_eligible_transition_streak": {
            "current_count": 0,
            "current_names": [],
            "persistent_names": [],
        },
        "transition_review_candidate_streak": {
            "current_count": 0,
            "current_names": [],
            "consecutive_snapshots": 0,
        },
        "entry_review_candidate_streak": {
            "current_count": 0,
            "current_names": [],
            "consecutive_snapshots": 0,
        },
        "transition_pressure_state": "CLEAR",
        "transition_readiness_state": "BLOCKED",
        "packet_transition_state": "NONE",
        "packet_entry_state": "NONE",
    }


def _build_scenario_transition_summary(
    rows: list[dict[str, Any]],
    scenario: str,
) -> dict[str, Any]:
    if not rows:
        return _empty_transition_summary(scenario)

    return {
        "scenario": scenario,
        "snapshot_count": len(rows),
        "window": {
            "first_timestamp": rows[0].get("timestamp"),
            "last_timestamp": rows[-1].get("timestamp"),
        },
        "blocked_promotable_transition_streak": _build_transition_streak(
            rows,
            "blocked_promotable_candidate_names",
        ),
        "clean_ready_pending_transition_streak": _build_transition_streak(
            rows,
            "clean_ready_pending_trigger_names",
        ),
        "clean_entry_eligible_transition_streak": _build_transition_streak(
            rows,
            "clean_entry_eligible_names",
        ),
        "transition_review_candidate_streak": _build_candidate_streak(
            rows,
            "transition_review_candidate_names",
        ),
        "entry_review_candidate_streak": _build_candidate_streak(
            rows,
            "entry_review_candidate_names",
        ),
        "transition_pressure_state": _derive_transition_pressure_state(rows),
        "transition_readiness_state": _derive_transition_readiness_state(rows),
        "packet_transition_state": _derive_packet_transition_state(rows),
        "packet_entry_state": _derive_packet_entry_state(rows),
    }


def build_trend_report(
    log_path: Path | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
    current_snapshot_row: dict[str, Any] | None = None,
    scenario_scope: str | None = None,
) -> dict[str, Any]:
    all_rows, errors = load_snapshot_rows(log_path)
    if isinstance(current_snapshot_row, dict):
        all_rows = [*all_rows, current_snapshot_row]
    output_target = output_path or TREND_REPORT_PATH
    effective_scenario_scope = str(
        scenario_scope or _scenario_from_row(current_snapshot_row or {})
    ).upper()
    if effective_scenario_scope not in SCENARIO_ORDER:
        effective_scenario_scope = "LIVE"
    rows = _rows_for_scenario(all_rows, effective_scenario_scope)
    scenario_transition_trends = {
        scenario: _build_scenario_transition_summary(
            _rows_for_scenario(all_rows, scenario),
            scenario,
        )
        for scenario in SCENARIO_ORDER
    }

    if not rows:
        report = {
            "source_log": repo_relative(log_path or SNAPSHOT_LOG_PATH),
            "scenario_scope": effective_scenario_scope,
            "available_scenarios": [
                scenario for scenario in SCENARIO_ORDER if _rows_for_scenario(all_rows, scenario)
            ],
            "snapshot_count": 0,
            "total_snapshot_count": len(all_rows),
            "errors": errors,
            "scm_trend": {"latest": 0.0, "slope": 0.0, "label": "FLAT"},
            "chaos_trend": {"latest": 0.0, "slope": 0.0, "label": "FLAT"},
            "watchlist_conversion_trend": {"latest": 0.0, "slope": 0.0, "label": "FLAT"},
            "policy_improvement_trend": {"latest": 0, "slope": 0.0, "label": "FLAT"},
            "promotable_queue_trend_label": "PROMOTABLE_QUEUE_FLAT",
            "blocked_promotable_queue_trend_label": "BLOCKED_PROMOTABLE_QUEUE_FLAT",
            "clean_ready_pending_trigger_trend_label": "CLEAN_READY_PENDING_TRIGGER_FLAT",
            "clean_entry_eligible_trend_label": "CLEAN_ENTRY_ELIGIBLE_FLAT",
            "transition_pressure_state": "CLEAR",
            "transition_readiness_state": "BLOCKED",
            "packet_transition_state": "NONE",
            "packet_entry_state": "NONE",
            "blocked_promotable_persistence": {
                "current_count": 0,
                "current_names": [],
                "persistent_names": [],
            },
            "blocked_promotable_transition_streak": {
                "current_count": 0,
                "current_names": [],
                "persistent_names": [],
            },
            "promotable_watchlist_streak": {
                "current_count": 0,
                "current_names": [],
                "consecutive_snapshots": 0,
            },
            "clean_ready_pending_trigger_persistence": {
                "current_count": 0,
                "current_names": [],
                "persistent_names": [],
            },
            "clean_ready_pending_transition_streak": {
                "current_count": 0,
                "current_names": [],
                "persistent_names": [],
            },
            "clean_entry_eligible_persistence": {
                "current_count": 0,
                "current_names": [],
                "persistent_names": [],
            },
            "clean_entry_eligible_transition_streak": {
                "current_count": 0,
                "current_names": [],
                "persistent_names": [],
            },
            "clean_ready_pending_trigger_streak": {
                "current_count": 0,
                "current_names": [],
                "consecutive_snapshots": 0,
            },
            "fully_cleared_candidate_streak": {
                "current_count": 0,
                "current_names": [],
                "consecutive_snapshots": 0,
            },
            "entry_review_candidate_streak": {
                "current_count": 0,
                "current_names": [],
                "consecutive_snapshots": 0,
            },
            "transition_review_candidate_streak": {
                "current_count": 0,
                "current_names": [],
                "consecutive_snapshots": 0,
            },
            "scenario_transition_trends": scenario_transition_trends,
        }
        if write_runtime:
            write_json_atomic(output_target, report)
        return report

    scm_values = _numeric_series(rows, "scm_rate")
    chaos_values = _numeric_series(rows, "chaos_count")
    watchlist_values = _numeric_series(rows, "watchlist_count")
    signals_values = _numeric_series(rows, "signals_above_threshold")
    watchlist_conversion_values = []
    for watchlist_count, signals in zip(watchlist_values, signals_values):
        denominator = signals if signals > 0 else 1.0
        watchlist_conversion_values.append(1.0 - (watchlist_count / denominator))

    policy_values = [policy_state_score(str(row.get("policy_state", "UNKNOWN"))) for row in rows]

    scm_slope = linear_regression_slope(scm_values)
    chaos_slope = linear_regression_slope(chaos_values)
    watchlist_slope = linear_regression_slope(watchlist_conversion_values)
    policy_slope = linear_regression_slope([float(value) for value in policy_values])

    blocked_names = _string_list_from_row(rows[-1], "blocked_promotable_candidate_names")
    promotable_names = _string_list_from_row(rows[-1], "promotable_watchlist_names")
    clean_ready_names = _string_list_from_row(rows[-1], "clean_ready_pending_trigger_names")
    clean_entry_eligible_names = _string_list_from_row(rows[-1], "clean_entry_eligible_names")

    report = {
        "source_log": repo_relative(log_path or SNAPSHOT_LOG_PATH),
        "scenario_scope": effective_scenario_scope,
        "available_scenarios": [
            scenario for scenario in SCENARIO_ORDER if _rows_for_scenario(all_rows, scenario)
        ],
        "snapshot_count": len(rows),
        "total_snapshot_count": len(all_rows),
        "errors": errors,
        "window": {
            "first_timestamp": rows[0].get("timestamp"),
            "last_timestamp": rows[-1].get("timestamp"),
        },
        "scm_trend": {
            "latest": round(scm_values[-1], 3),
            "slope": round(scm_slope, 6),
            "label": classify_trend(scm_slope, epsilon=0.001, positive_is_good=True),
        },
        "chaos_trend": {
            "latest": round(chaos_values[-1], 3),
            "slope": round(chaos_slope, 6),
            "label": classify_trend(chaos_slope, epsilon=0.05, positive_is_good=False),
        },
        "watchlist_conversion_trend": {
            "latest": round(watchlist_conversion_values[-1], 3),
            "slope": round(watchlist_slope, 6),
            "label": classify_trend(watchlist_slope, epsilon=0.001, positive_is_good=True),
        },
        "policy_improvement_trend": {
            "latest": policy_values[-1],
            "slope": round(policy_slope, 6),
            "label": classify_trend(policy_slope, epsilon=0.01, positive_is_good=True),
        },
        "promotable_queue_trend_label": _queue_trend_label(
            rows,
            "promotable_watchlist_count",
            "PROMOTABLE_QUEUE",
        ),
        "blocked_promotable_queue_trend_label": _queue_trend_label(
            rows,
            "blocked_promotable_candidate_count",
            "BLOCKED_PROMOTABLE_QUEUE",
        ),
        "clean_ready_pending_trigger_trend_label": _queue_trend_label(
            rows,
            "clean_ready_pending_trigger_count",
            "CLEAN_READY_PENDING_TRIGGER",
        ),
        "clean_entry_eligible_trend_label": _queue_trend_label(
            rows,
            "clean_entry_eligible_count",
            "CLEAN_ENTRY_ELIGIBLE",
        ),
        "transition_pressure_state": _derive_transition_pressure_state(rows),
        "transition_readiness_state": _derive_transition_readiness_state(rows),
        "packet_transition_state": _derive_packet_transition_state(rows),
        "packet_entry_state": _derive_packet_entry_state(rows),
        "blocked_promotable_persistence": {
            "current_count": int(rows[-1].get("blocked_promotable_candidate_count", len(blocked_names))),
            "current_names": blocked_names,
            "persistent_names": _name_persistence(rows, "blocked_promotable_candidate_names"),
        },
        "blocked_promotable_transition_streak": _build_transition_streak(
            rows,
            "blocked_promotable_candidate_names",
        ),
        "promotable_watchlist_streak": {
            "current_count": int(rows[-1].get("promotable_watchlist_count", len(promotable_names))),
            "current_names": promotable_names,
            "consecutive_snapshots": _positive_name_streak(rows, "promotable_watchlist_names"),
        },
        "clean_ready_pending_trigger_persistence": {
            "current_count": int(rows[-1].get("clean_ready_pending_trigger_count", len(clean_ready_names))),
            "current_names": clean_ready_names,
            "persistent_names": _name_persistence(rows, "clean_ready_pending_trigger_names"),
        },
        "clean_ready_pending_transition_streak": _build_transition_streak(
            rows,
            "clean_ready_pending_trigger_names",
        ),
        "clean_entry_eligible_persistence": {
            "current_count": int(rows[-1].get("clean_entry_eligible_count", len(clean_entry_eligible_names))),
            "current_names": clean_entry_eligible_names,
            "persistent_names": _name_persistence(rows, "clean_entry_eligible_names"),
        },
        "clean_entry_eligible_transition_streak": _build_transition_streak(
            rows,
            "clean_entry_eligible_names",
        ),
        "clean_ready_pending_trigger_streak": {
            "current_count": int(rows[-1].get("clean_ready_pending_trigger_count", len(clean_ready_names))),
            "current_names": clean_ready_names,
            "consecutive_snapshots": _positive_name_streak(rows, "clean_ready_pending_trigger_names"),
        },
        "fully_cleared_candidate_streak": {
            "current_count": int(rows[-1].get("clean_entry_eligible_count", len(clean_entry_eligible_names))),
            "current_names": clean_entry_eligible_names,
            "consecutive_snapshots": _positive_name_streak(rows, "clean_entry_eligible_names"),
        },
        "entry_review_candidate_streak": _build_candidate_streak(
            rows,
            "entry_review_candidate_names",
        ),
        "transition_review_candidate_streak": _build_candidate_streak(
            rows,
            "transition_review_candidate_names",
        ),
        "scenario_transition_trends": scenario_transition_trends,
    }

    if write_runtime:
        write_json_atomic(output_target, report)

    return report


def format_trend_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Trend Engine",
            f"snapshot_count={report['snapshot_count']}",
            f"scm_trend={report['scm_trend']['label']}",
            f"chaos_trend={report['chaos_trend']['label']}",
            f"watchlist_conversion_trend={report['watchlist_conversion_trend']['label']}",
            f"policy_improvement_trend={report['policy_improvement_trend']['label']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute deterministic trend diagnostics from snapshot memory.")
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Override the system snapshot JSONL path.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="Override the runtime trend report path.",
    )
    parser.add_argument("--no-write", action="store_true", help="Do not write runtime/trend_report.json.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    report = build_trend_report(
        log_path=args.log_path,
        output_path=args.output_path,
        write_runtime=not args.no_write,
    )
    if args.summary:
        print(format_trend_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
