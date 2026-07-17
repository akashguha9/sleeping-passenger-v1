"""Closed-loop daily shadow run — the runtime that makes the loop closed.

For each eligible candidate it: builds a MarketObservation, allocates an
intelligence budget (cheap-rejecting weak candidates), runs the six-lens council
at the allocated depth, ranks value-of-information, freezes a Decision Twin with
falsifiable predictions, evaluates immutable shadow policies, scores process
quality, and registers outcome-resolution windows. It returns a bounded operator
summary and a ranked research agenda.

Shadow mode (the default): all predictions are recorded, NO human action is
required, NO broker interaction occurs, outcomes resolve later, calibration
evidence accumulates safely. Advisory-only, record-only — never executes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence import api_surface as api
    from scripts.simulation_intelligence import intelligence_budget as budget_mod
    from scripts.simulation_intelligence import value_of_information as voi_mod
    from scripts.simulation_intelligence import decision_twin as twin_mod
    from scripts.simulation_intelligence import shadow_policies as shadow_mod
    from scripts.simulation_intelligence import process_outcome as po_mod
    from scripts.simulation_intelligence import regime as regime_mod
    from scripts.simulation_intelligence.contracts import MarketObservation, VOTE_DEFENSIVENESS
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence import api_surface as api  # type: ignore[no-redef]
    from simulation_intelligence import intelligence_budget as budget_mod  # type: ignore[no-redef]
    from simulation_intelligence import value_of_information as voi_mod  # type: ignore[no-redef]
    from simulation_intelligence import decision_twin as twin_mod  # type: ignore[no-redef]
    from simulation_intelligence import shadow_policies as shadow_mod  # type: ignore[no-redef]
    from simulation_intelligence import process_outcome as po_mod  # type: ignore[no-redef]
    from simulation_intelligence import regime as regime_mod  # type: ignore[no-redef]
    from simulation_intelligence.contracts import MarketObservation, VOTE_DEFENSIVENESS  # type: ignore[no-redef]

MAX_CANDIDATES = 50


@dataclass(slots=True)
class CandidateResult:
    candidate_id: str
    advisory_state: str
    analysis_depth: str
    priority_score: float
    rejected_cheaply: bool
    twin: dict[str, Any] | None
    research_priority: dict[str, Any] | None
    shadow_decisions: list[dict[str, Any]]
    process_quality: dict[str, Any] | None
    outcome_jobs: list[dict[str, Any]]
    regime_key: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _observation_from_payload(p: dict[str, Any]) -> MarketObservation:
    return api.build_observation(p)


def run_candidate(
    payload: dict[str, Any],
    *,
    session_date: str,
    calibration_reliability: float | None = None,
    seed: int = 0,
) -> CandidateResult:
    """Run the full closed-loop analysis for one candidate. Deterministic."""
    obs = _observation_from_payload(payload)
    reg = regime_mod.classify_regime(obs)

    # 1. Cheap prescreen + budget allocation (before the expensive council).
    prelim = budget_mod.allocate(
        obs, uncertainty=0.5, tail_risk=0.0, value_of_information=0.0,
        redundancy=1.0 - min(int(obs.source_count or 0), 5) / 5.0)
    if prelim.analysis_depth == "REJECT_CHEAP":
        return CandidateResult(
            candidate_id=obs.ticker, advisory_state="AVOID",
            analysis_depth="REJECT_CHEAP", priority_score=prelim.priority_score,
            rejected_cheaply=True, twin=None, research_priority=None,
            shadow_decisions=[], process_quality=None, outcome_jobs=[],
            regime_key=reg.regime_key)

    # 2. Run the council at the allocated depth (bounded scenarios).
    council = api.run_simulation({
        "ticker": obs.ticker, "market": obs.market, "seed": seed,
        "observation": obs.to_dict(),
        "max_runs": 512 if prelim.analysis_depth == "DEEP" else 256,
    })
    frag = float(council.get("fragility", 0.0) or 0.0)
    tail = 1.0 if council.get("tail_warnings") else (0.5 if council.get("risk_block_engaged") else 0.1)

    # 3. Value of information (with the redundancy/calibration surprise).
    rp = voi_mod.rank_information(obs, council, budget=0.5,
                                 calibration_reliability=calibration_reliability)
    top_voi = rp.ranked[0].net_voi if rp.ranked else 0.0

    # 4. Re-allocate budget now that we know tail risk + VoI (records the decision).
    final_budget = budget_mod.allocate(
        obs, prescreen_confidence=float(council.get("aggregate_confidence", 0.5) or 0.5),
        uncertainty=frag, tail_risk=tail, value_of_information=max(0.0, top_voi),
        redundancy=rp.ranked[0].redundancy_discount if rp.ranked else 0.5)

    # 5. Freeze the Decision Twin (+ falsifiable predictions).
    twin = twin_mod.build_twin(council, obs, top_research_action={
        "item": rp.top_action, "verdict": rp.verdict,
        "net_voi": top_voi, "note": rp.note})

    # 6. Immutable shadow-policy decisions.
    shadow = [d.to_dict() for d in shadow_mod.evaluate_policies(council, twin.twin_id)]

    # 7. Process quality (outcome-independent).
    pq = po_mod.score_process(obs, council, twin.to_dict())

    # 8. Register outcome-resolution jobs (one per frozen price-resolvable prediction).
    jobs = []
    for pred in twin.predictions:
        jobs.append({
            "prediction_id": pred.prediction_id, "twin_id": twin.twin_id,
            "candidate_id": obs.ticker, "info_cutoff": pred.info_cutoff,
            "outcome_window_days": pred.outcome_window_days,
            "resolution_method": pred.resolution_method, "status": "REGISTERED",
        })

    return CandidateResult(
        candidate_id=obs.ticker, advisory_state=twin.advisory_state,
        analysis_depth=final_budget.analysis_depth,
        priority_score=final_budget.priority_score, rejected_cheaply=False,
        twin=twin.to_dict(), research_priority=rp.to_dict(),
        shadow_decisions=shadow, process_quality=pq.to_dict(), outcome_jobs=jobs,
        regime_key=reg.regime_key)


def run_daily_shadow(
    candidates: list[dict[str, Any]],
    *,
    session_date: str,
    seed: int = 0,
) -> dict[str, Any]:
    """Run the closed loop over a bounded list of candidates. Returns a bounded
    operator summary + ranked research agenda. Shadow mode: no action required."""
    if not api.flags.sil_enabled():
        return {"report": "daily_shadow_run", "ok": False, "error": "sil_disabled",
                **advisory_safety_stamps()}
    cands = list(candidates or [])[:MAX_CANDIDATES]
    results = [run_candidate(c, session_date=session_date, seed=seed) for c in cands]

    ranked = sorted(results, key=lambda r: -r.priority_score)
    rejected = [r for r in results if r.rejected_cheaply]
    analysed = [r for r in results if not r.rejected_cheaply]
    all_jobs = [j for r in analysed for j in r.outcome_jobs]

    # Operator agenda: the single most valuable next research action across the day.
    research_actions = []
    for r in analysed:
        rp = r.research_priority or {}
        if rp.get("verdict") == "ACQUIRE":
            top = (rp.get("ranked") or [{}])[0]
            research_actions.append({
                "candidate": r.candidate_id, "action": rp.get("top_action"),
                "net_voi": top.get("net_voi", 0.0)})
    research_actions.sort(key=lambda a: -a.get("net_voi", 0.0))

    summary = {
        "report": "daily_shadow_run", "ok": True, "mode": "shadow",
        "session_date": session_date,
        "candidates_considered": len(results),
        "rejected_cheaply": len(rejected),
        "analysed": len(analysed),
        "twins_created": sum(1 for r in analysed if r.twin),
        "predictions_frozen": sum(len(r.outcome_jobs) for r in analysed),
        "outcome_jobs_registered": len(all_jobs),
        "attention_queue": [{
            "candidate": r.candidate_id, "advisory_state": r.advisory_state,
            "priority": r.priority_score, "depth": r.analysis_depth,
            "regime": r.regime_key,
            "process_quality": (r.process_quality or {}).get("score"),
        } for r in ranked[:20]],
        "top_research_actions": research_actions[:5],
        "no_research_needed": [r.candidate_id for r in analysed
                               if (r.research_priority or {}).get("verdict") in
                               ("NO_RESEARCH_WORTHWHILE",)],
        "results": [r.to_dict() for r in results],
        "human_action_required": False,
    }
    summary.update(advisory_safety_stamps())
    return summary


__all__ = ["CandidateResult", "run_candidate", "run_daily_shadow", "MAX_CANDIDATES"]
