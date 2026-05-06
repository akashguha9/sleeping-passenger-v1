from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


EPSILON = 1e-6
PRIMARY_ROLE_THRESHOLD = 0.60
STRUCTURAL_COMPROMISE_MAX = 0.45
SYSTEM_DEPENDENCY_MAX = 0.65
CHAOS_ALLOWED_ARCHETYPES = {"TARKOWSKI_CORE"}
BAINES_WEIGHTS = {
    "role_mismatch": 0.25,
    "multi_channel_output": 0.25,
    "repeatability": 0.20,
    "catalyst": 0.15,
    "attention_discount": 0.15,
}
TARKOWSKI_WEIGHTS = {
    "defense": 0.50,
    "survival": 0.30,
    "rare_upside": 0.20,
}
DEFAULT_ALLOCATION_BANDS = {
    "tarkowski_core": "40-60%",
    "baines_expansion": "30-40%",
    "optional_spikes": "5-15%",
}
CHAOS_ALLOCATION_BANDS = {
    "tarkowski_core": "70-100%",
    "baines_expansion": "0%",
    "optional_spikes": "0%",
}


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _safe_divide(numerator: Any, denominator: Any) -> float:
    try:
        numer = float(numerator)
    except (TypeError, ValueError):
        numer = 0.0
    try:
        denom = float(denominator)
    except (TypeError, ValueError):
        denom = 0.0
    return _clamp(numer / max(abs(denom), EPSILON))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class FootballPortfolioCandidateInput:
    candidate_id: str
    asset_symbol: str
    asset_name: str = ""
    primary_role_score: float = 0.0
    secondary_output_score: float = 0.0
    output_percentile: float = 0.0
    price_percentile: float = 0.0
    multi_channel_output_score: float = 0.0
    repeatability_score: float = 0.0
    catalyst_score: float = 0.0
    attention_score: float = 0.0
    relative_cost_score: float = 0.0
    risk_adjusted_cost: float = 0.0
    defense_score: float = 0.0
    survival_score: float = 0.0
    catalyst_probability: float = 0.0
    impact_magnitude: float = 0.0
    structural_safety_score: float = 0.0
    system_dependency_score: float = 0.0
    structural_compromise_score: float = 0.0
    validated_output_score: float = 0.0
    policy_veto: bool = False
    chaos_state: bool = False
    heat_state: bool = False
    run_id: str | None = None
    generated_at: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "FootballPortfolioCandidateInput":
        row = payload if isinstance(payload, dict) else {}
        return cls(
            candidate_id=_text(row.get("candidate_id"), _text(row.get("asset_symbol"), "UNKNOWN")),
            asset_symbol=_text(row.get("asset_symbol"), _text(row.get("candidate_id"), "UNKNOWN")),
            asset_name=_text(row.get("asset_name")),
            primary_role_score=_clamp(row.get("primary_role_score")),
            secondary_output_score=_clamp(row.get("secondary_output_score")),
            output_percentile=_clamp(row.get("output_percentile")),
            price_percentile=_clamp(row.get("price_percentile")),
            multi_channel_output_score=_clamp(row.get("multi_channel_output_score")),
            repeatability_score=_clamp(row.get("repeatability_score")),
            catalyst_score=_clamp(row.get("catalyst_score")),
            attention_score=_clamp(row.get("attention_score")),
            relative_cost_score=_clamp(row.get("relative_cost_score")),
            risk_adjusted_cost=max(float(row.get("risk_adjusted_cost", 0.0) or 0.0), 0.0),
            defense_score=_clamp(row.get("defense_score")),
            survival_score=_clamp(row.get("survival_score")),
            catalyst_probability=_clamp(row.get("catalyst_probability")),
            impact_magnitude=_clamp(row.get("impact_magnitude")),
            structural_safety_score=_clamp(row.get("structural_safety_score")),
            system_dependency_score=_clamp(row.get("system_dependency_score")),
            structural_compromise_score=_clamp(row.get("structural_compromise_score")),
            validated_output_score=_clamp(
                row.get("validated_output_score", row.get("secondary_output_score"))
            ),
            policy_veto=_truthy(row.get("policy_veto")),
            chaos_state=_truthy(row.get("chaos_state")),
            heat_state=_truthy(row.get("heat_state")),
            run_id=_text(row.get("run_id")) or None,
            generated_at=_text(row.get("generated_at")) or None,
        )


