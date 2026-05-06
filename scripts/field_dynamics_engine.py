from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

EPSILON = 1e-6

GAUSS_SOURCE_WEIGHTS = {
    "sentiment": 0.22,
    "price": 0.24,
    "volume": 0.16,
    "event_prior": 0.20,
    "narrative": 0.18,
}

FIELD_WEAK_THRESHOLD = 0.25
FIELD_STRONG_THRESHOLD = 0.55
FIELD_PERSISTENCE_STRONG_THRESHOLD = 0.65
COHERENCE_WEAK_THRESHOLD = 0.35
COHERENCE_STRONG_THRESHOLD = 0.60
COHERENCE_HIGH_THRESHOLD = 0.80
EXECUTION_ALIGNMENT_THRESHOLD = 0.55
EXECUTION_CLARITY_THRESHOLD = 0.60
TRADE_READINESS_THRESHOLD = 0.42

NO_FIELD = "NO_FIELD"
WEAK_FIELD = "WEAK_FIELD"
FORMING_FIELD = "FORMING_FIELD"
STRONG_FIELD = "STRONG_FIELD"

NO_INTERACTION_DATA = "NO_INTERACTION_DATA"
DIVERGENT = "DIVERGENT"
WEAKLY_COHERENT = "WEAKLY_COHERENT"
COHERENT = "COHERENT"
HIGHLY_COHERENT = "HIGHLY_COHERENT"

NO_VECTOR = "NO_VECTOR"
MISALIGNED = "MISALIGNED"
WATCH = "WATCH"
ACTIONABLE_UNDER_POLICY = "ACTIONABLE_UNDER_POLICY"


def _clamp(value: Any, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = lower
    if numeric < lower:
        return lower
    if numeric > upper:
        return upper
    return numeric


def _safe_divide(numerator: float, denominator: float) -> float:
    if abs(denominator) <= EPSILON:
        return 0.0
    return numerator / denominator


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _direction_value(value: Any) -> float:
    if isinstance(value, str):
        text = value.strip().upper()
        if text in {"UP", "LONG", "BULLISH", "POSITIVE"}:
            return 1.0
        if text in {"DOWN", "SHORT", "BEARISH", "NEGATIVE"}:
            return -1.0
    return max(-1.0, min(1.0, _coerce_float(value, 0.0)))


def _source_presence(*values: Any) -> bool:
    for value in values:
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (int, float)) and abs(float(value)) > EPSILON:
            return True
    return False


@dataclass(frozen=True)
class FieldPressureState:
    asset: str
    pressure_score: float
    pressure_direction: str
    pressure_persistence: float
    pressure_sources: dict[str, float]
    source_count: int
    boundary_effect: float
    classification: str
    rationale: list[str]


@dataclass(frozen=True)
class FieldInteractionMatrix:
    asset: str
    price_sentiment_correlation: float | None
    event_liquidity_coupling: float | None
    narrative_momentum: float
    divergence_score: float
    interaction_coherence: float
    lag_warning: bool
    classification: str
    rationale: list[str]


@dataclass(frozen=True)
class ExecutionVector:
    asset: str
    direction: str
    force_magnitude: float
    alignment_score: float
    timing_window: float | None
    execution_clarity: float
    invalid_if: str
    classification: str
    rationale: list[str]


