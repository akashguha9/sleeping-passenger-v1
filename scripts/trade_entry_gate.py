from __future__ import annotations

from scripts.hedge_trade_entry_common import EntryGateState


def evaluate_trade_entry_gate(
    *,
    signal_valid: bool,
    timing_valid: bool,
    risk_defined: bool,
    structure_valid: bool,
    policy_allows_new_risk: bool,
    chaos_veto: bool,
    shock_override: bool,
    tail_loss_state: str,
    leverage_safe: bool,
    exposure_understood: bool,
    structure_conflict: bool,
) -> dict:
    reasons: list[str] = []
    if not policy_allows_new_risk:
        return {"state": EntryGateState.NO_NEW_RISK.value, "reasons": ["policy forbids new risk"]}
    if chaos_veto:
        return {"state": EntryGateState.NO_NEW_RISK.value, "reasons": ["chaos veto active"]}
    if shock_override:
        return {"state": EntryGateState.ENTRY_REJECTED.value, "reasons": ["shock override active"]}
    if structure_conflict:
        return {"state": EntryGateState.ENTRY_REJECTED.value, "reasons": ["structure conflict detected"]}
    if tail_loss_state in {"EXIT_REQUIRED", "CHAOS_LOSS_ZONE"}:
        return {"state": EntryGateState.EXIT_REQUIRED.value, "reasons": [f"tail loss state {tail_loss_state}"]}
    if not leverage_safe or not exposure_understood:
        reasons.append("leverage or exposure not safe enough")
    if not risk_defined:
        reasons.append("risk is not fully defined")
    if not structure_valid:
        reasons.append("structure invalid")
    if not signal_valid:
        reasons.append("signal invalid")
    if not timing_valid:
        reasons.append("timing invalid")
    if reasons:
        return {
            "state": EntryGateState.REVIEW_REQUIRED.value if "risk is not fully defined" in reasons else EntryGateState.ENTRY_REJECTED.value,
            "reasons": reasons,
        }
    return {"state": EntryGateState.ENTRY_ALLOWED.value, "reasons": []}
