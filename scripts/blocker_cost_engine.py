from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        BLOCKER_COST_REPORT_PATH,
        BLOCKER_WEIGHTS_PATH,
        load_current_pipeline_state,
        load_json_file,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        BLOCKER_COST_REPORT_PATH,
        BLOCKER_WEIGHTS_PATH,
        load_current_pipeline_state,
        load_json_file,
        write_json_atomic,
    )


DEFAULT_CONFIG = {
    "weights": {
        "GSCE_PHASE_LOCK": 3.0,
        "REALM_BIS": 4.0,
        "CHAOS_ENTRY": 1.5,
        "WATCHLIST_STAGNATION": 1.0,
    },
    "friction_bands": {
        "low_max": 4.0,
        "medium_max": 9.0,
    },
}


def load_blocker_cost_config(path: Path | None = None) -> dict[str, Any]:
    target = path or BLOCKER_WEIGHTS_PATH
    payload = load_json_file(target, default=DEFAULT_CONFIG)
    if not isinstance(payload, dict):
        return DEFAULT_CONFIG

    weights = payload.get("weights", {})
    if not isinstance(weights, dict):
        weights = {}

    friction_bands = payload.get("friction_bands", {})
    if not isinstance(friction_bands, dict):
        friction_bands = {}

    return {
        "weights": {
            "GSCE_PHASE_LOCK": float(weights.get("GSCE_PHASE_LOCK", DEFAULT_CONFIG["weights"]["GSCE_PHASE_LOCK"])),
            "REALM_BIS": float(weights.get("REALM_BIS", DEFAULT_CONFIG["weights"]["REALM_BIS"])),
            "CHAOS_ENTRY": float(weights.get("CHAOS_ENTRY", DEFAULT_CONFIG["weights"]["CHAOS_ENTRY"])),
            "WATCHLIST_STAGNATION": float(
                weights.get(
                    "WATCHLIST_STAGNATION",
                    DEFAULT_CONFIG["weights"]["WATCHLIST_STAGNATION"],
                )
            ),
        },
        "friction_bands": {
            "low_max": float(friction_bands.get("low_max", DEFAULT_CONFIG["friction_bands"]["low_max"])),
            "medium_max": float(
                friction_bands.get("medium_max", DEFAULT_CONFIG["friction_bands"]["medium_max"])
            ),
        },
    }


def build_blocker_cost_report(
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    config = load_blocker_cost_config(config_path)
    weights = config["weights"]
    status_counts = state["signal_summary"].get("status_counts_above_threshold", {})
    watchlist_count = int(status_counts.get("WATCHLIST", 0))
    chaos_count = int(status_counts.get("EXECUTED_CHAOS", 0))
    active_blockers = state["active_blockers"]

    components = [
        {
            "name": "GSCE_PHASE_LOCK",
            "count": 1 if "GSCE_PHASE_LOCK" in active_blockers else 0,
            "unit_weight": weights["GSCE_PHASE_LOCK"],
            "score": round((1 if "GSCE_PHASE_LOCK" in active_blockers else 0) * weights["GSCE_PHASE_LOCK"], 3),
        },
        {
            "name": "REALM_BIS",
            "count": 1 if "REALM_BIS" in active_blockers else 0,
            "unit_weight": weights["REALM_BIS"],
            "score": round((1 if "REALM_BIS" in active_blockers else 0) * weights["REALM_BIS"], 3),
        },
        {
            "name": "CHAOS_ENTRY",
            "count": chaos_count,
            "unit_weight": weights["CHAOS_ENTRY"],
            "score": round(chaos_count * weights["CHAOS_ENTRY"], 3),
        },
        {
            "name": "WATCHLIST_STAGNATION",
            "count": watchlist_count,
            "unit_weight": weights["WATCHLIST_STAGNATION"],
            "score": round(watchlist_count * weights["WATCHLIST_STAGNATION"], 3),
        },
    ]

    total_score = round(sum(component["score"] for component in components), 3)
    friction_bands = config["friction_bands"]
    if total_score <= friction_bands["low_max"]:
        friction_band = "LOW_FRICTION"
    elif total_score <= friction_bands["medium_max"]:
        friction_band = "MEDIUM_FRICTION"
    else:
        friction_band = "HIGH_FRICTION"

    report = {
        "active_blockers": active_blockers,
        "weights": weights,
        "components": components,
        "total_system_friction_score": total_score,
        "friction_band": friction_band,
    }

    if write_runtime:
        write_json_atomic(BLOCKER_COST_REPORT_PATH, report)

    return report


def format_blocker_cost_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Blocker Cost Engine",
            f"friction_band={report['friction_band']}",
            f"total_system_friction_score={report['total_system_friction_score']}",
            f"active_blockers={', '.join(report['active_blockers']) or 'NONE'}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute blocker cost and total system friction.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Override the blocker weights config path.",
    )
    parser.add_argument("--write-runtime", action="store_true", help="Persist runtime/blocker_cost_report.json.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    report = build_blocker_cost_report(config_path=args.config, write_runtime=args.write_runtime)
    if args.summary:
        print(format_blocker_cost_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
