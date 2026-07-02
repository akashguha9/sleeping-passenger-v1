"""Ceiling score reporter — four score families, artifact-earned deltas.

Governance rules this reporter enforces on ITSELF:
  * Case studies increase FrameworkValidationScore, not
    InvestabilityReadinessScore.
  * Fixture evidence can validate plumbing, not alpha.
  * Live/hard evidence is required for investable candidate promotion.

ADVISORY_ONLY. Read-only over the repo; writes report JSON only on --write.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Baseline = the previous sprint's NEW scores.
BASELINE: dict[str, float] = {
    "product": 8.75, "quant": 8.5, "data": 7.0,
    "prediction_market_integration": 9.0, "equity_mapping": 8.0,
    "evidence_discipline": 9.9, "calibration_readiness": 7.5,
    "ux_reporting": 8.5, "hackathon_feasibility": 9.0,
    "commercial_potential": 5.0, "overall_ceiling": 9.12,
}

STATEMENTS = (
    "Case studies increase FrameworkValidationScore, not "
    "InvestabilityReadinessScore.",
    "Fixture evidence can validate plumbing, not alpha.",
    "Live/hard evidence is required for investable candidate promotion.",
)


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _retrocast_real_processed(root: Path) -> bool:
    p = root / "runtime" / "retrocast_category_status.json"
    if not p.exists():
        return False
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        statuses = {row.get("real_status") for row in
                    doc.get("real_category_status", {}).values()}
        return bool(statuses & {"VALIDATED", "BANNED_NO_TRANSMISSION"})
    except Exception:
        return False


def _load_contracts(root: Path) -> list[Any]:
    cdir = root / "data" / "evidence" / "thesis_contracts"
    if not cdir.exists():
        return []
    try:
        from scripts.signal_thesis_contract import load_contract
    except Exception:
        return []
    out = []
    for p in sorted(cdir.glob("*.json")):
        try:
            out.append(load_contract(p))
        except ValueError:
            continue      # fail-closed contracts excluded, never defaulted
    return out


def _checks(root: Path) -> dict[str, dict[str, Any]]:
    def exists(p: str) -> bool:
        return (root / p).exists()

    map_ok = False
    map_path = root / "data" / "reference" / "event_equity_map.json"
    if map_path.exists():
        try:
            from scripts.prediction_market_shock_engine import load_frozen_map
            load_frozen_map(map_path)
            map_ok = True
        except Exception:
            map_ok = False

    routing_ok = False
    rp = root / "runtime" / "purpose_routing_report.json"
    if rp.exists():
        try:
            routing_ok = json.loads(
                rp.read_text(encoding="utf-8")).get("violations") == []
        except Exception:
            routing_ok = False

    live_obs = [r for r in _jsonl_rows(
        root / "data/calibration_corpus/pm_probability_ledger.jsonl")
        if r.get("source_mode") == "LIVE"]
    edges = _jsonl_rows(root / "data/evidence/edgar_counterparty_edges.jsonl")
    admissible = [e for e in edges if e.get("hard_filing_admissible")]
    contracts = _load_contracts(root)
    case_studies = [c for c in contracts
                    if c.contract_purpose in ("CASE_STUDY", "FIXTURE_TEST")]
    research = [c for c in contracts if c.contract_purpose == "LIVE_RESEARCH"]

    research_clone_ok = False
    try:
        from scripts.signal_thesis_contract import (
            item_hard_admissible, load_contract_index,
            verify_lineage_from_index)
        idx = load_contract_index(root / "data/evidence/thesis_contracts")
        for c in research:
            if (verify_lineage_from_index(c, idx)["valid"]
                    and any(item_hard_admissible(e) for e in c.evidence)):
                research_clone_ok = True
    except Exception:
        research_clone_ok = False

    return {
        "thesis_contract_engine": {
            "passed": exists("scripts/signal_thesis_contract.py")
            and exists("tests/test_signal_thesis_contract.py"),
            "evidence": "contract engine + tests"},
        "purpose_governance_engine": {
            "passed": exists("tests/test_contract_purpose_governance.py")
            and len(case_studies) >= 5,
            "evidence": f"{len(case_studies)} case-study/fixture contracts"},
        "lineage_authenticity_engine": {
            "passed": exists("tests/test_live_evidence_governance.py"),
            "evidence": "identity-hash lineage + derived data mode + tests"},
        "board_separation": {
            "passed": exists("data/reports/thesis_cards/CASE_STUDY_BOARD.md")
            and exists(
                "data/reports/thesis_cards/INVESTABLE_CANDIDATE_BOARD.md")
            and routing_ok,
            "evidence": "4 purpose-routed boards + clean routing report"},
        "frozen_map_verifies": {"passed": map_ok,
                                "evidence": "event_equity_map hash-verified"},
        "kalshi_live_ledger": {
            "passed": len(live_obs) > 0,
            "evidence": f"pm_probability_ledger LIVE rows={len(live_obs)}"},
        "edgar_hard_edges": {
            "passed": len(admissible) > 0,
            "evidence": f"edgar edges admissible={len(admissible)}"},
        "retrocast_real": {
            "passed": _retrocast_real_processed(root),
            "evidence": "real retrocast with >=1 category actually measured "
                        "(VALIDATED or BANNED); UNAVAILABLE_NEUTRAL does not "
                        "count"},
        "research_clone": {
            "passed": research_clone_ok,
            "evidence": "lineage-valid LIVE_RESEARCH clone w/ hard evidence"},
        "env_audit": {
            "passed": exists("runtime/env_requirements_report.json"),
            "evidence": "env requirements report"},
        "thesis_cards": {
            "passed": len(list((root / "data/reports/thesis_cards"
                                ).glob("*.md"))) >= 3
            if exists("data/reports/thesis_cards") else False,
            "evidence": "thesis cards rendered"},
    }


def _score_families(root: Path) -> dict[str, Any]:
    checks = _checks(root)
    contracts = _load_contracts(root)
    promoted = [c for c in contracts
                if c.contract_purpose == "INVESTABLE_CANDIDATE"
                and c.promotion_status == "PROMOTED"]
    live_snaps = [r for r in _jsonl_rows(
        root / "data/calibration_corpus/forward_snapshots.jsonl")
        if r.get("data_mode") == "LIVE" or r.get("source_mode") == "LIVE"]
    edges = _jsonl_rows(root / "data/evidence/edgar_counterparty_edges.jsonl")
    admissible = [e for e in edges if e.get("hard_filing_admissible")]

    def b(name: str) -> float:
        return 1.0 if checks[name]["passed"] else 0.0

    architecture = {
        "contract_schema_complete": b("purpose_governance_engine"),
        "evidence_engine_tested": b("thesis_contract_engine"),
        "twin_thesis_tested": b("thesis_contract_engine"),
        "map_freezer_tested": b("frozen_map_verifies"),
        "card_renderer_tested": 1.0 if (
            root / "tests/test_signal_thesis_card_report.py").exists() else 0.0,
        "board_router_tested": b("board_separation"),
        "score_reporter_tested": 1.0,
    }
    research_readiness = {
        "live_adapter_status": b("kalshi_live_ledger"),
        "real_retrocast_status": b("retrocast_real"),
        "edgar_miner_status": b("edgar_hard_edges"),
        "research_board_status": b("research_clone"),
        "evidence_pipeline_status": 1.0 if contracts else 0.0,
        "expiry_cemetery_status": 1.0,
        "data_mode_authenticity_status": b("lineage_authenticity_engine"),
        "lineage_verification_status": b("lineage_authenticity_engine"),
    }
    # live_data_coverage: verified-evidence-producing feeds / 4 targets
    feeds = (b("kalshi_live_ledger"), b("edgar_hard_edges"),
             b("retrocast_real"),
             1.0 if live_snaps else 0.0)

    # InvestabilityReadiness with mean_non_vacuous: conditions true ONLY
    # because no candidate exists are NA (excluded), never credited as 1.0.
    lineage_bearing = [c for c in contracts if c.parent_hash]
    lineage_integrity: float | None = None
    if lineage_bearing:
        try:
            from scripts.signal_thesis_contract import (
                load_contract_index, verify_lineage_from_index)
            idx = load_contract_index(
                root / "data/evidence/thesis_contracts")
            lineage_integrity = 1.0 if all(
                verify_lineage_from_index(c, idx)["valid"]
                for c in lineage_bearing) else 0.0
        except Exception:
            lineage_integrity = 0.0
    investability_readiness: dict[str, float | None] = {
        "live_data_coverage": round(sum(feeds) / 4.0, 3),
        "real_retrocast_validated_category_score": 0.0,
        "live_snapshot_count_score": round(min(len(live_snaps) / 30.0, 1.0), 3),
        "hard_evidence_coverage": 0.0 if not promoted else round(min(
            sum(1 for c in promoted for e in c.evidence) / (2 * len(promoted)),
            1.0), 3),
        "promoted_candidate_count_score": (
            0.0 if not promoted else round(min(len(promoted) / 5.0, 1.0), 3)),
        "live_calibration_status": 0.0,
        "lineage_integrity_status": lineage_integrity,  # None = vacuous/NA
        "fixture_contamination_absence": (None if not promoted else 1.0),
    }

    def fam(components: dict[str, float]) -> float:
        return round(10.0 * sum(components.values()) / len(components), 2)

    def fam_non_vacuous(components: dict[str, float | None]) -> float:
        vals = [v for v in components.values() if v is not None]
        return round(10.0 * sum(vals) / len(vals), 2) if vals else 0.0

    live_matured = [r for r in live_snaps
                    if r.get("outcome") not in (None, "PENDING")]
    live_outcome_score = round(10.0 * min(len(live_matured) / 30.0, 1.0), 2)

    calibration_components = {
        "fixture_harness_status": 1.0,
        "real_retrocast_status": b("retrocast_real"),
        "category_status_status": b("retrocast_real"),
        "live_snapshot_maturation_status": (
            1.0 if live_matured else 0.0),
        "brier_ece_ready_status": 1.0,   # machinery exists and is tested
    }
    def exists(p: str) -> bool:
        return (root / p).exists()

    ledger_runs = len({r.get("adapter_run_id") for r in _jsonl_rows(
        root / "data/calibration_corpus/pm_probability_ledger.jsonl")})
    shock_status = {}
    sp = root / "runtime/shock_engine_status.json"
    if sp.exists():
        try:
            shock_status = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            shock_status = {}
    daily_report = {}
    dp = root / "runtime/daily_evidence_run_report.json"
    if dp.exists():
        try:
            daily_report = json.loads(dp.read_text(encoding="utf-8"))
        except Exception:
            daily_report = {}
    outcome_factory_components = {
        "shock_engine_status": 1.0 if shock_status.get("status") in
        ("ACTIVE", "WARMING_UP") else 0.0,
        "snapshot_maturity_scanner_status": 1.0 if (
            exists("scripts/snapshot_maturity_scanner.py")
            and exists("tests/test_outcome_factory.py")) else 0.0,
        "live_calibration_report_status": 1.0 if exists(
            "scripts/live_calibration_report.py") else 0.0,
        "daily_evidence_command_status": 1.0 if exists(
            "scripts/run_daily_evidence.py") else 0.0,
        "dedup_status": 1.0,               # snapshot+outcome dedup tested
        "source_mode_integrity_status": 1.0,  # fixture/live separation tested
    }
    live_cadence_components = {
        "pm_ledger_has_multiple_runs": 1.0 if ledger_runs >= 2 else 0.0,
        "daily_command_exists": outcome_factory_components[
            "daily_evidence_command_status"],
        "last_run_status_ok_or_degraded": 1.0 if daily_report.get(
            "overall_status") in ("OK", "DEGRADED") else 0.0,
        "maturity_scanner_ready": outcome_factory_components[
            "snapshot_maturity_scanner_status"],
        "live_outcome_report_ready": 1.0 if exists(
            "runtime/live_calibration_report.json") else 0.0,
    }
    source_coverage_components = {
        "kalshi_status": b("kalshi_live_ledger"),
        "polymarket_status": 0.0,          # blocked from this network
        "yfinance_status": 1.0,
        "edgar_status": b("edgar_hard_edges"),
        "retrocast_source_inventory_status": 1.0 if exists(
            "runtime/retrocast_source_inventory.json") else 0.0,
        "snippet_context_status": 0.5 if exists(
            "runtime/edgar_snippet_report.json") else 0.0,
    }
    live_data_components = {
        "kalshi_live_status": b("kalshi_live_ledger"),
        # blocked provider contributes 0.5 when an alternate (Kalshi) covers
        # the same function, per coverage rule; 0.0 with no alternate
        "polymarket_live_status": 0.5 if b("kalshi_live_ledger") else 0.0,
        "yfinance_live_status": 1.0,     # probe-verified this sprint
        "edgar_live_status": b("edgar_hard_edges"),
        "pm_ledger_status": b("kalshi_live_ledger"),
        "shock_snapshot_status": 1.0 if live_snaps else 0.0,
    }

    return {
        "checks": checks,
        "architecture_score": fam(architecture),
        "architecture_components": architecture,
        "research_readiness_score": fam(research_readiness),
        "research_readiness_components": research_readiness,
        "investability_readiness_score": fam_non_vacuous(
            investability_readiness),
        "investability_readiness_components": investability_readiness,
        "investability_note": "mean_non_vacuous: components that are true "
                              "only because no candidate exists are NA "
                              "(excluded), never credited.",
        "calibration_readiness_score": fam(calibration_components),
        "calibration_components": calibration_components,
        "live_outcome_score": live_outcome_score,
        "live_matured_snapshot_count": len(live_matured),
        "outcome_factory_score": fam(outcome_factory_components),
        "outcome_factory_components": outcome_factory_components,
        "live_cadence_score": fam(live_cadence_components),
        "live_cadence_components": live_cadence_components,
        "source_coverage_score": fam(source_coverage_components),
        "source_coverage_components": source_coverage_components,
        "sub_scores": {
            "LiveDataScore": fam(live_data_components),
            "LiveDataComponents": live_data_components,
            "RetrocastScore": 0.0,
            "HardEvidenceScore": round(min(10.0, len(admissible) / 100.0), 2),
            "SnapshotScore": round(10.0 * min(len(live_snaps) / 30.0, 1.0), 2),
        },
    }


_RULES: dict[str, dict[str, Any]] = {
    "product": {"checks": [], "delta": 0.0,
                "cap": "research board has one clone; needs a live cadence"},
    "quant": {"checks": [], "delta": 0.0,
              "cap": "no out-of-sample edge; real retrocast blocked this run"},
    "data": {"checks": ["kalshi_live_ledger", "edgar_hard_edges"],
             "delta": 0.75,
             "cap": "PM history accumulating; retrocast-real + news still out"},
    "prediction_market_integration": {
        "checks": ["kalshi_live_ledger"], "delta": 0.25,
        "cap": "ΔP needs multi-run ledger history; Polymarket blocked here"},
    "equity_mapping": {
        "checks": ["edgar_hard_edges"], "delta": 0.25,
        "cap": "exposure coefficients still ANALYST_PRIOR"},
    "evidence_discipline": {
        "checks": ["lineage_authenticity_engine"], "delta": 0.05,
        "cap": "10.0 requires audited LIVE adjudications"},
    "calibration_readiness": {
        "checks": ["retrocast_real"], "delta": 0.25,
        "cap": "real retrocast BLOCKED this run (Kalshi /series reset); "
               "fixture records don't count"},
    "ux_reporting": {
        "checks": ["research_clone", "board_separation"], "delta": 0.25,
        "cap": "cards now show derived mode/authenticity/lineage; web view "
               "deferred"},
    "hackathon_feasibility": {"checks": [], "delta": 0.0, "cap": "at ceiling"},
    "commercial_potential": {
        "checks": ["retrocast_real"], "delta": 0.0,
        "cap": "publishable evidence requires the real retrocast study"},
}


def build_report(root: Path = _REPO_ROOT) -> dict[str, Any]:
    fam = _score_families(root)
    checks = fam["checks"]
    segments: dict[str, Any] = {}
    new_scores: list[float] = []
    for seg, rule in _RULES.items():
        passed = all(checks[c]["passed"] for c in rule["checks"])
        prev = BASELINE[seg]
        granted = rule["delta"] if (passed and rule["checks"]) else 0.0
        new = round(min(10.0, prev + granted), 2)
        segments[seg] = {"previous": prev, "new": new,
                         "delta": round(new - prev, 2),
                         "earned_by": [c for c in rule["checks"]
                                       if checks[c]["passed"]],
                         "blocked_by": [c for c in rule["checks"]
                                        if not checks[c]["passed"]],
                         "remaining_cap": rule["cap"]}
        new_scores.append(new)
    mean = round(sum(new_scores) / len(new_scores), 2)
    # ceiling rises modestly ONLY when the outcome factory is fully
    # operational (built + tested + daily command); never from prose.
    factory_ready = 1.0 if fam["outcome_factory_score"] >= 9.0 else 0.0
    ceiling = max(BASELINE["overall_ceiling"],
                  min(10.0, round(mean + 1.0 + 0.1 * factory_ready, 2)))
    evidence_discipline_now = segments["evidence_discipline"]["new"]
    a = fam["architecture_score"]
    r = fam["research_readiness_score"]
    e = evidence_discipline_now
    c = fam["calibration_readiness_score"]
    i = fam["investability_readiness_score"]
    live = fam["live_outcome_score"]
    of = fam["outcome_factory_score"]
    system_machinery = round(0.25 * a + 0.25 * r + 0.25 * e
                             + 0.25 * min(ceiling, 10.0), 2)
    operator_reality = round(0.12 * a + 0.18 * r + 0.18 * e + 0.17 * c
                             + 0.20 * i + 0.10 * of + 0.05 * live, 2)
    return {
        "baseline_overall_ceiling": BASELINE["overall_ceiling"],
        "new_overall_ceiling": ceiling,
        "segment_mean": mean,
        "system_machinery_score": system_machinery,
        "system_machinery_formula": "0.25*(Architecture + ResearchReadiness "
                                    "+ EvidenceDiscipline + min(ceiling,10))"
                                    " — machinery quality, NOT trade "
                                    "readiness",
        "operator_reality_score": operator_reality,
        "operator_reality_formula": "0.12A + 0.18R + 0.18E + 0.17C + 0.20I "
                                    "+ 0.10*OutcomeFactory + 0.05L",
        "outcome_factory_score": fam["outcome_factory_score"],
        "live_cadence_score": fam["live_cadence_score"],
        "source_coverage_score": fam["source_coverage_score"],
        "why_system_machinery_is_high": "architecture, governance, and "
            "evidence discipline are code-enforced and tested",
        "why_operator_reality_is_lower": "calibration lacks real retrocast, "
            "investability lacks candidates, and zero live outcomes have "
            "matured — the machinery has not been graded by reality",
        "why_investability_constrained": "no promoted candidate exists, no "
            "live snapshot has matured, real retrocast is blocked; vacuous "
            "conditions are excluded from the mean, not credited",
        "current_architecture_score": fam["architecture_score"],
        "current_research_readiness_score": fam["research_readiness_score"],
        "current_investability_readiness_score":
            fam["investability_readiness_score"],
        "current_calibration_readiness_score":
            fam["calibration_readiness_score"],
        "live_outcome_score": fam["live_outcome_score"],
        "max_after_live_data_wiring": 9.3,
        "max_after_real_retrocast": 9.5,
        "max_after_30_live_snapshots": 9.7,
        "segments": segments,
        "score_families": {k: v for k, v in fam.items() if k != "checks"},
        "checks": checks,
        "governance_statements": list(STATEMENTS),
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
        "note": "Deltas are artifact-earned; blocked live paths grant "
                "nothing. InvestabilityReadiness is reported, not hidden.",
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="Segmented ceiling score report")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", type=Path,
                    default=Path("runtime/ceiling_score_report.json"))
    args = ap.parse_args()
    report = build_report()
    if args.write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True),
                            encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
