from __future__ import annotations

from scripts.hedge_trade_entry_common import safe_div


def evaluate_execution_quality(
    *,
    realized_return: float,
    available_signal_return: float | None,
    drawdown_reduction: float,
    lost_upside: float,
    hedge_cost: float,
    actual_loss: float,
    max_allowed_loss: float,
    late_entry_penalty: float = 0.0,
    premature_exit_penalty: float = 0.0,
) -> dict:
    """ExecutionQuality = RealizedReturn / AvailableSignalReturn."""
    execution_quality = safe_div(realized_return, available_signal_return, default=None)
    hedge_efficiency = float(drawdown_reduction) - float(lost_upside) - float(hedge_cost)
    missed_upside = None if available_signal_return is None else float(available_signal_return) - float(realized_return)
    loss_control_score = max(0.0, 1.0 - safe_div(abs(actual_loss), abs(max_allowed_loss), default=1.0))
    return {
        "execution_quality_ratio": execution_quality,
        "hedge_efficiency": hedge_efficiency,
        "tail_loss_prevention_score": round(loss_control_score, 6),
        "missed_upside_score": missed_upside,
        "late_entry_penalty": late_entry_penalty,
        "premature_exit_penalty": premature_exit_penalty,
    }
