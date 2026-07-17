"""Value-of-Information engine — turn uncertainty into a BOUNDED research agenda.

The council can say *what* is uncertain; this says *which missing information is
worth obtaining next*, and can conclude that **no research is currently worth the
cost**. It ranks a fixed catalogue of information items under a bounded budget.

The surprise (see docs/eureka_limitations.md — discovered by noticing naive VoI
recommends acquiring evidence the system already effectively has):
VoI is **redundancy-discounted** and **calibration-aware**:
  * an item that merely duplicates existing (concentrated) evidence gets its value
    cut by a redundancy discount — you don't pay to learn what you already know;
  * VoI is amplified where the system is *poorly calibrated* in this regime (its
    beliefs there are untrustworthy, so reducing epistemic uncertainty is worth
    more) and damped where it is well-calibrated — coupling research to learning.

Pure/deterministic. Bounded output. Never an endless checklist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import MarketObservation, VOTE_DEFENSIVENESS
    from scripts.simulation_intelligence import actionable_uncertainty as unc_mod
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import MarketObservation, VOTE_DEFENSIVENESS  # type: ignore[no-redef]
    from simulation_intelligence import actionable_uncertainty as unc_mod  # type: ignore[no-redef]

_COST = {"LOW": 0.1, "MEDIUM": 0.35, "HIGH": 0.7}

# Fixed information catalogue: each item targets an uncertainty kind and declares
# its acquisition cost, freshness requirement, reliability, and inherent
# redundancy risk (how likely it duplicates evidence the system already has).
_CATALOGUE = [
    ("new_filing",            "epistemic",         "MEDIUM", 0.9, 0.15),
    ("earnings_transcript",   "epistemic",         "MEDIUM", 0.85, 0.2),
    ("management_guidance",   "epistemic",         "MEDIUM", 0.8, 0.25),
    ("competitor_filing",     "model_disagreement","MEDIUM", 0.7, 0.35),
    ("sector_data",           "model_disagreement","LOW",    0.7, 0.45),
    ("updated_price_data",    "data_quality",      "LOW",    0.95, 0.3),
    ("volume_confirmation",   "data_quality",      "LOW",    0.9, 0.4),
    ("macro_release",         "regime",            "MEDIUM", 0.75, 0.3),
    ("regulatory_update",     "epistemic",         "HIGH",   0.85, 0.2),
    ("alternative_source",    "model_disagreement","MEDIUM", 0.6, 0.2),
    ("governance_evidence",   "epistemic",         "HIGH",   0.8, 0.15),
    ("supply_chain_data",     "model_disagreement","HIGH",   0.65, 0.35),
    ("analyst_dispersion",    "model_disagreement","LOW",    0.6, 0.5),
    ("better_benchmark",      "outcome_definition","LOW",    0.7, 0.4),
]


def _clip(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, f)) if f == f else lo


@dataclass(slots=True)
class ValueOfInformationEstimate:
    item: str
    targets_uncertainty: str
    decision_change_probability: float
    expected_uncertainty_reduction: float
    expected_regret_reduction: float
    tail_relevance: float
    redundancy_discount: float       # surprise: cut for duplicating existing evidence
    calibration_amplifier: float     # surprise: >1 when poorly calibrated in regime
    acquisition_cost: float
    raw_voi: float
    net_voi: float                   # after discount, amplifier, cost
    worth_acquiring: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class ResearchPriority:
    candidate_id: str
    ranked: list[ValueOfInformationEstimate]
    top_action: str                  # item name or "NO_RESEARCH_WORTHWHILE"
    verdict: str                     # ACQUIRE | NO_RESEARCH_WORTHWHILE | WAIT_FOR_CATALYST
    budget: float
    spent_if_top: float
    reducible_fraction: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__ if k != "ranked"}
        d["ranked"] = [e.to_dict() for e in self.ranked]
        d.update(advisory_safety_stamps())
        return d


def rank_information(
    obs: MarketObservation,
    council: dict[str, Any],
    *,
    budget: float = 0.5,
    calibration_reliability: float | None = None,
) -> ResearchPriority:
    """Rank information items by net VoI under a bounded budget.

    ``calibration_reliability`` (0..1) is the system's measured calibration in this
    regime cohort; when None (no/low-sample calibration) a conservative neutral
    prior (0.5) is used so VoI is neither over- nor under-amplified.
    """
    profile = unc_mod.decompose(obs, council)
    unc_by_kind = {c.kind: c for c in profile.components}
    vote = council.get("aggregate_vote", "WATCH")
    frag = _clip(council.get("fragility", 0.5))
    dis = council.get("disagreement_class", "")
    near_boundary = frag >= 0.5 or dis in ("SPLIT_DECISION", "CONSENSUS_FRAGILE",
                                           "MINORITY_TAIL_WARNING")

    # Redundancy proxy: few independent sources → new correlated evidence is more
    # redundant. But redundancy is NOT only source overlap — when the council
    # already holds a robust, well-sourced consensus, additional information
    # largely tells the system what it already believes, so redundancy rises.
    src = int(obs.source_count or 0)
    base_redundancy = _clip(1.0 - min(src, 5) / 5.0)  # 0 sources → 1.0, 5+ → 0.0
    robust_consensus = (not near_boundary) and dis in (
        "CONSENSUS_ROBUST", "SIMULATION_ONLY_CONSENSUS", "")
    if robust_consensus and src >= 4:
        # Convergent, well-sourced beliefs → new info is largely redundant.
        base_redundancy = _clip(base_redundancy + 0.5)

    # Calibration amplifier: poorly calibrated (low reliability) → amplify epistemic
    # research value; well-calibrated → damp it. Neutral prior 0.5 → amplifier 1.0.
    reliab = 0.5 if calibration_reliability is None else _clip(calibration_reliability)
    cal_amp = round(0.6 + (1.0 - reliab), 3)  # reliab 1.0→0.6, 0.5→1.1, 0.0→1.6

    tail_present = bool(council.get("tail_warnings"))
    estimates: list[ValueOfInformationEstimate] = []
    for item, kind, cost_band, reliability, red_risk in _CATALOGUE:
        uc = unc_by_kind.get(kind)
        if uc is None or not uc.reducible:
            continue  # only reducible uncertainty is researchable
        # Expected uncertainty reduction: proportional to the targeted magnitude
        # and the item's reliability, capped.
        eur = _clip(uc.magnitude * reliability * 0.8)
        # Decision-change probability: higher near a boundary AND when the item
        # targets a decision-relevant uncertainty.
        dcp = _clip((0.15 + 0.5 * uc.decision_relevance) * (1.3 if near_boundary else 0.7) * reliability)
        # Regret reduction ~ decision-change probability * uncertainty magnitude.
        err = _clip(dcp * uc.magnitude)
        tail_rel = _clip((0.7 if tail_present else 0.3) if kind in ("epistemic", "regime") else 0.2)
        redundancy = _clip(base_redundancy * 0.5 + red_risk * 0.5)
        cost = _COST.get(cost_band, 0.35)
        raw = 0.45 * dcp + 0.30 * eur + 0.15 * err + 0.10 * tail_rel
        net = round(raw * (1.0 - redundancy) * cal_amp - cost, 4)
        worth = net > 0.0
        reason = (f"targets {kind} (reducible); dcp={round(dcp,2)}, "
                  f"redundancy−{round(redundancy,2)}, cal×{cal_amp}, cost−{cost}")
        estimates.append(ValueOfInformationEstimate(
            item=item, targets_uncertainty=kind,
            decision_change_probability=round(dcp, 4),
            expected_uncertainty_reduction=round(eur, 4),
            expected_regret_reduction=round(err, 4), tail_relevance=round(tail_rel, 4),
            redundancy_discount=round(redundancy, 4), calibration_amplifier=cal_amp,
            acquisition_cost=cost, raw_voi=round(raw, 4), net_voi=net,
            worth_acquiring=worth, reason=reason))

    estimates.sort(key=lambda e: -e.net_voi)
    worth_any = [e for e in estimates if e.worth_acquiring and e.acquisition_cost <= budget]
    if not worth_any:
        # Honest conclusion: nothing is worth the cost right now.
        fresh = (obs.freshness_status or "").upper()
        if fresh in ("AGING", "STALE"):
            verdict, top = "WAIT_FOR_CATALYST", "NO_RESEARCH_WORTHWHILE"
            note = "no item clears its cost; data is aging — waiting for a catalyst dominates research"
        else:
            verdict, top = "NO_RESEARCH_WORTHWHILE", "NO_RESEARCH_WORTHWHILE"
            note = "no information item's net value exceeds its cost under the current budget"
        spent = 0.0
    else:
        best = worth_any[0]
        verdict, top = "ACQUIRE", best.item
        spent = best.acquisition_cost
        note = f"acquire {best.item}: net VoI {best.net_voi} > 0 within budget {budget}"

    return ResearchPriority(
        candidate_id=obs.ticker, ranked=estimates[:8], top_action=top, verdict=verdict,
        budget=budget, spent_if_top=spent, reducible_fraction=profile.reducible_fraction,
        note=note)


__all__ = ["ValueOfInformationEstimate", "ResearchPriority", "rank_information"]
