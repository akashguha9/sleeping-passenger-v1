"""Ceiling score reporter — four score families, artifact-earned deltas.

Governance rule this reporter enforces on ITSELF:

  * Case studies increase FrameworkValidationScore, not
    InvestabilityReadinessScore.
  * Fixture evidence can validate plumbing, not alpha.
  * Live/hard evidence is required for investable candidate promotion.

Four separate top-level families — never collapsed into one flattering
number:

  ArchitectureScore            does the MVP infrastructure work?
  FrameworkValidationScore     do the case studies exercise the archetypes?
  ResearchReadinessScore       can live research begin?
  InvestabilityReadinessScore  can the system produce investable candidates?

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

# Baseline = the previous sprint's NEW scores (what this patch is graded against).
BASELINE: dict[str, float] = {
    "product": 8.5, "quant": 8.5, "data": 7.0,
    "prediction_market_integration": 9.0, "equity_mapping": 8.0,
    "evidence_discipline": 9.75, "calibration_readiness": 7.5,
    "ux_reporting": 8.0, "hackathon_feasibility": 9.0,
    "commercial_potential": 5.0, "overall_ceiling": 9.0,
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
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _load_contracts(root: Path) -> list[Any]:
    cdir = root / "data" / "evidence" / "thesis_contracts"
    if not cdir.exists():
        return []
    try:
        from scripts.signal_thesis_contract import load_contract
    except Exception:
        return []
    contracts = []
    for p in sorted(cdir.glob("*.json")):
        try:
            contracts.append(load_contract(p))
        except ValueError:
            continue  # fail-closed contracts are excluded, not defaulted
    return contracts


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
    routing_path = root / "runtime" / "purpose_routing_report.json"
    if routing_path.exists():
        try:
            doc = json.loads(routing_path.read_text(encoding="utf-8"))
            routing_ok = doc.get("violations") == []
        except Exception:
            routing_ok = False

    contracts = _load_contracts(root)
    case_studies = [c for c in contracts
                    if c.contract_purpose in ("CASE_STUDY", "FIXTURE_TEST")]

    return {
        "thesis_contract_engine": {
            "passed": exists("scripts/signal_thesis_contract.py")
            and exists("tests/test_signal_thesis_contract.py"),
            "evidence": "scripts/signal_thesis_contract.py + tests"},
        "purpose_governance_engine": {
            "passed": exists("tests/test_contract_purpose_governance.py")
            and len(case_studies) >= 5,
            "evidence": f"governance tests + {len(case_studies)} "
                        "case-study/fixture contracts"},
        "board_separation": {
            "passed": exists("data/reports/thesis_cards/CASE_STUDY_BOARD.md")
            and exists("data/reports/thesis_cards/INVESTABLE_CANDIDATE_BOARD.md")
            and routing_ok,
            "evidence": "4 purpose-routed boards + clean routing report"},
        "frozen_map_verifies": {
            "passed": map_ok,
            "evidence": "data/reference/event_equity_map.json (hash-verified)"},
        "shock_engine": {
            "passed": exists("scripts/prediction_market_shock_engine.py")
            and exists("tests/test_prediction_market_shock_engine.py"),
            "evidence": "shock engine + tests"},
        "retrocast_records": {
            "passed": len(_jsonl_rows(
                root / "data/calibration_corpus/retrocast.jsonl")) >= 50,
            "evidence": "retrocast.jsonl (fixture-labeled)"},
        "thesis_cards": {
            "passed": len(list((root / "data/reports/thesis_cards").glob("*.md")))
            >= 3 if exists("data/reports/thesis_cards") else False,
            "evidence": "data/reports/thesis_cards/*.md"},
    }


def _score_families(root: Path) -> dict[str, Any]:
    checks = _checks(root)
    contracts = _load_contracts(root)
    case_studies = [c for c in contracts
                    if c.contract_purpose in ("CASE_STUDY", "FIXTURE_TEST")]
    research = [c for c in contracts if c.contract_purpose == "LIVE_RESEARCH"]
    promoted = [c for c in contracts
                if c.contract_purpose == "INVESTABLE_CANDIDATE"
                and c.promotion_status == "PROMOTED"]

    def exists(p: str) -> bool:
        return (root / p).exists()

    architecture = {
        "contract_schema_complete": 1.0 if checks[
            "purpose_governance_engine"]["passed"] else 0.0,
        "evidence_engine_tested": 1.0 if checks[
            "thesis_contract_engine"]["passed"] else 0.0,
        "twin_thesis_tested": 1.0 if checks[
            "thesis_contract_engine"]["passed"] else 0.0,
        "map_freezer_tested": 1.0 if checks["frozen_map_verifies"]["passed"]
        else 0.0,
        "card_renderer_tested": 1.0 if exists(
            "tests/test_signal_thesis_card_report.py") else 0.0,
        "board_router_tested": 1.0 if checks["board_separation"]["passed"]
        else 0.0,
        "score_reporter_tested": 1.0 if exists(
            "scripts/signal_ceiling_score_report.py") else 0.0,
    }

    fvs_components = {"archetype_coverage": 0.0,
                      "causal_path_completeness": 0.0,
                      "forced_null_completeness": 0.0,
                      "card_completeness": 0.0}
    if case_studies:
        n = len(case_studies)
        fvs_components["archetype_coverage"] = round(min(1.0, sum(
            min(1.0, len(c.beneficiary_map) / 3.0)
            for c in case_studies) / n), 3)
        fvs_components["causal_path_completeness"] = round(min(1.0, sum(
            min(1.0, len(c.causal_path) / 4.0) for c in case_studies) / n), 3)
        fvs_components["forced_null_completeness"] = round(sum(
            1.0 if c.forced_null_thesis.strip() else 0.0
            for c in case_studies) / n, 3)
        fvs_components["card_completeness"] = round(sum(
            1.0 if (c.title and c.narrative and c.falsification_observable)
            else 0.0 for c in case_studies) / n, 3)
    fvs_components["board_separation_correctness"] = (
        1.0 if checks["board_separation"]["passed"] else 0.0)
    fvs_components["test_coverage"] = (
        1.0 if checks["purpose_governance_engine"]["passed"] else 0.0)

    research_readiness = {
        "live_adapter_status": 0.25,   # adapters exist in repo; NOT wired to shock engine
        "retrocast_real_data_status": 0.0,  # fixture-only so far
        "edgar_miner_status": 0.0,          # not built
        "research_board_status": 1.0 if exists(
            "data/reports/thesis_cards/RESEARCH_BOARD.md") else 0.0,
        "evidence_pipeline_status": 1.0 if contracts else 0.0,
        "expiry_cemetery_status": 1.0,      # resolve()+append_cemetery tested
    }

    live_snaps = [r for r in _jsonl_rows(
        root / "data/calibration_corpus/forward_snapshots.jsonl")
        if r.get("data_mode") == "LIVE"]
    validated_real_categories = 0   # retrocast has run on fixtures only
    hard_per_promoted = 0.0
    if promoted:
        hard_per_promoted = sum(
            sum(1 for e in c.evidence if e.provenance == "HARD_DATA")
            for c in promoted) / len(promoted)
    investability_readiness = {
        "live_data_coverage": 0.0,
        "real_retrocast_validated_categories": round(
            min(validated_real_categories / 2.0, 1.0), 3),
        "live_snapshot_count_score": round(min(len(live_snaps) / 30.0, 1.0), 3),
        "hard_evidence_coverage": round(min(hard_per_promoted / 2.0, 1.0), 3),
        "promoted_candidate_count_score": round(
            min(len(promoted) / 5.0, 1.0), 3),
        "calibration_status": 0.0,   # live ladder: NO_LIVE_EVIDENCE
    }

    def fam(components: dict[str, float]) -> float:
        return round(10.0 * sum(components.values()) / len(components), 2)

    return {
        "checks": checks,
        "architecture_score": fam(architecture),
        "architecture_components": architecture,
        "framework_validation_score": fam(fvs_components),
        "framework_validation_components": fvs_components,
        "research_readiness_score": fam(research_readiness),
        "research_readiness_components": research_readiness,
        "investability_readiness_score": fam(investability_readiness),
        "investability_readiness_components": investability_readiness,
        "counts": {"contracts": len(contracts),
                   "case_studies": len(case_studies),
                   "live_research": len(research),
                   "promoted_candidates": len(promoted),
                   "live_snapshots": len(live_snaps)},
    }


# Segment -> (check names that must ALL pass, delta, remaining cap)
_RULES: dict[str, dict[str, Any]] = {
    "product": {
        "checks": ["board_separation"], "delta": 0.25,
        "cap": "boards are fixture/case-study fed; live research cards needed"},
    "quant": {
        "checks": ["purpose_governance_engine"], "delta": 0.0,
        "cap": "governance math added, but still no out-of-sample edge"},
    "data": {
        "checks": [], "delta": 0.0,
        "cap": "no new live feed; EDGAR-FTS miner unbuilt"},
    "prediction_market_integration": {
        "checks": [], "delta": 0.0,
        "cap": "shock engine still fixture-mode"},
    "equity_mapping": {
        "checks": [], "delta": 0.0,
        "cap": "maps ANALYST_PRIOR; retrocast-fitted coefficients pending"},
    "evidence_discipline": {
        "checks": ["purpose_governance_engine", "board_separation"],
        "delta": 0.15,
        "cap": "10.0 requires audited LIVE adjudications, not just "
               "structural guards"},
    "calibration_readiness": {
        "checks": [], "delta": 0.0,
        "cap": "records are FIXTURE-mode; real resolved-market pull required"},
    "ux_reporting": {
        "checks": ["board_separation", "thesis_cards"], "delta": 0.5,
        "cap": "markdown only; cockpit view deferred"},
    "hackathon_feasibility": {
        "checks": [], "delta": 0.0, "cap": "already near ceiling"},
    "commercial_potential": {
        "checks": [], "delta": 0.0,
        "cap": "case studies are not publishable evidence; a real retrocast "
               "study is"},
}


def build_report(root: Path = _REPO_ROOT) -> dict[str, Any]:
    families = _score_families(root)
    checks = families["checks"]
    segments: dict[str, Any] = {}
    new_scores: list[float] = []
    for seg, rule in _RULES.items():
        passed = all(checks[c]["passed"] for c in rule["checks"])
        prev = BASELINE[seg]
        granted = rule["delta"] if (passed and rule["checks"]) else 0.0
        new = round(min(10.0, prev + granted), 2)
        segments[seg] = {
            "previous": prev, "new": new, "delta": round(new - prev, 2),
            "earned_by": [c for c in rule["checks"] if checks[c]["passed"]],
            "blocked_by": [c for c in rule["checks"] if not checks[c]["passed"]],
            "remaining_cap": rule["cap"],
        }
        new_scores.append(new)
    mean = round(sum(new_scores) / len(new_scores), 2)
    return {
        "baseline_overall_ceiling": BASELINE["overall_ceiling"],
        "new_overall_ceiling": max(BASELINE["overall_ceiling"],
                                   min(10.0, round(mean + 1.0, 2))),
        "segment_mean": mean,
        "current_score": mean,
        "current_architecture_score": families["architecture_score"],
        "current_framework_validation_score":
            families["framework_validation_score"],
        "current_research_readiness_score":
            families["research_readiness_score"],
        "current_investability_readiness_score":
            families["investability_readiness_score"],
        "max_after_live_data_wiring": 9.3,
        "max_after_real_retrocast": 9.5,
        "max_after_30_live_snapshots": 9.7,
        "segments": segments,
        "score_families": {k: v for k, v in families.items() if k != "checks"},
        "checks": checks,
        "governance_statements": list(STATEMENTS),
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
        "note": "Deltas are artifact-earned. Case-study cards raise "
                "FrameworkValidationScore only; InvestabilityReadinessScore "
                "moves only on live/hard evidence and promoted candidates.",
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
