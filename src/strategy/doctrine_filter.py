"""Doctrine Filter — the pre-pre game. Reject weak ideas before scoring.

Like Nadal, the system does not wait for the match to begin: the frame is
set before analysis starts. Hard rejects (any one is fatal):

    hype-only narrative · no economic mechanism · no evidence source ·
    unclear value-chain role · fatal balance-sheet fragility ·
    unresolved existential bear case · uncrossed survival threshold ·
    pure story with no cash-flow path

    Pass = Mechanism_Valid ∧ Evidence_Exists ∧ No_Fatal_Fragility
           ∧ No_Existential_Bear_Case ∧ Survival_Threshold_Crossed
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.strategy.mechanism import MechanismAssessment
from src.utils.validation_utils import normalized_score

FATAL_FRAGILITY_THRESHOLD = 0.8


@dataclass(slots=True)
class DoctrineVerdict:
    """Pre-pre game gate result."""

    passed: bool
    reject_reasons: list[str] = field(default_factory=list)
    evidence_standard: str = "at least one traceable evidence source"
    risk_regime: str = "normal"
    minimum_required_thresholds: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def apply_doctrine_filter(
    *,
    mechanism: MechanismAssessment | None,
    evidence_source_count: int = 0,
    value_chain_role_known: bool = False,
    balance_sheet_fragility: float = 0.0,
    existential_bear_case_unresolved: bool = False,
    survival_threshold_crossed: bool = True,
    has_cash_flow_path: bool = True,
    hype_only: bool = False,
    risk_regime: str = "normal",
) -> DoctrineVerdict:
    """Apply the doctrine gate. Any reject reason fails the candidate."""
    reasons: list[str] = []
    if hype_only:
        reasons.append("hype_only_narrative")
    if mechanism is None or not mechanism.mechanism_valid:
        reasons.append("no_economic_mechanism")
    if evidence_source_count <= 0:
        reasons.append("no_evidence_source")
    if not value_chain_role_known:
        reasons.append("unclear_value_chain_role")
    if normalized_score(balance_sheet_fragility) >= FATAL_FRAGILITY_THRESHOLD:
        reasons.append("fatal_balance_sheet_fragility")
    if existential_bear_case_unresolved:
        reasons.append("unresolved_existential_bear_case")
    if not survival_threshold_crossed:
        reasons.append("survival_threshold_not_crossed")
    if not has_cash_flow_path:
        reasons.append("pure_story_no_cash_flow_path")

    passed = not reasons
    rationale = (
        ["doctrine gate passed — analysis may begin"]
        if passed
        else [f"doctrine reject: {', '.join(reasons)} — no deep scoring earned"]
    )
    minimums = []
    if not survival_threshold_crossed:
        minimums.append("survival threshold must be crossed before any BUY class")
    if evidence_source_count <= 0:
        minimums.append("at least one traceable evidence source")

    return DoctrineVerdict(
        passed=passed,
        reject_reasons=reasons,
        risk_regime=str(risk_regime),
        minimum_required_thresholds=minimums,
        rationale=rationale,
    )
