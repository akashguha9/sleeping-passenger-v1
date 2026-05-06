from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


TIMING_QUALITY_MIN = 0.60
SPACE_QUALITY_MIN = 0.55


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
class BusquetsAuditResult:
    busquets_state: str
    allowed_to_execute: bool
    audit_score: float
    failed_gates: list[str]
    rationale: list[str]
    commitment_detected: bool
    space_created: bool
    timing_quality: float
    space_quality: float
    risk_clearance: bool
    chaos_veto_active: bool
    execution_packet_present: bool
    execution_packet_locked: bool
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_busquets_pre_execution_audit(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    required_fields = (
        "signal_validated",
        "commitment_detected",
        "space_created",
        "timing_quality",
        "space_quality",
        "risk_clearance",
        "chaos_veto_active",
        "execution_packet",
        "execution_packet_locked",
        "policy_state",
    )
    missing_fields = [field for field in required_fields if field not in payload]

    signal_validated = _truthy(payload.get("signal_validated"))
    commitment_detected = _truthy(payload.get("commitment_detected"))
    space_created = _truthy(payload.get("space_created"))
    timing_quality = _clamp(payload.get("timing_quality"))
    space_quality = _clamp(payload.get("space_quality"))
    risk_clearance = _truthy(payload.get("risk_clearance"))
    chaos_veto_active = _truthy(payload.get("chaos_veto_active"))
    execution_packet_present = isinstance(payload.get("execution_packet"), dict)
    execution_packet_locked = _truthy(payload.get("execution_packet_locked"))
    policy_state = str(payload.get("policy_state") or "UNKNOWN").upper()

    rationale: list[str] = []
    failed_gates: list[str] = []
    score_inputs = [
        1.0 if signal_validated else 0.0,
        1.0 if commitment_detected else 0.0,
        1.0 if space_created else 0.0,
        timing_quality,
        space_quality,
        1.0 if risk_clearance else 0.0,
        1.0 if execution_packet_present else 0.0,
        1.0 if execution_packet_locked else 0.0,
    ]
    audit_score = round(sum(score_inputs) / len(score_inputs), 3)

    if chaos_veto_active:
        failed_gates.append("chaos_veto_active")
        rationale.append("Chaos veto is active, so normal execution logic is disabled.")
        return BusquetsAuditResult(
            busquets_state="HARD_VETO",
            allowed_to_execute=False,
            audit_score=audit_score,
            failed_gates=failed_gates,
            rationale=rationale,
            commitment_detected=commitment_detected,
            space_created=space_created,
            timing_quality=timing_quality,
            space_quality=space_quality,
            risk_clearance=risk_clearance,
            chaos_veto_active=chaos_veto_active,
            execution_packet_present=execution_packet_present,
            execution_packet_locked=execution_packet_locked,
            missing_fields=missing_fields,
        ).to_dict()

    if policy_state in {"RESTRICTED", "BLOCKED", "DO_NOT_DEPLOY", "NOT_READY"}:
        failed_gates.append("policy_veto")
        rationale.append("Policy state forbids new risk, so Busquets cannot authorize execution.")
        return BusquetsAuditResult(
            busquets_state="HARD_VETO",
            allowed_to_execute=False,
            audit_score=audit_score,
            failed_gates=failed_gates,
            rationale=rationale,
            commitment_detected=commitment_detected,
            space_created=space_created,
            timing_quality=timing_quality,
            space_quality=space_quality,
            risk_clearance=risk_clearance,
            chaos_veto_active=chaos_veto_active,
            execution_packet_present=execution_packet_present,
            execution_packet_locked=execution_packet_locked,
            missing_fields=missing_fields,
        ).to_dict()

    if missing_fields:
        failed_gates.append("missing_required_fields")
        rationale.append("Busquets fails safe on missing required execution-audit fields.")
        state = "WAIT" if signal_validated else "NO_TRADE"
        return BusquetsAuditResult(
            busquets_state=state,
            allowed_to_execute=False,
            audit_score=audit_score,
            failed_gates=failed_gates,
            rationale=rationale,
            commitment_detected=commitment_detected,
            space_created=space_created,
            timing_quality=timing_quality,
            space_quality=space_quality,
            risk_clearance=risk_clearance,
            chaos_veto_active=chaos_veto_active,
            execution_packet_present=execution_packet_present,
            execution_packet_locked=execution_packet_locked,
            missing_fields=missing_fields,
        ).to_dict()

    if not signal_validated:
        failed_gates.append("signal_not_validated")
        rationale.append("Validated structure is absent, so no trade can be authorized.")
        state = "NO_TRADE"
    elif not commitment_detected:
        failed_gates.append("commitment_not_detected")
        rationale.append("Commitment is not detected yet, so the correct state is WAIT.")
        state = "WAIT"
    elif not space_created:
        failed_gates.append("space_not_created")
        rationale.append("Space has not been created yet, so execution must wait.")
        state = "WAIT"
    elif timing_quality < TIMING_QUALITY_MIN:
        failed_gates.append("timing_quality_below_threshold")
        rationale.append("Timing quality is below the Busquets minimum threshold.")
        state = "NO_TRADE"
    elif space_quality < SPACE_QUALITY_MIN:
        failed_gates.append("space_quality_below_threshold")
        rationale.append("Space quality is below the Busquets minimum threshold.")
        state = "NO_TRADE"
    elif not risk_clearance:
        failed_gates.append("risk_clearance_failed")
        rationale.append("Risk clearance is not clean enough for pre-execution approval.")
        state = "NO_TRADE"
    elif not execution_packet_present:
        failed_gates.append("execution_packet_missing")
        rationale.append("Execution packet is missing, so Busquets cannot pass it forward.")
        state = "WAIT"
    elif not execution_packet_locked:
        failed_gates.append("execution_packet_unlocked")
        rationale.append("Execution packet is present but not locked, so mutation risk remains.")
        state = "WAIT"
    else:
        rationale.append("Validated signal, created space, timing, and locked packet all passed.")
        state = "PASS"

    return BusquetsAuditResult(
        busquets_state=state,
        allowed_to_execute=state == "PASS",
        audit_score=audit_score,
        failed_gates=failed_gates,
        rationale=rationale,
        commitment_detected=commitment_detected,
        space_created=space_created,
        timing_quality=timing_quality,
        space_quality=space_quality,
        risk_clearance=risk_clearance,
        chaos_veto_active=chaos_veto_active,
        execution_packet_present=execution_packet_present,
        execution_packet_locked=execution_packet_locked,
        missing_fields=missing_fields,
    ).to_dict()
