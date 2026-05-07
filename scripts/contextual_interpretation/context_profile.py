from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ContextProfile:
    regime: str
    liquidity: str
    volatility: str
    spread: str
    session: str
    narrative_state: str
    timeframe: str
    participant_mix: str
    funding: str
    fee_context: str
    data_truth_origin: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label_from_score(
    value: float,
    *,
    low_label: str,
    mid_label: str,
    high_label: str,
) -> str:
    if value >= 0.7:
        return high_label
    if value >= 0.4:
        return mid_label
    return low_label


def build_context_profile(
    raw_signal: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> ContextProfile:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    execution_policy = state.get("execution_policy", {})
    volatility_score = float(raw_signal.get("chaos_score", raw_signal.get("volatility_score", 0.3)) or 0.0)
    spread_score = float(raw_signal.get("spread_score", raw_signal.get("liquidity_fragility", 0.2)) or 0.0)
    liquidity_score = float(raw_signal.get("liquidity_score", 1.0 - spread_score) or 0.0)
    policy_allows = bool(execution_policy.get("allow_new_risk", False))

    regime = str(
        raw_signal.get(
            "regime",
            "CHAOS" if (volatility_score >= 0.72 or not policy_allows) else "VOLATILE" if volatility_score >= 0.45 else "NORMAL",
        )
    ).upper()

    return ContextProfile(
        regime=regime,
        liquidity=_label_from_score(liquidity_score, low_label="THIN", mid_label="NORMAL", high_label="DEEP"),
        volatility=_label_from_score(volatility_score, low_label="LOW", mid_label="ELEVATED", high_label="HIGH"),
        spread=_label_from_score(spread_score, low_label="TIGHT", mid_label="NORMAL", high_label="WIDE"),
        session=str(raw_signal.get("session", state.get("session", "UNKNOWN"))).upper(),
        narrative_state=str(raw_signal.get("narrative_state", "MIXED")).upper(),
        timeframe=str(raw_signal.get("timeframe", "SWING")).upper(),
        participant_mix=str(raw_signal.get("participant_mix", "MIXED")).upper(),
        funding=str(raw_signal.get("funding", "NEUTRAL")).upper(),
        fee_context=str(raw_signal.get("fee_context", "STANDARD")).upper(),
        data_truth_origin=str(
            raw_signal.get(
                "data_truth_origin",
                state.get("truth_origin", state.get("source_mode", "SEEDED")),
            )
        ).upper(),
    )
