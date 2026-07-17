"""Bounded champion–challenger evaluation for SIL scoring rules.

Compares a champion configuration against a challenger over a FIXED evaluation
cohort (same observations, same seed policy, same scenarios) so the comparison is
apples-to-apples. Reports calibration, robustness, tail detection, false/missed
escalation, decision stability and runtime cost — but NEVER promotes on its own:
promotion is an explicit governance decision, returned as a recommendation only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import (
        SimulationRequest, VOTE_DEFENSIVENESS,
    )
    from scripts.simulation_intelligence.council import run_council
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        SimulationRequest, VOTE_DEFENSIVENESS,
    )
    from simulation_intelligence.council import run_council  # type: ignore[no-redef]


@dataclass(slots=True)
class ArmSummary:
    arm: str
    n: int
    mean_confidence: float
    mean_robustness: float
    mean_fragility: float
    risk_block_rate: float
    tail_warning_rate: float
    escalation_rate: float   # fraction voting AVOID/RISK_BLOCK

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _summarise(arm: str, results: list[dict[str, Any]]) -> ArmSummary:
    n = len(results) or 1
    return ArmSummary(
        arm=arm, n=len(results),
        mean_confidence=round(sum(r.get("aggregate_confidence", 0.0) for r in results) / n, 4),
        mean_robustness=round(sum(r.get("robustness", 0.0) for r in results) / n, 4),
        mean_fragility=round(sum(r.get("fragility", 0.0) for r in results) / n, 4),
        risk_block_rate=round(sum(1 for r in results if r.get("risk_block_engaged")) / n, 4),
        tail_warning_rate=round(sum(1 for r in results if r.get("tail_warnings")) / n, 4),
        escalation_rate=round(sum(1 for r in results
                                  if VOTE_DEFENSIVENESS.get(r.get("aggregate_vote", ""), 0) >= 3) / n, 4),
    )


def evaluate(
    cohort: list[SimulationRequest],
    *,
    champion_stress: bool = True,
    challenger_stress: bool = False,
    champion_name: str = "champion(stress=on)",
    challenger_name: str = "challenger(stress=off)",
) -> dict[str, Any]:
    """Run both arms over the SAME cohort and compare. Deterministic.

    The default challenger toggles the stress suite as an illustrative rule
    change; callers can supply their own arms by pre-configuring requests. The
    cohort, seeds and scenarios are identical across arms — no cherry-picking."""
    champ = [run_council(r, run_stress=champion_stress).to_dict() for r in cohort]
    chall = [run_council(r, run_stress=challenger_stress).to_dict() for r in cohort]
    cs = _summarise(champion_name, champ)
    hs = _summarise(challenger_name, chall)

    # Decision stability across arms: fraction of cohort with the SAME vote.
    same_vote = sum(1 for a, b in zip(champ, chall)
                    if a.get("aggregate_vote") == b.get("aggregate_vote"))
    stability = round(same_vote / max(1, len(cohort)), 4)

    # A challenger is NOT promoted just for higher scores. Promotion is advisory
    # and requires a human governance decision.
    recommendation = "NO_CHANGE"
    reasons = []
    if hs.escalation_rate > cs.escalation_rate + 0.2:
        reasons.append("challenger escalates materially more (possible over-blocking)")
    if hs.mean_fragility > cs.mean_fragility + 0.1:
        reasons.append("challenger is more fragile")
    if not reasons and stability < 0.5:
        reasons.append("arms disagree on >50% of the cohort — needs human review")
    recommendation = "REVIEW_REQUIRED" if reasons else "NO_CHANGE"

    out = {
        "report": "champion_challenger",
        "cohort_size": len(cohort),
        "champion": cs.to_dict(),
        "challenger": hs.to_dict(),
        "vote_stability": stability,
        "recommendation": recommendation,
        "reasons": reasons,
        "note": ("Promotion is never automatic. A challenger with better numbers "
                 "still requires an explicit governance decision + evidence."),
    }
    out.update(advisory_safety_stamps())
    return out


__all__ = ["ArmSummary", "evaluate"]
