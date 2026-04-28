from __future__ import annotations

from .models import DO_NOT_DEPLOY_POLICY_STATES, ExtremeStateSignal, ExtremeStateThresholds
from .utils import clamp01


def evaluate_executable_edge_gate(
    signal: ExtremeStateSignal,
    *,
    executable_edge: float,
    conversion_probability: float,
    exit_clarity_score: float,
    silent_chaos_flag: bool,
    thresholds: ExtremeStateThresholds | None = None,
) -> dict[str, object]:
    active = thresholds or ExtremeStateThresholds()
    policy_blocked = signal.policy_state.upper() in DO_NOT_DEPLOY_POLICY_STATES
    executable = (
        not policy_blocked
        and not silent_chaos_flag
        and clamp01(signal.signal_validity_score) >= 0.60
        and clamp01(conversion_probability) >= 0.50
        and clamp01(exit_clarity_score) >= 0.65
        and clamp01(executable_edge) >= active.theta_executable
    )
    return {
        "policy_blocked": policy_blocked,
        "executable": executable,
    }
