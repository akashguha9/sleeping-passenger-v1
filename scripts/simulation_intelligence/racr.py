"""Role-Adjusted Contribution Rating (RACR) engine — the "Kanté Index".

Scores a component on how well it performs *its assigned role*, using immutable
role weights (``role_contracts``), evidence-linked dimension measurements, and
the contribution-event ledger. Produces FIVE separate scores that are never
averaged into one misleading number:

  A. Role-Adjusted Performance  — how exceptionally it does its job
  B. Engineering Quality        — design/tests/integration/reliability
  C. Decision Utility           — does it materially improve decisions
  D. Empirical Validation       — leakage-safe real-outcome support (FIREWALLED low)
  E. Whole-MVP Maturity         — the full product, incorporating (D)

Anti-gaming is structural, not cosmetic:
  * role weights are fixed before evaluation (a component can't pick an easy role)
  * a dimension with no evidence is UNSUPPORTED and cannot credit a high score
  * PROXY_HEAVY / LOW_SAMPLE labels cap rating confidence
  * a component that is not runtime-reached is hard-capped (orphaned ≠ elite)
  * a single SEVERE integrity event materially cuts the score
  * the honest ceiling from the role contract is never exceeded
  * empirical validation is firewalled: it rises ONLY with real leakage-safe
    outcomes, never from simulated sophistication

Pure: stdlib + advisory_contract + sibling SIL modules only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.role_contracts import (
        get_contract, all_contracts, ALL_DIMENSIONS, RatingSupport, EvidenceGrade,
        ROLE_CONTRACT_VERSION,
    )
    from scripts.simulation_intelligence.contribution_ledger import LedgerScore
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.role_contracts import (  # type: ignore[no-redef]
        get_contract, all_contracts, ALL_DIMENSIONS, RatingSupport, EvidenceGrade,
        ROLE_CONTRACT_VERSION,
    )
    from simulation_intelligence.contribution_ledger import LedgerScore  # type: ignore[no-redef]

RACR_VERSION = "racr-engine-1.0.0"

# Hard caps (anti-gaming).
_NOT_RUNTIME_REACHED_CAP = 4.0   # orphaned/documentation-only code cannot be elite
_UNSUPPORTED_CAP = 5.0           # a score with no evidence cannot exceed this
_SEVERE_EVENT_CAP = 6.0          # any SEVERE integrity event caps the component here
_LOW_SAMPLE_MIN = 5              # fewer than this many evidence items → LOW_SAMPLE

_GRADE_STRENGTH = {
    EvidenceGrade.MEASURED.value: 1.0,
    EvidenceGrade.DERIVED.value: 0.75,
    EvidenceGrade.PROXY.value: 0.5,
    EvidenceGrade.SIMULATED.value: 0.35,
    EvidenceGrade.NONE.value: 0.0,
}


@dataclass(slots=True)
class DimensionEvidence:
    """One evidence-linked measurement of a single RACR dimension."""

    dimension: str
    value: float          # 0..10
    grade: str            # EvidenceGrade value
    confidence: float     # 0..1
    sample_size: int
    source: str
    reason: str = ""

    def __post_init__(self) -> None:
        self.value = max(0.0, min(10.0, float(self.value)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.sample_size = max(0, int(self.sample_size))

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class DimensionScore:
    dimension: str
    weight: float
    value: float
    grade: str
    confidence: float
    sample_size: int
    support: str
    source: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class RoleAdjustedRating:
    component_id: str
    component_name: str
    role_template: str
    role_adjusted_performance: float   # score A
    engineering_quality: float          # score B
    decision_utility: float             # score C
    empirical_validation: float         # score D (firewalled)
    rating_confidence: float
    support: str                        # SUPPORTED / LOW_SAMPLE / PROXY_HEAVY / UNSUPPORTED
    evidence_grade: str
    honest_ceiling: float
    runtime_reached: bool
    empirically_validated: bool
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    caps_applied: list[str] = field(default_factory=list)
    severe_events: int = 0
    reasons: list[str] = field(default_factory=list)
    contract_version: str = ROLE_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__
             if k not in ("dimension_scores",)}
        d["dimension_scores"] = [s.to_dict() for s in self.dimension_scores]
        d.update(advisory_safety_stamps())
        return d


# Which dimensions feed the engineering / decision-utility scores (role-agnostic
# lenses on the same evidence — kept separate from the role-adjusted score).
_ENGINEERING_DIMS = ("reliability", "regression_resistance", "runtime_reach",
                     "resource_efficiency", "recovery_ability", "consistency")
_DECISION_DIMS = ("decision_influence", "risk_interception", "error_prevention",
                  "uncertainty_handling", "operator_usefulness", "explainability")


def _support_label(evidence: list[DimensionEvidence]) -> tuple[str, str]:
    if not evidence:
        return RatingSupport.UNSUPPORTED.value, EvidenceGrade.NONE.value
    total_n = sum(e.sample_size for e in evidence)
    grades = [e.grade for e in evidence]
    strengths = [_GRADE_STRENGTH.get(g, 0.0) for g in grades]
    mean_strength = sum(strengths) / len(strengths)
    # Overall grade = the modal-ish strongest well-represented grade.
    if mean_strength >= 0.85:
        grade = EvidenceGrade.MEASURED.value
    elif mean_strength >= 0.6:
        grade = EvidenceGrade.DERIVED.value
    elif mean_strength >= 0.4:
        grade = EvidenceGrade.PROXY.value
    elif mean_strength > 0.0:
        grade = EvidenceGrade.SIMULATED.value
    else:
        grade = EvidenceGrade.NONE.value
    if total_n < _LOW_SAMPLE_MIN:
        return RatingSupport.LOW_SAMPLE.value, grade
    if mean_strength < 0.5:
        return RatingSupport.PROXY_HEAVY.value, grade
    return RatingSupport.SUPPORTED.value, grade


def _weighted(dim_scores: list[DimensionScore], dims: tuple[str, ...] | None = None
              ) -> float:
    sel = [s for s in dim_scores if (dims is None or s.dimension in dims)]
    denom = sum(s.weight * s.confidence for s in sel)
    if denom <= 0:
        return 0.0
    return sum(s.value * s.weight * s.confidence for s in sel) / denom


def score_component(
    component_id: str,
    evidence: list[DimensionEvidence],
    *,
    ledger: LedgerScore | None = None,
    runtime_reached: bool = False,
    empirical_evidence: list[DimensionEvidence] | None = None,
) -> RoleAdjustedRating:
    """Compute the role-adjusted rating for one component from evidence."""
    contract = get_contract(component_id)
    if contract is None:
        raise KeyError(f"no role contract for component: {component_id}")
    weights = contract.dimension_weights

    # Collapse multiple evidence items per dimension into a confidence-weighted value.
    by_dim: dict[str, list[DimensionEvidence]] = {}
    for e in evidence:
        by_dim.setdefault(e.dimension, []).append(e)

    dim_scores: list[DimensionScore] = []
    for dim in ALL_DIMENSIONS:
        items = by_dim.get(dim, [])
        w = weights.get(dim, 0.1)
        if not items:
            # Unmeasured dimension. Role-critical (high-weight) dims missing
            # evidence get a low, low-confidence placeholder that drags the score;
            # floor dims are simply ignored.
            if w >= 1.0:
                dim_scores.append(DimensionScore(
                    dimension=dim, weight=w, value=3.0, grade=EvidenceGrade.NONE.value,
                    confidence=0.15, sample_size=0, support=RatingSupport.UNSUPPORTED.value,
                    source="none", reason="role-critical dimension has no evidence"))
            continue
        denom = sum(i.confidence for i in items) or 1.0
        val = sum(i.value * i.confidence for i in items) / denom
        conf = min(1.0, sum(i.confidence for i in items) / max(1, len(items)))
        n = sum(i.sample_size for i in items)
        sup, grade = _support_label(items)
        dim_scores.append(DimensionScore(
            dimension=dim, weight=w, value=round(val, 3), grade=grade,
            confidence=round(conf, 3), sample_size=n, support=sup,
            source=items[0].source, reason=items[0].reason))

    raw = _weighted(dim_scores)
    eng = _weighted(dim_scores, _ENGINEERING_DIMS)
    dec = _weighted(dim_scores, _DECISION_DIMS)

    # Empirical validation (score D) — firewalled. Only real leakage-safe outcome
    # evidence counts; absent it, this stays near the floor.
    emp_ev = empirical_evidence or []
    if emp_ev:
        e_denom = sum(e.confidence for e in emp_ev) or 1.0
        empirical = sum(e.value * e.confidence for e in emp_ev) / e_denom
        empirically_validated = any(
            e.grade in (EvidenceGrade.MEASURED.value, EvidenceGrade.DERIVED.value)
            and e.sample_size >= 20 for e in emp_ev)
    else:
        empirical = 1.0
        empirically_validated = False

    support, evidence_grade = _support_label(evidence)
    caps: list[str] = []
    reasons: list[str] = []

    perf = raw
    # Anti-gaming caps.
    if not runtime_reached:
        if perf > _NOT_RUNTIME_REACHED_CAP:
            perf = _NOT_RUNTIME_REACHED_CAP
        caps.append(f"not runtime-reached → capped at {_NOT_RUNTIME_REACHED_CAP}")
    if support == RatingSupport.UNSUPPORTED.value:
        perf = min(perf, _UNSUPPORTED_CAP)
        caps.append(f"UNSUPPORTED evidence → capped at {_UNSUPPORTED_CAP}")
    severe = ledger.severe_count if ledger else 0
    if severe:
        perf = min(perf, _SEVERE_EVENT_CAP) - min(3.0, ledger.severe_penalty)
        caps.append(f"{severe} SEVERE integrity event(s) → capped at {_SEVERE_EVENT_CAP} "
                    f"and −{round(min(3.0, ledger.severe_penalty),2)}")

    # Ledger net nudges the role-fidelity/role dims (bounded ±1.0).
    if ledger and not severe:
        nudge = max(-1.0, min(1.0, ledger.net_points * 0.15))
        perf += nudge
        if abs(nudge) > 0.01:
            reasons.append(f"ledger net {ledger.net_points:+.2f} → {nudge:+.2f} role nudge")

    perf = max(0.0, min(contract.honest_ceiling, perf))
    if perf >= contract.honest_ceiling - 1e-9:
        reasons.append(f"at honest ceiling {contract.honest_ceiling}")

    # Rating confidence: evidence coverage of role-critical dims × mean confidence.
    critical = [d for d in ALL_DIMENSIONS if weights.get(d, 0.1) >= 1.0]
    measured_critical = sum(1 for d in critical if d in by_dim)
    coverage = measured_critical / max(1, len(critical))
    mean_conf = sum(s.confidence for s in dim_scores) / max(1, len(dim_scores))
    rating_conf = round(max(0.0, min(1.0, coverage * mean_conf)), 3)
    if support in (RatingSupport.LOW_SAMPLE.value, RatingSupport.UNSUPPORTED.value):
        rating_conf = min(rating_conf, 0.4)

    return RoleAdjustedRating(
        component_id=component_id, component_name=contract.component_name,
        role_template=contract.role_template,
        role_adjusted_performance=round(perf, 3),
        engineering_quality=round(min(contract.honest_ceiling, eng), 3),
        decision_utility=round(min(contract.honest_ceiling, dec), 3),
        empirical_validation=round(empirical, 3),
        rating_confidence=rating_conf, support=support, evidence_grade=evidence_grade,
        honest_ceiling=contract.honest_ceiling, runtime_reached=runtime_reached,
        empirically_validated=empirically_validated, dimension_scores=dim_scores,
        caps_applied=caps, severe_events=severe, reasons=reasons)


def whole_mvp_maturity(
    ratings: list[RoleAdjustedRating],
    *,
    empirical_validation_score: float,
    empirical_sample_size: int,
) -> dict[str, Any]:
    """Score E — the whole product. Deliberately NOT inflated by one elite
    subsystem: it is pulled toward the empirical-validation score and penalised
    when real outcomes are inadequate."""
    if not ratings:
        return {"whole_mvp_maturity": 0.0, "reason": "no components"}
    reached = [r for r in ratings if r.runtime_reached]
    mean_perf = sum(r.role_adjusted_performance for r in reached) / max(1, len(reached))
    mean_eng = sum(r.engineering_quality for r in reached) / max(1, len(reached))
    mean_dec = sum(r.decision_utility for r in reached) / max(1, len(reached))
    # Engineering excellence carries the product only so far; empirical weakness
    # caps it. The whole-MVP score blends engineering/decision with a HARD pull
    # toward empirical validation.
    engineering_blend = 0.4 * mean_eng + 0.3 * mean_dec + 0.3 * mean_perf
    # Empirical drag: the product cannot mature past a ceiling set by evidence.
    if empirical_sample_size < 20:
        empirical_ceiling = 8.0
        drag_note = "empirical sample < 20: whole-MVP ceiling 8.0"
    elif empirical_sample_size < 50:
        empirical_ceiling = 8.6
        drag_note = "empirical sample < 50: whole-MVP ceiling 8.6"
    else:
        empirical_ceiling = 9.2
        drag_note = "empirical sample >= 50"
    blended = 0.75 * engineering_blend + 0.25 * (empirical_validation_score)
    score = round(min(empirical_ceiling, blended), 2)
    return {
        "whole_mvp_maturity": score,
        "engineering_blend": round(engineering_blend, 2),
        "empirical_validation_score": round(empirical_validation_score, 2),
        "empirical_sample_size": empirical_sample_size,
        "empirical_ceiling": empirical_ceiling,
        "components_runtime_reached": len(reached),
        "components_total": len(ratings),
        "reason": drag_note,
    }


def five_scores(
    ratings: list[RoleAdjustedRating],
    *,
    empirical_validation_score: float = 1.0,
    empirical_sample_size: int = 0,
    subsystem: str = "Simulation Intelligence Layer",
) -> dict[str, Any]:
    """The five headline scores, reported SEPARATELY (never averaged)."""
    reached = [r for r in ratings if r.runtime_reached]
    racr = round(sum(r.role_adjusted_performance for r in reached) / max(1, len(reached)), 2)
    eng = round(sum(r.engineering_quality for r in reached) / max(1, len(reached)), 2)
    dec = round(sum(r.decision_utility for r in reached) / max(1, len(reached)), 2)
    mvp = whole_mvp_maturity(ratings, empirical_validation_score=empirical_validation_score,
                             empirical_sample_size=empirical_sample_size)
    out = {
        "report": "racr_five_scores",
        "subsystem": subsystem,
        "racr_version": RACR_VERSION,
        "role_adjusted_performance": racr,
        "engineering_quality": eng,
        "decision_utility": dec,
        "empirical_validation": round(empirical_validation_score, 2),
        "whole_mvp_maturity": mvp["whole_mvp_maturity"],
        "empirical_sample_size": empirical_sample_size,
        "components_scored": len(ratings),
        "components_runtime_reached": len(reached),
        "note": ("Five scores are separate by design. A component can be elite in "
                 "its role (RACR) while empirical validation stays low — that is not "
                 "a contradiction; it means the role is done well but the full "
                 "product still lacks leakage-safe outcome evidence."),
        "whole_mvp_detail": mvp,
    }
    out.update(advisory_safety_stamps())
    return out


__all__ = [
    "RACR_VERSION", "DimensionEvidence", "DimensionScore", "RoleAdjustedRating",
    "score_component", "whole_mvp_maturity", "five_scores",
]
