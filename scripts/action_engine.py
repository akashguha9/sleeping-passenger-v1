from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.execution_governance import (
        assess_action_governance,
        summarize_action_governance,
    )
    from scripts.runtime_common import (
        ACTION_REPORT_PATH,
        COMPLEXITY_LADDER_CONTROLLER_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        load_current_pipeline_state,
        load_json_file,
        load_open_positions,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts import tag_engine as tags
except ModuleNotFoundError:
    from execution_governance import assess_action_governance, summarize_action_governance
    from runtime_common import (
        ACTION_REPORT_PATH,
        COMPLEXITY_LADDER_CONTROLLER_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        load_current_pipeline_state,
        load_json_file,
        load_open_positions,
        write_json_atomic,
    )
    from signal_conversion_monitor import build_signal_conversion_report
    import tag_engine as tags

# Canonical action vocabulary sourced from tag_engine (values byte-identical).
ACTION_ORDER = [tags.EXIT_NOW, tags.REDUCE, tags.HOLD, tags.MONITOR, tags.BLOCK_ENTRY]
OPTIONAL_ACTION_ORDER = [tags.REVIEW_FOR_ENTRY]


def _load_optional_runtime_artifact(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = load_json_file(path, default={}) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _normalize_surface_profile(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"trainer", "utility", "jet"}:
        return text
    return "trainer"


def _build_experience_mode_advisory(
    *,
    experience_mode_report: dict[str, Any] | None,
    complexity_ladder_controller: dict[str, Any] | None,
) -> dict[str, Any] | None:
    experience = experience_mode_report if isinstance(experience_mode_report, dict) else {}
    controller = (
        complexity_ladder_controller if isinstance(complexity_ladder_controller, dict) else {}
    )
    if not experience and not controller:
        return None

    utility_layer = experience.get("utility_resilience_layer", {})
    trainer_metadata = experience.get("trainer_mode_metadata", {})
    readiness_ladder = experience.get("readiness_ladder", {})

    degraded_from_experience = utility_layer.get("degraded_mode_required")
    degraded_from_controller = controller.get("degraded_mode_annotations_required")
    confidence_downgrade = utility_layer.get("confidence_downgrade_required")
    surface_profile = _normalize_surface_profile(
        controller.get("operator_surface_recommendation")
        or trainer_metadata.get("recommended_surface_profile")
        or readiness_ladder.get("recommended_surface_profile")
    )

    advisory: dict[str, Any] = {
        "recommendation_surface_profile": surface_profile,
    }
    if degraded_from_experience is not None:
        advisory["degraded_mode_required"] = bool(degraded_from_experience)
    elif degraded_from_controller is not None:
        advisory["degraded_mode_required"] = bool(degraded_from_controller)
    if confidence_downgrade is not None:
        advisory["confidence_downgrade_required"] = bool(confidence_downgrade)

    controller_reasoning = controller.get("controller_reasoning", [])
    if not isinstance(controller_reasoning, list):
        controller_reasoning = []

    reason_parts: list[str] = [f"surface={surface_profile}"]
    if "seeded_mode_forces_trainer_surface" in controller_reasoning:
        reason_parts.append("seeded_trainer_surface")
    if "unresolved_gap_breach_forces_no_premium" in controller_reasoning:
        reason_parts.append("premium_blocked_by_gaps")
    elif "jet_readiness_below_threshold" in controller_reasoning:
        reason_parts.append("premium_not_ready")
    if advisory.get("degraded_mode_required") is True:
        reason_parts.append("degraded_mode_required")
    if advisory.get("confidence_downgrade_required") is True:
        reason_parts.append("confidence_downgraded")

    advisory["advisory_reason"] = "; ".join(reason_parts)
    return advisory


def _default_seeded_experience_mode_advisory() -> dict[str, Any]:
    return {
        "recommendation_surface_profile": "trainer",
        "degraded_mode_required": True,
        "confidence_downgrade_required": True,
        "advisory_reason": (
            "surface=trainer; seeded_trainer_surface; premium_blocked_by_gaps; "
            "degraded_mode_required; confidence_downgraded"
        ),
    }


def _lookup_launch_row(
    ticker: str,
    signal_refinery_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(signal_refinery_report, dict):
        return None
    launch_control = signal_refinery_report.get("launch_control", {})
    rows = launch_control.get("launch_rows", []) if isinstance(launch_control, dict) else []
    if not isinstance(rows, list):
        return None
    target = str(ticker or "").upper()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").upper() == target:
            return row
    return None


def _lookup_validation_row(
    ticker: str,
    signal_refinery_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(signal_refinery_report, dict):
        return None
    validation_engine = signal_refinery_report.get("validation_engine", {})
    rows = validation_engine.get("signals", []) if isinstance(validation_engine, dict) else []
    if not isinstance(rows, list):
        return None
    target = str(ticker or "").upper()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").upper() == target:
            return row
    return None


def _lookup_perception_row(
    ticker: str,
    perception_control_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(perception_control_report, dict):
        return None
    rows = perception_control_report.get("signals", [])
    if not isinstance(rows, list):
        return None
    target = str(ticker or "").upper()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").upper() == target:
            return row
    return None


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
    signal_refinery_report: dict[str, Any] | None = None,
    perception_row: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    signal_state = (signal_row or {}).get("signal_state", "UNKNOWN")
    pre_entry_state = str((signal_row or {}).get("pre_entry_state") or tags.NONE).upper()
    entry_type = (signal_row or {}).get("entry_type") or (position or {}).get(
        "entry_type", "UNKNOWN"
    )
    entry_type = str(entry_type).upper()
    has_open_position = _position_is_open(position)

    if position and position.get("state") == "EXIT_PENDING":
        reasons.append("Position already marked EXIT_PENDING")
        return tags.EXIT_NOW, reasons
    if _price_breached_stop(position):
        reasons.append("Current price breached stop_loss")
        return tags.EXIT_NOW, reasons
    if position and position.get("chaos_flag") is True and "REALM_BIS" in active_blockers:
        reasons.append("Chaos position is live while REALM_BIS is active")
        return tags.EXIT_NOW, reasons
    if _price_reached_target(position):
        reasons.append("Current price reached take_profit")
        return tags.REDUCE, reasons
    if (
        has_open_position
        and position
        and position.get("entry_type") == "CHAOS"
        and not policy.get("allow_new_risk", False)
    ):
        reasons.append("Policy is blocked while holding a CHAOS position")
        return tags.REDUCE, reasons

    # UPGRADE 1: promotable-candidate-aware BLOCK_ENTRY reason.
    # Routes to BLOCK_ENTRY (same as generic watchlist path) but with richer
    # reason text surfacing the promotable classification. No count change.
    if (
        pre_entry_state == tags.BLOCKED_PROMOTABLE_CLEAN_CANDIDATE
        and "GSCE_PHASE_LOCK" in active_blockers
    ):
        reasons.append(
            "Promotable clean candidate remains blocked while GSCE_PHASE_LOCK is active"
        )
        return tags.BLOCK_ENTRY, reasons

    if (
        pre_entry_state == tags.CLEAN_READY_PENDING_TRIGGER
        and not policy.get("allow_new_risk", False)
    ):
        reasons.append(
            "Promotable clean candidate advanced to CLEAN_READY_PENDING_TRIGGER after GSCE_PHASE_LOCK cleared; policy still forbids new risk"
        )
        return tags.MONITOR, reasons

    if (
        pre_entry_state == tags.CLEAN_ENTRY_ELIGIBLE
        and policy.get("allow_new_risk", False)
    ):
        if perception_row is not None and not bool(perception_row.get("gravity_pass", False)):
            reasons.append(
                "Perception control high-constraint evaluation did not survive review promotion"
            )
            return tags.MONITOR, reasons
        launch_row = _lookup_launch_row(ticker, signal_refinery_report)
        launch_state = str((launch_row or {}).get("launch_state") or "").upper()
        if launch_state == "BLOCKED_CROWDING":
            reasons.append("Launch control blocked review because repricing headroom is too low")
            return tags.BLOCK_ENTRY, reasons
        if launch_state in {"BLOCKED_VALIDATION", "BLOCKED_POLICY", "BLOCKED_THERMAL"}:
            reasons.append(f"Launch control blocked review: {launch_state}")
            return tags.MONITOR, reasons
        reasons.append(
            "Promotable clean candidate is fully gate-cleared and ready for entry review"
        )
        return tags.REVIEW_FOR_ENTRY, reasons

    if signal_state == "WATCHLIST" and "GSCE_PHASE_LOCK" in active_blockers:
        reasons.append("Signal remains WATCHLIST while GSCE_PHASE_LOCK is active")
        return tags.BLOCK_ENTRY, reasons
    if entry_type == "CLEAN" and not active_blockers and policy.get("allow_new_risk", False):
        if has_open_position:
            reasons.append("Clean position has no active blockers and policy allows new risk")
            return tags.HOLD, reasons
        reasons.append("Clean signal has no active blockers but no position is live yet")
        return tags.MONITOR, reasons
    reasons.append("No hard rule matched; using deterministic MONITOR fallback")
    return tags.MONITOR, reasons


def _build_external_observation_context(
    state: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach advisory external-observation context to the action report.

    Observation data is reality context only. It cannot create new actions,
    override policy, or change rankings. We only surface:
      * whether the external observation lane attached for this run
      * how many observations covered action tickers
      * per-quality counts so a reader can see if external data was
        actually usable (VALID_EXTERNAL) vs degraded (STALE / ERROR)
    """
    summary = state.get("external_observation_summary") if isinstance(state, dict) else None
    if not isinstance(summary, dict):
        summary = {}
    active = bool(summary.get("external_observation_active"))
    if not active:
        return {
            "external_observation_attached": False,
            "external_observation_context_count": 0,
            "external_observation_symbols": [],
            "external_observation_quality_summary": {},
            "note": (
                "Advisory external-observation context not attached to this run; "
                "action rankings are derived from seeded runtime state only."
            ),
        }

    obs_symbols = [str(s).strip().upper() for s in summary.get("external_observation_symbols", []) if str(s).strip()]
    action_tickers = {str(a.get("ticker") or "").strip().upper() for a in actions}
    covered = sorted(obs_symbols_set & action_tickers) if (obs_symbols_set := set(obs_symbols)) else []
    return {
        "external_observation_attached": True,
        "external_observation_context_count": len(covered),
        "external_observation_symbols": covered,
        "external_observation_provider": summary.get("external_observation_provider"),
        "external_observation_quality_summary": {
            "valid_count": int(summary.get("external_observation_valid_count", 0) or 0),
            "error_count": int(summary.get("external_observation_error_count", 0) or 0),
            "total_count": int(summary.get("external_observation_count", 0) or 0),
        },
        "note": (
            "Advisory reality context only. External observations do not "
            "create trade signals or alter action rankings."
        ),
    }


def build_action_report(
    runtime_state: dict[str, Any] | None = None,
    open_positions_path: Path | None = None,
    experience_mode_report_path: Path | None = None,
    complexity_ladder_controller_path: Path | None = None,
    signal_refinery_report: dict[str, Any] | None = None,
    perception_control_report: dict[str, Any] | None = None,
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
    signal_refinery_report = signal_refinery_report or state.get("signal_refinery")
    simulation_context = state.get("simulation_context", {})
    use_default_advisory_artifacts = runtime_state is None and not simulation_requested
    effective_experience_mode_path = (
        experience_mode_report_path
        if experience_mode_report_path is not None
        else (
            EXPERIENCE_MODE_REPORT_PATH if use_default_advisory_artifacts else None
        )
    )
    effective_complexity_ladder_path = (
        complexity_ladder_controller_path
        if complexity_ladder_controller_path is not None
        else (
            COMPLEXITY_LADDER_CONTROLLER_PATH if use_default_advisory_artifacts else None
        )
    )
    perception_control_report = perception_control_report or state.get("perception_control")
    experience_mode_advisory = _build_experience_mode_advisory(
        experience_mode_report=_load_optional_runtime_artifact(
            effective_experience_mode_path
        ),
        complexity_ladder_controller=_load_optional_runtime_artifact(
            effective_complexity_ladder_path
        ),
    )
    if experience_mode_advisory is None and use_default_advisory_artifacts:
        experience_mode_advisory = _default_seeded_experience_mode_advisory()
    # Close-the-Loop sprint (2026-07-04), forensic audit SP-001: the default
    # position source is the CANONICAL holdings truth gate, never the demoted
    # moltbook ledger.  An explicit open_positions_path (tests, drills) is
    # honored but stamped, so the report always says what it watched.
    holdings_truth: dict[str, Any]
    position_risk_alerts: list[dict[str, Any]] = []
    if open_positions_path is None:
        from scripts.holdings_truth_gate import (
            load_holdings_truth_gate,
            to_action_engine_position,
        )

        gate = load_holdings_truth_gate()
        open_positions = [
            to_action_engine_position(p) for p in gate["positions"]
        ]
        for blocked in gate["blocked_positions"]:
            position_risk_alerts.append(
                {
                    "ticker": blocked["ticker"],
                    "risk_monitoring": blocked["risk_monitoring"],
                    "blocks": blocked["risk_monitoring_blocks"],
                    "leverage": blocked["leverage"],
                    "severity": (
                        "CRITICAL"
                        if blocked["leverage"] > 1
                        and blocked["stop_loss"] is None
                        else "HIGH"
                    ),
                    "operator_action_required": (
                        "record stop_loss (and refresh holdings truth) before "
                        "this position can be risk-monitored"
                    ),
                }
            )
        validation = {
            "path": gate["path"],
            "file_exists": gate["status"] != "HOLDINGS_TRUTH_MISSING",
            "valid": gate["status"] == "OK",
            "position_count": len(open_positions),
            "states": {"OPEN": len(open_positions)},
            "errors": list(gate["issues"]),
        }
        holdings_truth = {
            "source": gate["source"],
            "status": gate["status"],
            "run_date": gate["run_date"],
            "age_days": gate["age_days"],
            "canonical_holding_count": gate["canonical_holding_count"],
            "monitorable_position_count": gate["monitorable_position_count"],
            "missing_stop_count": gate["missing_stop_count"],
            "leveraged_without_stop_count": gate["leveraged_without_stop_count"],
            "risk_engine_ready": gate["risk_engine_ready"],
        }
    else:
        open_positions, validation = load_open_positions(open_positions_path)
        holdings_truth = {
            "source": "EXPLICIT_PATH",
            "status": "EXPLICIT_PATH",
            "path": str(open_positions_path),
            "risk_engine_ready": False,
        }
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
            signal_refinery_report=signal_refinery_report,
            perception_row=_lookup_perception_row(
                ticker=ticker,
                perception_control_report=perception_control_report,
            ),
        )
        if action not in summary_by_action:
            summary_by_action[action] = 0
        summary_by_action[action] += 1
        priority_score = 0.0
        if position is not None:
            priority_score = float(position["priority_score"])
        elif signal_row is not None:
            priority_score = float(signal_row["priority_score"])
        action_row = {
            "ticker": ticker,
            "signal_id": (signal_row or {}).get("signal_id", ""),
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
        perception_row = _lookup_perception_row(
            ticker=ticker,
            perception_control_report=perception_control_report,
        )
        if perception_row is not None:
            action_row["perception_control_state"] = perception_row.get(
                "perception_control_state",
                "UNSCORED",
            )
            action_row["action_visibility_priority"] = perception_row.get(
                "action_visibility_priority",
                round(priority_score, 3),
            )
            action_row["signal_lux"] = perception_row.get("signal_lux")
            action_row["gravity_pass"] = perception_row.get("gravity_pass")
            action_row["exposure_timing_state"] = perception_row.get(
                "exposure_timing_state",
                "UNKNOWN",
            )
        action_row["execution_governance"] = assess_action_governance(
            action_row=action_row,
            signal_row=signal_row,
            position_row=position,
            signal_refinery_row=_lookup_validation_row(
                ticker=ticker,
                signal_refinery_report=signal_refinery_report,
            ),
            runtime_state=state,
        )
        if experience_mode_advisory is not None:
            action_row["experience_mode_advisory"] = dict(experience_mode_advisory)
        actions.append(action_row)
    actions.sort(key=lambda item: (-item["priority_score"], item["ticker"]))
    external_observation_context = _build_external_observation_context(state, actions)
    report = {
        "policy_state": policy["policy_state"],
        "active_blockers": active_blockers,
        "simulation_context": simulation_context,
        "summary_by_action": summary_by_action,
        "execution_governance_summary": summarize_action_governance(actions),
        "actions": actions,
        "open_positions_validation": validation,
        "position_source": holdings_truth,
        "position_risk_alerts": position_risk_alerts,
        "external_observation_context": external_observation_context,
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
