from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


EPSILON = 1e-6
ROUTE_DEFAULTS = {
    "news": {"latency": "medium", "reliability_prior": 0.65},
    "social": {"latency": "fast", "reliability_prior": 0.35},
    "price": {"latency": "fast", "reliability_prior": 0.70},
    "prediction_market": {"latency": "medium", "reliability_prior": 0.60},
    "filing": {"latency": "slow_medium", "reliability_prior": 0.80},
    "rumor": {"latency": "fast", "reliability_prior": 0.20},
    "manual_observation": {"latency": "variable", "reliability_prior": 0.50},
    "unknown": {"latency": "variable", "reliability_prior": 0.30},
}
VIRALITY_THRESHOLD = 0.70
TRUTH_THRESHOLD = 0.55
HIGH_INTENSITY_THRESHOLD = 0.75
LOW_STABILITY_THRESHOLD = 0.50
ROUTE_KEYWORDS = {
    "filing": ("8-k", "10-q", "10-k", "filing", "sec"),
    "prediction_market": ("prediction market", "polymarket", "odds"),
    "news": ("breaking", "news", "headline", "reuters", "bloomberg"),
    "social": ("tweet", "twitter", "x.com", "reddit", "discord", "social"),
    "rumor": ("rumor", "unconfirmed", "whisper"),
    "manual_observation": ("manual", "observed", "operator note"),
    "price": ("price", "tape", "market", "quote"),
}
POSITIVE_WORDS = {"bullish", "beat", "surge", "upgrade", "strong", "growth", "squeeze"}
NEGATIVE_WORDS = {"bearish", "miss", "drop", "downgrade", "weak", "fraud", "collapse"}
URGENCY_WORDS = {"now", "urgent", "immediately", "exploding", "must", "breaking", "alert"}


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


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _word_score(text: str, words: set[str]) -> float:
    if not text:
        return 0.0
    lowered = text.lower()
    count = sum(1 for word in words if word in lowered)
    return _clamp(count / max(len(words), 1))


def _detect_route_label(signal: dict[str, Any]) -> str:
    explicit = _text(signal.get("signal_route")).lower()
    if explicit in ROUTE_DEFAULTS:
        return explicit
    haystack = " ".join(
        [
            _text(signal.get("source_name")),
            _text(signal.get("source_type")),
            _text(signal.get("provider")),
            _text(signal.get("headline")),
            _text(signal.get("text")),
            _text(signal.get("notes")),
        ]
    ).lower()
    for route, markers in ROUTE_KEYWORDS.items():
        if any(marker in haystack for marker in markers):
            return route
    origin = _text(signal.get("signal_origin")).lower()
    if origin == "external":
        return "price"
    return "unknown"


def classify_signal_route(signal: dict[str, Any] | None) -> dict[str, Any]:
    payload = signal if isinstance(signal, dict) else {}
    route = _detect_route_label(payload)
    default = ROUTE_DEFAULTS[route]
    source_quality = _clamp(payload.get("source_quality_score", payload.get("source_quality", 0.5)))
    route_confidence = round(
        _clamp((0.55 * default["reliability_prior"]) + (0.45 * source_quality)),
        3,
    )
    return {
        "signal_route": route,
        "route_latency_profile": default["latency"],
        "route_reliability_prior": round(default["reliability_prior"], 3),
        "route_confidence": route_confidence,
        "route_notes": [
            f"signal_effect = raw_signal x channel_modifier({route})",
            f"route reliability prior defaults to {default['reliability_prior']:.2f}",
        ],
    }


