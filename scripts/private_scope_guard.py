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
``REVIEW_REQUIRED``), and tracks any *quarantined tool directories*
that have been moved out of ``scripts/`` into ``tools/`` so they no
longer pollute the MVP runtime surface.

The report is consumed by:

* ``tests/test_private_scope_guard.py`` — locks the inventory so adding
  a new out-of-scope module trips a clearly-named test.
* ``scripts/local_mvp_audit.py`` (optional consumer) — surfaces the
  count as a WARN-level signal, not a FAIL.

Out-of-scope is NOT an instruction to delete anything.  Existing modules
that have already shipped (e.g. an experimental scraper) remain in
place — either grandfathered in ``PREEXISTING_BASELINE`` or quarantined
under ``tools/``.  The guard simply prevents *silent* expansion: every
new module either lands in an approved domain or shows up here for an
explicit operator decision.
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
_TOOLS_DIR = _REPO_ROOT / "tools"

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
    "performance_baseline",
    "restore_drill",
    "config",
    "supported_currencies",
    "execution_governance",
    "execution_integrity_audit",
    "no_execution",
    # leverage governance/safety is a core advisory-risk domain: the doctrine
    # ceilings (India 4x / rest-of-world 1x) and the manual-trade-log breach
    # check live here. leverage_safety_layer.py + leverage_governance.py.
    "leverage",
    "hygiene",
    "complex_systems",  # advisory-only complex-systems signal doctrine layer
    # Kanté defensive sprint — advisory-only safety / deploy / compliance layer.
    "advisory",       # advisory_contract.py — shared safety stamp
    "deploy",         # local_deploy_preflight.py
    "release",        # release_gate.py
    "local_stack",    # start_local_stack.ps1 launcher
    "business",       # business_value_report.py
    "compliance",     # compliance_preflight.py
    # Kanté Sprint 2 — enforcement / fitness / resilience defensive layer.
    "architecture",     # architecture_fitness.py — dependency-boundary fitness
    "fault_injection",  # fault_injection_probe.py — resilience probe
    "performance_probe",  # performance_probe.py — bounded-load probe
    "schema_migration",   # schema_migrations.py — non-destructive schema versioning
    "query_plan",         # sqlite_query_plan_audit.py — indexed-read evidence
    # Closed-loop learning sprint — advisory-only DB-backed audit/report layer.
    "broken_windows",   # broken_windows_report.py — repair-debt visibility
    "defensive",        # defensive_alpha_report.py — bad-decisions-prevented ledger
    "truth_purity",     # runtime_truth_purity_audit.py — fake-data canonical guard
    "closed_loop",      # closed_loop_learning_audit.py — signal->lesson chain audit
    # Bruce Lee / JKD sprint — advisory-only decision-discipline diagnostics.
    # Scores/gates only; no broker execution, no order placement, no API writes.
    "jkd",              # jkd_decision_discipline.py — JKD advisory decision score
    "bruce_lee",        # bruce_lee_*.py — decision-quality index + discipline report
    "reality_check",    # finger_moon_reality_check.py — reality-confirmation diagnostic
    "diablo",           # diablo_narrative_veto.py — advisory hard-veto combinations
    "economy_of_motion",  # economy_of_motion_audit.py — hygiene/ornamentation audit
    # Enforcement / scalability / compliance ceiling sprint — advisory-only,
    # read-only diagnostics service + derived cache + reliability ledger.
    # No broker execution, no order placement, no API trading writes.
    "diagnostics",      # diagnostics_snapshot_cache.py / diagnostics_service.py
    "model_reliability",  # model_reliability_ledger.py — per-model calibration ledger
    # Kanté defensive sprint (follow-up) — advisory-only cockpit hot-path
    # query/index evidence + guarded additive-index apply.  Read-only audit;
    # the apply path is ADMIN/MIGRATION_WRITE guarded, CREATE INDEX IF NOT
    # EXISTS only, never drops/deletes, no broker execution.
    "cockpit_hot_path",  # cockpit_hot_path_query_audit.py / apply_cockpit_hot_path_indexes.py
    # Kanté defensive sprint (Task C) — advisory-only, read-only concurrency /
    # stress probe over signal_events + cockpit hot paths.  No mutation, no
    # broker execution, no order placement, no API writes; bounded workers.
    "stress_probe",  # cockpit_concurrency_stress_probe.py
    # Daily five-model synthesis truth/discovery sprint — advisory-only layer
    # that sources holdings truth from data/daily_payload/ and produces fresh
    # candidates without letting phantom positions block discovery.  Scores and
    # gates only; no broker execution, no order placement, no API trading writes.
    "daily",            # daily_payload.py / daily_synthesis_pipeline.py / daily_discovery_config.py / daily_scoring.py
    "portfolio_truth",  # portfolio_truth_gate.py — H = V \ (C ∪ S ∪ D)
    "discovery",        # fresh_market_discovery.py — null-safe candidate quality score
    "candidate_executable",  # candidate_executable_split.py — CQS/EQS classification
    "anti_staleness",   # anti_staleness.py — freshness labels + novelty enforcement
    # Daily fresh-data sprint — advisory-only payload builders + scoring signals
    # that feed (never execute) the five-model synthesis. Scores/gates only; no
    # broker execution, no order placement, no API trading writes.
    "build_today",      # build_today_market_snapshot/price_movers/news_events/filings_events.py
    "build_yesterday",  # build_yesterday_final_candidates.py — anti-staleness set Y
    "universe",         # minimum_daily_universe.py — minimum viable fresh universe (U_static)
    "why_today",        # why_today.py — "why today, not yesterday?" executable gate
    "memory_decay",     # candidate_memory_decay.py — exp(-lambda*d) candidate decay
    "disagreement",     # model_disagreement.py — cross-model variance / consensus quality
    # Kalshi read-only adapter sprint — public market-data ingestion + category
    # allowlist + advisory-only signal normalizer.  Read-only end-to-end; no
    # trading endpoints, no auth, no order placement, no broker calls.
    "kalshi",           # kalshi_normalizer.py / kalshi_market_data_adapter.py / kalshi_runner.py
    # Cross-venue prediction-market sprint — advisory-only information-fracture
    # detector across Polymarket × Kalshi.  Semantic pairing + disagreement
    # scanner.  No execution, no broker calls, no order placement, no
    # arbitrage/buy/sell language.  Persistence reuses signal_events under a
    # distinct source_name="prediction_market_disagreement"; no new mutation
    # table; JSONL is not made canonical.
    "prediction_market",  # prediction_market_semantic_pairing.py / prediction_market_disagreement_scanner.py
    # Integrated sprint — advisory-only LPQ + promotion downgrade + AI report
    # ingestion + per-provider verification.  Scores/gates only; no broker
    # execution, no order placement, no API trading writes.
    "live_payload",         # live_payload_quality.py — LPQ + M_live
    "promotion_downgrade",  # promotion_downgrade.py — candidate state decider
    "ai_report",            # ai_report_ingestion.py — AIReportSignal normalizer
    "provider_verification",  # provider_verification.py — source-health classifier
    "typed_config",         # typed_config.py — typed config schema
    "prewarm",              # prewarm_diagnostics_snapshot.py — diagnostics warm
    "snapshot_key",         # diagnostics_snapshot_key.py — deterministic key
    "tail_metrics",         # diagnostics_tail_metrics.py — p95/p99/max/tail
    "compliance_registers",  # compliance_registers.py — privacy + license JSON
    # Kanté defensive batch 2 — advisory-only release-gate readiness layer.
    # Scores/gates only; no broker execution, no order placement, no API
    # trading writes.
    "ai_integration",       # ai_integration_readiness.py — AI/API readiness
    "five_model",           # five_model_independence.py — model_runs independence
    # Sprint 3 (score-upgrade) — advisory-only readiness/contract modules.
    # Scores/gates only; no broker execution, no order placement, no API
    # trading writes; no executable trade language.
    "promotion_contract",     # candidate_promotion_contract.py — composite gate
    "universe_coverage",      # universe_coverage.py — 44-ticker advisory universe
    "operator_demo_value",    # operator_demo_value.py — paper/advisory proxy
    "compliance_trace",       # live_provider_compliance_trace.py — per-provider audit
    "backend_api_quality",    # backend_api_quality.py — readiness envelope
    "operator_live_provider", # operator_live_provider_refresh.py — explicit refresh
    # Forensic-audit remediation — advisory-only correctness/integrity layer.
    # Scores/records only; no broker execution, no order placement, no API
    # trading writes.
    "money",          # money.py (L1) — Decimal-faithful money parsing for the
                      # manual-trade journal; replaces lossy float at the boundary
    "idempotency",    # idempotency.py (L3) — Idempotency-Key dedupe cache for
                      # POST /manual-trades; prevents double-logged journal rows
    # Gap-area remediation — advisory-only canonical tagging + observation
    # scaffold.  Scores/labels only; no broker execution, no order placement,
    # no API trading writes.
    "tag_engine",     # tag_engine.py — canonical candidate-classification tag catalog
    "chronology",     # chronology_store.py / chronology_detectors.py — observation
                      # substrate + fail-closed T1-T4 detector stubs (NOT_IMPLEMENTED)
    "governance_verdict",  # governance_verdict.py — extracted system-readiness
                           # verdict (god-module reduction); pure, no execution
    "action_doctrine",     # action_doctrine_status.py — UNRATIFIED doctrine
                           # status reporter; unlocks nothing, no execution
    "observation",         # run_observation_cycle.py — observation-only T1-T4
                           # cycle runner; no execution, no broker
    "decision_board",      # manual_decision_board.py — advisory-only human-review
                           # classifier; emits no order/execution instruction
    "mvp_readiness",       # mvp_readiness_report.py — single advisory truth surface
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
    # Core score-honesty contract shared by the scoring APIs — keeps a precise
    # score from ever being presented as validated. In-scope by definition.
    "score_output_contract.py",
    # Calibration/data/hygiene sprint core modules — all advisory-only,
    # no-execution, and load-bearing for honest real-money readiness.
    "outcome_evidence.py",
    "outcome_evidence_extractor.py",
    "securities_master_coverage.py",
    "core_module_boundary.py",
    # Real-evidence sprint: read-only OHLCV import for backtest evidence.
    "ohlcv_import_contract.py",
    "import_ohlcv_csv.py",
    "run_imported_backtest.py",
    "import_outcomes_csv.py",
})

