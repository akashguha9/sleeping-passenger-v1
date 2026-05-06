from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ALTERED_OPERATOR_STATES = {"STRESSED", "EUPHORIC", "FATIGUED", "INTOXICATED"}
OPERATOR_BASE_STABILITY = {
    "CALM": 0.95,
    "NEUTRAL": 0.85,
    "STRESSED": 0.35,
    "EUPHORIC": 0.20,
    "FATIGUED": 0.25,
    "INTOXICATED": 0.0,
    "UNKNOWN": 0.40,
}


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass(frozen=True)
class NarrativeOperatorWisdomResult:
    narrative_signal_class: str
    hallucination_risk: float
    operator_state: str
    operator_stability_score: float
    action_authority: str
    wisdom_state: str
    allowed_to_execute: bool
    tags: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    cross_state_validated: bool = False
    evidence_strength: float = 0.0
    narrative_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_narrative_operator_wisdom_filter(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    operator_state = str(payload.get("operator_state") or "UNKNOWN").upper()
    evidence_strength = _clamp(payload.get("evidence_strength"))
    narrative_confidence = _clamp(payload.get("narrative_confidence"))
    emotional_resonance = _clamp(payload.get("emotional_resonance"))
    interpretation_width = _clamp(payload.get("interpretation_width"))
    falsifiable = _truthy(payload.get("falsifiable", True))
    cross_state_validated = _truthy(payload.get("cross_state_validated"))
    passing_state_tag = _truthy(payload.get("passing_state_tag"))
    urgency_spike = _truthy(payload.get("urgency_spike"))
    confidence_surge = _truthy(payload.get("confidence_surge"))
    selected_feeling_match = _truthy(payload.get("selected_feeling_match"))
    operator_stability_score = _clamp(
        payload.get("operator_stability_score", OPERATOR_BASE_STABILITY.get(operator_state, 0.40))
    )
    hallucination_risk = round(
        _clamp(narrative_confidence / max(evidence_strength, 0.05) / 2.0),
        3,
    )

    tags: list[str] = []
    failed_gates: list[str] = []
    rationale: list[str] = []
    if narrative_confidence > evidence_strength:
        tags.append("NARRATIVE_OVERLAY")
    if emotional_resonance >= 0.7 and evidence_strength <= 0.4:
        tags.extend(["LOW_EVIDENCE_HIGH_MEANING", "CONTEXT_MISREAD_RISK"])
    if interpretation_width >= 0.7:
        tags.append("INTERPRETATION_SPACE_TOO_WIDE")
    if not falsifiable:
        tags.append("NON_FALSIFIABLE_SIGNAL")
    if passing_state_tag:
        tags.append("PASSING_STATE_TAG")
    if urgency_spike:
        tags.append("URGENCY_SPIKE")
    if confidence_surge:
        tags.append("CONFIDENCE_SURGE")
    if operator_state == "STRESSED":
        tags.append("FEAR_RESPONSE")
    if operator_state == "EUPHORIC":
        tags.append("EUPHORIC_CONVICTION")
    if not cross_state_validated:
        tags.append("CROSS_STATE_UNVALIDATED")
    if selected_feeling_match:
        tags.append("IDENTITY_CONSISTENT_SELECTION")
    if operator_state in ALTERED_OPERATOR_STATES:
        tags.append("STATE_VOLATILE")

    if not falsifiable:
        signal_class = "NOISE"
    elif hallucination_risk >= 0.7 or (
        narrative_confidence >= 0.7 and evidence_strength <= 0.3
    ):
        signal_class = "NARRATIVE_CONSTRUCTED_SIGNAL"
    elif evidence_strength >= 0.65 and interpretation_width <= 0.5:
        signal_class = "SIGNAL"
    else:
        signal_class = "NOISE"

    if operator_state in ALTERED_OPERATOR_STATES or operator_stability_score < 0.5:
        action_authority = "REVOKED"
        failed_gates.append("operator_stability_below_threshold")
        rationale.append("Operator state is too unstable for execution authority.")
    else:
        action_authority = "ACTIVE"

    if not falsifiable:
        wisdom_state = "REJECT"
        failed_gates.append("non_falsifiable_signal")
        rationale.append("Non-falsifiable signals cannot become decision-grade.")
    elif action_authority == "REVOKED":
        wisdom_state = "ACTION_AUTHORITY_REVOKED"
    elif not cross_state_validated:
        wisdom_state = "OBSERVE_ONLY"
        failed_gates.append("cross_state_unvalidated")
        rationale.append("Signal did not validate across operator states and remains below promotion authority.")
    elif signal_class != "SIGNAL":
        wisdom_state = "OBSERVE_ONLY"
        failed_gates.append("signal_not_decision_grade")
        rationale.append("Interpretation remains too narrative-heavy or too weak for action.")
    elif passing_state_tag or interpretation_width >= 0.7:
        wisdom_state = "HOLD"
        failed_gates.append("interpretation_space_too_wide")
        rationale.append("Signal quality is not poor, but interpretation width is still too large for action.")
    else:
        wisdom_state = "ACT"
        rationale.append("Evidence, falsifiability, operator stability, and cross-state validation all passed.")

    return NarrativeOperatorWisdomResult(
        narrative_signal_class=signal_class,
        hallucination_risk=hallucination_risk,
        operator_state=operator_state,
        operator_stability_score=round(operator_stability_score, 3),
        action_authority=action_authority,
        wisdom_state=wisdom_state,
        allowed_to_execute=wisdom_state == "ACT" and action_authority == "ACTIVE",
        tags=sorted(set(tags)),
        failed_gates=failed_gates,
        rationale=rationale,
        cross_state_validated=cross_state_validated,
        evidence_strength=round(evidence_strength, 3),
        narrative_confidence=round(narrative_confidence, 3),
    ).to_dict()
