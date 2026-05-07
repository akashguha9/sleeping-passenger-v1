from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import clamp01


DO_NOT_DEPLOY_POLICY_STATES = {"RESTRICTED", "DO_NOT_DEPLOY", "BLOCKED", "NOT_READY"}


@dataclass(frozen=True)
class ExtremeStateThresholds:
    """Central thresholds for the extreme-state logic layer."""

    theta_validity: float = 0.60
    theta_conversion: float = 0.50
    theta_exit: float = 0.65
    theta_executable: float = 0.50
    minimum_repeatability_for_promotion: float = 0.55
    high_symmetry_threshold: float = 0.80
    low_conversion_threshold: float = 0.35
    equilibrium_threshold: float = 0.70
    silent_chaos_threshold: float = 0.70
    low_transition_threshold: float = 0.25
    loop_risk_threshold: float = 0.75
    duration_threshold: float = 0.80
    holding_cost_threshold: float = 0.70


@dataclass
class ExtremeStateSignal:
    signal_id: str = "UNKNOWN_SIGNAL"
    symbol: str = "UNKNOWN"
    timestamp: str | None = None
    policy_state: str = "UNKNOWN"
    operating_mode: str = "seeded"
    truth_origin: str = "seeded"
    external_reality_connected: bool = False
    signal_strength_score: float = 0.0
    signal_validity_score: float = 0.0
    technique_score: float = 0.0
    structure_score: float = 0.0
    timing_score: float = 0.0
    sequence_quality: float = 0.0
    timing_precision: float = 0.0
    transfer_efficiency: float = 0.0
    contact_quality: float = 0.0
    access_score: float = 0.0
    angle_score: float = 0.0
    timing_access_score: float = 0.0
    constraint_reduction_score: float = 0.0
    successful_repetitions: int = 0
    total_attempts: int = 0
    stress_survival_score: float = 0.0
    persistence_score: float = 0.0
    conversion_trigger_score: float = 0.0
    trigger_presence_score: float = 0.0
    timing_window_score: float = 0.0
    opponent_weakness_score: float = 0.0
    opponent_counter_signal_strength: float = 0.0
    exit_clarity_score: float = 0.0
    stability_score: float = 0.0
    duration_zscore_normalized: float = 0.0
    transition_count: int = 0
    transition_rate: float = 0.0
    cost_increase_score: float = 0.0
    visible_volatility_score: float = 0.0
    time_cost: float = 0.0
    mental_cost: float = 0.0
    opportunity_cost: float = 0.0
    risk_cost: float = 0.0
    hold_probability: float = 0.0
    forced_exit_presence: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "ExtremeStateSignal":
        row = payload if isinstance(payload, dict) else {}
        warnings: list[str] = [
            str(item) for item in (row.get("warnings") or []) if str(item).strip()
        ]

        def _text(key: str, default: str = "") -> str:
            value = row.get(key, default)
            return str(value).strip() if value is not None else default

        def _float(key: str, default: float = 0.0) -> float:
            value = row.get(key, default)
            if value is None:
                warnings.append(f"missing:{key}")
                return default
            try:
                return clamp01(float(value))
            except (TypeError, ValueError):
                warnings.append(f"invalid:{key}")
                return default

        def _raw_float(key: str, default: float = 0.0) -> float:
            value = row.get(key, default)
            if value is None:
                warnings.append(f"missing:{key}")
                return default
            try:
                return float(value)
            except (TypeError, ValueError):
                warnings.append(f"invalid:{key}")
                return default

        def _int(key: str, default: int = 0) -> int:
            value = row.get(key, default)
            if value is None:
                warnings.append(f"missing:{key}")
                return default
            try:
                return int(value)
            except (TypeError, ValueError):
                warnings.append(f"invalid:{key}")
                return default

        signal = cls(
            signal_id=_text("signal_id", "UNKNOWN_SIGNAL"),
            symbol=_text("symbol", _text("ticker", "UNKNOWN")).upper() or "UNKNOWN",
            timestamp=_text("timestamp") or None,
            policy_state=_text("policy_state", "UNKNOWN").upper() or "UNKNOWN",
            operating_mode=_text("operating_mode", "seeded"),
            truth_origin=_text("truth_origin", "seeded"),
            external_reality_connected=bool(row.get("external_reality_connected", False)),
            signal_strength_score=_float("signal_strength_score", _raw_float("ce_score", 0.0)),
            signal_validity_score=_float("signal_validity_score", _raw_float("ce_score", 0.0)),
            technique_score=_float("technique_score"),
            structure_score=_float("structure_score"),
            timing_score=_float("timing_score"),
            sequence_quality=_float("sequence_quality"),
            timing_precision=_float("timing_precision"),
            transfer_efficiency=_float("transfer_efficiency"),
            contact_quality=_float("contact_quality"),
            access_score=_float("access_score"),
            angle_score=_float("angle_score"),
            timing_access_score=_float("timing_access_score"),
            constraint_reduction_score=_float("constraint_reduction_score"),
            successful_repetitions=_int("successful_repetitions", 0),
            total_attempts=_int("total_attempts", 0),
            stress_survival_score=_float("stress_survival_score"),
            persistence_score=_float("persistence_score"),
            conversion_trigger_score=_float("conversion_trigger_score"),
            trigger_presence_score=_float("trigger_presence_score"),
            timing_window_score=_float("timing_window_score"),
            opponent_weakness_score=_float("opponent_weakness_score"),
            opponent_counter_signal_strength=_float("opponent_counter_signal_strength"),
            exit_clarity_score=_float("exit_clarity_score"),
            stability_score=_float("stability_score"),
            duration_zscore_normalized=_float("duration_zscore_normalized"),
            transition_count=_int("transition_count", 0),
            transition_rate=_float("transition_rate"),
            cost_increase_score=_float("cost_increase_score"),
            visible_volatility_score=_float("visible_volatility_score"),
            time_cost=_float("time_cost"),
            mental_cost=_float("mental_cost"),
            opportunity_cost=_float("opportunity_cost"),
            risk_cost=_float("risk_cost"),
            hold_probability=_float("hold_probability"),
            forced_exit_presence=_float("forced_exit_presence"),
            warnings=warnings,
        )
        return signal


@dataclass
class ExtremeStateEvaluation:
    signal_id: str
    symbol: str
    extreme_state: str
    scores: dict[str, float]
    flags: dict[str, bool]
    decision: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
