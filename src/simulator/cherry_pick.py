"""Final cherry-pick decision engine: no score is naked.

    Final Candidate Score (0–100) =
        opportunity_quality + narrative_inflection + company_exposure
        + signal_grip + evidence_downforce + ground_effect + confirmation
        - crash_risk - information_drag - valuation_heat - dirty_air
        - driver_penalty

Every decision ships its full breakdown, gates, and decision reason —
never a naked Buy / No-Buy. All output is ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.simulator import ADVISORY_NOTE
from src.simulator.aero_engine import AeroState
from src.simulator.circuit_classifier import CircuitClassification
from src.simulator.crash_simulator import CrashReport
from src.simulator.driver_license import DriverState, license_meets_circuit
from src.simulator.meal_box import MealBoxStatus
from src.simulator.narrative_radar import NarrativeShock
from src.simulator.signal_tyres import (
    TyreState,
    blended_grip_pct,
    hard_conviction_allowed,
)
from src.simulator.threshold_ladder import (
    InflectionScore,
    LadderDecision,
    resolve_ladder_state,
)
from src.simulator.scrutineering import ScrutineeringReport
from src.simulator.triple_blind import TripleBlindReview
from src.utils.math_utils import clip
from src.utils.validation_utils import normalized_score

# Positive / negative component weights on the 0–100 final score scale.
SCORE_WEIGHTS: dict[str, float] = {
    "opportunity_quality": 25.0,
    "narrative_inflection": 10.0,
    "company_exposure": 15.0,
    "signal_grip": 15.0,
    "evidence_downforce": 20.0,
    "ground_effect": 10.0,
    "confirmation": 5.0,
    "crash_risk": -30.0,
    "information_drag": -10.0,
    "valuation_heat": -10.0,
    "dirty_air": -10.0,
    "driver_penalty": -15.0,
}

# Gate thresholds.
CRASH_RISK_GATE = 0.60
CRASH_DENSITY_GATE = 0.50
GRIP_GATE_PCT = 35.0
DATA_QUALITY_FLOOR = 0.30


@dataclass(slots=True)
class CherryPickDecision:
    """Full, never-naked final decision for one candidate."""

    ticker: str
    theme: str
    circuit: str
    final_state: str
    final_candidate_score: float
    decision_reason: str
    advisory_note: str
    narrative_shock: float
    company_exposure: float
    exposure_class: str
    signal_compound: str
    signal_grip: float
    track_condition: float
    downforce: float
    drag: float
    aero_efficiency: float
    dirty_air: float
    crash_risk: float
    crash_density: float
    meal_box_status: dict[str, object]
    driver_permission: float
    driver_status: str
    license_ok_for_circuit: bool
    hard_conviction_ok: bool
    ladder: dict[str, object]
    score_components: dict[str, float] = field(default_factory=dict)
    gate_results: dict[str, bool] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    triple_blind: dict[str, object] | None = None
    scrutineering: dict[str, object] | None = None
    suspicion_score: float = 0.0
    humility_index: float = 1.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _dominant_compound(tyres: list[TyreState]) -> str:
    if not tyres:
        return "none"
    return max(tyres, key=lambda t: t.effective_signal_strength).compound


def evaluate_candidate(
    *,
    ticker: str,
    theme: str,
    opportunity_quality: float,
    track_condition_score: float,
    valuation_heat: float,
    exposure_score: float,
    exposure_class: str,
    tyres: list[TyreState],
    hard_evidence_score: float,
    inflection: InflectionScore,
    aero: AeroState,
    crash: CrashReport,
    meal_box: MealBoxStatus,
    driver: DriverState,
    circuit: CircuitClassification,
    narrative_shock: NarrativeShock | None = None,
    triple_blind: TripleBlindReview | None = None,
    scrutineering: ScrutineeringReport | None = None,
    confirmation_level: float = 0.0,
    previous_state: str | None = None,
    thesis_damaged: bool = False,
) -> CherryPickDecision:
    """Combine every engine into one gated, explained, advisory decision."""
    grip_pct = blended_grip_pct(tyres)
    grip_fraction = grip_pct / 100.0
    conviction_ok, conviction_reasons = hard_conviction_allowed(
        tyres, hard_evidence_score=hard_evidence_score
    )
    data_quality = aero.raw_components.get("data_quality", 1.0)

    # Inflection contribution normalized from [-6, +5] to [0, 1].
    inflection_norm = clip((inflection.score + 6.0) / 11.0, 0.0, 1.0)
    driver_penalty = 1.0 - driver.permission_multiplier

    # Humility: claimed confirmation is capped by what the evidence volume
    # can actually carry (scrutineering's humility index in [0, 1]).
    humility = scrutineering.humility_index if scrutineering else 1.0

    components = {
        "opportunity_quality": normalized_score(opportunity_quality),
        "narrative_inflection": inflection_norm,
        "company_exposure": normalized_score(exposure_score),
        "signal_grip": grip_fraction,
        "evidence_downforce": aero.evidence_downforce,
        "ground_effect": aero.ground_effect,
        "confirmation": normalized_score(confirmation_level) * humility,
        "crash_risk": crash.crash_risk_score,
        "information_drag": aero.information_drag,
        "valuation_heat": normalized_score(valuation_heat),
        "dirty_air": aero.dirty_air,
        "driver_penalty": driver_penalty,
    }
    weighted = {
        name: SCORE_WEIGHTS[name] * value for name, value in components.items()
    }
    final_score = clip(sum(weighted.values()), 0.0, 100.0)

    crash_gate = (
        crash.crash_risk_score <= CRASH_RISK_GATE
        and crash.crash_density <= CRASH_DENSITY_GATE
    )
    grip_gate = grip_pct >= GRIP_GATE_PCT
    data_gate = data_quality >= DATA_QUALITY_FLOOR and not aero.aero_stall_warning
    stability_gate = not aero.porpoising_warning
    license_ok = license_meets_circuit(
        driver.license_level, circuit.profile.required_driver_license
    )
    scrutineering_ok = scrutineering.passed if scrutineering else True

    ladder: LadderDecision = resolve_ladder_state(
        score=final_score,
        previous_state=previous_state,
        circuit_threshold_multiplier=circuit.profile.threshold_multiplier,
        meal_box_complete=meal_box.complete,
        crash_gate_passed=crash_gate,
        grip_gate_passed=grip_gate and stability_gate,
        data_quality_gate_passed=data_gate,
        hard_conviction_allowed=conviction_ok and license_ok,
        scrutineering_passed=scrutineering_ok,
        thesis_damaged=thesis_damaged,
        driver_black_flag=driver.black_flag,
    )

    gate_results = {
        "crash_gate": crash_gate,
        "grip_gate": grip_gate,
        "data_quality_gate": data_gate,
        "stability_gate": stability_gate,
        "meal_box_gate": meal_box.complete,
        "hard_conviction_gate": conviction_ok,
        "driver_license_gate": license_ok,
        "driver_not_black_flagged": not driver.black_flag,
        "scrutineering_gate": scrutineering_ok,
    }

    reasons: list[str] = list(conviction_reasons)
    reasons.extend(ladder.reason_codes)
    if scrutineering is not None:
        reasons.extend(scrutineering.reason_codes)
    if not crash_gate:
        reasons.append("CRASH_GATE_BLOCKED")
    if not license_ok:
        reasons.append("LICENSE_BELOW_CIRCUIT_REQUIREMENT")
    if driver.permission_multiplier < 1.0:
        reasons.append("DRIVER_PERMISSION_REDUCED")

    failed_gates = [name for name, passed in gate_results.items() if not passed]
    if ladder.state in ("pit_stop", "black_flag"):
        decision_reason = (
            f"Interrupt state '{ladder.state}': "
            + ("driver black flag. " if driver.black_flag else "thesis damaged. ")
            + "No promotion possible until resolved."
        )
    elif failed_gates:
        decision_reason = (
            f"Score {final_score:.1f}/100 on circuit '{circuit.circuit}' "
            f"(eligible: {ladder.eligible_state}), capped to '{ladder.state}' "
            f"by failed gates: {', '.join(failed_gates)}."
        )
    else:
        decision_reason = (
            f"Score {final_score:.1f}/100 on circuit '{circuit.circuit}' "
            f"with all gates passed; state '{ladder.state}'."
        )
    decision_reason += " " + ADVISORY_NOTE

    return CherryPickDecision(
        ticker=str(ticker).upper(),
        theme=str(theme),
        circuit=circuit.circuit,
        final_state=ladder.state,
        final_candidate_score=final_score,
        decision_reason=decision_reason,
        advisory_note=ADVISORY_NOTE,
        narrative_shock=(
            narrative_shock.narrative_shock_score if narrative_shock else 0.0
        ),
        company_exposure=normalized_score(exposure_score),
        exposure_class=str(exposure_class),
        signal_compound=_dominant_compound(tyres),
        signal_grip=grip_pct,
        track_condition=normalized_score(track_condition_score),
        downforce=aero.evidence_downforce,
        drag=aero.information_drag,
        aero_efficiency=aero.aero_efficiency,
        dirty_air=aero.dirty_air,
        crash_risk=crash.crash_risk_score,
        crash_density=crash.crash_density,
        meal_box_status=meal_box.to_dict(),
        driver_permission=driver.permission_multiplier,
        driver_status=driver.status,
        license_ok_for_circuit=license_ok,
        hard_conviction_ok=conviction_ok,
        ladder=ladder.to_dict(),
        score_components=weighted,
        gate_results=gate_results,
        reason_codes=reasons,
        triple_blind=triple_blind.to_dict() if triple_blind else None,
        scrutineering=scrutineering.to_dict() if scrutineering else None,
        suspicion_score=scrutineering.suspicion_score if scrutineering else 0.0,
        humility_index=humility,
    )