def compute_field_pressure_state(candidate_or_snapshot: dict[str, Any]) -> dict[str, Any]:
    asset = str(
        candidate_or_snapshot.get("asset")
        or candidate_or_snapshot.get("asset_symbol")
        or candidate_or_snapshot.get("ticker")
        or candidate_or_snapshot.get("candidate_id")
        or "UNKNOWN"
    ).upper()
    persistence = _clamp(
        candidate_or_snapshot.get("pressure_persistence")
        or candidate_or_snapshot.get("repeatability_score")
        or candidate_or_snapshot.get("persistence_score")
        or candidate_or_snapshot.get("first_order_score")
        or candidate_or_snapshot.get("durability_score")
        or 0.0
    )
    sentiment_signal = _direction_value(
        candidate_or_snapshot.get("sentiment_direction_score")
        or candidate_or_snapshot.get("sentiment_score")
        or candidate_or_snapshot.get("narrative_direction_score")
        or candidate_or_snapshot.get("attention_bias")
    )
    price_signal = _direction_value(
        candidate_or_snapshot.get("price_direction_score")
        or candidate_or_snapshot.get("price_signal_score")
        or candidate_or_snapshot.get("price_move_pct")
        or candidate_or_snapshot.get("price_confirmation_score")
    )
    volume_signal = _direction_value(
        candidate_or_snapshot.get("volume_direction_score")
        or candidate_or_snapshot.get("volume_signal_score")
        or candidate_or_snapshot.get("volume_move_ratio")
        or candidate_or_snapshot.get("volume_bias")
    )
    event_signal = _direction_value(
        candidate_or_snapshot.get("event_prior_direction_score")
        or candidate_or_snapshot.get("event_prior_score")
        or candidate_or_snapshot.get("event_score")
    )
    narrative_signal = _direction_value(
        candidate_or_snapshot.get("narrative_direction_score")
        or candidate_or_snapshot.get("narrative_score")
        or candidate_or_snapshot.get("truth_score")
    )

    signed_sources = {
        "sentiment": sentiment_signal * GAUSS_SOURCE_WEIGHTS["sentiment"] * persistence,
        "price": price_signal * GAUSS_SOURCE_WEIGHTS["price"] * persistence,
        "volume": volume_signal * GAUSS_SOURCE_WEIGHTS["volume"] * persistence,
        "event_prior": event_signal * GAUSS_SOURCE_WEIGHTS["event_prior"] * persistence,
        "narrative": narrative_signal * GAUSS_SOURCE_WEIGHTS["narrative"] * persistence,
    }
    pressure_sources = {key: round(abs(value), 3) for key, value in signed_sources.items()}
    source_count = sum(
        1
        for key in signed_sources
        if _source_presence(candidate_or_snapshot.get(f"{key}_score"), signed_sources[key])
    )
    raw_pressure = sum(signed_sources.values())
    pressure_score = _clamp(sum(abs(value) for value in signed_sources.values()))
    positive_flow = sum(value for value in signed_sources.values() if value > 0)
    negative_flow = abs(sum(value for value in signed_sources.values() if value < 0))
    boundary_effect = round(positive_flow - negative_flow, 3)
    if raw_pressure > EPSILON:
        pressure_direction = "UP"
    elif raw_pressure < -EPSILON:
        pressure_direction = "DOWN"
    else:
        pressure_direction = "NEUTRAL"

    rationale: list[str] = []
    if source_count == 0 or pressure_score <= EPSILON:
        classification = NO_FIELD
        rationale.append("No sustained field pressure sources were detected.")
    elif pressure_score < FIELD_WEAK_THRESHOLD:
        classification = WEAK_FIELD
        rationale.append("Field pressure exists but remains below the weak threshold.")
    elif pressure_score >= FIELD_STRONG_THRESHOLD and persistence >= FIELD_PERSISTENCE_STRONG_THRESHOLD:
        classification = STRONG_FIELD
        rationale.append("Pressure score and persistence both exceed strong-field thresholds.")
    else:
        classification = FORMING_FIELD
        rationale.append("Field pressure is present but persistence is still forming.")

    if pressure_direction == "NEUTRAL":
        rationale.append("Directional pressure is neutral after netting inflows and outflows.")
    else:
        rationale.append(f"Net field direction resolved to {pressure_direction}.")

    return asdict(
        FieldPressureState(
            asset=asset,
            pressure_score=round(pressure_score, 3),
            pressure_direction=pressure_direction,
            pressure_persistence=round(persistence, 3),
            pressure_sources=pressure_sources,
            source_count=source_count,
            boundary_effect=boundary_effect,
            classification=classification,
            rationale=rationale,
        )
    )