# Modules deliberately marked OUT_OF_SCOPE inside ``scripts/``.  This
# list exists so the guard report distinguishes "we know this is out of
# scope and have accepted it" from "this is new and needs an operator
# decision".  Adding here is an explicit operator acknowledgement: the
# file is intentionally outside the approved MVP domains but accepted.
KNOWN_OUT_OF_SCOPE: frozenset[str] = frozenset({
    # local operator helper for advisory-only five-model synthesis prompt
    # recovery; no broker execution, no order placement, no API trading writes.
    "run_five_model_synthesis.ps1",
})

# Quarantined non-MVP tool directories.  These live under ``tools/`` so
# they are physically off the MVP runtime surface — no module under
# ``scripts/`` or ``src/`` is allowed to import them.  Each entry maps
# the directory name (relative to ``tools/``) to a short rationale that
# is surfaced in the operator-facing report.
#
# Quarantine is *reversible*: removing an entry from this map does not
# delete anything; it simply tells the guard to stop expecting the
# directory to exist under ``tools/``.
QUARANTINED_TOOL_DIRS: dict[str, str] = {
    "gmat_scraper": (
        "GMAT Club scraper + advisory reasoning bridge — not part of "
        "the private-operator MVP runtime; relocated from scripts/ to "
        "tools/ to remove it from the MVP surface."
    ),
}