@dataclass(frozen=True)
class FootballPortfolioCandidateOutput:
    candidate_id: str
    asset_symbol: str
    asset_name: str
    primary_role_score: float
    secondary_output_score: float
    role_mismatch_score: float
    multi_channel_output_score: float
    repeatability_score: float
    catalyst_score: float
    attention_score: float
    attention_discount: float
    relative_cost_score: float
    risk_adjusted_cost: float
    defense_score: float
    survival_score: float
    rare_upside_score: float
    system_dependency_score: float
    structural_compromise_score: float
    baines_score: float
    tarkowski_score: float
    net_value_score: float
    bpm_score: float
    archetype_classification: str
    admission_decision: str
    rejection_reason: str | None
    policy_veto_applied: bool
    chaos_gate_applied: bool
    preferred_asset_score: float
    true_value_score: float
    formula_trace: dict[str, str] = field(default_factory=dict)
    explanation: list[str] = field(default_factory=list)
    run_id: str | None = None
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rare_upside_score(candidate: FootballPortfolioCandidateInput) -> float:
    return _clamp(
        candidate.catalyst_probability
        * candidate.impact_magnitude
        * candidate.structural_safety_score
    )


def _role_mismatch_score(candidate: FootballPortfolioCandidateInput) -> float:
    return _clamp(candidate.output_percentile - candidate.price_percentile)


def _attention_discount(attention_score: float) -> float:
    return _clamp(1.0 - attention_score)


def _baines_score(
    *,
    role_mismatch_score: float,
    multi_channel_output_score: float,
    repeatability_score: float,
    catalyst_score: float,
    attention_discount: float,
) -> float:
    return _clamp(
        (BAINES_WEIGHTS["role_mismatch"] * role_mismatch_score)
        + (BAINES_WEIGHTS["multi_channel_output"] * multi_channel_output_score)
        + (BAINES_WEIGHTS["repeatability"] * repeatability_score)
        + (BAINES_WEIGHTS["catalyst"] * catalyst_score)
        + (BAINES_WEIGHTS["attention_discount"] * attention_discount)
    )


def _tarkowski_score(
    *,
    defense_score: float,
    survival_score: float,
    rare_upside_score: float,
) -> float:
    return _clamp(
        (TARKOWSKI_WEIGHTS["defense"] * defense_score)
        + (TARKOWSKI_WEIGHTS["survival"] * survival_score)
        + (TARKOWSKI_WEIGHTS["rare_upside"] * rare_upside_score)
    )


def _preferred_asset_score(
    *,
    primary_role_score: float,
    durable_output_score: float,
    controlled_upside_score: float,
) -> float:
    return _clamp(primary_role_score * durable_output_score * controlled_upside_score)


