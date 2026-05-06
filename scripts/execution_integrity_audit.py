from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


HESITATION_LEAK_MAX = 0.55
RHYTHM_MIN = 0.60
PATTERN_MIN = 0.60
ZERO_DELAY_EPSILON = 0.05


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
class ExecutionIntegrityAuditResult:
    execution_integrity_state: str
    rhythm_integrity_score: float
    pattern_fidelity_score: float
    hesitation_leak_score: float
    mid_execution_reopen_detected: bool
    visible_reopen: bool
    hidden_adaptation_detected: bool
    adaptation_allowed: bool
    operator_uncertainty_score: float
    delay_cost: float
    information_gain: float
    adversary_read_risk: float
    execution_integrity_score: float
    allowed_to_execute: bool
    failed_gates: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_execution_integrity_audit(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    rhythm = _clamp(payload.get("rhythm_integrity_score"))
    pattern = _clamp(payload.get("pattern_fidelity_score"))
    operator_uncertainty = _clamp(payload.get("operator_uncertainty_score"))
    delay_cost = _clamp(payload.get("delay_cost"))
    information_gain = _clamp(payload.get("information_gain"))
    visible_reopen = _truthy(payload.get("visible_reopen"))
    mid_execution_reopen_detected = _truthy(payload.get("mid_execution_reopen_detected"))
    hidden_adaptation_detected = _truthy(payload.get("hidden_adaptation_detected"))
    concealment_score = _clamp(payload.get("concealment_score"))
    policy_aligned = _truthy(payload.get("policy_aligned"))
    execution_packet_valid = _truthy(payload.get("execution_packet_valid"))
    pattern_deviation = 1.0 - pattern

    hesitation_leak = round(
        _clamp((0.45 * operator_uncertainty) + (0.35 * delay_cost) + (0.20 * pattern_deviation)),
        3,
    )
    execution_integrity_score = round(
        _clamp(rhythm * pattern * (1.0 - hesitation_leak)),
        3,
    )
    adversary_read_risk = round(
        _clamp((0.4 * hesitation_leak) + (0.35 * pattern_deviation) + (0.25 * delay_cost)),
        3,
    )
    adaptation_allowed = bool(
        hidden_adaptation_detected
        and concealment_score >= 0.7
        and delay_cost <= ZERO_DELAY_EPSILON
        and policy_aligned
        and execution_packet_valid
    )

    failed_gates: list[str] = []
    rationale: list[str] = []
    if visible_reopen:
        failed_gates.append("visible_reopen")
        rationale.append("Visible reopen leaks execution intent to the adversary layer.")
        state = "BROKEN_EXECUTION"
    elif hesitation_leak > HESITATION_LEAK_MAX:
        failed_gates.append("hesitation_leak_above_threshold")
        rationale.append("Hesitation leak is too high for execution integrity.")
        state = "BROKEN_EXECUTION"
    elif mid_execution_reopen_detected and not hidden_adaptation_detected:
        failed_gates.append("mid_execution_reopen_without_hidden_adaptation")
        rationale.append("Mid-execution reopen was detected without concealed adaptation.")
        state = "BROKEN_EXECUTION"
    elif hidden_adaptation_detected and not adaptation_allowed:
        failed_gates.append("hidden_adaptation_not_policy_safe")
        rationale.append("Adaptation was detected but concealment, delay, policy, or packet validity failed.")
        state = "HARD_VETO"
    elif rhythm < RHYTHM_MIN:
        failed_gates.append("rhythm_integrity_below_threshold")
        rationale.append("Rhythm integrity is below minimum execution quality.")
        state = "BROKEN_EXECUTION"
    elif pattern < PATTERN_MIN:
        failed_gates.append("pattern_fidelity_below_threshold")
        rationale.append("Pattern fidelity is below minimum execution quality.")
        state = "BROKEN_EXECUTION"
    elif hidden_adaptation_detected and adaptation_allowed:
        rationale.append("Hidden adaptation is allowed because concealment, delay, policy, and packet validity passed.")
        state = "ADAPTIVE_EXECUTION_ALLOWED"
    else:
        rationale.append("Execution packet remains locked with clean rhythm and pattern fidelity.")
        state = "LOCKED_EXECUTION"

    return ExecutionIntegrityAuditResult(
        execution_integrity_state=state,
        rhythm_integrity_score=round(rhythm, 3),
        pattern_fidelity_score=round(pattern, 3),
        hesitation_leak_score=hesitation_leak,
        mid_execution_reopen_detected=mid_execution_reopen_detected,
        visible_reopen=visible_reopen,
        hidden_adaptation_detected=hidden_adaptation_detected,
        adaptation_allowed=adaptation_allowed,
        operator_uncertainty_score=round(operator_uncertainty, 3),
        delay_cost=round(delay_cost, 3),
        information_gain=round(information_gain, 3),
        adversary_read_risk=adversary_read_risk,
        execution_integrity_score=execution_integrity_score,
        allowed_to_execute=state in {"LOCKED_EXECUTION", "ADAPTIVE_EXECUTION_ALLOWED"},
        failed_gates=failed_gates,
        rationale=rationale,
    ).to_dict()