def compute_phase_arrival(signal: dict[str, Any] | None) -> dict[str, Any]:
    payload = signal if isinstance(signal, dict) else {}
    detected_at = _parse_timestamp(payload.get("signal_detected_at") or payload.get("event_emergence_ts"))
    narrative_seen_at = _parse_timestamp(payload.get("narrative_seen_at"))
    market_reaction_at = _parse_timestamp(payload.get("market_reaction_at"))
    price_confirmation_at = _parse_timestamp(
        payload.get("price_confirmation_at") or payload.get("validation_completion_ts")
    )
    priced_status_at = _parse_timestamp(payload.get("priced_status_at"))

    if not detected_at:
        return {
            "timing_delta": None,
            "phase_state": "unknown",
            "timing_alignment_score": 0.5,
            "timing_notes": ["No detection timestamp was available."],
        }

    delta_hours = None
    if market_reaction_at:
        delta_hours = round((market_reaction_at - detected_at).total_seconds() / 3600.0, 2)

    as_of = _parse_timestamp(payload.get("as_of")) or datetime.now(timezone.utc)
    age_hours = round((as_of - detected_at).total_seconds() / 3600.0, 2)
    if priced_status_at:
        phase_state = "already_priced"
        alignment = 0.25
    elif price_confirmation_at:
        phase_state = "price_confirmation"
        alignment = 0.7
    elif narrative_seen_at and market_reaction_at:
        phase_state = "narrative_amplification"
        alignment = 0.55
    elif market_reaction_at:
        phase_state = "early_reaction"
        alignment = 0.75
    elif age_hours > 72.0:
        phase_state = "stale_or_late"
        alignment = 0.2
    else:
        phase_state = "pre_reaction"
        alignment = 0.8

    return {
        "timing_delta": delta_hours,
        "phase_state": phase_state,
        "timing_alignment_score": round(_clamp(alignment), 3),
        "timing_notes": [
            "PhaseExperience = sum(Input_i x ArrivalTime_i)",
            f"Detected age_hours={age_hours}",
        ],
    }