def classify_football_portfolio_candidate(
    payload: FootballPortfolioCandidateInput | dict[str, Any] | None,
) -> dict[str, Any]:
    candidate = (
        payload
        if isinstance(payload, FootballPortfolioCandidateInput)
        else FootballPortfolioCandidateInput.from_payload(payload)
    )
    role_mismatch_score = round(_role_mismatch_score(candidate), 3)
    attention_discount = round(_attention_discount(candidate.attention_score), 3)
    rare_upside_score = round(_rare_upside_score(candidate), 3)
    bpm_score = round(
        _safe_divide(candidate.validated_output_score, candidate.risk_adjusted_cost),
        3,
    )
    baines_score = round(
        _baines_score(
            role_mismatch_score=role_mismatch_score,
            multi_channel_output_score=candidate.multi_channel_output_score,
            repeatability_score=candidate.repeatability_score,
            catalyst_score=candidate.catalyst_score,
            attention_discount=attention_discount,
        ),
        3,
    )
    tarkowski_score = round(
        _tarkowski_score(
            defense_score=candidate.defense_score,
            survival_score=candidate.survival_score,
            rare_upside_score=rare_upside_score,
        ),
        3,
    )
    net_value_score = round(
        _clamp(candidate.secondary_output_score - candidate.structural_compromise_score),
        3,
    )
    true_value_score = round(
        _safe_divide(
            candidate.secondary_output_score,
            candidate.relative_cost_score
            + candidate.structural_compromise_score
            + candidate.attention_score,
        ),
        3,
    )
    durable_output_score = _clamp(candidate.repeatability_score * candidate.survival_score)
    controlled_upside_score = _clamp(rare_upside_score * (1.0 - candidate.system_dependency_score))
    preferred_asset_score = round(
        _preferred_asset_score(
            primary_role_score=candidate.primary_role_score,
            durable_output_score=durable_output_score,
            controlled_upside_score=controlled_upside_score,
        ),
        3,
    )

    policy_veto_applied = candidate.policy_veto
    chaos_gate_applied = False
    rejection_reason: str | None = None

    if policy_veto_applied:
        archetype_classification = "UNCLASSIFIED"
        admission_decision = "BLOCKED_POLICY_VETO"
        rejection_reason = "policy_veto"
    elif candidate.primary_role_score < PRIMARY_ROLE_THRESHOLD:
        archetype_classification = "REJECT_PRIMARY_ROLE_FAILURE"
        admission_decision = "REJECT"
        rejection_reason = "primary_role_below_threshold"
    elif candidate.structural_compromise_score > STRUCTURAL_COMPROMISE_MAX:
        archetype_classification = "REJECT_PRIMARY_ROLE_FAILURE"
        admission_decision = "REJECT"
        rejection_reason = "structural_compromise_exceeded"
    elif candidate.chaos_state and tarkowski_score < 0.65:
        archetype_classification = "REJECT_CHAOS_REGIME"
        admission_decision = "REJECT"
        rejection_reason = "chaos_regime_non_defensive_candidate"
        chaos_gate_applied = True
    elif (
        candidate.defense_score >= 0.75
        and candidate.survival_score >= 0.75
        and candidate.structural_compromise_score <= 0.25
        and candidate.system_dependency_score <= 0.35
    ):
        archetype_classification = "TARKOWSKI_CORE"
        admission_decision = "ADMIT_CORE"
    elif (
        role_mismatch_score >= 0.20
        and candidate.multi_channel_output_score >= 0.65
        and candidate.repeatability_score >= 0.65
        and attention_discount >= 0.25
        and candidate.relative_cost_score <= 0.60
        and candidate.structural_compromise_score <= 0.25
    ):
        archetype_classification = "BAINES_EXPANSION"
        admission_decision = "VALIDATION_QUEUE"
    elif (
        candidate.defense_score >= 0.65
        and candidate.secondary_output_score >= 0.80
        and candidate.catalyst_score >= 0.60
        and candidate.structural_compromise_score <= 0.35
    ):
        archetype_classification = "ALONSO_FINISHER_VARIANT"
        admission_decision = "CAPPED_OPTIONAL_SPIKE"
    elif (
        candidate.secondary_output_score >= 0.70
        and (
            candidate.system_dependency_score > SYSTEM_DEPENDENCY_MAX
            or candidate.primary_role_score < 0.70
        )
    ):
        archetype_classification = "TRENT_SYSTEM_DEPENDENT_RISK"
        admission_decision = "CAP_OR_REJECT"
    else:
        archetype_classification = "UNCLASSIFIED"
        admission_decision = "WATCHLIST"

    if candidate.chaos_state and archetype_classification not in CHAOS_ALLOWED_ARCHETYPES:
        if not policy_veto_applied and admission_decision != "REJECT":
            archetype_classification = "REJECT_CHAOS_REGIME"
            admission_decision = "REJECT"
            rejection_reason = "chaos_regime_non_tarkowski"
            chaos_gate_applied = True

    explanation: list[str] = []
    if archetype_classification == "BAINES_EXPANSION":
        explanation.append("Primary role integrity is intact and output expands beyond label.")
    elif archetype_classification == "TARKOWSKI_CORE":
        explanation.append("Defensive reliability and survival dominate under current conditions.")
    elif archetype_classification == "ALONSO_FINISHER_VARIANT":
        explanation.append("Defensive label carries finisher upside without failing core role.")
    elif archetype_classification == "TRENT_SYSTEM_DEPENDENT_RISK":
        explanation.append("Output is high but too dependent on ideal system conditions.")
    elif archetype_classification == "REJECT_PRIMARY_ROLE_FAILURE":
        explanation.append("Primary role integrity failed before upside could be considered.")
    elif archetype_classification == "REJECT_CHAOS_REGIME":
        explanation.append("Chaos regime allows only defensive-core candidates.")
    if policy_veto_applied:
        explanation.append("Policy veto outranks all archetype scores.")
    if not explanation:
        explanation.append("Candidate remains observational until stronger structural evidence appears.")

    formula_trace = {
        "preferred_asset": (
            f"{candidate.primary_role_score:.3f} * {durable_output_score:.3f} * "
            f"{controlled_upside_score:.3f} = {preferred_asset_score:.3f}"
        ),
        "baines_value": (
            f"{candidate.multi_channel_output_score:.3f} / max({candidate.relative_cost_score:.3f}, "
            f"{EPSILON}) = {_safe_divide(candidate.multi_channel_output_score, candidate.relative_cost_score):.3f}"
        ),
        "role_mismatch_score": (
            f"{candidate.output_percentile:.3f} - {candidate.price_percentile:.3f} = "
            f"{role_mismatch_score:.3f}"
        ),
        "bpm_score": (
            f"{candidate.validated_output_score:.3f} / max({candidate.risk_adjusted_cost:.3f}, "
            f"{EPSILON}) = {bpm_score:.3f}"
        ),
        "tarkowski_value": (
            f"{candidate.defense_score:.3f} + {candidate.survival_score:.3f} + "
            f"{rare_upside_score:.3f} -> {tarkowski_score:.3f}"
        ),
        "rare_upside_score": (
            f"{candidate.catalyst_probability:.3f} * {candidate.impact_magnitude:.3f} * "
            f"{candidate.structural_safety_score:.3f} = {rare_upside_score:.3f}"
        ),
        "net_value_score": (
            f"{candidate.secondary_output_score:.3f} - {candidate.structural_compromise_score:.3f} = "
            f"{net_value_score:.3f}"
        ),
        "true_value_score": (
            f"{candidate.secondary_output_score:.3f} / "
            f"({candidate.relative_cost_score:.3f} + {candidate.structural_compromise_score:.3f} + "
            f"{candidate.attention_score:.3f}) = {true_value_score:.3f}"
        ),
        "gates": (
            f"policy_veto={str(policy_veto_applied).lower()}, "
            f"chaos_gate={str(chaos_gate_applied).lower()}, "
            f"primary_role_threshold={PRIMARY_ROLE_THRESHOLD:.2f}, "
            f"structural_compromise_max={STRUCTURAL_COMPROMISE_MAX:.2f}, "
            f"system_dependency_max={SYSTEM_DEPENDENCY_MAX:.2f}"
        ),
    }

    return FootballPortfolioCandidateOutput(
        candidate_id=candidate.candidate_id,
        asset_symbol=candidate.asset_symbol,
        asset_name=candidate.asset_name,
        primary_role_score=round(candidate.primary_role_score, 3),
        secondary_output_score=round(candidate.secondary_output_score, 3),
        role_mismatch_score=role_mismatch_score,
        multi_channel_output_score=round(candidate.multi_channel_output_score, 3),
        repeatability_score=round(candidate.repeatability_score, 3),
        catalyst_score=round(candidate.catalyst_score, 3),
        attention_score=round(candidate.attention_score, 3),
        attention_discount=attention_discount,
        relative_cost_score=round(candidate.relative_cost_score, 3),
        risk_adjusted_cost=round(candidate.risk_adjusted_cost, 3),
        defense_score=round(candidate.defense_score, 3),
        survival_score=round(candidate.survival_score, 3),
        rare_upside_score=rare_upside_score,
        system_dependency_score=round(candidate.system_dependency_score, 3),
        structural_compromise_score=round(candidate.structural_compromise_score, 3),
        baines_score=baines_score,
        tarkowski_score=tarkowski_score,
        net_value_score=net_value_score,
        bpm_score=bpm_score,
        archetype_classification=archetype_classification,
        admission_decision=admission_decision,
        rejection_reason=rejection_reason,
        policy_veto_applied=policy_veto_applied,
        chaos_gate_applied=chaos_gate_applied,
        preferred_asset_score=preferred_asset_score,
        true_value_score=true_value_score,
        formula_trace=formula_trace,
        explanation=explanation,
        run_id=candidate.run_id,
        generated_at=candidate.generated_at or _utc_now(),
    ).to_dict()


