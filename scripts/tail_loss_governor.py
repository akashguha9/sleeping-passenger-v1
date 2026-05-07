from __future__ import annotations

from scripts.hedge_trade_entry_common import TailLossState


def evaluate_tail_loss(
    *,
    projected_loss_pct: float,
    current_loss_pct: float,
    max_allowed_loss: float = 0.05,
    emergency_max_loss: float = 0.06,
    chaos_loss_frequency: float = 0.0,
    average_chaos_loss: float = 0.0,
) -> dict:
    """TailDrag = ChaosLossFrequency × AverageChaosLoss."""
    tail_drag = float(chaos_loss_frequency) * abs(float(average_chaos_loss))
    worst = min(float(projected_loss_pct), float(current_loss_pct))
    if worst <= -0.10:
        state = TailLossState.EXIT_REQUIRED
    elif worst <= -0.085:
        state = TailLossState.CHAOS_LOSS_ZONE
    elif worst <= -abs(emergency_max_loss):
        state = TailLossState.EXIT_REQUIRED
    elif worst <= -abs(max_allowed_loss):
        state = TailLossState.HOLD_WITH_ALERT
    else:
        state = TailLossState.ACCEPTABLE_RISK
    return {
        "state": state.value,
        "tail_drag": round(tail_drag, 6),
        "worst_loss_pct": round(worst, 6),
        "max_allowed_loss": max_allowed_loss,
        "emergency_max_loss": emergency_max_loss,
    }
