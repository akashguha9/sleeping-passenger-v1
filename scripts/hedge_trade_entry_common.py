from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


EPSILON = 1e-9


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"
    CHAOS = "CHAOS"
    UNKNOWN = "UNKNOWN"


class TimingQuality(str, Enum):
    EARLY = "EARLY"
    VALID = "VALID"
    LATE = "LATE"
    UNKNOWN = "UNKNOWN"


class TradeMode(str, Enum):
    SURVIVAL_MODE = "SURVIVAL_MODE"
    BALANCED_MODE = "BALANCED_MODE"
    GROWTH_MODE = "GROWTH_MODE"
    NO_NEW_RISK_MODE = "NO_NEW_RISK_MODE"


class EntryGateState(str, Enum):
    ENTRY_ALLOWED = "ENTRY_ALLOWED"
    ENTRY_REJECTED = "ENTRY_REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_NEW_RISK = "NO_NEW_RISK"
    EXIT_REQUIRED = "EXIT_REQUIRED"


class PositionConflictState(str, Enum):
    VALID_STRUCTURE = "VALID_STRUCTURE"
    VALID_HEDGE = "VALID_HEDGE"
    INTERNAL_CONFLICT = "INTERNAL_CONFLICT"
    REDUNDANT_COMPLEXITY = "REDUNDANT_COMPLEXITY"
    ARBITRAGE_REQUIRES_PROOF = "ARBITRAGE_REQUIRES_PROOF"
    STRUCTURE_REVIEW_READY = "STRUCTURE_REVIEW_READY"


class LeverageSafetyState(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    UNSAFE = "UNSAFE"
    REJECTED = "REJECTED"


class TailLossState(str, Enum):
    ACCEPTABLE_RISK = "ACCEPTABLE_RISK"
    HOLD_WITH_ALERT = "HOLD_WITH_ALERT"
    EXIT_REQUIRED = "EXIT_REQUIRED"
    CHAOS_LOSS_ZONE = "CHAOS_LOSS_ZONE"


class HedgeClass(str, Enum):
    UNHEDGED = "UNHEDGED"
    LIGHT_HEDGE = "LIGHT_HEDGE"
    MODERATE_HEDGE = "MODERATE_HEDGE"
    HEAVY_HEDGE = "HEAVY_HEDGE"
    FULL_HEDGE = "FULL_HEDGE"
    OVER_HEDGED = "OVER_HEDGED"


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def safe_div(a: Any, b: Any, default: float | None = 0.0) -> float | None:
    try:
        denominator = float(b)
    except (TypeError, ValueError):
        return default
    if abs(denominator) < EPSILON:
        return default
    try:
        numerator = float(a)
    except (TypeError, ValueError):
        return default
    return numerator / denominator


@dataclass(slots=True)
class HedgePlaybookInput:
    signal_id: str
    asset: str = "UNKNOWN"
    spot_notional: float = 0.0
    futures_long_notional: float = 0.0
    futures_short_notional: float = 0.0
    futures_hedge_notional: float = 0.0
    declared_leg_purposes: list[str] | None = None
    arbitrage_rationale_present: bool = False
    funding_edge_present: bool = False
    basis_edge_present: bool = False
    leverage: float = 1.0
    user_max_leverage: float = 1.0
    regime: str = "NORMAL"
    signal_strength: SignalStrength = SignalStrength.UNKNOWN
    timing_quality: TimingQuality = TimingQuality.UNKNOWN
    chaos_score: float = 0.0
    drawdown_state: str = "NORMAL"
    volatility_state: str = "NORMAL"
    signal_valid: bool = False
    timing_valid: bool = False
    risk_defined: bool = False
    structure_valid: bool = False
    chaos_veto: bool = False
    shock_override: bool = False
    policy_allows_new_risk: bool = False
    projected_loss_pct: float = 0.0
    current_loss_pct: float = 0.0
    chaos_loss_frequency: float = 0.0
    average_chaos_loss: float = 0.0
    realized_return: float = 0.0
    available_signal_return: float | None = None
    drawdown_reduction: float = 0.0
    lost_upside: float = 0.0
    hedge_cost: float = 0.0
    actual_loss: float = 0.0
    max_allowed_loss: float = 0.05
    profit: float = 0.0
    starting_capital: float = 1.0
    period_weeks: float = 1.0
    fees: float = 0.0
    funding_cost: float = 0.0
    liquidation_risk_penalty: float = 0.0
    complexity_penalty: float = 0.0
    expected_price_edge: float = 0.0
    win_rate: float = 0.0
    average_win: float = 0.0
    loss_rate: float = 0.0
    average_loss: float = 0.0
    risk_cap_active: bool = False
    source: str = "synthetic"