def build_football_portfolio_allocation_recommendation(
    *,
    policy_state: str,
    chaos_state: bool,
    candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    rows = list(candidates or [])
    policy_blocked = str(policy_state or "").upper() in {"RESTRICTED", "BLOCKED", "DO_NOT_DEPLOY", "NOT_READY"}
    if chaos_state or policy_blocked:
        return {
            "portfolio_mode": "DEFENSE_FIRST",
            "allocation_bands": dict(CHAOS_ALLOCATION_BANDS),
            "advisory": "Policy/chaos regime restricts portfolio to defensive-core suggestions only.",
            "policy_veto_applied": policy_blocked,
        }

    top_tarkowski = max(
        (float(row.get("tarkowski_score", 0.0) or 0.0) for row in rows if row.get("archetype_classification") == "TARKOWSKI_CORE"),
        default=0.0,
    )
    top_baines = max(
        (float(row.get("baines_score", 0.0) or 0.0) for row in rows if row.get("archetype_classification") == "BAINES_EXPANSION"),
        default=0.0,
    )
    return {
        "portfolio_mode": "BALANCED_EXPANSION" if top_baines >= 0.65 else "DEFENSE_TILTED",
        "allocation_bands": dict(DEFAULT_ALLOCATION_BANDS),
        "advisory": "Suggest core-first allocation bands only; human executor decides whether to act.",
        "policy_veto_applied": policy_blocked,
        "top_tarkowski_score": round(top_tarkowski, 3),
        "top_baines_score": round(top_baines, 3),
    }


def build_football_portfolio_archetype_report(
    candidates: list[FootballPortfolioCandidateInput | dict[str, Any]] | None,
    *,
    policy_state: str,
    chaos_state: bool,
    run_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    rows = list(candidates or [])
    outputs = [classify_football_portfolio_candidate(row) for row in rows]
    outputs.sort(
        key=lambda item: (
            -float(item.get("preferred_asset_score", 0.0) or 0.0),
            str(item.get("asset_symbol") or ""),
        )
    )
    counts = {
        "baines_candidates_count": sum(1 for item in outputs if item["archetype_classification"] == "BAINES_EXPANSION"),
        "tarkowski_candidates_count": sum(1 for item in outputs if item["archetype_classification"] == "TARKOWSKI_CORE"),
        "alonso_variant_count": sum(1 for item in outputs if item["archetype_classification"] == "ALONSO_FINISHER_VARIANT"),
        "trent_risk_count": sum(1 for item in outputs if item["archetype_classification"] == "TRENT_SYSTEM_DEPENDENT_RISK"),
        "primary_role_rejections_count": sum(1 for item in outputs if item["archetype_classification"] == "REJECT_PRIMARY_ROLE_FAILURE"),
        "chaos_rejections_count": sum(1 for item in outputs if item["archetype_classification"] == "REJECT_CHAOS_REGIME"),
    }
    top_baines = next((item for item in outputs if item["archetype_classification"] == "BAINES_EXPANSION"), None)
    top_tarkowski = next((item for item in outputs if item["archetype_classification"] == "TARKOWSKI_CORE"), None)
    allocation = build_football_portfolio_allocation_recommendation(
        policy_state=policy_state,
        chaos_state=chaos_state,
        candidates=outputs,
    )
    rejected = [
        {
            "asset_symbol": item["asset_symbol"],
            "classification": item["archetype_classification"],
            "rejection_reason": item["rejection_reason"],
        }
        for item in outputs
        if item["admission_decision"] in {"REJECT", "BLOCKED_POLICY_VETO"}
    ]
    policy_veto_applied = any(bool(item.get("policy_veto_applied", False)) for item in outputs)
    if not outputs:
        state = "EMPTY"
    elif counts["tarkowski_candidates_count"] > 0 and chaos_state:
        state = "DEFENSIVE_ONLY"
    elif counts["baines_candidates_count"] > 0 or counts["alonso_variant_count"] > 0:
        state = "EXPANSION_CANDIDATES_PRESENT"
    else:
        state = "SCANNING"
    return {
        "run_id": run_id,
        "generated_at": generated_at or _utc_now(),
        "football_portfolio_archetype_engine_available": True,
        "football_portfolio_archetype_engine_state": state,
        "policy_state": policy_state,
        "chaos_state": chaos_state,
        "policy_veto_applied": policy_veto_applied,
        "portfolio_mode": allocation["portfolio_mode"],
        "allocation_recommendation": allocation,
        **counts,
        "top_baines_candidate": top_baines["asset_symbol"] if top_baines else None,
        "top_tarkowski_candidate": top_tarkowski["asset_symbol"] if top_tarkowski else None,
        "top_baines_score": top_baines["baines_score"] if top_baines else None,
        "top_tarkowski_score": top_tarkowski["tarkowski_score"] if top_tarkowski else None,
        "candidates": outputs,
        "rejected_candidates": rejected,
    }
