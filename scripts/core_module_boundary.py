"""Core module boundary — clarity, not refactoring theater.

Classifies the backend modules into CORE / SUPPORT / EXPERIMENTAL / ARCHIVED so
the load-bearing surface is explicit, and enforces import hygiene: a CORE
module may import CORE or SUPPORT, never EXPERIMENTAL or ARCHIVED.

Read-only / pure (AST inspection of source). No DB, no network, no execution.

Metrics
-------
K          = (N_core + N_support + N_experimental) / N_total   (classified fraction)
U_penalty  = N_unknown / N_total
H          = max(0, 1 - U_penalty)                              (boundary clarity)
I          = 1 if no CORE module imports EXPERIMENTAL/ARCHIVED else 0
CH         = 10 * (0.60·H + 0.40·I)                             (hygiene score)
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SCRIPTS = _REPO_ROOT / "scripts"
_SRC = _REPO_ROOT / "src"

CORE = "CORE"
SUPPORT = "SUPPORT"
EXPERIMENTAL = "EXPERIMENTAL"
ARCHIVED = "ARCHIVED"
UNKNOWN = "UNKNOWN"

# Production-core: the manifest engines + load-bearing infrastructure.
CORE_MODULES: frozenset[str] = frozenset({
    "leverage_governance", "score_calibration", "calibration_recommendations",
    "score_output_contract", "pre_real_money_preflight", "diablo_narrative_veto",
    "event_prior_detector", "moltbook_feedback", "signal_inbox_api",
    "persistence", "calibration_gate", "api_server", "advisory_contract",
    "outcome_evidence", "outcome_evidence_extractor", "securities_master_coverage",
    "runtime_common", "private_scope_guard", "core_module_boundary",
    "signal_refinery", "signal_reactor", "chronology_store", "chronology_detectors",
    "calibration_map", "backtest_calibration", "signal_quality_report",
})

# Experimental: archetype/mythology layers that are NOT load-bearing. The
# boundary test verifies no CORE module imports any of these (import hygiene).
EXPERIMENTAL_MODULES: frozenset[str] = frozenset({
    "chess_archetype_decision_layer", "tennis_archetype_execution",
    "football_portfolio_archetype_engine", "bruce_lee_decision_quality_index",
    "bruce_lee_signal_discipline_report", "jkd_decision_discipline",
    "optical_operating_system", "finger_moon_reality_check", "improv_layer",
    "pendentive_engine", "narrative_operator_wisdom_filter",
    "latent_signal_release_bull_layer", "false_negative_casino_monopoly_layer",
    "economy_of_motion_audit", "regime_translation_tester",
    # Real-evidence sprint review (docs/UNKNOWN_MODULE_REVIEW.md): archetype/
    # regime experiment, not load-bearing.
    "cycle_clarity_chaos_intensity",
})

# Reviewed in docs/UNKNOWN_MODULE_REVIEW.md: previously-UNKNOWN modules
# confirmed as SUPPORT (none imported by CORE; most have tests). KEEP_SUPPORT.
_SUPPORT_REVIEWED: frozenset[str] = frozenset({
    "action_doctrine_status", "anti_staleness", "backup_db", "backup_local_state",
    "candidate_memory_decay_v2", "continuity_mode", "daily_synthesis_pipeline",
    "diagnostics_snapshot_cache", "diagnostics_snapshot_key",
    "diagnostics_snapshot_warmer", "diagnostics_tail_metrics", "error_contracts",
    "expectation_divergence_signal", "extreme_state_logic", "five_model_independence",
    "fresh_market_discovery", "governance_status", "governance_verdict",
    "kalshi_live_smoke", "late_adoption_lockout", "live_provider_compliance_trace",
    "live_signal_filters", "live_source_runner_phase2", "local_mvp_smoke_test",
    "market_data_freshness", "minimum_daily_universe", "model_disagreement",
    "moltbook_cleanup_fake_seed", "narrative_structure_divergence",
    "operator_live_provider_refresh", "paper_execution", "paper_trade_retirement",
    "perception_control", "performance_baseline", "persistence_global_securities",
    "persistence_integrity", "portfolio_truth_integrity", "position_truth_resolver",
    "prediction_market_embedding_providers", "prediction_market_semantic_pairing",
    "promotion_downgrade", "provider_verification", "repo_operating_mode", "restore_db",
    "restore_drill", "signal_geometry_persistence", "signal_index_query",
    "survivorship_bias_corrector", "tail_loss_governor", "universe_coverage",
    "why_today_enforcement",
})

# Naming families that denote SUPPORT tooling (not core, not experimental).
_SUPPORT_SUFFIXES: tuple[str, ...] = (
    "_engine", "_report", "_audit", "_adapter", "_gate", "_score", "_scorer",
    "_quality", "_detector", "_contract", "_tracker", "_ledger", "_index",
    "_diagnostics", "_classifier", "_check", "_runner", "_reconciliation",
    "_readiness", "_probe", "_preflight", "_normalizer", "_monitor", "_history",
    "_loader", "_scanner", "_estimator", "_mapper", "_calculator", "_builder",
    "_sync", "_export", "_backup", "_restore", "_registry", "_config", "_filter",
    "_layer", "_engine2", "_summary", "_router", "_bridge", "_store", "_client",
    "_utils", "_common", "_guard", "_lane", "_tester", "_census", "_decay",
    "_handling", "_logger", "_dashboard", "_playbook", "_metabolism",
    "_geometry", "_inputs", "_attach", "_calibration", "_governance",
    "_detectors", "_store", "_controller", "_bootstrap", "_lab", "_split",
    "_schema", "_ingestion", "_profile", "_signals", "_fitness", "_registers",
    "_value", "_engine_belief_extension", "_extension", "_purity_audit",
)
_SUPPORT_PREFIXES: tuple[str, ...] = (
    "build_", "run_", "apply_", "backfill_", "seed_", "import_", "export_",
    "fetch_", "update_", "verify_", "check_", "refresh_", "quarantine_",
    "repair_", "cleanup_", "bulk_", "sync_", "prewarm_", "milk_test_",
)
# Explicit SUPPORT modules that don't match a naming family.
_SUPPORT_EXPLICIT: frozenset[str] = frozenset({
    "money", "idempotency", "rate_limiter", "config", "why_today", "smoke_check",
    "typed_config", "runtime_config", "schema_migrations", "snapshot_logger",
    "manual_trade_origin", "manual_decision_board", "operator_auth",
    "operator_control", "supported_currencies", "symbol_normalizer",
    "reflection_frameworks", "daily_payload", "daily_scoring", "trend_engine",
    # Local operator-journal reset maintenance tool (DB + JSONL); dry-run by
    # default, --apply guarded by operator_permission_guard. SUPPORT tooling.
    "reset_local_logs",
})


# Accepted-unknown baseline snapshot. These modules are not yet boundary-
# classified but are KNOWN. A NEW module that is neither CORE/EXPERIMENTAL nor
# matched by a SUPPORT pattern nor in this baseline trips the boundary test,
# forcing an explicit classification decision (clarity, not refactoring).
ACCEPTED_UNKNOWN_BASELINE: frozenset[str] = frozenset({
    # Reviewed (docs/UNKNOWN_MODULE_REVIEW.md): untested legacy backtest
    # experiments, recommendation ARCHIVE_LATER. Left UNKNOWN deliberately so
    # they stay visible as archive candidates rather than being dressed up as
    # SUPPORT. Everything else from the prior 54 is now classified.
    "belief_backtest", "branch_payload",
})


def _stem(path: Path) -> str:
    return path.stem


def new_unknown_modules() -> list[str]:
    """UNKNOWN modules not covered by the accepted baseline (must be classified)."""
    rep = build_report()
    return sorted(m for m in rep["unknown_modules"] if m not in ACCEPTED_UNKNOWN_BASELINE)


def _is_archived(name: str) -> bool:
    return "archived_experimental" in name or name.startswith("tribev2")


def classify(stem: str) -> str:
    if stem in CORE_MODULES:
        return CORE
    if stem in EXPERIMENTAL_MODULES:
        return EXPERIMENTAL
    if stem in _SUPPORT_EXPLICIT or stem in _SUPPORT_REVIEWED:
        return SUPPORT
    for suf in _SUPPORT_SUFFIXES:
        if stem.endswith(suf):
            return SUPPORT
    for pre in _SUPPORT_PREFIXES:
        if stem.startswith(pre):
            return SUPPORT
    return UNKNOWN


def all_module_stems() -> list[str]:
    stems: list[str] = []
    if _SCRIPTS.exists():
        stems += [p.stem for p in sorted(_SCRIPTS.glob("*.py"))]
    if _SRC.exists():
        stems += [f"src::{p.stem}" for p in sorted(_SRC.rglob("*.py")) if p.stem != "__init__"]
    return stems


def core_import_closure() -> set[str]:
    """Transitive set of script modules reachable from any CORE module."""
    seen: set[str] = set()
    frontier = list(CORE_MODULES)
    while frontier:
        cur = frontier.pop()
        path = _SCRIPTS / f"{cur}.py"
        if not path.exists():
            continue
        for imp in _imports_of(path):
            if imp not in seen:
                seen.add(imp)
                frontier.append(imp)
    return seen


def _classify_all() -> dict[str, str]:
    out: dict[str, str] = {}
    closure = core_import_closure()
    for s in all_module_stems():
        if s.startswith("src::"):
            out[s] = SUPPORT  # the legacy src/ scoring shell is support infra
            continue
        c = classify(s)
        # A module CORE actually depends on is, by definition, load-bearing
        # SUPPORT (never left UNKNOWN).
        if c == UNKNOWN and s in closure and s not in EXPERIMENTAL_MODULES:
            c = SUPPORT
        out[s] = c
    return out


def _imports_of(path: Path) -> set[str]:
    """Script-module names imported by a file (best-effort AST)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod.startswith("scripts."):
                names.add(mod.split(".", 2)[1])
            elif "." not in mod:
                names.add(mod)  # script-style `from X import`
            if "archived_experimental" in mod:
                names.add(mod)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("scripts."):
                    names.add(a.name.split(".", 2)[1])
                elif "archived_experimental" in a.name:
                    names.add(a.name)
    return names