def compute_field_interaction_matrix(candidate_or_snapshot: dict[str, Any]) -> dict[str, Any]:
    asset = str(
        candidate_or_snapshot.get("asset")
        or candidate_or_snapshot.get("asset_symbol")
        or candidate_or_snapshot.get("ticker")
        or candidate_or_snapshot.get("candidate_id")
        or "UNKNOWN"
    ).upper()
    sentiment = _direction_value(
        candidate_or_snapshot.get("sentiment_direction_score")
        or candidate_or_snapshot.get("sentiment_score")
        or candidate_or_snapshot.get("narrative_direction_score")
    )
    price = _direction_value(
        candidate_or_snapshot.get("price_direction_score")
        or candidate_or_snapshot.get("price_signal_score")
        or candidate_or_snapshot.get("price_move_pct")
    )
    event_prior = _clamp(
        candidate_or_snapshot.get("event_prior_score")
        or candidate_or_snapshot.get("event_score")
        or 0.0
    )
    liquidity = _clamp(
        candidate_or_snapshot.get("liquidity_score")
        or candidate_or_snapshot.get("source_quality_score")
        or candidate_or_snapshot.get("liquidity_support_score")
        or 0.0
    )
    volume = _clamp(
        candidate_or_snapshot.get("volume_signal_score")
        or candidate_or_snapshot.get("volume_move_ratio")
        or 0.0
    )
    narrative = _clamp(
        candidate_or_snapshot.get("narrative_score")
        or candidate_or_snapshot.get("truth_score")
        or candidate_or_snapshot.get("cross_source_confirmation_score")
        or 0.0
    )
    momentum = _clamp(
        candidate_or_snapshot.get("momentum_score")
        or candidate_or_snapshot.get("price_confirmation_score")
        or 0.0
    )

    price_sentiment_correlation: float | None
    if _source_presence(sentiment) and _source_presence(price):
        price_sentiment_correlation = round(
            max(-1.0, min(1.0, 1.0 - abs(sentiment - price))),
            3,
        )
    else:
        price_sentiment_correlation = None

    event_liquidity_coupling: float | None
    if _source_presence(event_prior) or _source_presence(liquidity):
        event_liquidity_coupling = round(min(event_prior, liquidity), 3)
    else:
        event_liquidity_coupling = None

    narrative_momentum = round(_clamp((narrative * 0.55) + (momentum * 0.45)), 3)
    divergence_components: list[float] = []
    rationale: list[str] = []
    observed_components = sum(
        1
        for value in (sentiment, price, event_prior, liquidity, volume, narrative, momentum)
        if _source_presence(value)
    )

    if price_sentiment_correlation is not None:
        divergence_components.append(_clamp((1.0 - price_sentiment_correlation) / 2.0))
        if price_sentiment_correlation < -0.10:
            rationale.append("Sentiment and price are moving in opposite directions.")

    if event_liquidity_coupling is not None:
        divergence_components.append(_clamp(1.0 - event_liquidity_coupling))
        if event_prior >= 0.55 and liquidity < 0.35:
            rationale.append("Event prior is rising without sufficient liquidity support.")

    if _source_presence(volume) or _source_presence(narrative):
        volume_gap = _clamp(abs(volume - narrative))
        divergence_components.append(volume_gap)
        if volume >= 0.55 and narrative < 0.30:
            rationale.append("Volume is expanding without narrative confirmation.")
        if _clamp(abs(price)) >= 0.60 and narrative < 0.25:
            rationale.append("Price is moving without supporting field narrative.")

    if observed_components == 0:
        divergence_score = 1.0
        interaction_coherence = 0.0
    else:
        divergence_score = round(
            _clamp(sum(divergence_components) / max(len(divergence_components), 1)),
            3,
        )
        interaction_coherence = round(_clamp(1.0 - divergence_score), 3)
    lag_warning = bool(
        event_prior >= 0.60 and liquidity < 0.35
        or volume >= 0.55 and narrative < 0.30
    )

    if observed_components == 0:
        classification = NO_INTERACTION_DATA
        rationale.append("No interaction data was available across field components.")
    elif divergence_score >= 0.65:
        classification = DIVERGENT
        rationale.append("Observed field components are materially divergent.")
    elif interaction_coherence >= COHERENCE_HIGH_THRESHOLD:
        classification = HIGHLY_COHERENT
        rationale.append("Field components are highly aligned.")
    elif interaction_coherence >= COHERENCE_STRONG_THRESHOLD:
        classification = COHERENT
        rationale.append("Field components are coherent enough for further validation.")
    else:
        classification = WEAKLY_COHERENT
        rationale.append("Field components are partially aligned but not yet robust.")

    return asdict(
        FieldInteractionMatrix(
            asset=asset,
            price_sentiment_correlation=price_sentiment_correlation,
            event_liquidity_coupling=event_liquidity_coupling,
            narrative_momentum=narrative_momentum,
            divergence_score=divergence_score,
            interaction_coherence=interaction_coherence,
            lag_warning=lag_warning,
            classification=classification,
            rationale=rationale,
        )
    )


