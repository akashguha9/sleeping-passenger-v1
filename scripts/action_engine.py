from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        ACTION_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        load_current_pipeline_state,
        load_open_positions,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from runtime_common import (
        ACTION_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        load_current_pipeline_state,
        load_open_positions,
        write_json_atomic,
    )
    from signal_conversion_monitor import build_signal_conversion_report

ACTION_ORDER = ["EXIT_NOW", "REDUCE", "HOLD", "MONITOR", "BLOCK_ENTRY"]
OPTIONAL_ACTION_ORDER = ["REVIEW_FOR_ENTRY"]


def _position_is_open(position: dict[str, Any] | None) -> bool:
    if not position:
        return False
    return position.get("state") in {"OPEN", "REDUCED", "EXIT_PENDING"}


def _price_breached_stop(position: dict[str, Any] | None) -> bool:
    if not position or not _position_is_open(position):
        return False
    return float(position["current_price"]) <= float(position["stop_loss"])


def _price_reached_target(position: dict[str, Any] | None) -> bool:
    if not position or not _position_is_open(position):
        return False
    return float(position["current_price"]) >= float(position["take_profit"])


def _select_action(
    ticker: str,
    signal_row: dict[str, Any] | None,
    position: dict[str, Any] | None,
    policy: dict[str, Any],
    active_blockers: list[str],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    signal_state = (signal_row or {}).get("signal_state", "UNKNOWN")
    pre_entry_state = str((signal_row or {}).get("pre_entry_state") or "NONE").upper()
    entry_type = (signal_row or {}).get("entry_type") or (position or {}).get(
        "entry_type", "UNKNOWN"
    )
    entry_type = str(entry_type).upper()
    has_open_position = _position_is_open(position)

    if position and position.get("state") == "EXIT_PENDING":
        reasons.append("Position already marked EXIT_PENDING")
        return "EXIT_NOW", reasons
    if _price_breached_stop(position):
        reasons.append("Current price breached stop_loss")
        return "EXIT_NOW", reasons
    if position and position.get("chaos_flag") is True and "REALM_BIS" in active_blockers:
        reasons.append("Chaos position is live while REALM_BIS is active")
        return "EXIT_NOW", reasons
    if _price_reached_target(position):
        reasons.append("Current price reached take_profit")
        return "REDUCE", reasons
    if (
        has_open_position
        and position
        and position.get("entry_type") == "CHAOS"
        and not policy.get("allow_new_risk", False)
    ):
        reasons.append("Policy is blocked while holding a CHAOS position")
        return "REDUCE", reasons

    # UPGRADE 1: promotable-candidate-aware BLOCK_ENTRY reason.
    # Routes to BLOCK_ENTRY (same as generic watchlist path) but with richer
    # reason text surfacing the promotable classification. No count change.
    if (
        (
            pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
            or any(
                isinstance(tag, dict)
                and str(tag.get("tag_code") or "").upper()
                == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
                and str(tag.get("status") or "ACTIVE").upper() == "ACTIVE"
                for tag in ((signal_row or {}).get("tags") or [])
            )
        )
        and "GSCE_PHASE_LOCK" in active_blockers
    ):
        reasons.append(
            "Promotable clean candidate remains blocked while GSCE_PHASE_LOCK is active"
        )
        return "BLOCK_ENTRY", reasons

    if (
        pre_entry_state == "CLEAN_READY_PENDING_TRIGGER"
        and not policy.get("allow_new_risk", False)
    ):
        reasons.append(
            "Promotable clean candidate advanced to CLEAN_READY_PENDING_TRIGGER after GSCE_PHASE_LOCK cleared; policy still forbids new risk"
        )
        return "MONITOR", reasons

    if (
        pre_entry_state == "CLEAN_ENTRY_ELIGIBLE"
        and policy.get("allow_new_risk", False)
    ):
        reasons.append(
            "Promotable clean candidate is fully gate-cleared and ready for entry review"
        )
        return "REVIEW_FOR_ENTRY", reasons

    if signal_state == "WATCHLIST" and "GSCE_PHASE_LOCK" in active_blockers:
        reasons.append("Signal remains WATCHLIST while GSCE_PHASE_LOCK is active")
        return "BLOCK_ENTRY", reasons
    if entry_type == "CLEAN" and not active_blockers and policy.get("allow_new_risk", False):
        if has_open_position:
            reasons.append("Clean position has no active blockers and policy allows new risk")
            return "HOLD", reasons
        reasons.append("Clean signal has no active blockers but no position is live yet")
        return "MONITOR", reasons
    reasons.append("No hard rule matched; using deterministic MONITOR fallback")
    return "MONITOR", reasons


def build_action_report(
    runtime_state: dict[str, Any] | None = None,
    open_positions_path: Path | None = None,
    write_runtime: bool = False,
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict[str, Any]:
    simulation_requested = any(
        [simulate_gsce_clear, simulate_realm_bis_clear, simulate_all_clear]
    )
    if simulation_requested and write_runtime:
        raise ValueError("Simulated action reports cannot write runtime artifacts.")

    if runtime_state is not None:
        state = runtime_state
    elif simulation_requested:
        state = build_runtime_state_from_scm_report_payload(
            build_signal_conversion_report(
                simulate_gsce_clear=simulate_gsce_clear,
                simulate_realm_bis_clear=simulate_realm_bis_clear,
                simulate_all_clear=simulate_all_clear,
            )
        )
    else:
        state = load_current_pipeline_state()
    open_positions, validation = load_open_positions(open_positions_path)
    positions_by_ticker: dict[str, dict[str, Any]] = {}
    for position in open_positions:
        ticker = str(position["ticker"]).upper()
        positions_by_ticker[ticker] = position
    signals_by_ticker: dict[str, dict[str, Any]] = {}
    for row in state["per_signal_attribution"]:
        signals_by_ticker[row["ticker"]] = row
    policy = state["execution_policy"]
    active_blockers = state["active_blockers"]
    tickers = sorted(set(positions_by_ticker) | set(signals_by_ticker))
    actions = []
    summary_by_action = {action: 0 for action in ACTION_ORDER}
    for ticker in tickers:
        signal_row = signals_by_ticker.get(ticker)
        position = positions_by_ticker.get(ticker)
        action, reasons = _select_action(
            ticker=ticker,
            signal_row=signal_row,
            position=position,
            policy=policy,
            active_blockers=active_blockers,
        )
        if action not in summary_by_action:
            summary_by_action[action] = 0
        summary_by_action[action] += 1
        priority_score = 0.0
        if position is not None:
            priority_score = float(position["priority_score"])
        elif signal_row is not None:
            priority_score = float(signal_row["priority_score"])
        actions.append(
            {
                "ticker": ticker,
                "action": action,
                "reasons": reasons,
                "policy_state": policy["policy_state"],
                "active_blockers": active_blockers,
                "has_open_position": _position_is_open(position),
                "position_state": (position or {}).get("state", "NONE"),
                "entry_type": (position or signal_row or {}).get("entry_type", "UNKNOWN"),
                "signal_state": (signal_row or {}).get("signal_state", "UNKNOWN"),
                "priority_score": round(priority_score, 3),
            }
        )
    actions.sort(key=lambda item: (-item["priority_score"], item["ticker"]))
    report = {
        "policy_state": policy["policy_state"],
        "active_blockers": active_blockers,
        "simulation_context": state.get("simulation_context", {}),
        "summary_by_action": summary_by_action,
        "actions": actions,
        "open_positions_validation": validation,
    }
    if write_runtime:
        write_json_atomic(ACTION_REPORT_PATH, report)
    return report


def format_action_summary(report: dict[str, Any]) -> str:
    action_order = list(ACTION_ORDER)
    for action in OPTIONAL_ACTION_ORDER:
        if report["summary_by_action"].get(action, 0) > 0:
            action_order.append(action)
    parts = [f"{action}={report['summary_by_action'][action]}" for action in action_order]
    return "\n".join(
        [
            "Action Engine",
            f"policy_state={report['policy_state']}",
            f"active_blockers={', '.join(report['active_blockers']) or 'NONE'}",
            f"summary={', '.join(parts)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Derive per-ticker actions from live runtime state."
    )
    parser.add_argument(
        "--open-positions",
        type=Path,
        default=None,
        help="Override the open_positions.json path.",
    )
    parser.add_argument(
        "--write-runtime", action="store_true", help="Persist runtime/action_report.json."
    )
    simulation = parser.add_mutually_exclusive_group()
    simulation.add_argument(
        "--simulate-gsce-clear",
        action="store_true",
        help="Preview actions after GSCE_PHASE_LOCK clears. Does not permit entries or write runtime output.",
    )
    simulation.add_argument(
        "--simulate-realm-bis-clear",
        action="store_true",
        help="Preview actions after REALM_BIS clears. Does not permit entries or write runtime output.",
    )
    simulation.add_argument(
        "--simulate-all-clear",
        action="store_true",
        help="Preview actions after GSCE_PHASE_LOCK and REALM_BIS both clear. Does not permit entries or write runtime output.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument(
        "--summary", action="store_true", help="Emit a compact human-readable summary."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    if (
        any(
            [
                args.simulate_gsce_clear,
                args.simulate_realm_bis_clear,
                args.simulate_all_clear,
            ]
        )
        and args.write_runtime
    ):
        parser.error("simulation flags cannot be combined with --write-runtime")
    report = build_action_report(
        open_positions_path=args.open_positions,
        write_runtime=args.write_runtime,
        simulate_gsce_clear=args.simulate_gsce_clear,
        simulate_realm_bis_clear=args.simulate_realm_bis_clear,
        simulate_all_clear=args.simulate_all_clear,
    )
    if args.summary:
        print(format_action_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