def core_import_violations() -> list[str]:
    """CORE modules whose imports reach an EXPERIMENTAL or ARCHIVED module."""
    violations: list[str] = []
    for stem in sorted(CORE_MODULES):
        path = _SCRIPTS / f"{stem}.py"
        if not path.exists():
            continue
        for imp in _imports_of(path):
            if imp in EXPERIMENTAL_MODULES:
                violations.append(f"{stem} imports EXPERIMENTAL {imp}")
            if _is_archived(imp):
                violations.append(f"{stem} imports ARCHIVED {imp}")
    return violations


def build_report() -> dict[str, Any]:
    classified = _classify_all()
    n_total = len(classified)
    n_core = sum(1 for v in classified.values() if v == CORE)
    n_support = sum(1 for v in classified.values() if v == SUPPORT)
    n_exp = sum(1 for v in classified.values() if v == EXPERIMENTAL)
    n_unknown = sum(1 for v in classified.values() if v == UNKNOWN)
    unknown = sorted(k for k, v in classified.items() if v == UNKNOWN)

    k = (n_core + n_support + n_exp) / n_total if n_total else 0.0
    u_penalty = n_unknown / n_total if n_total else 0.0
    h = max(0.0, 1.0 - u_penalty)
    violations = core_import_violations()
    i = 1 if not violations else 0
    ch = 10.0 * (0.60 * h + 0.40 * i)

    return {
        "report": "core_module_boundary",
        "n_total": n_total, "n_core": n_core, "n_support": n_support,
        "n_experimental": n_exp, "n_unknown": n_unknown,
        "classified_fraction_K": k, "unknown_penalty": u_penalty,
        "boundary_clarity_H": h, "import_isolation_I": i,
        "code_hygiene_CH": ch,
        "import_violations": violations,
        "unknown_modules": unknown,
        "advisory_status": "ADVISORY_ONLY", "broker_api_called": False,
        "human_review_required": True,
    }


def main(argv: list[str] | None = None) -> int:
    import json
    rep = build_report()
    print(json.dumps({k: v for k, v in rep.items() if k != "unknown_modules"}, indent=2))
    if rep["unknown_modules"]:
        print(f"\n{len(rep['unknown_modules'])} UNKNOWN modules need classification:")
        for u in rep["unknown_modules"]:
            print(f"  - {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CORE", "SUPPORT", "EXPERIMENTAL", "ARCHIVED", "UNKNOWN",
    "CORE_MODULES", "EXPERIMENTAL_MODULES",
    "classify", "build_report", "core_import_violations",
]