def compute_execution_vector(
    candidate_or_snapshot: dict[str, Any],
    pressure_state: dict[str, Any],
    interaction_state: dict[str, Any],
) -> dict[str, Any]:
    asset = str(
        candidate_or_snapshot.get("asset")
        or candidate_or_snapshot.get("asset_symbol")
        or candidate_or_snapshot.get("ticker")
        or candidate_or_snapshot.get("candidate_id")
        or "UNKNOWN"
    ).upper()
    pressure_direction = str(pressure_state.get("pressure_direction") or "NEUTRAL").upper()
    pressure_score = _clamp(pressure_state.get("pressure_score", 0.0))
    pressure_persistence = _clamp(pressure_state.get("pressure_persistence", 0.0))
    interaction_coherence = _clamp(interaction_state.get("interaction_coherence", 0.0))
    minimum_validation_passed = bool(candidate_or_snapshot.get("minimum_validation_passed", False))
    execution_survivability_score = _clamp(
        candidate_or_snapshot.get("execution_survivability_score")
        or candidate_or_snapshot.get("blocker_clearance_score")
        or candidate_or_snapshot.get("source_quality_score")
        or 0.0
    )
    timing_alignment = _clamp(
        candidate_or_snapshot.get("timing_alignment_score")
        or candidate_or_snapshot.get("price_confirmation_score")
        or candidate_or_snapshot.get("momentum_score")
        or 0.0
    )
    timing_window = candidate_or_snapshot.get("timing_window")
    if timing_window is None:
        timing_window = candidate_or_snapshot.get("opportunity_half_life")
    timing_fit = timing_alignment
    directional_clarity = 1.0 if pressure_direction in {"UP", "DOWN"} else 0.0
    alignment_score = round(
        _clamp((pressure_persistence * 0.35) + (interaction_coherence * 0.35) + (timing_fit * 0.30)),
        3,
    )
    force_magnitude = round(_clamp(pressure_score * interaction_coherence), 3)
    execution_clarity = round(
        _clamp(directional_clarity * alignment_score * execution_survivability_score),
        3,
    )

    policy_allowed = bool(candidate_or_snapshot.get("policy_permission", True))
    chaos_blocked = bool(candidate_or_snapshot.get("chaos_veto", False))
    rationale: list[str] = []
    invalid_if = ""
    if pressure_direction == "UP":
        direction = "LONG"
    elif pressure_direction == "DOWN":
        direction = "SHORT"
    else:
        direction = "NONE"

    if pressure_state.get("classification") == NO_FIELD:
        classification = NO_VECTOR
        invalid_if = "field_pressure_absent"
        rationale.append("Execution vector is unavailable because no field pressure was detected.")
    elif interaction_state.get("classification") in {NO_INTERACTION_DATA, DIVERGENT}:
        classification = MISALIGNED
        invalid_if = "interaction_not_coherent"
        rationale.append("Execution vector is blocked by divergent or missing interaction data.")
    elif not minimum_validation_passed or alignment_score < EXECUTION_ALIGNMENT_THRESHOLD:
        classification = WATCH
        invalid_if = "validation_or_alignment_incomplete"
        rationale.append("Execution vector is still in watch mode because alignment is incomplete.")
    elif not policy_allowed or chaos_blocked:
        classification = WATCH
        invalid_if = "policy_or_chaos_guard"
        rationale.append("Execution vector is suppressed by policy or chaos restrictions.")
    elif execution_clarity >= EXECUTION_CLARITY_THRESHOLD and force_magnitude >= FIELD_WEAK_THRESHOLD:
        classification = ACTIONABLE_UNDER_POLICY
        invalid_if = "policy_permission_required"
        rationale.append("Execution vector is clear enough for policy-gated review.")
    else:
        classification = WATCH
        invalid_if = "clarity_below_threshold"
        rationale.append("Execution vector remains below the clarity threshold.")

    return asdict(
        ExecutionVector(
            asset=asset,
            direction=direction,
            force_magnitude=force_magnitude,
            alignment_score=alignment_score,
            timing_window=_coerce_float(timing_window) if timing_window is not None else None,
            execution_clarity=execution_clarity,
            invalid_if=invalid_if,
            classification=classification,
            rationale=rationale,
        )
    )


