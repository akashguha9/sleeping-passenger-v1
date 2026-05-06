from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


COMPLEXITY_LAMBDA = 0.12


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass(frozen=True)
class AssetDurabilityReport:
    hundred_wash_score: float
    stress_survival_score: float
    material_integrity_score: float
    brand_distortion_score: float
    source_layer_advantage_score: float
    paracetamol_score: float
    complexity_penalty: float
    positive_adaptation_score: float
    durability_class: str
    adjusted_score: float
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_asset_durability_report(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    durability = _clamp(payload.get("durability"))
    recovery = _clamp(payload.get("recovery"))
    adaptation = _clamp(payload.get("adaptation"))
    liquidity = _clamp(payload.get("liquidity"))
    low_fragility = _clamp(payload.get("low_fragility"))
    performance_before = max(float(payload.get("performance_before_stress", 1.0) or 1.0), 0.0001)
    performance_after = max(float(payload.get("performance_after_stress", performance_before) or performance_before), 0.0)
    stress_survival = round(_clamp(performance_after / performance_before), 3)

    material_integrity_score = round(
        _clamp(
            payload.get(
                "material_integrity_score",
                _mean(
                    [
                        _clamp(payload.get("cash_flow_quality", durability)),
                        _clamp(payload.get("margin_quality", recovery)),
                        1.0 - _clamp(payload.get("debt_burden", 1.0 - low_fragility)),
                        _clamp(payload.get("pricing_power", liquidity)),
                        _clamp(payload.get("revenue_recurrence", adaptation)),
                    ]
                ),
            )
        ),
        3,
    )
    fundamental_durability_value = max(float(payload.get("fundamental_durability_value", 1.0) or 1.0), 0.0001)
    market_price = max(float(payload.get("market_price", fundamental_durability_value) or fundamental_durability_value), 0.0001)
    brand_distortion_score = round(
        _clamp(max(0.0, market_price - fundamental_durability_value) / market_price),
        3,
    )
    source_layer_advantage_score = round(
        _clamp(
            _mean(
                [
                    _clamp(payload.get("dependency_importance", 0.5)),
                    _clamp(payload.get("low_visibility", 0.5)),
                    _clamp(payload.get("high_recurrence", 0.5)),
                ]
            )
        ),
        3,
    )
    paracetamol_score = round(
        _clamp(
            _clamp(payload.get("simple_mechanism"))
            * _clamp(payload.get("universal_need"))
            * _clamp(payload.get("repeat_demand"))
            * low_fragility
        ),
        3,
    )
    complexity_components = [
        _clamp(payload.get("unrelated_business_lines")),
        _clamp(payload.get("single_founder_dependency")),
        _clamp(payload.get("single_regulation_dependency")),
        _clamp(payload.get("single_liquidity_dependency")),
        _clamp(payload.get("single_narrative_dependency")),
        _clamp(payload.get("unclear_core_mechanism")),
    ]
    complexity_penalty = round(_clamp(_mean(complexity_components) * COMPLEXITY_LAMBDA * 2.0), 3)
    positive_adaptation_score = round(
        _clamp(
            payload.get(
                "positive_adaptation_score",
                max(0.0, performance_after - performance_before) / max(performance_before, 0.0001),
            )
        ),
        3,
    )
    hundred_wash_score = round(
        _clamp(
            (0.25 * durability)
            + (0.20 * recovery)
            + (0.20 * adaptation)
            + (0.20 * liquidity)
            + (0.15 * low_fragility)
        ),
        3,
    )
    adjusted_score = round(
        _clamp((0.55 * hundred_wash_score) + (0.20 * stress_survival) + (0.15 * material_integrity_score) + (0.10 * paracetamol_score) - complexity_penalty),
        3,
    )

    if adjusted_score >= 0.85 and positive_adaptation_score >= 0.05:
        durability_class = "HUNDRED_WASH_CANDIDATE"
    elif adjusted_score >= 0.75 and positive_adaptation_score > 0.0:
        durability_class = "ADAPTIVE"
    elif adjusted_score >= 0.60:
        durability_class = "SURVIVOR"
    elif adjusted_score >= 0.40:
        durability_class = "UNPROVEN"
    else:
        durability_class = "FRAGILE"

    rationale: list[str] = []
    if positive_adaptation_score > 0.0:
        rationale.append("Asset quality improved or held up after stress.")
    if brand_distortion_score >= 0.4:
        rationale.append("Brand premium appears to exceed durability value.")
    if paracetamol_score >= 0.5:
        rationale.append("Core mechanism serves a recurring, universal need with low fragility.")
    if complexity_penalty >= 0.15:
        rationale.append("Complexity penalty materially reduced the adjusted durability score.")
    if not rationale:
        rationale.append("Durability profile is derived conservatively from current offline artifacts.")

    return AssetDurabilityReport(
        hundred_wash_score=hundred_wash_score,
        stress_survival_score=stress_survival,
        material_integrity_score=material_integrity_score,
        brand_distortion_score=brand_distortion_score,
        source_layer_advantage_score=source_layer_advantage_score,
        paracetamol_score=paracetamol_score,
        complexity_penalty=complexity_penalty,
        positive_adaptation_score=positive_adaptation_score,
        durability_class=durability_class,
        adjusted_score=adjusted_score,
        rationale=rationale,
    ).to_dict()
