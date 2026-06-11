"""Aero / chassis stability engine: evidence is downforce, noise is drag.

    Downforce        = weighted sum of high-quality evidence components
    Drag             = noise + contradictions + duplication + ambiguity + promo bias
    Aero Efficiency  = downforce / drag
    Dirty Air        = 1 - origins / mentions
    Slipstream       = sector momentum share of observed momentum
    Ground Effect    = hidden fundamental improvement * (1 - narrative crowding)
    DRS              = confirmed near-term catalyst window
    Aero Stall       = regime shift or data-quality collapse
    Porpoising       = unstable score oscillation
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

from src.simulator.narrative_tracker import dirty_air_score
from src.utils.math_utils import clamp01, clip, safe_div
from src.utils.validation_utils import normalized_score

DOWNFORCE_WEIGHTS: dict[str, float] = {
    "filing_evidence": 0.30,
    "cash_flow_quality": 0.25,
    "backlog_evidence": 0.20,
    "insider_alignment": 0.15,
    "primary_source_confirmation": 0.10,
}

DRS_CATALYST_WINDOW_DAYS = 30.0
AERO_STALL_REGIME_SHIFT_THRESHOLD = 0.5
AERO_STALL_DATA_QUALITY_FLOOR = 0.30
PORPOISING_STDDEV_THRESHOLD = 0.12
MIN_DRAG = 0.05


@dataclass(slots=True)
class AeroState:
    """Information-flow physics for one candidate."""

    evidence_downforce: float
    information_drag: float
    aero_efficiency: float
    dirty_air: float
    slipstream: float
    stock_specific_thrust: float
    ground_effect: float
    drs_status: str
    drs_active: bool
    aero_stall_warning: bool
    porpoising_warning: bool
    score_volatility: float
    aero_balance: str
    reason_codes: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_downforce(evidence: dict[str, float]) -> float:
    """Weighted evidence quality in [0, 1]."""
    return clamp01(
        sum(
            weight * normalized_score(evidence.get(key, 0.0))
            for key, weight in DOWNFORCE_WEIGHTS.items()
        )
    )


def compute_drag(
    *,
    noise_level: float,
    contradiction_level: float,
    duplication_level: float,
    ambiguity_level: float,
    promotional_bias: float,
) -> float:
    """Mean of the five drag components, floored so efficiency never explodes."""
    components = [
        normalized_score(noise_level),
        normalized_score(contradiction_level),
        normalized_score(duplication_level),
        normalized_score(ambiguity_level),
        normalized_score(promotional_bias),
    ]
    return clip(sum(components) / len(components), MIN_DRAG, 1.0)


def score_aero(
    *,
    evidence: dict[str, float],
    noise_level: float,
    contradiction_level: float,
    duplication_level: float,
    ambiguity_level: float,
    promotional_bias: float,
    independent_origin_count: int,
    total_source_count: int,
    sector_momentum: float,
    stock_specific_thrust: float,
    hidden_fundamental_improvement: float,
    narrative_crowding: float,
    catalyst_proximity_days: float | None = None,
    catalyst_confirmed: bool = False,
    regime_shift_level: float = 0.0,
    data_quality: float = 1.0,
    score_history: list[float] | None = None,
    bull_force: float = 0.5,
    bear_force: float = 0.5,
) -> AeroState:
    """Compute the full aero package for one candidate."""
    downforce = compute_downforce(evidence)
    drag = compute_drag(
        noise_level=noise_level,
        contradiction_level=contradiction_level,
        duplication_level=duplication_level,
        ambiguity_level=ambiguity_level,
        promotional_bias=promotional_bias,
    )
    efficiency = safe_div(downforce, drag)
    dirty_air = dirty_air_score(independent_origin_count, total_source_count)

    sector = normalized_score(sector_momentum)
    thrust = normalized_score(stock_specific_thrust)
    slipstream = clamp01(safe_div(sector, sector + thrust, 0.0))

    ground_effect = clamp01(
        normalized_score(hidden_fundamental_improvement)
        * (1.0 - normalized_score(narrative_crowding))
    )

    drs_active = (
        catalyst_proximity_days is not None
        and float(catalyst_proximity_days) <= DRS_CATALYST_WINDOW_DAYS
        and bool(catalyst_confirmed)
    )
    if drs_active:
        drs_status = "open"
    elif catalyst_proximity_days is not None and not catalyst_confirmed:
        drs_status = "unconfirmed_catalyst"
    else:
        drs_status = "closed"

    stall = (
        normalized_score(regime_shift_level) > AERO_STALL_REGIME_SHIFT_THRESHOLD
        or normalized_score(data_quality, 1.0) < AERO_STALL_DATA_QUALITY_FLOOR
    )

    history = [float(s) for s in (score_history or [])]
    score_volatility = (
        statistics.pstdev(history) if len(history) >= 3 else 0.0
    )
    porpoising = score_volatility > PORPOISING_STDDEV_THRESHOLD

    bull = normalized_score(bull_force, 0.5)
    bear = normalized_score(bear_force, 0.5)
    if bull - bear >= 0.15:
        balance = "bull_dominant"
    elif bear - bull >= 0.15:
        balance = "bear_dominant"
    else:
        balance = "balanced"

    reasons: list[str] = []
    if efficiency >= 1.5:
        reasons.append("CLEAN_AIR_HIGH_EFFICIENCY")
    elif efficiency < 0.75:
        reasons.append("DRAG_DOMINATED")
    if dirty_air >= 0.7 and total_source_count >= 5:
        reasons.append("DIRTY_AIR_PENALTY")
    if slipstream >= 0.7:
        reasons.append("SLIPSTREAM_DEPENDENT")
    if ground_effect >= 0.5:
        reasons.append("GROUND_EFFECT_DETECTED")
    if drs_active:
        reasons.append("DRS_OPEN")
    if stall:
        reasons.append("AERO_STALL_WARNING")
    if porpoising:
        reasons.append("PORPOISING_FREEZE_PROMOTION")

    return AeroState(
        evidence_downforce=downforce,
        information_drag=drag,
        aero_efficiency=efficiency,
        dirty_air=dirty_air,
        slipstream=slipstream,
        stock_specific_thrust=thrust,
        ground_effect=ground_effect,
        drs_status=drs_status,
        drs_active=drs_active,
        aero_stall_warning=stall,
        porpoising_warning=porpoising,
        score_volatility=score_volatility,
        aero_balance=balance,
        reason_codes=reasons,
        raw_components={
            "sector_momentum": sector,
            "regime_shift_level": normalized_score(regime_shift_level),
            "data_quality": normalized_score(data_quality, 1.0),
            "bull_force": bull,
            "bear_force": bear,
        },
    )