def compute_valid_signal_rate(
    pressure_state: dict[str, Any],
    interaction_state: dict[str, Any],
    execution_vector: dict[str, Any],
) -> float:
    f_strength = _clamp(pressure_state.get("pressure_score", 0.0))
    i_coherence = _clamp(interaction_state.get("interaction_coherence", 0.0))
    e_clarity = _clamp(execution_vector.get("execution_clarity", 0.0))
    return round(_clamp(f_strength * i_coherence * e_clarity), 3)


def compute_trade_readiness(
    pressure_state: dict[str, Any],
    interaction_state: dict[str, Any],
    execution_vector: dict[str, Any],
    policy_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy_state if isinstance(policy_state, dict) else {}
    policy_permission = bool(policy.get("allow_new_risk", False))
    policy_state_label = str(policy.get("policy_state") or "RESTRICTED").upper()
    chaos_veto = bool(policy.get("chaos_veto", False))
    field_strength = _clamp(pressure_state.get("pressure_score", 0.0))
    coherence = _clamp(interaction_state.get("interaction_coherence", 0.0))
    execution_clarity = _clamp(execution_vector.get("execution_clarity", 0.0))
    policy_permission_score = 1.0 if policy_permission and not chaos_veto else 0.0
    trade_readiness = round(
        _clamp(field_strength * coherence * execution_clarity * policy_permission_score),
        3,
    )
    if policy_state_label != "READY" or not policy_permission:
        final_permission_state = "BLOCKED_POLICY"
        action_promotion_state = "BLOCKED_POLICY"
    elif chaos_veto:
        final_permission_state = "BLOCKED_CHAOS"
        action_promotion_state = "BLOCKED_CHAOS"
    elif pressure_state.get("classification") not in {FORMING_FIELD, STRONG_FIELD}:
        final_permission_state = "BLOCKED_WEAK_FIELD"
        action_promotion_state = "BLOCKED_WEAK_FIELD"
    elif interaction_state.get("classification") in {NO_INTERACTION_DATA, DIVERGENT}:
        final_permission_state = "BLOCKED_DIVERGENT_FIELD"
        action_promotion_state = "BLOCKED_DIVERGENT_FIELD"
    elif execution_vector.get("classification") != ACTIONABLE_UNDER_POLICY:
        final_permission_state = "BLOCKED_NO_EXECUTION_VECTOR"
        action_promotion_state = "BLOCKED_NO_EXECUTION_VECTOR"
    elif trade_readiness >= TRADE_READINESS_THRESHOLD:
        final_permission_state = "POLICY_GATED_REVIEW_ONLY"
        action_promotion_state = "REVIEW_WITH_EXISTING_GATES"
    else:
        final_permission_state = "BLOCKED_LOW_READINESS"
        action_promotion_state = "BLOCKED_LOW_READINESS"

    return {
        "valid_signal_rate": compute_valid_signal_rate(
            pressure_state,
            interaction_state,
            execution_vector,
        ),
        "trade_readiness": trade_readiness,
        "final_permission_state": final_permission_state,
        "action_promotion_state": action_promotion_state,
        "policy_permission_required": True,
        "policy_permission": policy_permission,
        "doctrine": [
            "Detection is not admission",
            "Pressure before validation",
            "Interaction before conviction",
            "Direction before execution",
            "Policy veto outranks field logic",
        ],
    }


def attach_field_dynamics(
    candidate_or_snapshot: dict[str, Any],
    policy_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pressure_state = compute_field_pressure_state(candidate_or_snapshot)
    interaction_state = compute_field_interaction_matrix(candidate_or_snapshot)
    execution_vector = compute_execution_vector(
        {
            **candidate_or_snapshot,
            "policy_permission": bool((policy_state or {}).get("allow_new_risk", False)),
            "chaos_veto": bool((policy_state or {}).get("chaos_veto", False)),
        },
        pressure_state,
        interaction_state,
    )
    readiness = compute_trade_readiness(
        pressure_state,
        interaction_state,
        execution_vector,
        policy_state=policy_state,
    )
    return {
        **candidate_or_snapshot,
        "gauss_maxwell_lorentz_state": {
            "field_pressure_state": pressure_state,
            "field_interaction_matrix": interaction_state,
            "execution_vector": execution_vector,
            "valid_signal_rate": readiness["valid_signal_rate"],
            "trade_readiness": readiness["trade_readiness"],
            "final_permission_state": readiness["final_permission_state"],
            "action_promotion_state": readiness["action_promotion_state"],
            "policy_permission_required": True,
            "doctrine": readiness["doctrine"],
        },
    }


def build_field_dynamics_report(
    candidates: list[dict[str, Any]] | None,
    *,
    policy_state: dict[str, Any] | None = None,
    run_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    rows = candidates if isinstance(candidates, list) else []
    attached = [attach_field_dynamics(row, policy_state=policy_state) for row in rows if isinstance(row, dict)]
    payloads = [row["gauss_maxwell_lorentz_state"] for row in attached]

    actionable_count = sum(
        1
        for state in payloads
        if state["execution_vector"]["classification"] == ACTIONABLE_UNDER_POLICY
    )
    strong_field_count = sum(
        1
        for state in payloads
        if state["field_pressure_state"]["classification"] == STRONG_FIELD
    )
    divergent_count = sum(
        1
        for state in payloads
        if state["field_interaction_matrix"]["classification"] == DIVERGENT
    )
    top_state = max(
        payloads,
        key=lambda item: (
            float(item.get("trade_readiness", 0.0) or 0.0),
            float(item.get("valid_signal_rate", 0.0) or 0.0),
            str(item["field_pressure_state"].get("asset") or ""),
        ),
        default=None,
    )

    if not payloads:
        engine_state = "EMPTY"
    elif any(
        state["final_permission_state"] == "POLICY_GATED_REVIEW_ONLY" for state in payloads
    ):
        engine_state = "ACTIONABLE_UNDER_POLICY"
    elif strong_field_count > 0:
        engine_state = "PRESSURE_FORMING"
    elif divergent_count > 0:
        engine_state = "DIVERGENT"
    else:
        engine_state = "SCANNING"

    top_asset = None
    top_valid_signal_rate = None
    top_trade_readiness = None
    dashboard: dict[str, Any] = {}
    if top_state is not None:
        top_asset = top_state["field_pressure_state"]["asset"]
        top_valid_signal_rate = top_state["valid_signal_rate"]
        top_trade_readiness = top_state["trade_readiness"]
        dashboard = {
            "gauss": {
                "pressure_score": top_state["field_pressure_state"]["pressure_score"],
                "direction": top_state["field_pressure_state"]["pressure_direction"],
                "persistence": top_state["field_pressure_state"]["pressure_persistence"],
                "classification": top_state["field_pressure_state"]["classification"],
            },
            "maxwell": {
                "coherence": top_state["field_interaction_matrix"]["interaction_coherence"],
                "divergence_score": top_state["field_interaction_matrix"]["divergence_score"],
                "classification": top_state["field_interaction_matrix"]["classification"],
            },
            "lorentz_fleming": {
                "direction": top_state["execution_vector"]["direction"],
                "force_magnitude": top_state["execution_vector"]["force_magnitude"],
                "execution_clarity": top_state["execution_vector"]["execution_clarity"],
                "classification": top_state["execution_vector"]["classification"],
            },
            "final": {
                "valid_signal_rate": top_state["valid_signal_rate"],
                "trade_readiness": top_state["trade_readiness"],
                "final_permission_state": top_state["final_permission_state"],
            },
        }

    return {
        "field_dynamics_engine_available": True,
        "field_dynamics_engine_state": engine_state,
        "valid_signal_rate": top_valid_signal_rate if top_valid_signal_rate is not None else 0.0,
        "trade_readiness": top_trade_readiness if top_trade_readiness is not None else 0.0,
        "field_dynamics_candidate_count": len(payloads),
        "strong_field_count": strong_field_count,
        "divergent_field_count": divergent_count,
        "actionable_under_policy_count": actionable_count,
        "top_field_asset": top_asset,
        "gauss_maxwell_lorentz_dashboard": dashboard,
        "policy_permission_required": True,
        "doctrine": [
            "Detection is not admission",
            "Pressure before validation",
            "Interaction before conviction",
            "Direction before execution",
            "Policy veto outranks field logic",
        ],
        "candidates": attached,
        "run_id": run_id,
        "generated_at": generated_at,
    }