def classify_signal_stage(
    signal: dict[str, Any] | None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = signal if isinstance(signal, dict) else {}
    context = market_context if isinstance(market_context, dict) else {}
    reposts = max(int(payload.get("repost_count", 0) or 0), 0)
    confirmations = max(
        int(payload.get("confirmation_count", payload.get("cross_source_confirmation_count", 0)) or 0),
        0,
    )
    narrative_mentions = max(int(payload.get("narrative_mentions", 0) or 0), 0)
    price_move = abs(float(context.get("price_move_pct", payload.get("price_move_pct", 0.0)) or 0.0))
    volume_move = float(context.get("volume_move_ratio", payload.get("volume_move_ratio", 0.0)) or 0.0)
    saturation = _clamp(payload.get("narrative_saturation", 0.0))
    priced_risk = round(
        _clamp((0.45 * min(price_move, 1.0)) + (0.30 * _clamp(volume_move)) + (0.25 * saturation)),
        3,
    )

    if priced_risk >= 0.7:
        stage = "PRICED"
        confidence = 0.8
    elif narrative_mentions >= 2 or confirmations >= 2:
        stage = "NARRATIVE"
        confidence = 0.75
    elif reposts >= 2 or confirmations >= 1:
        stage = "AMPLIFIED"
        confidence = 0.65
    elif _truthy(payload.get("decayed")):
        stage = "DECAYED"
        confidence = 0.75
    elif payload:
        stage = "RAW"
        confidence = 0.6
    else:
        stage = "UNKNOWN"
        confidence = 0.3
    return {
        "signal_stage": stage,
        "stage_confidence": round(_clamp(confidence), 3),
        "priced_risk": priced_risk,
        "transformation_quality_score": round(_clamp(1.0 - (priced_risk * 0.6)), 3),
        "transformation_notes": [
            "Signal_t+1 = Transform(Signal_t)",
            f"priced_status = price_move + volume_move + narrative_saturation -> {priced_risk:.3f}",
        ],
    }


def score_psychological_chemistry(
    signal: dict[str, Any] | None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = signal if isinstance(signal, dict) else {}
    context = market_context if isinstance(market_context, dict) else {}
    text = " ".join(
        [
            _text(payload.get("headline")),
            _text(payload.get("text")),
            _text(payload.get("notes")),
        ]
    ).strip()
    uppercase_ratio = 0.0
    if text:
        uppercase_ratio = sum(1 for char in text if char.isupper()) / max(len(text), 1)
    intensity_score = round(
        _clamp(
            (0.25 * _word_score(text, URGENCY_WORDS))
            + (0.20 * uppercase_ratio * 4.0)
            + (0.20 * min(text.count("!"), 3) / 3.0)
            + (0.20 * _clamp(payload.get("engagement_velocity", payload.get("engagement_proxy", 0.0))))
            + (0.15 * _clamp(payload.get("repetition_score", payload.get("repost_count", 0) / 4.0)))
        ),
        3,
    )
    positive = _word_score(text, POSITIVE_WORDS)
    negative = _word_score(text, NEGATIVE_WORDS)
    narrative_direction_score = round(max(-1.0, min(1.0, positive - negative)), 3)
    confirmation_quality = _clamp(payload.get("confirmation_count", payload.get("cross_source_confirmation_score", 0.0)))
    source_quality = _clamp(payload.get("source_quality_score", payload.get("source_quality", 0.5)))
    price_confirmation = _clamp(
        context.get("price_confirmation_score", payload.get("price_confirmation_score", 0.0))
    )
    evidence_stability_score = round(
        _clamp((0.35 * source_quality) + (0.35 * confirmation_quality) + (0.30 * price_confirmation)),
        3,
    )
    virality_score = round(
        _clamp(
            (0.45 * _clamp(payload.get("engagement_velocity", payload.get("engagement_proxy", 0.0))))
            + (0.35 * _clamp(payload.get("repost_count", 0) / 5.0))
            + (0.20 * intensity_score)
        ),
        3,
    )
    truth_score = round(
        _clamp(
            (0.40 * evidence_stability_score)
            + (0.35 * confirmation_quality)
            + (0.25 * source_quality)
        ),
        3,
    )
    validity_gap = round(virality_score - truth_score, 3)
    overreaction_risk = round(
        _clamp(intensity_score / max(evidence_stability_score, EPSILON)),
        3,
    )
    return {
        "intensity_score": intensity_score,
        "narrative_direction_score": narrative_direction_score,
        "evidence_stability_score": evidence_stability_score,
        "virality_score": virality_score,
        "truth_score": truth_score,
        "validity_gap": validity_gap,
        "overreaction_risk": overreaction_risk,
        "psychology_notes": [
            "Validity != Virality",
            "PostImpact = Intensity x NarrativeDirection x EvidenceStability x MarketState",
        ],
    }


def split_virality_vs_validity(
    *,
    virality_score: Any,
    truth_score: Any,
    evidence_score: Any | None = None,
    virality_threshold: float = VIRALITY_THRESHOLD,
    truth_threshold: float = TRUTH_THRESHOLD,
) -> dict[str, Any]:
    virality = _clamp(virality_score)
    truth = _clamp(truth_score if evidence_score is None else evidence_score)
    validity_gap = round(virality - truth, 3)
    if virality >= virality_threshold and truth < truth_threshold:
        state = "high_attention_low_truth"
        require_validation = True
    elif virality >= virality_threshold and truth >= truth_threshold:
        state = "high_attention_high_truth"
        require_validation = False
    elif virality < virality_threshold and truth >= truth_threshold:
        state = "low_attention_high_truth"
        require_validation = False
    elif virality < virality_threshold and truth < truth_threshold:
        state = "low_attention_low_truth"
        require_validation = False
    else:
        state = "unknown"
        require_validation = True
    return {
        "attention_truth_state": state,
        "require_validation": require_validation,
        "validity_gap": validity_gap,
    }


def compute_signal_interaction(
    signals: list[dict[str, Any]] | None,
    *,
    asset_symbol: str | None = None,
) -> dict[str, Any]:
    rows = [row for row in (signals or []) if isinstance(row, dict)]
    if asset_symbol:
        rows = [row for row in rows if _text(row.get("asset_symbol") or row.get("ticker")).upper() == asset_symbol.upper()]
    if len(rows) <= 1:
        return {
            "reinforcement_score": 0.0,
            "contradiction_score": 0.0,
            "interaction_score": 0.0,
            "interaction_state": "isolated" if rows else "unknown",
        }
    directions = [_clamp((float(row.get("narrative_direction_score", 0.0) or 0.0) + 1.0) / 2.0) for row in rows]
    raw_signed = [float(row.get("narrative_direction_score", 0.0) or 0.0) for row in rows]
    truth_scores = [_clamp(row.get("truth_score", 0.0)) for row in rows]
    avg_direction = sum(directions) / len(directions)
    sign_spread = max(raw_signed) - min(raw_signed) if raw_signed else 0.0
    reinforcement_score = round(
        _clamp((sum(truth_scores) / len(truth_scores)) * (1.0 - min(sign_spread, 1.0))),
        3,
    )
    contradiction_score = round(_clamp(min(sign_spread, 1.0)), 3)
    interaction_score = round(reinforcement_score - contradiction_score, 3)
    if contradiction_score >= 0.55:
        state = "contradictory"
    elif reinforcement_score >= 0.60:
        state = "reinforcing"
    elif contradiction_score > 0.0 and reinforcement_score > 0.0:
        state = "mixed"
    else:
        state = "isolated"
    return {
        "reinforcement_score": reinforcement_score,
        "contradiction_score": contradiction_score,
        "interaction_score": interaction_score,
        "interaction_state": state,
        "interaction_notes": [f"CombinedEffect = A + B + A*B; avg_direction={avg_direction:.3f}"],
    }


def compute_regime_factor(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    policy_state = _text(payload.get("policy_state"), "UNKNOWN").upper()
    friction_band = _text(payload.get("friction_band"), "UNKNOWN").upper()
    chaos_flag = _truthy(payload.get("chaos_flag")) or "REALM_BIS" in {
        _text(item).upper() for item in payload.get("existing_blockers", [])
    }
    allow_new_risk = _truthy(payload.get("allow_new_risk"))
    can_deploy_capital = _truthy(payload.get("can_deploy_capital"))
    no_new_risk_due_to_regime = chaos_flag or not allow_new_risk or not can_deploy_capital or policy_state in {
        "RESTRICTED",
        "BLOCKED",
        "DO_NOT_DEPLOY",
        "NOT_READY",
    }
    if no_new_risk_due_to_regime:
        regime_factor = 0.2 if not chaos_flag else 0.1
        regime_state = "CHAOS_LOCKED" if chaos_flag else "POLICY_RESTRICTED"
    elif friction_band == "HIGH_FRICTION":
        regime_factor = 0.45
        regime_state = "FRICTION_HEAVY"
    elif friction_band == "MEDIUM_FRICTION":
        regime_factor = 0.65
        regime_state = "CAUTIOUS"
    else:
        regime_factor = 0.85
        regime_state = "NORMALIZING"
    return {
        "regime_factor": round(_clamp(regime_factor), 3),
        "regime_state": regime_state,
        "regime_notes": [
            f"Outcome = Signal x RegimeState({regime_state})",
            f"policy_state={policy_state}, friction_band={friction_band}, chaos_flag={str(chaos_flag).lower()}",
        ],
        "no_new_risk_due_to_regime": no_new_risk_due_to_regime,
    }


def compute_compatibility(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    profile_similarity = _clamp(payload.get("profile_similarity", 0.5))
    historical_success_rate = _clamp(payload.get("historical_success_rate", 0.5))
    repeatability_score = _clamp(payload.get("repeatability_score", 0.5))
    external_validation = _clamp(payload.get("external_validation_score", payload.get("external_validation", 0.5)))
    compatibility_score = round(
        _clamp(profile_similarity * historical_success_rate * repeatability_score),
        3,
    )
    overfit_risk = round(_clamp(profile_similarity - external_validation), 3)
    notes = []
    if not payload:
        notes.append("Compatibility returned neutral defaults due to insufficient history.")
    notes.append("TrustedSignal = Repeatability x OutcomeConsistency")
    return {
        "profile_similarity": round(profile_similarity, 3),
        "historical_success_rate": round(historical_success_rate, 3),
        "repeatability_score": round(repeatability_score, 3),
        "compatibility_score": compatibility_score,
        "overfit_risk": overfit_risk,
        "compatibility_notes": notes,
    }


def apply_high_intensity_guard(
    *,
    intensity_score: Any,
    stability_score: Any,
    truth_score: Any = 0.0,
    no_new_risk_due_to_regime: bool = False,
    intensity_threshold: float = HIGH_INTENSITY_THRESHOLD,
    stability_threshold: float = LOW_STABILITY_THRESHOLD,
) -> dict[str, Any]:
    intensity = _clamp(intensity_score)
    stability = _clamp(stability_score)
    truth = _clamp(truth_score)
    distortion_risk = round(_clamp(intensity / max(stability, EPSILON)), 3)
    triggered = intensity > intensity_threshold and stability < stability_threshold
    if no_new_risk_due_to_regime and intensity >= intensity_threshold:
        action = "block"
        reason = "regime_blocks_high_intensity_signal"
    elif triggered and truth < 0.45:
        action = "block"
        reason = "high_intensity_low_stability_low_truth"
    elif triggered:
        action = "delay"
        reason = "high_intensity_low_stability"
    elif intensity > intensity_threshold:
        action = "reduce_confidence"
        reason = "high_intensity_requires_stability_discount"
    else:
        action = "allow"
        reason = "stability_sufficient"
    guard_multiplier = 0.0 if action == "block" else 0.4 if action in {"delay", "reduce_confidence"} else 1.0
    return {
        "high_intensity_guard_triggered": triggered or action == "block",
        "guard_action": action,
        "guard_reason": reason,
        "guard_multiplier": guard_multiplier,
        "overreaction_risk": distortion_risk,
    }


def classify_bull_archetype(
    *,
    signal_stage: str,
    regime_state: str,
    no_new_risk_due_to_regime: bool,
    truth_score: float,
    evidence_stability_score: float,
    repeatability_score: float,
    durability_score: float,
    execution_survivability_score: float,
    minimum_validation_passed: bool,
    shock_override_active: bool = False,
    momentum_score: float = 0.0,
) -> str:
    if shock_override_active:
        return "ISLERO"
    if regime_state == "CHAOS_LOCKED" or no_new_risk_due_to_regime and signal_stage in {"RAW", "AMPLIFIED"}:
        return "DIABLO"
    if signal_stage == "RAW":
        return "MIURA"
    if momentum_score >= 0.75 and minimum_validation_passed and evidence_stability_score >= 0.5:
        return "HURACAN"
    if execution_survivability_score >= 0.75 and truth_score >= 0.7 and not no_new_risk_due_to_regime:
        return "GALLARDO"
    if minimum_validation_passed and durability_score >= 0.65 and evidence_stability_score >= 0.6:
        return "AVENTADOR"
    if truth_score >= 0.55 and repeatability_score >= 0.55:
        return "MURCIELAGO"
    return "MIURA"


@dataclass(frozen=True)
class SignalMetabolismCandidate:
    candidate_id: str
    asset_symbol: str
    signal_metabolism: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_signal_metabolism(
    signal: dict[str, Any] | None,
    *,
    related_signals: list[dict[str, Any]] | None = None,
    market_context: dict[str, Any] | None = None,
    regime_context: dict[str, Any] | None = None,
    compatibility_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = signal if isinstance(signal, dict) else {}
    route = classify_signal_route(payload)
    timing = compute_phase_arrival(payload)
    stage = classify_signal_stage(payload, market_context=market_context)
    chemistry = score_psychological_chemistry(payload, market_context=market_context)
    validity = split_virality_vs_validity(
        virality_score=chemistry["virality_score"],
        truth_score=chemistry["truth_score"],
    )
    interaction = compute_signal_interaction(
        related_signals or [payload | chemistry],
        asset_symbol=_text(payload.get("asset_symbol") or payload.get("ticker")),
    )
    regime = compute_regime_factor(regime_context)
    compatibility = compute_compatibility(
        {
            **(compatibility_context or {}),
            "repeatability_score": payload.get("repeatability_score", 0.5),
        }
    )
    stability_score = round(
        _clamp(
            (0.45 * chemistry["evidence_stability_score"])
            + (0.30 * compatibility["repeatability_score"])
            + (0.25 * route["route_reliability_prior"])
        ),
        3,
    )
    guard = apply_high_intensity_guard(
        intensity_score=chemistry["intensity_score"],
        stability_score=stability_score,
        truth_score=chemistry["truth_score"],
        no_new_risk_due_to_regime=regime["no_new_risk_due_to_regime"],
    )
    route_factor = route["route_reliability_prior"]
    timing_factor = timing["timing_alignment_score"]
    transformation_factor = stage["transformation_quality_score"]
    interaction_factor = _clamp((interaction["interaction_score"] + 1.0) / 2.0)
    compatibility_factor = compatibility["compatibility_score"]
    guard_multiplier = guard["guard_multiplier"]
    dynamic_signal_score = round(
        _clamp(
            route_factor
            * timing_factor
            * transformation_factor
            * interaction_factor
            * chemistry["evidence_stability_score"]
            * regime["regime_factor"]
            * compatibility_factor
            * guard_multiplier
        ),
        3,
    )
    actionability_score = round(
        _clamp(dynamic_signal_score * (0.0 if validity["require_validation"] else 1.0 if not regime["no_new_risk_due_to_regime"] else 0.2)),
        3,
    )
    durability_score = round(
        _clamp(
            (0.50 * compatibility["repeatability_score"])
            + (0.30 * chemistry["evidence_stability_score"])
            + (0.20 * route["route_reliability_prior"])
        ),
        3,
    )
    execution_survivability_score = round(
        _clamp(
            (0.40 * regime["regime_factor"])
            + (0.35 * chemistry["truth_score"])
            + (0.25 * stability_score)
        ),
        3,
    )
    bull_archetype = classify_bull_archetype(
        signal_stage=stage["signal_stage"],
        regime_state=regime["regime_state"],
        no_new_risk_due_to_regime=regime["no_new_risk_due_to_regime"],
        truth_score=chemistry["truth_score"],
        evidence_stability_score=chemistry["evidence_stability_score"],
        repeatability_score=compatibility["repeatability_score"],
        durability_score=durability_score,
        execution_survivability_score=execution_survivability_score,
        minimum_validation_passed=_truthy(payload.get("minimum_validation_passed", chemistry["truth_score"] >= 0.55)),
        shock_override_active=_truthy(payload.get("shock_override_active")),
        momentum_score=_clamp(payload.get("momentum_score", 0.0)),
    )
    notes = []
    notes.extend(route["route_notes"])
    notes.extend(timing["timing_notes"])
    notes.extend(stage["transformation_notes"])
    notes.extend(chemistry["psychology_notes"])
    notes.extend(interaction.get("interaction_notes", []))
    notes.extend(regime["regime_notes"])
    notes.extend(compatibility["compatibility_notes"])
    notes.append(f"guard_action={guard['guard_action']}")
    return {
        "signal_route": route["signal_route"],
        "route_latency_profile": route["route_latency_profile"],
        "route_reliability_prior": route["route_reliability_prior"],
        "route_confidence": route["route_confidence"],
        "phase_state": timing["phase_state"],
        "timing_delta": timing["timing_delta"],
        "signal_stage": stage["signal_stage"],
        "priced_risk": stage["priced_risk"],
        "intensity_score": chemistry["intensity_score"],
        "narrative_direction_score": chemistry["narrative_direction_score"],
        "evidence_stability_score": chemistry["evidence_stability_score"],
        "virality_score": chemistry["virality_score"],
        "truth_score": chemistry["truth_score"],
        "validity_gap": chemistry["validity_gap"],
        "attention_truth_state": validity["attention_truth_state"],
        "interaction_score": interaction["interaction_score"],
        "interaction_state": interaction["interaction_state"],
        "regime_factor": regime["regime_factor"],
        "regime_state": regime["regime_state"],
        "compatibility_score": compatibility["compatibility_score"],
        "profile_similarity": compatibility["profile_similarity"],
        "historical_success_rate": compatibility["historical_success_rate"],
        "repeatability_score": compatibility["repeatability_score"],
        "overfit_risk": compatibility["overfit_risk"],
        "overreaction_risk": guard["overreaction_risk"],
        "high_intensity_guard_triggered": guard["high_intensity_guard_triggered"],
        "guard_action": guard["guard_action"],
        "guard_reason": guard["guard_reason"],
        "bull_archetype": bull_archetype,
        "dynamic_signal_score": dynamic_signal_score,
        "attention_score": chemistry["virality_score"],
        "stability_score": stability_score,
        "actionability_score": actionability_score,
        "durability_score": durability_score,
        "execution_survivability_score": execution_survivability_score,
        "metabolism_notes": notes,
    }


def build_signal_metabolism_report(
    signals: list[dict[str, Any]] | None,
    *,
    regime_context: dict[str, Any] | None = None,
    compatibility_defaults: dict[str, Any] | None = None,
    run_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    rows = [row for row in (signals or []) if isinstance(row, dict)]
    outputs: list[dict[str, Any]] = []
    for row in rows:
        asset_symbol = _text(row.get("asset_symbol") or row.get("ticker"), "UNKNOWN")
        related = [candidate for candidate in rows if _text(candidate.get("asset_symbol") or candidate.get("ticker")).upper() == asset_symbol.upper()]
        metabolism = evaluate_signal_metabolism(
            row,
            related_signals=related,
            market_context=row,
            regime_context=regime_context,
            compatibility_context=compatibility_defaults,
        )
        outputs.append(
            SignalMetabolismCandidate(
                candidate_id=_text(row.get("candidate_id") or row.get("signal_id"), asset_symbol),
                asset_symbol=asset_symbol,
                signal_metabolism=metabolism,
            ).to_dict()
        )
    outputs.sort(
        key=lambda item: (
            -float(item["signal_metabolism"].get("dynamic_signal_score", 0.0) or 0.0),
            item["asset_symbol"],
        )
    )
    high_attention_low_truth_count = sum(
        1
        for item in outputs
        if item["signal_metabolism"].get("attention_truth_state") == "high_attention_low_truth"
    )
    guard_triggered_count = sum(
        1
        for item in outputs
        if bool(item["signal_metabolism"].get("high_intensity_guard_triggered", False))
    )
    bull_counts: dict[str, int] = {}
    for item in outputs:
        bull = _text(item["signal_metabolism"].get("bull_archetype"), "UNKNOWN")
        bull_counts[bull] = bull_counts.get(bull, 0) + 1
    if not outputs:
        state = "EMPTY"
        top_candidate = None
        top_score = None
    elif guard_triggered_count > 0:
        state = "GUARDED"
        top_candidate = outputs[0]["asset_symbol"]
        top_score = outputs[0]["signal_metabolism"]["dynamic_signal_score"]
    else:
        state = "SCANNING"
        top_candidate = outputs[0]["asset_symbol"]
        top_score = outputs[0]["signal_metabolism"]["dynamic_signal_score"]
    return {
        "run_id": run_id,
        "generated_at": generated_at or _utc_now(),
        "signal_metabolism_engine_available": True,
        "signal_metabolism_engine_state": state,
        "signal_metabolism_candidate_count": len(outputs),
        "signal_metabolism_guarded_count": guard_triggered_count,
        "signal_metabolism_high_attention_low_truth_count": high_attention_low_truth_count,
        "signal_metabolism_top_candidate": top_candidate,
        "signal_metabolism_top_score": top_score,
        "bull_archetype_distribution": bull_counts,
        "candidates": outputs,
    }