# Pre-existing baseline of scripts/ entries that do not match an approved
# domain substring but were already in the tree at the moment this
# discipline tool was introduced.  Their continued presence is accepted;
# new files outside the approved domains will fall into review_required
# instead of being silently grandfathered.  Adding to this set is a
# *retroactive* decision and should be avoided — prefer placing new
# files inside an approved domain or expanding ``APPROVED_DOMAINS``.
PREEXISTING_BASELINE: frozenset[str] = frozenset({
    "_quarantine",
    "gmat_scraper",  # historical baseline reference; the directory itself
    # is now relocated to ``tools/gmat_scraper`` and tracked through
    # ``QUARANTINED_TOOL_DIRS``.  Keeping the name here means a future
    # operator who accidentally re-creates ``scripts/gmat_scraper`` will
    # see it land in ``out_of_scope`` but not ``review_required`` — the
    # quarantine-leak check below is what fails loudly.
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


def _inspect_quarantined_tools(
    *,
    scripts_dir: Path,
    tools_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (quarantined_summary, quarantine_leaks).

    A *leak* is a quarantined directory that has reappeared inside the
    MVP surface — i.e. ``scripts/<name>`` exists.  Leaks are a hard
    discipline-failure signal: the whole point of relocating the
    directory was to keep it out of the MVP runtime.
    """
    summary: list[dict[str, Any]] = []
    leaks: list[str] = []
    for name, rationale in sorted(QUARANTINED_TOOL_DIRS.items()):
        tools_path = tools_dir / name
        scripts_path = scripts_dir / name
        tools_present = tools_path.exists()
        leaked_to_scripts = scripts_path.exists()
        summary.append(
            {
                "name": name,
                "expected_relative_path": f"tools/{name}",
                "tools_path_exists": tools_present,
                "leaked_back_to_scripts": leaked_to_scripts,
                "rationale": rationale,
            }
        )
        if leaked_to_scripts:
            leaks.append(f"scripts/{name}")
    return summary, leaks


def build_report(
    scripts_dir: Path = _SCRIPTS_DIR,
    *,
    tools_dir: Path | None = None,
) -> dict[str, Any]:
    """Walk the scripts/ tree once and classify every top-level entry.

    Also inspects ``tools/`` (or the explicit ``tools_dir`` override) to
    confirm quarantined tool directories remain physically outside the
    MVP runtime surface.
    """
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    review_required: list[str] = []
    resolved_tools_dir = (
        tools_dir if tools_dir is not None else scripts_dir.parent / "tools"
    )
    quarantined_tools, quarantine_leaks = _inspect_quarantined_tools(
        scripts_dir=scripts_dir, tools_dir=resolved_tools_dir
    )

    if not scripts_dir.exists():
        return {
            "report": "private_scope_guard",
            "scripts_dir": str(scripts_dir),
            "scripts_dir_exists": False,
            "tools_dir": str(resolved_tools_dir),
            "tools_dir_exists": resolved_tools_dir.exists(),
            "in_scope": [],
            "out_of_scope": [],
            "review_required": [],
            "known_out_of_scope": sorted(KNOWN_OUT_OF_SCOPE),
            "quarantined_tools": quarantined_tools,
            "quarantine_leaks": quarantine_leaks,
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
            # explicitly-acknowledged out-of-scope list.  This is the
            # discipline surface: the only thing that should ever trip
            # is something a new commit added.
            if (
                name not in KNOWN_OUT_OF_SCOPE
                and name not in PREEXISTING_BASELINE
            ):
                review_required.append(name)

    return {
        "report": "private_scope_guard",
        "scripts_dir": str(scripts_dir),
        "scripts_dir_exists": True,
        "tools_dir": str(resolved_tools_dir),
        "tools_dir_exists": resolved_tools_dir.exists(),
        "in_scope_count": len(in_scope),
        "out_of_scope_count": len(out_of_scope),
        "review_required_count": len(review_required),
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "review_required": review_required,
        "known_out_of_scope": sorted(KNOWN_OUT_OF_SCOPE),
        "quarantined_tools": quarantined_tools,
        "quarantine_leaks": quarantine_leaks,
        "approved_domains": list(APPROVED_DOMAINS),
        "operator_message": _operator_message(
            out_of_scope, review_required, quarantine_leaks
        ),
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
    }


def _operator_message(
    out_of_scope: list[str],
    review_required: list[str],
    quarantine_leaks: list[str] | None = None,
) -> str:
    leaks = list(quarantine_leaks or [])
    if leaks:
        return (
            f"REVIEW_REQUIRED: quarantined tool directory leaked back into "
            f"the MVP surface — {', '.join(leaks)} — move it back under "
            "tools/ or update QUARANTINED_TOOL_DIRS."
        )
    if review_required:
        return (
            f"REVIEW_REQUIRED: {len(review_required)} new out-of-scope "
            f"module(s) detected — {', '.join(review_required)} — "
            "either move into an approved private-operator domain, "
            "quarantine under tools/, or add to KNOWN_OUT_OF_SCOPE with "
            "justification."
        )
    if out_of_scope:
        return (
            f"OK: {len(out_of_scope)} out-of-scope module(s) present but "
            "all are pre-accepted — do not extend them as part of MVP work."
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
        print(f"quarantined_tools   : {len(report.get('quarantined_tools') or [])}")
        print(f"quarantine_leaks    : {len(report.get('quarantine_leaks') or [])}")
        print("")
        print(report.get("operator_message", ""))
        if report.get("review_required"):
            print("")
            print("REVIEW_REQUIRED entries:")
            for name in report["review_required"]:
                print(f"  - {name}")
        if report.get("quarantine_leaks"):
            print("")
            print("Quarantine leaks (move back under tools/):")
            for name in report["quarantine_leaks"]:
                print(f"  - {name}")
    strict_failed = (
        report.get("review_required_count", 0) > 0
        or bool(report.get("quarantine_leaks"))
    )
    if args.strict and strict_failed:
        return 1
    return 0


__all__ = [
    "APPROVED_DOMAINS",
    "EXPLICIT_IN_SCOPE",
    "KNOWN_OUT_OF_SCOPE",
    "PREEXISTING_BASELINE",
    "QUARANTINED_TOOL_DIRS",
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "build_report",
]


if __name__ == "__main__":
    sys.exit(main())
