from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


EPSILON = 1e-6
DEFAULT_WEIGHTS = {
    "role_mismatch": 0.22,
    "multichannel": 0.18,
    "attention_discount": 0.15,
    "repeatability": 0.18,
    "durability": 0.17,
    "cost_efficiency": 0.10,
    "volatility_penalty": 0.08,
    "liquidity_penalty": 0.07,
    "reality_gap_penalty": 0.10,
}
DEFAULT_THRESHOLDS = {
    "baines": 0.70,
    "repeatability": 0.60,
    "durability": 0.65,
    "multichannel": 0.55,
    "attention_max": 0.70,
    "role_mismatch": 0.20,
}
MAX_CHANNELS_FOR_FULL_SCORE = 3.0


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


@dataclass(frozen=True)
class BainesInput:
    asset_id: str
    asset_class: str = "unknown"
    listed_role: str = "unknown"
    observed_function: str = "unknown"
    price_score: float = 0.0
    output_score: float = 0.0
    output_percentile: float = 0.0
    price_expectation_percentile: float = 0.0
    attention_score: float = 0.0
    payoff_channels: dict[str, float] = field(default_factory=dict)
    persistence_score: float = 0.0
    stability_score: float = 0.0
    historical_conversion_score: float = 0.0
    performance_before_stress: float = 0.0
    performance_after_stress: float = 0.0
    risk_adjusted_cost: float = 0.0
    volatility_penalty: float = 0.0
    liquidity_penalty: float = 0.0
    reality_gap_penalty: float = 0.0
    policy_veto: bool = False
    chaos_veto: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "BainesInput":
        item = payload if isinstance(payload, dict) else {}
        return cls(
            asset_id=_text(item.get("asset_id"), "UNKNOWN"),
            asset_class=_text(item.get("asset_class"), "unknown"),
            listed_role=_text(item.get("listed_role"), "unknown"),
            observed_function=_text(item.get("observed_function"), "unknown"),
            price_score=_clamp(item.get("price_score")),
            output_score=_clamp(item.get("output_score")),
            output_percentile=_clamp(item.get("output_percentile")),
            price_expectation_percentile=_clamp(item.get("price_expectation_percentile")),
            attention_score=_clamp(item.get("attention_score")),
            payoff_channels={
                _text(key): _clamp(value)
                for key, value in (item.get("payoff_channels") or {}).items()
                if _text(key)
            },
            persistence_score=_clamp(item.get("persistence_score")),
            stability_score=_clamp(item.get("stability_score")),
            historical_conversion_score=_clamp(item.get("historical_conversion_score")),
            performance_before_stress=max(
                float(item.get("performance_before_stress", 0.0) or 0.0),
                0.0,
            ),
            performance_after_stress=max(
                float(item.get("performance_after_stress", 0.0) or 0.0),
                0.0,
            ),
            risk_adjusted_cost=max(float(item.get("risk_adjusted_cost", 0.0) or 0.0), 0.0),
            volatility_penalty=_clamp(item.get("volatility_penalty")),
            liquidity_penalty=_clamp(item.get("liquidity_penalty")),
            reality_gap_penalty=_clamp(item.get("reality_gap_penalty")),
            policy_veto=_bool(item.get("policy_veto")),
            chaos_veto=_bool(item.get("chaos_veto")),
        )


@dataclass(frozen=True)
class BainesOutput:
    asset_id: str
    baines_score: float
    bpm_score: float
    role_mismatch_score: float
    multichannel_score: float
    attention_discount: float
    repeatability_score: float
    durability_score: float
    classification: str
    recommended_next_state: str
    veto_reason: str | None
    explanation: list[str] = field(default_factory=list)
    formula_trace: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _multichannel_score(payoff_channels: dict[str, float]) -> float:
    channels = [_clamp(value) for value in payoff_channels.values()]
    if not channels:
        return 0.0
    return _clamp(sum(channels) / MAX_CHANNELS_FOR_FULL_SCORE)


def _repeatability_score(candidate: BainesInput) -> float:
    return _clamp(
        candidate.persistence_score
        * candidate.stability_score
        * candidate.historical_conversion_score
    )


def _durability_score(candidate: BainesInput) -> float:
    baseline = max(candidate.performance_before_stress, EPSILON)
    return _clamp(candidate.performance_after_stress / baseline)


