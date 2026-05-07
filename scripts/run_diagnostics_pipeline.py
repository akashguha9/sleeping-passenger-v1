from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.attention_proxy_engine import build_attention_proxy_report
    from scripts.action_engine import build_action_report
    from scripts.blocker_cost_engine import build_blocker_cost_report
    from scripts.external_data_runtime_sync import (
        apply_external_observation_report,
        build_external_data_runtime_report,
        write_external_data_runtime_report,
    )
    from scripts.external_observation_lane import (
        ProviderFetchFn,
        apply_observation_summary_to_runtime_state,
        fetch_external_observations,
        observations_to_scm_candidates,
        safe_write_external_observation_report,
    )
    from scripts.paper_execution import build_paper_candidate_decision_rows
    from scripts.pipeline_health_report import (
        build_pipeline_health_report,
        build_runtime_state_from_scm_report,
        format_pipeline_health_summary,
    )
    from scripts.integrity_diagnostics import build_temporal_integrity_summary
    from scripts.moltbook_feedback import build_moltbook_feedback_report
    from scripts.perception_control import build_perception_control_report
    from scripts.latent_signal_release_bull_layer import (
        build_latent_signal_release_bull_report,
    )
    from scripts.chess_archetype_decision_layer import write_chess_archetype_report
    from scripts.contextual_interpretation import (
        build_contextual_interpretation_summary,
    )
    from scripts.extreme_state import build_extreme_state_report
    from scripts.hedge_trade_entry_playbook import build_hedge_trade_entry_report
    from scripts.signal_surface_engine import build_signal_surface_report
    from scripts.tennis_archetype_execution import (
        load_runtime_compatible_signals,
        write_tennis_archetype_report,
    )
    from scripts.runtime_common import (
        SNAPSHOT_LOG_PATH,
        persist_current_runtime_state,
        resolve_bridge_mode,
        resolve_source_mode,
        set_source_mode,
        utc_timestamp,
    )
    from scripts.structural_admission_layer import build_structural_admission_report
    from scripts.signal_refinery import build_signal_refinery_report
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.snapshot_logger import build_snapshot_row, log_snapshot
    from scripts.trend_engine import build_trend_report
except ModuleNotFoundError:
    from attention_proxy_engine import build_attention_proxy_report
    from action_engine import build_action_report
    from blocker_cost_engine import build_blocker_cost_report
    from external_data_runtime_sync import (
        apply_external_observation_report,
        build_external_data_runtime_report,
        write_external_data_runtime_report,
    )
    from external_observation_lane import (  # type: ignore[no-redef]
        ProviderFetchFn,
        apply_observation_summary_to_runtime_state,
        fetch_external_observations,
        observations_to_scm_candidates,
        safe_write_external_observation_report,
    )
    from paper_execution import build_paper_candidate_decision_rows
    from moltbook_feedback import build_moltbook_feedback_report
    from pipeline_health_report import (
        build_pipeline_health_report,
        build_runtime_state_from_scm_report,
        format_pipeline_health_summary,
    )
    from integrity_diagnostics import build_temporal_integrity_summary
    from perception_control import build_perception_control_report
    from latent_signal_release_bull_layer import (  # type: ignore[no-redef]
        build_latent_signal_release_bull_report,
    )
    from chess_archetype_decision_layer import (  # type: ignore[no-redef]
        write_chess_archetype_report,
    )
    from contextual_interpretation import (  # type: ignore[no-redef]
        build_contextual_interpretation_summary,
    )
    from extreme_state import build_extreme_state_report  # type: ignore[no-redef]
    from hedge_trade_entry_playbook import (  # type: ignore[no-redef]
        build_hedge_trade_entry_report,
    )
    from signal_surface_engine import build_signal_surface_report  # type: ignore[no-redef]
    from tennis_archetype_execution import (  # type: ignore[no-redef]
        load_runtime_compatible_signals,
        write_tennis_archetype_report,
    )
    from runtime_common import (
        SNAPSHOT_LOG_PATH,
        persist_current_runtime_state,
        resolve_bridge_mode,
        resolve_source_mode,
        set_source_mode,
        utc_timestamp,
    )
    from structural_admission_layer import build_structural_admission_report
    from signal_refinery import build_signal_refinery_report
    from signal_conversion_monitor import build_signal_conversion_report
    from snapshot_logger import build_snapshot_row, log_snapshot
    from trend_engine import build_trend_report


