"""Scrutineering bay: post-race technical inspection for candidate payloads.

The eureka: the simulator's scoring engines trust their inputs. A payload
of self-consistent optimistic numbers (every component 0.85, zero claimed
risks) sails through every gate — the model can be fooled by confident
garbage. In racing, a car that is suspiciously fast is not celebrated; it
is wheeled into the scrutineering bay and stripped. A car that fails
technical inspection is disqualified regardless of where it finished.

This module cross-examines a candidate payload against the simulator's own
physics invariants — conservation laws that honest inputs obey and
fabricated inputs tend to violate:

    1. Confirmation cannot exceed what the origin counts can carry.
    2. Hard evidence claims require hard/medium tyres on the car.
    3. Claimed crash risk cannot undercut the circuit's crash baseline.
    4. Downforce claims require a stocked meal box (filing evidence text).
    5. Narrative shock requires an actual narrative (mentions on the wire).
    6. Uniform optimism — many extreme-favorable inputs with near-zero
       variance — is statistically improbable in honest research.
    7. Evidence-volume humility: confidence must be earned by volume.

Each violation carries a severity; the suspicion score aggregates them.
A failed inspection does not delete the verdict — it caps the ladder at
watchlist and stamps the decision DISQUALIFIED_PENDING_EVIDENCE, exactly
like a provisional result under stewards' inquiry. ADVISORY_ONLY.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import coerce_float, normalized_score

# Suspicion at or above this fails inspection.
SUSPICION_FAIL_THRESHOLD = 0.50

# Tolerance slack on the confirmation-vs-origins conservation law.
CONFIRMATION_SLACK = 0.25

# Uniform-optimism detector: flag when at least this many favorable inputs
# are present, their mean is extreme, and their spread is implausibly tight.
UNIFORM_MIN_INPUTS = 6
UNIFORM_MEAN_FLOOR = 0.75
UNIFORM_STDEV_CEILING = 0.06

# Humility: confidence claims above the volume-supported ceiling are flagged.
HUMILITY_FULL_VOLUME_MENTIONS = 12
HUMILITY_FULL_VOLUME_ORIGINS = 4


@dataclass(slots=True)
class ScrutineeringViolation:
    """One failed technical check."""

    check: str
    severity: float
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ScrutineeringReport:
    """Inspection result for one candidate payload."""

    suspicion_score: float
    passed: bool
    humility_index: float
    violations: list[ScrutineeringViolation] = field(default_factory=list)
    checks_run: int = 0
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _favorable_inputs(payload: dict) -> list[float]:
    """Collect the caller-controlled inputs that push the score up."""
    values: list[float] = [
        normalized_score(payload.get("opportunity_quality", 0.0)),
        normalized_score(payload.get("hard_evidence_score", 0.0)),
        normalized_score(payload.get("confirmation_level", 0.0)),
    ]
    theme = payload.get("theme_assessment") or {}
    for key in ("policy_fit", "macro_fit", "sector_momentum", "liquidity_support"):
        if key in theme:
            values.append(normalized_score(theme.get(key)))
    exposure = payload.get("exposure") or {}
    for key in ("revenue_exposure", "backlog_linkage", "supply_chain_position"):
        if key in exposure:
            values.append(normalized_score(exposure.get(key)))
    aero = payload.get("aero") or {}
    evidence = aero.get("evidence") or {}
    for value in evidence.values():
        values.append(normalized_score(value))
    blind = (payload.get("triple_blind") or {}).get("blinded_metrics") or {}
    for value in blind.values():
        values.append(normalized_score(value))
    return values


def compute_humility_index(
    *,
    claimed_confidence: float,
    mention_count: int,
    independent_origin_count: int,
    tyre_count: int,
    meal_box_complete: bool,
) -> float:
    """Volume-supported confidence ceiling in [0, 1].

    Thin evidence caps how much confidence the model is allowed to carry:
    the index is the ratio of evidence volume to claimed confidence
    (1.0 = humble or fully earned, lower = overconfident on thin evidence).
    """
    volume = (
        0.35 * min(max(mention_count, 0) / HUMILITY_FULL_VOLUME_MENTIONS, 1.0)
        + 0.35 * min(max(independent_origin_count, 0) / HUMILITY_FULL_VOLUME_ORIGINS, 1.0)
        + 0.20 * min(max(tyre_count, 0) / 3.0, 1.0)
        + 0.10 * (1.0 if meal_box_complete else 0.0)
    )
    confidence = normalized_score(claimed_confidence)
    if confidence <= volume or confidence <= 0.0:
        return 1.0
    return clamp01(volume / confidence)


def inspect_payload(payload: dict) -> ScrutineeringReport:
    """Run every technical check against one raw candidate payload."""
    violations: list[ScrutineeringViolation] = []
    checks_run = 0
    narrative = payload.get("narrative") or {}
    mentions = int(coerce_float(narrative.get("mention_count")))
    origins = int(coerce_float(narrative.get("independent_origin_count")))
    signals = [s for s in payload.get("signals", []) or [] if isinstance(s, dict)]
    meal = payload.get("meal_box") or {}
    confirmation = normalized_score(payload.get("confirmation_level", 0.0))
    hard_evidence = normalized_score(payload.get("hard_evidence_score", 0.0))

    # 1. Confirmation conservation: claimed confirmation must be carried
    # by independent origins actually on the wire. Capacity grows with the
    # absolute origin count — four independent origins can carry full
    # confirmation regardless of how many echoes amplified them.
    checks_run += 1
    carried = clamp01(origins / HUMILITY_FULL_VOLUME_ORIGINS)
    if confirmation > carried + CONFIRMATION_SLACK:
        violations.append(
            ScrutineeringViolation(
                check="confirmation_without_origins",
                severity=clamp01(confirmation - carried),
                explanation=(
                    f"confirmation_level {confirmation:.2f} exceeds what "
                    f"{origins} independent origins can carry "
                    f"({carried:.2f} + {CONFIRMATION_SLACK} slack)"
                ),
            )
        )

    # 2. Hard evidence requires hard/medium rubber on the car.
    checks_run += 1
    hard_compounds = {"free_cash_flow", "roic", "low_debt", "moat", "backlog",
                      "insider_ownership", "earnings_beat", "earnings_miss",
                      "analyst_revision", "contract_win", "guidance_change",
                      "defensive_balance_sheet", "low_beta", "recession_resilience"}
    has_hard_tyre = any(
        str(s.get("signal_type", "")).strip().lower() in hard_compounds
        for s in signals
    )
    if hard_evidence >= 0.6 and not has_hard_tyre:
        violations.append(
            ScrutineeringViolation(
                check="hard_evidence_without_hard_tyres",
                severity=hard_evidence - 0.3,
                explanation=(
                    f"hard_evidence_score {hard_evidence:.2f} claimed but no "
                    "hard/medium/wet-compound signal was supplied"
                ),
            )
        )

    # 3. Crash-risk conservation: claimed total risk cannot undercut the
    # circuit's own crash baseline.
    checks_run += 1
    risk_factors = payload.get("risk_factors") or {}
    claimed_risk = sum(normalized_score(v) for v in risk_factors.values())
    circuit_section = payload.get("circuit") or {}
    market_cap = coerce_float(circuit_section.get("market_cap_usd"))
    from src.simulator.circuit_classifier import classify_circuit

    circuit = classify_circuit(
        market_cap_usd=market_cap,
        sector=str(circuit_section.get("sector", "")),
        is_biotech_event_driven=bool(
            circuit_section.get("is_biotech_event_driven", False)
        ),
        annualized_volatility=coerce_float(
            circuit_section.get("annualized_volatility")
        ),
        policy_dependent=bool(circuit_section.get("policy_dependent", False)),
    )
    baseline = circuit.profile.crash_baseline
    if claimed_risk < baseline * 0.5:
        violations.append(
            ScrutineeringViolation(
                check="clean_crash_on_dirty_circuit",
                severity=clamp01(baseline - claimed_risk),
                explanation=(
                    f"claimed total risk {claimed_risk:.2f} undercuts circuit "
                    f"'{circuit.circuit}' crash baseline {baseline:.2f} — "
                    "no car is that clean on this track"
                ),
            )
        )

    # 4. Downforce claims require a stocked meal box.
    checks_run += 1
    aero_evidence = (payload.get("aero") or {}).get("evidence") or {}
    claimed_downforce = (
        max((normalized_score(v) for v in aero_evidence.values()), default=0.0)
    )
    evidence_text = str(meal.get("evidence") or "").strip()
    if claimed_downforce >= 0.6 and len(evidence_text) < 10:
        violations.append(
            ScrutineeringViolation(
                check="downforce_without_filings",
                severity=claimed_downforce - 0.3,
                explanation=(
                    "aero evidence components claimed at "
                    f"{claimed_downforce:.2f} but the meal-box evidence text "
                    "is empty — downforce with no wing"
                ),
            )
        )

    # 5. Narrative shock requires an actual narrative.
    checks_run += 1
    radar = payload.get("prediction_market") or {}
    delta = abs(
        coerce_float(radar.get("probability_after"))
        - coerce_float(radar.get("probability_before"))
    )
    if radar and delta >= 0.15 and mentions < 3:
        violations.append(
            ScrutineeringViolation(
                check="shock_without_narrative",
                severity=clamp01(delta),
                explanation=(
                    f"prediction-market delta {delta:.2f} claimed with only "
                    f"{mentions} narrative mentions — radar contact with an "
                    "empty sky"
                ),
            )
        )

    # 6. Uniform optimism: many extreme favorable inputs, implausibly tight.
    checks_run += 1
    favorable = [v for v in _favorable_inputs(payload) if v > 0.0]
    if len(favorable) >= UNIFORM_MIN_INPUTS:
        mean = statistics.mean(favorable)
        spread = statistics.pstdev(favorable)
        if mean >= UNIFORM_MEAN_FLOOR and spread <= UNIFORM_STDEV_CEILING:
            violations.append(
                ScrutineeringViolation(
                    check="uniform_optimism",
                    severity=clamp01(mean - spread),
                    explanation=(
                        f"{len(favorable)} favorable inputs with mean "
                        f"{mean:.2f} and stdev {spread:.3f} — honest research "
                        "is never this smooth"
                    ),
                )
            )

    # 7. Humility: confidence must be earned by evidence volume.
    checks_run += 1
    meal_complete = all(
        len(str(meal.get(k) or "").strip()) >= 10 or meal.get(k) is True
        for k in ("thesis", "evidence", "catalyst", "invalidation")
    )
    humility = compute_humility_index(
        claimed_confidence=max(confirmation, hard_evidence),
        mention_count=mentions,
        independent_origin_count=origins,
        tyre_count=len(signals),
        meal_box_complete=meal_complete,
    )
    if humility < 0.6:
        violations.append(
            ScrutineeringViolation(
                check="overconfident_thin_evidence",
                severity=clamp01(1.0 - humility),
                explanation=(
                    f"humility index {humility:.2f}: claimed confidence is "
                    "not carried by mention/origin/signal volume"
                ),
            )
        )

    # Aggregate: 1 - Π(1 - severity) so independent violations compound.
    suspicion = 1.0
    for violation in violations:
        suspicion *= 1.0 - clamp01(violation.severity)
    suspicion = clamp01(1.0 - suspicion)
    passed = suspicion < SUSPICION_FAIL_THRESHOLD

    reasons: list[str] = []
    if passed and not violations:
        reasons.append("SCRUTINEERING_CLEAN")
    elif passed:
        reasons.append("SCRUTINEERING_NOTES")
    else:
        reasons.append("SCRUTINEERING_FAILED")
        reasons.append("DISQUALIFIED_PENDING_EVIDENCE")
    reasons.extend(f"CHECK_{v.check.upper()}" for v in violations)

    return ScrutineeringReport(
        suspicion_score=suspicion,
        passed=passed,
        humility_index=humility,
        violations=violations,
        checks_run=checks_run,
        reason_codes=reasons,
    )