def _bpm_score(candidate: BainesInput) -> float:
    return _clamp(candidate.output_score / max(candidate.risk_adjusted_cost, EPSILON))


def evaluate_baines_candidate(
    payload: BainesInput | dict[str, Any] | None,
    *,
    thresholds: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    candidate = payload if isinstance(payload, BainesInput) else BainesInput.from_payload(payload)
    configured_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    configured_weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    role_mismatch_score = round(
        _clamp(candidate.output_percentile - candidate.price_expectation_percentile),
        3,
    )
    multichannel_score = round(_multichannel_score(candidate.payoff_channels), 3)
    attention_discount = round(_clamp(1.0 - candidate.attention_score), 3)
    repeatability_score = round(_repeatability_score(candidate), 3)
    durability_score = round(_durability_score(candidate), 3)
    bpm_score = round(_bpm_score(candidate), 3)
    cost_efficiency_score = bpm_score

    weighted_score = (
        configured_weights["role_mismatch"] * role_mismatch_score
        + configured_weights["multichannel"] * multichannel_score
        + configured_weights["attention_discount"] * attention_discount
        + configured_weights["repeatability"] * repeatability_score
        + configured_weights["durability"] * durability_score
        + configured_weights["cost_efficiency"] * cost_efficiency_score
        - configured_weights["volatility_penalty"] * candidate.volatility_penalty
        - configured_weights["liquidity_penalty"] * candidate.liquidity_penalty
        - configured_weights["reality_gap_penalty"] * candidate.reality_gap_penalty
    )
    baines_score = round(_clamp(weighted_score), 3)

    veto_reason: str | None = None
    if candidate.policy_veto:
        classification = "BAINES_VETOED_POLICY"
        recommended_next_state = "BLOCKED_BY_POLICY"
        veto_reason = "policy_veto"
    elif candidate.chaos_veto:
        classification = "BAINES_VETOED_CHAOS"
        recommended_next_state = "BLOCKED_BY_CHAOS"
        veto_reason = "chaos_veto"
    elif baines_score < 0.50:
        classification = "BAINES_REJECTED"
        recommended_next_state = "IGNORE"
    elif baines_score < configured_thresholds["baines"]:
        classification = "BAINES_WATCHLIST"
        recommended_next_state = "WATCHLIST"
    elif (
        repeatability_score < configured_thresholds["repeatability"]
        or durability_score < configured_thresholds["durability"]
        or multichannel_score < configured_thresholds["multichannel"]
        or role_mismatch_score < configured_thresholds["role_mismatch"]
        or candidate.attention_score > configured_thresholds["attention_max"]
    ):
        classification = "BAINES_VALIDATION_REQUIRED"
        recommended_next_state = "MURCIELAGO_VALIDATION_QUEUE"
    elif _bool((payload or {}).get("downstream_validation_confirmed") if isinstance(payload, dict) else False):
        classification = "BAINES_PROMOTION_ELIGIBLE"
        recommended_next_state = "AVENTADOR_PROMOTION_GATE_REVIEW"
    else:
        classification = "BAINES_DURABLE_CANDIDATE"
        recommended_next_state = "MURCIELAGO_DURABILITY_CONFIRMED"

    explanation: list[str] = []
    if role_mismatch_score >= configured_thresholds["role_mismatch"]:
        explanation.append("Observed output exceeds market role expectations.")
    if multichannel_score >= configured_thresholds["multichannel"]:
        explanation.append("Multiple payoff channels support the candidate.")
    if attention_discount >= 0.5:
        explanation.append("Attention remains discounted relative to observed output.")
    if repeatability_score < configured_thresholds["repeatability"]:
        explanation.append("Repeatability is below durable-candidate requirements.")
    if durability_score < configured_thresholds["durability"]:
        explanation.append("Stress survival is not yet strong enough for promotion.")
    if classification.startswith("BAINES_VETOED"):
        explanation.append("Upstream veto outranks BAINES classification.")
    if not explanation:
        explanation.append("Candidate remains observation-grade until downstream validation confirms durability.")

    formula_trace = {
        "role_mismatch_score": (
            f"{candidate.output_percentile:.3f} - "
            f"{candidate.price_expectation_percentile:.3f} = {role_mismatch_score:.3f}"
        ),
        "multichannel_score": (
            f"sum(channels={list(candidate.payoff_channels.values())}) / "
            f"{MAX_CHANNELS_FOR_FULL_SCORE:.0f} = {multichannel_score:.3f}"
        ),
        "attention_discount": f"1 - {candidate.attention_score:.3f} = {attention_discount:.3f}",
        "repeatability_score": (
            f"{candidate.persistence_score:.3f} * {candidate.stability_score:.3f} * "
            f"{candidate.historical_conversion_score:.3f} = {repeatability_score:.3f}"
        ),
        "durability_score": (
            f"{candidate.performance_after_stress:.3f} / "
            f"max({candidate.performance_before_stress:.3f}, {EPSILON}) = {durability_score:.3f}"
        ),
        "bpm_score": (
            f"{candidate.output_score:.3f} / max({candidate.risk_adjusted_cost:.3f}, "
            f"{EPSILON}) = {bpm_score:.3f}"
        ),
        "final_baines_score": (
            f"weighted_positive - penalties = {baines_score:.3f}"
        ),
        "veto_logic": veto_reason or "no_veto",
    }

    return BainesOutput(
        asset_id=candidate.asset_id,
        baines_score=baines_score,
        bpm_score=bpm_score,
        role_mismatch_score=role_mismatch_score,
        multichannel_score=multichannel_score,
        attention_discount=attention_discount,
        repeatability_score=repeatability_score,
        durability_score=durability_score,
        classification=classification,
        recommended_next_state=recommended_next_state,
        veto_reason=veto_reason,
        explanation=explanation,
        formula_trace=formula_trace,
    ).to_dict()


def build_baines_engine_report(
    candidates: list[BainesInput | dict[str, Any]] | None,
    *,
    thresholds: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    rows = list(candidates or [])
    if not rows:
        return {
            "baines_engine_available": True,
            "baines_engine_state": "EMPTY",
            "baines_candidates_detected": 0,
            "baines_durable_candidates": 0,
            "baines_policy_vetoed": 0,
            "baines_chaos_vetoed": 0,
            "top_baines_candidate": None,
            "top_baines_score": None,
            "outputs": [],
        }

    outputs = [
        evaluate_baines_candidate(row, thresholds=thresholds, weights=weights)
        for row in rows
    ]
    outputs.sort(
        key=lambda item: (
            -float(item.get("baines_score", 0.0) or 0.0),
            str(item.get("asset_id") or ""),
        )
    )

    candidate_count = sum(
        1
        for item in outputs
        if item["classification"]
        in {
            "BAINES_WATCHLIST",
            "BAINES_VALIDATION_REQUIRED",
            "BAINES_DURABLE_CANDIDATE",
            "BAINES_PROMOTION_ELIGIBLE",
        }
    )
    durable_count = sum(
        1
        for item in outputs
        if item["classification"] in {"BAINES_DURABLE_CANDIDATE", "BAINES_PROMOTION_ELIGIBLE"}
    )
    policy_vetoed = sum(1 for item in outputs if item["classification"] == "BAINES_VETOED_POLICY")
    chaos_vetoed = sum(1 for item in outputs if item["classification"] == "BAINES_VETOED_CHAOS")

    if durable_count > 0:
        engine_state = "DURABLE_SIGNAL_FOUND"
    elif any(item["classification"] == "BAINES_VALIDATION_REQUIRED" for item in outputs):
        engine_state = "VALIDATION_REQUIRED"
    elif candidate_count > 0:
        engine_state = "CANDIDATES_FOUND"
    elif policy_vetoed > 0 or chaos_vetoed > 0:
        engine_state = "VETOED"
    else:
        engine_state = "SCANNING"

    return {
        "baines_engine_available": True,
        "baines_engine_state": engine_state,
        "baines_candidates_detected": candidate_count,
        "baines_durable_candidates": durable_count,
        "baines_policy_vetoed": policy_vetoed,
        "baines_chaos_vetoed": chaos_vetoed,
        "top_baines_candidate": outputs[0]["asset_id"] if outputs else None,
        "top_baines_score": outputs[0]["baines_score"] if outputs else None,
        "outputs": outputs,
    }