def run_diagnostics_pipeline(
    include_tests: bool = False,
    include_external_data: bool = False,
    include_external_observations: bool = False,
    include_contextual_interpretation: bool = False,
    contextual_interpretation_summary: bool = False,
    interpretation_drift_threshold: float | None = None,
    render_operator_mode: str = "validate",
    bridge_external_candidates: bool = True,
    external_observation_symbols: list[str] | None = None,
    external_observation_provider: str = "yahoo",
    external_observation_provider_fn: ProviderFetchFn | None = None,
    write_runtime: bool = True,
    write_snapshot: bool = False,
    snapshot_log_path: Path | None = None,
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict:
    simulation_requested = any(
        [simulate_gsce_clear, simulate_realm_bis_clear, simulate_all_clear]
    )
    effective_write_runtime = write_runtime and not simulation_requested
    external_data_report = None
    if include_external_data and effective_write_runtime:
        external_data_report = write_external_data_runtime_report(
            runtime_state={"source": "external_data_bootstrap"}
        )
        # Resolve source_mode after any external ETIL input has been refreshed.
        resolve_source_mode()
    else:
        # Default diagnostics runs stay synthetic unless this run explicitly
        # requested external ETIL refresh.
        set_source_mode("SYNTHETIC_RUNTIME_FALLBACK")

    scm_report = build_signal_conversion_report(
        simulate_gsce_clear=simulate_gsce_clear,
        simulate_realm_bis_clear=simulate_realm_bis_clear,
        simulate_all_clear=simulate_all_clear,
    )
    runtime_state = build_runtime_state_from_scm_report(scm_report)
    if include_external_data:
        if external_data_report is None:
            external_data_report = build_external_data_runtime_report(runtime_state=runtime_state)
        runtime_state = apply_external_observation_report(runtime_state, external_data_report)
    scenario = str(runtime_state.get("simulation_context", {}).get("scenario") or "LIVE").upper()
    resolved_snapshot_log_path = snapshot_log_path or SNAPSHOT_LOG_PATH

    if effective_write_runtime:
        persist_current_runtime_state(runtime_state)

    pre_snapshot_trend_report = build_trend_report(
        log_path=resolved_snapshot_log_path,
        write_runtime=False,
        scenario_scope=scenario,
    )
    attention_proxy_report = build_attention_proxy_report(
        runtime_state=runtime_state,
        trend_report=pre_snapshot_trend_report,
        write_runtime=False,
    )
    runtime_state["attention_proxy"] = attention_proxy_report
    signal_refinery_report = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report=pre_snapshot_trend_report,
        write_runtime=False,
    )
    runtime_state["signal_refinery"] = signal_refinery_report
    perception_control_report = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        trend_report=pre_snapshot_trend_report,
        write_runtime=False,
    )
    runtime_state["perception_control"] = perception_control_report
    friction_report = build_blocker_cost_report(
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    latest_snapshot_timestamp = None
    current_snapshot_row = None
    should_write_snapshot = effective_write_runtime or write_snapshot
    if should_write_snapshot:
        snapshot_row = log_snapshot(path=resolved_snapshot_log_path, runtime_state=runtime_state)
        latest_snapshot_timestamp = snapshot_row.get("timestamp")
    else:
        current_snapshot_row = build_snapshot_row(
            runtime_state=runtime_state,
            snapshot_path=resolved_snapshot_log_path,
        )

    trend_report = build_trend_report(
        log_path=resolved_snapshot_log_path,
        write_runtime=effective_write_runtime,
        current_snapshot_row=current_snapshot_row,
        scenario_scope=scenario,
    )
    final_attention_proxy_report = build_attention_proxy_report(
        runtime_state=runtime_state,
        trend_report=trend_report,
        write_runtime=effective_write_runtime,
    )
    runtime_state["attention_proxy"] = final_attention_proxy_report
    final_signal_refinery_report = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report=trend_report,
        write_runtime=effective_write_runtime,
    )
    runtime_state["signal_refinery"] = final_signal_refinery_report
    final_perception_control_report = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=final_signal_refinery_report,
        trend_report=trend_report,
        write_runtime=effective_write_runtime,
    )
    runtime_state["perception_control"] = final_perception_control_report
    moltbook_feedback_report = build_moltbook_feedback_report(
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    runtime_state["moltbook_feedback"] = moltbook_feedback_report
    runtime_state["external_observation_requested"] = include_external_observations
    runtime_state["external_candidate_bridge_enabled"] = bool(bridge_external_candidates)
    runtime_state["external_candidate_count"] = 0
    runtime_state["external_paper_candidate_count"] = 0
    runtime_state["external_candidate_rows"] = []
    runtime_state["external_paper_candidate_rows"] = []
    runtime_state["decision_timestamp"] = utc_timestamp()

    external_observation_report: dict | None = None
    if include_external_observations:
        candidate_symbols: list[str] = []
        if external_observation_symbols:
            candidate_symbols = [str(s) for s in external_observation_symbols if str(s).strip()]
        else:
            # Fall back to the tickers already visible inside runtime state.
            per_signal_rows = runtime_state.get("per_signal_attribution") or []
            if isinstance(per_signal_rows, list):
                seen: set[str] = set()
                for row in per_signal_rows:
                    if not isinstance(row, dict):
                        continue
                    ticker = str(row.get("ticker") or "").strip().upper()
                    if ticker and ticker not in seen:
                        seen.add(ticker)
                        candidate_symbols.append(ticker)
        observations = fetch_external_observations(
            candidate_symbols,
            provider=external_observation_provider,
            provider_fn=external_observation_provider_fn,
        )
        external_observation_report = safe_write_external_observation_report(
            observations,
            provider=external_observation_provider,
            write=effective_write_runtime,
        )
        # Flip runtime state so build_truth_context / classify_operating_mode
        # pick up the active external lane (turns truth_origin=external,
        # operating_mode=hybrid). Only does anything when the report is
        # genuinely active — seeded fallback stays untouched otherwise.
        runtime_state = apply_observation_summary_to_runtime_state(
            runtime_state, external_observation_report
        )
        temporal_rejections: list[str] = []
        external_candidates = (
            observations_to_scm_candidates(
                observations,
                decision_timestamp=runtime_state.get("decision_timestamp"),
                rejection_reasons=temporal_rejections,
            )
            if bridge_external_candidates
            else []
        )
        paper_candidate_rows = (
            build_paper_candidate_decision_rows(
                external_candidates,
                runtime_state=runtime_state,
            )
            if external_candidates
            else []
        )
        runtime_state["external_candidate_count"] = len(external_candidates)
        runtime_state["external_candidate_rows"] = external_candidates
        runtime_state["external_paper_candidate_count"] = len(paper_candidate_rows)
        runtime_state["external_paper_candidate_rows"] = paper_candidate_rows
        external_observation_report["external_observation_temporal_rejection_count"] = len(
            temporal_rejections
        )
        external_observation_report["external_observation_temporal_rejections"] = temporal_rejections
        if external_candidates:
            bridged_scm_report = build_signal_conversion_report(
                external_signal_inputs=external_candidates,
                include_external_signal_inputs=True,
                simulate_gsce_clear=simulate_gsce_clear,
                simulate_realm_bis_clear=simulate_realm_bis_clear,
                simulate_all_clear=simulate_all_clear,
            )
            runtime_state["scm_input_origin"] = bridged_scm_report.get(
                "scm_input_origin",
                runtime_state.get("scm_input_origin", "seeded"),
            )
            runtime_state["scm_external_row_count"] = int(
                bridged_scm_report.get("scm_external_row_count", 0) or 0
            )
            runtime_state["scm_seeded_row_count"] = int(
                bridged_scm_report.get("scm_seeded_row_count", 0) or 0
            )
        runtime_state["external_observation_summary"] = {
            "external_observation_active": external_observation_report[
                "external_observation_active"
            ],
            "external_observation_count": external_observation_report[
                "external_observation_count"
            ],
            "external_observation_valid_count": external_observation_report[
                "external_observation_valid_count"
            ],
            "external_observation_error_count": external_observation_report[
                "external_observation_error_count"
            ],
            "external_observation_symbols": external_observation_report[
                "external_observation_symbols"
            ],
            "external_observation_provider": external_observation_report[
                "external_observation_provider"
            ],
            "external_candidate_count": len(external_candidates),
            "external_observation_temporal_rejection_count": len(temporal_rejections),
            "external_observation_temporal_rejections": temporal_rejections,
        }
        runtime_state["temporal_integrity"] = build_temporal_integrity_summary(
            decision_timestamp=runtime_state.get("decision_timestamp"),
            observations=external_observation_report.get("observations", []),
        )
    bridge_mode_context = resolve_bridge_mode(
        include_external_observations=include_external_observations,
        external_candidate_bridge_enabled=bool(bridge_external_candidates),
        external_observation_active=bool(
            (external_observation_report or {}).get("external_observation_active", False)
        ),
        external_observation_valid_count=int(
            (external_observation_report or {}).get("external_observation_valid_count", 0) or 0
        ),
        external_candidate_count=int(runtime_state.get("external_candidate_count", 0) or 0),
        scm_external_row_count=int(runtime_state.get("scm_external_row_count", 0) or 0),
        paper_candidate_count=int(
            runtime_state.get("external_paper_candidate_count", 0) or 0
        ),
        provider_error_count=int(
            (external_observation_report or {}).get("external_observation_error_count", 0)
            or 0
        ),
    )
    runtime_state.update(bridge_mode_context)
    structural_admission_report = build_structural_admission_report(
        runtime_state=runtime_state,
        signal_refinery_report=final_signal_refinery_report,
        attention_proxy_report=final_attention_proxy_report,
        perception_control_report=final_perception_control_report,
        friction_report=friction_report,
        trend_report=trend_report,
        write_runtime=effective_write_runtime,
    )
    runtime_state["structural_admission"] = structural_admission_report
    latent_signal_release_bull_report = build_latent_signal_release_bull_report(
        runtime_state=runtime_state,
        signal_refinery_report=final_signal_refinery_report,
        attention_proxy_report=final_attention_proxy_report,
        perception_control_report=final_perception_control_report,
        structural_admission_report=structural_admission_report,
        friction_report=friction_report,
        write_runtime=effective_write_runtime,
    )
    runtime_state["latent_signal_release_bull"] = latent_signal_release_bull_report
    tennis_signals = load_runtime_compatible_signals(
        runtime_state=runtime_state,
        signal_refinery_report=final_signal_refinery_report,
        perception_control_report=final_perception_control_report,
    )
    if include_contextual_interpretation:
        contextual_report = build_contextual_interpretation_summary(
            tennis_signals,
            runtime_state=runtime_state,
            drift_threshold=(
                interpretation_drift_threshold
                if interpretation_drift_threshold is not None
                else 0.35
            ),
            render_operator_mode=render_operator_mode,
            write_runtime=effective_write_runtime,
        )
        runtime_state["contextual_interpretation"] = contextual_report
        runtime_state["contextual_interpretation_enabled"] = True
        runtime_state["validation_input_mode"] = contextual_report["validation_input_mode"]
        runtime_state["interpreted_signals"] = list(contextual_report["interpreted_signals"])
    elif contextual_interpretation_summary:
        runtime_state["contextual_interpretation_summary_requested"] = True
    tennis_archetype_report = write_tennis_archetype_report(
        tennis_signals,
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    runtime_state["tennis_archetype"] = tennis_archetype_report
    chess_archetype_report = write_chess_archetype_report(
        tennis_signals,
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    runtime_state["chess_archetype"] = chess_archetype_report
    hedge_trade_entry_report = build_hedge_trade_entry_report(
        tennis_signals,
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    runtime_state["hedge_trade_entry"] = hedge_trade_entry_report
    signal_surface_report = build_signal_surface_report(
        tennis_signals,
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    runtime_state["signal_surface_report"] = signal_surface_report
    extreme_state_report = build_extreme_state_report(
        tennis_signals,
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    runtime_state["extreme_state_report"] = extreme_state_report
    action_report = build_action_report(
        runtime_state=runtime_state,
        signal_refinery_report=final_signal_refinery_report,
        perception_control_report=final_perception_control_report,
        write_runtime=effective_write_runtime,
    )
    report = build_pipeline_health_report(
        include_tests=include_tests,
        write_runtime=effective_write_runtime,
        runtime_state=runtime_state,
        action_report=action_report,
        attention_proxy_report=final_attention_proxy_report,
        moltbook_feedback_report=moltbook_feedback_report,
        friction_report=friction_report,
        trend_report=trend_report,
        signal_refinery_report=final_signal_refinery_report,
        perception_control_report=final_perception_control_report,
        external_data_report=external_data_report,
        external_observation_report=external_observation_report,
        signal_surface_report=signal_surface_report,
        latest_snapshot_timestamp=latest_snapshot_timestamp,
        simulate_gsce_clear=simulate_gsce_clear,
        simulate_realm_bis_clear=simulate_realm_bis_clear,
        simulate_all_clear=simulate_all_clear,
    )
    return report


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full diagnostics pipeline in dependency order and emit the final health report."
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Run the targeted test slice as part of the final health report.",
    )
    parser.add_argument(
        "--include-external-data",
        action="store_true",
        help="Run the read-only Polymarket/Blockscout sync before the final health report.",
    )
    parser.add_argument(
        "--include-external-observations",
        action="store_true",
        help=(
            "Attach the external observation lane (yahoo by default) to this "
            "diagnostics run. Advisory only: observations cannot enable "
            "capital deployment."
        ),
    )
    parser.add_argument(
        "--observation-only",
        action="store_true",
        help=(
            "Attach external observations without admitting external candidates "
            "into SCM. Keeps the run in hybrid_observation mode when valid "
            "observations exist."
        ),
    )
    parser.add_argument(
        "--external-observation-symbol",
        action="append",
        dest="external_observation_symbols",
        default=None,
        help=(
            "Restrict the external observation lane to these symbols. May be "
            "repeated; defaults to the tickers present in the current "
            "per-signal attribution."
        ),
    )
    parser.add_argument(
        "--external-observation-provider",
        default="yahoo",
        help="Provider key for the external observation lane (default: yahoo).",
    )
    parser.add_argument(
        "--include-contextual-interpretation",
        action="store_true",
        help=(
            "Enable the contextual interpretation layer. This attaches "
            "interpretation packets to signals before downstream validation-style "
            "diagnostics and writes contextual runtime artifacts."
        ),
    )
    parser.add_argument(
        "--contextual-interpretation-summary",
        action="store_true",
        help=(
            "Print the compact contextual interpretation summary view. Implies "
            "summary-style output when combined with the interpretation layer."
        ),
    )
    parser.add_argument(
        "--interpretation-drift-threshold",
        type=float,
        default=None,
        help="Override the drift threshold used by the contextual interpretation layer.",
    )
    parser.add_argument(
        "--render-operator-mode",
        choices=["scout", "validate", "execute", "risk", "review"],
        default="validate",
        help="Renderer mode for contextual interpretation artifacts.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not persist runtime artifacts while running the pipeline.",
    )
    parser.add_argument(
        "--write-snapshot",
        action="store_true",
        help="Persist a scenario-tagged snapshot row even during simulation mode.",
    )
    simulation = parser.add_mutually_exclusive_group()
    simulation.add_argument(
        "--simulate-gsce-clear",
        action="store_true",
        help="Preview the GSCE-clear transition path without writing runtime artifacts.",
    )
    simulation.add_argument(
        "--simulate-realm-bis-clear",
        action="store_true",
        help="Preview the REALM_BIS-clear transition path without writing runtime artifacts.",
    )
    simulation.add_argument(
        "--simulate-all-clear",
        action="store_true",
        help="Preview the fully cleared transition path without writing runtime artifacts.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    report = run_diagnostics_pipeline(
        include_tests=args.include_tests,
        include_external_data=args.include_external_data,
        include_external_observations=args.include_external_observations,
        include_contextual_interpretation=args.include_contextual_interpretation
        or args.contextual_interpretation_summary,
        contextual_interpretation_summary=args.contextual_interpretation_summary,
        interpretation_drift_threshold=args.interpretation_drift_threshold,
        render_operator_mode=args.render_operator_mode,
        bridge_external_candidates=not args.observation_only,
        external_observation_symbols=args.external_observation_symbols,
        external_observation_provider=args.external_observation_provider,
        write_runtime=not args.no_write,
        write_snapshot=args.write_snapshot,
        simulate_gsce_clear=args.simulate_gsce_clear,
        simulate_realm_bis_clear=args.simulate_realm_bis_clear,
        simulate_all_clear=args.simulate_all_clear,
    )
    if args.summary or args.contextual_interpretation_summary:
        print(format_pipeline_health_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
