"""Company exposure resolver: theme -> ticker exposure class and score.

    Exposure Score =
        revenue_exposure + margin_sensitivity + backlog_linkage
        + customer_linkage + geographic_fit + policy_fit
        + supply_chain_position - weak_evidence_penalty

Components are normalized [0, 1]; raw score lives in [-1, +7], also exposed
normalized to [0, 1].
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

EXPOSURE_DIRECT = "direct_beneficiary"
EXPOSURE_SECOND_ORDER = "second_order_beneficiary"
EXPOSURE_OPTIONALITY = "optionality_play"
EXPOSURE_NARRATIVE_PASSENGER = "narrative_passenger"
EXPOSURE_FALSE_POSITIVE = "false_positive"

EXPOSURE_CLASSES: tuple[str, ...] = (
    EXPOSURE_DIRECT,
    EXPOSURE_SECOND_ORDER,
    EXPOSURE_OPTIONALITY,
    EXPOSURE_NARRATIVE_PASSENGER,
    EXPOSURE_FALSE_POSITIVE,
)


@dataclass(slots=True)
class ExposureAssessment:
    """One company's resolved exposure to a theme."""

    ticker: str
    theme: str
    revenue_exposure: float
    margin_sensitivity: float
    backlog_linkage: float
    customer_linkage: float
    geographic_fit: float
    policy_fit: float
    supply_chain_position: float
    weak_evidence_penalty: float
    exposure_score_raw: float
    exposure_score: float
    exposure_class: str
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _classify_exposure(
    *,
    revenue_exposure: float,
    backlog_linkage: float,
    supply_chain_position: float,
    margin_sensitivity: float,
    policy_fit: float,
    weak_evidence_penalty: float,
    exposure_score: float,
) -> str:
    if weak_evidence_penalty >= 0.7 or exposure_score < 0.15:
        return EXPOSURE_FALSE_POSITIVE
    if weak_evidence_penalty >= 0.5 and revenue_exposure < 0.3:
        return EXPOSURE_NARRATIVE_PASSENGER
    if revenue_exposure >= 0.5 or backlog_linkage >= 0.6:
        return EXPOSURE_DIRECT
    if supply_chain_position >= 0.5 or margin_sensitivity >= 0.5:
        return EXPOSURE_SECOND_ORDER
    if policy_fit >= 0.5 or margin_sensitivity >= 0.3:
        return EXPOSURE_OPTIONALITY
    return EXPOSURE_NARRATIVE_PASSENGER


def resolve_exposure(
    *,
    ticker: str,
    theme: str,
    revenue_exposure: float,
    margin_sensitivity: float,
    backlog_linkage: float,
    customer_linkage: float,
    geographic_fit: float,
    policy_fit: float,
    supply_chain_position: float,
    weak_evidence_penalty: float = 0.0,
) -> ExposureAssessment:
    """Score and classify one company's exposure to one theme."""
    revenue = normalized_score(revenue_exposure)
    margin = normalized_score(margin_sensitivity)
    backlog = normalized_score(backlog_linkage)
    customer = normalized_score(customer_linkage)
    geo = normalized_score(geographic_fit)
    policy = normalized_score(policy_fit)
    chain = normalized_score(supply_chain_position)
    penalty = normalized_score(weak_evidence_penalty)

    raw = revenue + margin + backlog + customer + geo + policy + chain - penalty
    normalized = clamp01((raw + 1.0) / 8.0)

    exposure_class = _classify_exposure(
        revenue_exposure=revenue,
        backlog_linkage=backlog,
        supply_chain_position=chain,
        margin_sensitivity=margin,
        policy_fit=policy,
        weak_evidence_penalty=penalty,
        exposure_score=normalized,
    )

    reasons: list[str] = [f"EXPOSURE_{exposure_class.upper()}"]
    if penalty >= 0.5:
        reasons.append("WEAK_EVIDENCE_PENALTY")
    if backlog >= 0.6:
        reasons.append("BACKLOG_LINKED")
    if revenue >= 0.5:
        reasons.append("REVENUE_LINKED")

    return ExposureAssessment(
        ticker=str(ticker).upper(),
        theme=str(theme),
        revenue_exposure=revenue,
        margin_sensitivity=margin,
        backlog_linkage=backlog,
        customer_linkage=customer,
        geographic_fit=geo,
        policy_fit=policy,
        supply_chain_position=chain,
        weak_evidence_penalty=penalty,
        exposure_score_raw=raw,
        exposure_score=normalized,
        exposure_class=exposure_class,
        reason_codes=reasons,
    )
