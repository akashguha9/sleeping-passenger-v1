"""Private-operator MVP scope guard — review-required surface inventory.

The Sleeping Passenger MVP is a *private operator* tool.  Its scope is
explicitly narrow: ingest signals, score them, capture decisions in a
journal, reconcile outcomes, surface refresh + reactor diagnostics.  Any
module that drifts outside that scope dilutes product clarity, increases
maintenance cost, and confuses future audits about what the MVP actually
does.

This module is a *discipline tool*, not a deletion tool.  It scans the
``scripts/`` tree, classifies each top-level entry as either in-scope
(an approved private-operator domain) or out-of-scope (a candidate for
``REVIEW_REQUIRED``), and produces a structured report.  The report is
consumed by:

* ``tests/test_private_scope_guard.py`` — locks the inventory so adding
  a new out-of-scope module trips a clearly-named test.
* ``scripts/local_mvp_audit.py`` (optional consumer) — surfaces the
  count as a WARN-level signal, not a FAIL.

Out-of-scope is NOT an instruction to delete anything.  Existing modules
that have already shipped (e.g. an experimental scraper) remain in
place.  The guard simply prevents *silent* expansion: every new module
either lands in an approved domain or shows up here for an explicit
operator decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

# Approved private-operator domains.  A module is considered in-scope if
# any of these substrings appears in its filename or package directory
# name.  Substring matching is intentional — it tolerates suffixes like
# ``_extras``, ``_helpers``, ``_summary``, etc. without enumerating them.
APPROVED_DOMAINS: tuple[str, ...] = (
    "signal",
    "source",
    "live_refresh",
    "refresh_live",
    "live_source",
    "reactor",
    "calibration",
    "manual_trade",
    "paper_trade",
    "paper_reconciliation",
    "paper_execution",
    "learning",
    "reconciliation",
    "preflight",
    "backup",
    "restore",
    "audit",
    "security",
    "frontend",
    "api_server",
    "api",
    "persistence",
    "scheduler",
    "moltbook",
    "operator",
    "scope_guard",
    "config",
    "supported_currencies",
    "execution_governance",
    "execution_integrity_audit",
    "no_execution",
)

# Explicit allowlist for individual files / directories whose name does
# not contain an approved domain substring but which are nonetheless
# part of the MVP surface (e.g. plumbing, archetype helpers used by
# scoring, etc.).  Avoid expanding this without justification — it is
# the escape hatch, not the default.
EXPLICIT_IN_SCOPE: frozenset[str] = frozenset({
    "windows",  # PowerShell helpers for the local scheduled task
    "fixtures",
    "__init__.py",
    "__pycache__",
})

# Modules deliberately marked OUT_OF_SCOPE.  This list exists so the
# guard report distinguishes "we know this is out of scope and have
# accepted it" from "this is new and needs an operator decision".
KNOWN_OUT_OF_SCOPE: frozenset[str] = frozenset({
    "gmat_scraper",
})

# Pre-existing baseline of scripts/ entries that do not match an approved
# domain substring but were already in the tree at the moment this
# discipline tool was introduced.  Their continued presence is accepted;
# new files outside the approved domains will fall into review_required
# instead of being silently grandfathered.  Adding to this set is a
# *retroactive* decision and should be avoided — prefer placing new
# files inside an approved domain or expanding ``APPROVED_DOMAINS``.
PREEXISTING_BASELINE: frozenset[str] = frozenset({
    "_quarantine",
    "action_engine.py",
    "activation_trigger_tracker.py",
    "ai_output_schema.py",
    "apply_uso_removal.py",
    "archetype_profile.py",
    "archetype_registry.py",
    "artifact_coherence_check.py",
    "asset_durability_filter.py",
    "asymmetry_survival_scorer.py",
    "attention_proxy_engine.py",
    "backfill_global_ohlcv.py",
    "backfill_ohlcv_history.py",
    "baines_engine.py",
    "belief_backtest.py",
    "blocker_cost_engine.py",
    "blockscout_adapter.py",
    "board_control_safety_layer.py",
    "branch_payload.py",
    "build_dataset.py",
    "chart_structure_engine.py",
    "chart_structure_price_truth.py",
    "chart_symbol_bootstrap.py",
    "chess_archetype_decision_layer.py",
    "chronology_store.py",
    "cleanup_polymarket_db.py",
    "closure_deficit_monitor.py",
    "competence_exploitation_engine.py",
    "complexity_ladder_controller.py",
    "composite_edge_score.py",
    "consensus_formation_detector.py",
    "contextual_interpretation",
    "contextual_interpretation_engine.py",
    "continuity_mode.py",
    "core",
    "crowding_detector.py",
    "cycle_clarity_chaos_intensity.py",
    "data_void_engine.py",
    "db_integrity_check.py",
    "demographic_engine.py",
    "echo_risk_engine.py",
    "environment_fit_report.py",
    "environment_quality_score.py",
    "error_contracts.py",
    "event_prior_detector.py",
    "execution_conversion_tracker.py",
    "execution_quality_engine.py",
    "execution_quality_scorer.py",
    "experience_mode_report.py",
    "external",
    "external_adapters",
    "external_data_common.py",
    "external_data_runtime_sync.py",
    "external_observation_lane.py",
    "external_tool_integration_layer.py",
    "extreme_state",
    "extreme_state_logic.py",
    "extreme_state_report.py",
    "false_negative_casino_monopoly_layer.py",
    "fetch_polymarket.py",
    "field_dynamics_engine.py",
    "fission_branch_mapper.py",
    "football_portfolio_archetype_engine.py",
    "fusion_thesis_engine.py",
    "game_state_control_engine.py",
    "governance_feedback_report.py",
    "governance_status.py",
    "grok_xai_adapter.py",
    "gsheet_export.py",
    "hedge_ratio_engine.py",
    "hedge_trade_entry_common.py",
    "hedge_trade_entry_playbook.py",
    "improv_layer.py",
    "ingestion",
    "integrity_diagnostics.py",
    "late_adoption_lockout.py",
    "leverage_safety_layer.py",
    "local_mvp_smoke_test.py",
    "market_data_adapter.py",
    "market_data_freshness.py",
    "micro_timing_layer.py",
    "milk_test_polymarket_history.py",
    "milk_test_uso_removal.py",
    "narrative_archetype_router.py",
    "narrative_distortion_index.py",
    "narrative_drift_monitor.py",
    "narrative_inertia_score.py",
    "narrative_inflation_index.py",
    "narrative_structure_divergence.py",
    "net_exposure_calculator.py",
    "optical_operating_system.py",
    "pendentive_engine.py",
    "perception_control.py",
    "performance_projection_engine.py",
    "phase_classifier.py",
    "pipeline_health_report.py",
    "polymarket_clob_adapter.py",
    "polymarket_data_adapter.py",
    "polymarket_gamma_adapter.py",
    "position_conflict_detector.py",
    "position_truth_resolver.py",
    "pre_execution_scan_engine.py",
    "process_quality_classifier.py",
    "propagation_spread_estimator.py",
    "rate_limiter.py",
    "reflection_frameworks.py",
    "regime_translation_tester.py",
    "repo_operating_mode.py",
    "run_contextual_interpretation_demo.py",
    "run_dashboard.py",
    "run_diagnostics_pipeline.py",
    "run_extreme_state_report.py",
    "run_ingestion.py",
    "run_paper_trading.py",
    "run_scoring.py",
    "run_tennis_archetype_diagnostics.py",
    "runtime_common.py",
    "seed_chart_ohlcv_history.py",
    "selective_hedge_classifier.py",
    "self_test_journal_quality.py",
    "self_test_report.py",
    "silence_filter.py",
    "smoke_check.py",
    "snapshot_logger.py",
    "structural_admission_layer.py",
    "structural_design_engine.py",
    "structural_integrity_score.py",
    "survivorship_bias_corrector.py",
    "symbol_normalizer.py",
    "tail_loss_governor.py",
    "temporal_position_engine.py",
    "tennis_archetype_execution.py",
    "tension_accumulation_tracker.py",
    "trade_entry_gate.py",
    "trend_engine.py",
    "tribev2_adapter.py",
    "update_global_ohlcv_latest.py",
    "update_ohlcv_latest.py",
    "visibility_engine.py",
    "visibility_timing_sync.py",
    "yahoo_market_data_adapter.py",
    "zone_precision_detector.py",
    "phase_c_final_audit.py",
    "global_security_master_discovery.py",
})


def _classify(name: str) -> str:
    """Return ``"in_scope"`` or ``"out_of_scope"`` for a script-tree entry.

    Approved-domain matching is case-insensitive and substring-based.
    Explicit allowlist entries match exactly on the bare basename.
    """
    if name in EXPLICIT_IN_SCOPE:
        return "in_scope"
    lowered = name.lower()
    for domain in APPROVED_DOMAINS:
        if domain in lowered:
            return "in_scope"
    return "out_of_scope"


def _iter_scripts_entries() -> Iterable[Path]:
    if not _SCRIPTS_DIR.exists():
        return ()
    return sorted(
        p
        for p in _SCRIPTS_DIR.iterdir()
        if p.name not in {"__pycache__"}
    )


def build_report(scripts_dir: Path = _SCRIPTS_DIR) -> dict[str, Any]:
    """Walk the scripts/ tree once and classify every top-level entry."""
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    review_required: list[str] = []

    if not scripts_dir.exists():
        return {
            "report": "private_scope_guard",
            "scripts_dir": str(scripts_dir),
            "scripts_dir_exists": False,
            "in_scope": [],
            "out_of_scope": [],
            "review_required": [],
            "known_out_of_scope": sorted(KNOWN_OUT_OF_SCOPE),
            "advisory_status": ADVISORY_STATUS,
            "execution_gate": EXECUTION_GATE_LOCKED,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "execution_permission": False,
            "can_execute": False,
        }

    for entry in sorted(p for p in scripts_dir.iterdir() if p.name != "__pycache__"):
        name = entry.name
        if name in EXPLICIT_IN_SCOPE:
            in_scope.append(name)
            continue
        cls = _classify(name)
        if cls == "in_scope":
            in_scope.append(name)
        else:
            out_of_scope.append(name)
            # Review-required = newly-introduced out-of-scope files that
            # are neither in the pre-existing baseline nor in the
            # explicitly-acknowledged out-of-scope list (e.g. the GMAT
            # scraper).  This is the discipline surface: the only thing
            # that should ever trip is something a new commit added.
            if (
                name not in KNOWN_OUT_OF_SCOPE
                and name not in PREEXISTING_BASELINE
            ):
                review_required.append(name)

    return {
        "report": "private_scope_guard",
        "scripts_dir": str(scripts_dir),
        "scripts_dir_exists": True,
        "in_scope_count": len(in_scope),
        "out_of_scope_count": len(out_of_scope),
        "review_required_count": len(review_required),
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "review_required": review_required,
        "known_out_of_scope": sorted(KNOWN_OUT_OF_SCOPE),
        "approved_domains": list(APPROVED_DOMAINS),
        "operator_message": _operator_message(out_of_scope, review_required),
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
    }


def _operator_message(out_of_scope: list[str], review_required: list[str]) -> str:
    if review_required:
        return (
            f"REVIEW_REQUIRED: {len(review_required)} new out-of-scope "
            f"module(s) detected — {', '.join(review_required)} — "
            "either move into an approved private-operator domain or add "
            "to KNOWN_OUT_OF_SCOPE with justification."
        )
    if out_of_scope:
        return (
            f"OK: {len(out_of_scope)} out-of-scope module(s) present but "
            "all are pre-accepted in KNOWN_OUT_OF_SCOPE — do not extend "
            "them as part of MVP work."
        )
    return "OK: all scripts/ entries are within approved private-operator domains."


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="private_scope_guard.py",
        description=(
            "Report which scripts/ entries are inside the approved private-"
            "operator MVP domain and which are out of scope.  Read-only; "
            "never deletes; never grants execution permission."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit code 1 if any module is REVIEW_REQUIRED (newly out of "
            "scope).  Default exit code is always 0."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print("Private Operator Scope Guard")
        print("=" * 28)
        print(f"in_scope            : {report.get('in_scope_count', 0)}")
        print(f"out_of_scope        : {report.get('out_of_scope_count', 0)}")
        print(f"review_required     : {report.get('review_required_count', 0)}")
        print("")
        print(report.get("operator_message", ""))
        if report.get("review_required"):
            print("")
            print("REVIEW_REQUIRED entries:")
            for name in report["review_required"]:
                print(f"  - {name}")
    if args.strict and report.get("review_required_count", 0) > 0:
        return 1
    return 0


__all__ = [
    "APPROVED_DOMAINS",
    "EXPLICIT_IN_SCOPE",
    "KNOWN_OUT_OF_SCOPE",
    "PREEXISTING_BASELINE",
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "build_report",
]


if __name__ == "__main__":
    sys.exit(main())
