"""Complex-systems signal doctrine — pure, deterministic, advisory-only.

This module is the engineering translation of the "complex systems
reflection" described in ``docs/COMPLEX_SYSTEMS_SIGNAL_DOCTRINE.md``. It
collapses sixteen complex-systems concepts (signal half-life, source
independence, narrative cascade, winner's-curse / crowding, phase
transition, ant-mill confirmation loop, queueing attention gate,
Rawlsian survival sizing, broken-windows / Moltbook repair, sector
flocking, keystone node, firebreak / support failure, AI vote
aggregation, narrative diffusion, chaos regime, final trade-quality
decomposition) into one deterministic diagnostic payload.

The doctrine reduces to a single discrete update step::

    X_{t+1} = F(X_t, A_t, E_t, G, theta)

and a single human-facing operating formula::

                Signal Strength * Source Independence * Freshness
                * Narrative Durability * Risk/Reward * Learning Value
    Quality = ---------------------------------------------------------
                Noise + Crowding + Chaos + Contradiction
                + Invalidation Ambiguity + Operator Load

Final doctrine: **Survive first. Learn second. Scale later.**

Hard contract — every public output is safety-stamped::

    output["safety"]["advisory_status"]       == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]        == "LOCKED"
    output["safety"]["broker_api_called"]     is False
    output["safety"]["ai_execution_count"]    == 0
    output["safety"]["execution_permission"]  is False
    output["safety"]["can_execute"]           is False
    output["safety"]["broker_order_id"]       == "NONE"
    output["safety"]["human_review_required"] is True

The module is pure: no DB writes, no live API, no filesystem writes, no
broker calls, no AI execution. It never returns ``BUY`` / ``SELL`` /
``EXECUTE``. The strongest positive recommendation it can produce is
``probe_candidate`` / ``review_candidate``, which still requires the
operator to act. Missing data degrades to ``wait_insufficient_data`` /
``review`` / ``insufficient_data`` — never to a buy.

This module deliberately mirrors the structure, helpers and safety
posture of ``scripts/signal_geometry_reflection.py`` so the two layers
read as siblings. It reuses (rather than re-derives) the existing
signal-geometry persistence vocabulary (signal cells, duplicate
fingerprints) where the caller passes it in.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "broker_order_id": "NONE",
    "human_review_required": True,
}

# Indian equities may be evaluated up to 4x leverage as a CEILING, not a
# default. Everything else is spot-only (ceiling = 1.0).
INDIA_LEVERAGE_CEILING: float = 4.0
ROW_LEVERAGE_CEILING: float = 1.0
DEFAULT_LEVERAGE: float = 1.0

# Default per-day operator processing capacity when no explicit capacity is
# supplied. Deliberately conservative — overload should be easy to trip.
DEFAULT_OPERATOR_CAPACITY: float = 8.0

# Default narrative half-life (hours) used by the decay engine when the
# signal does not carry an explicit ``half_life_hours``.
DEFAULT_HALF_LIFE_HOURS: float = 48.0

CASCADE_STATES: tuple[str, ...] = (
    "no_cascade",
    "early_feedback",
    "self_reinforcing",
    "crowded_cascade",
    "fragile_cascade",
    "insufficient_data",
)

PHASE_TRANSITION_STATES: tuple[str, ...] = (
    "ignored",
    "forming",
    "confirmed",
    "crowded",
    "exhausted",
    "collapsing",
    "insufficient_data",
)

FLOCKING_STATES: tuple[str, ...] = (
    "isolated",
    "weak_cluster",
    "leader_follower",
    "crowded_sector_flock",
    "unstable_rotation",
    "insufficient_data",
)

KEYSTONE_ROLES: tuple[str, ...] = (
    "none",
    "theme_leader",
    "liquidity_anchor",
    "sentiment_anchor",
    "fragility_node",
)

DIFFUSION_STATES: tuple[str, ...] = (
    "contained",
    "spreading",
    "sector_wide",
    "overheated",
    "unknown",
)

CHAOS_STATES: tuple[str, ...] = (
    "stable",
    "unstable",
    "whiplash",
    "nonlinear",
    "insufficient_data",
)

SIZE_BANDS: tuple[str, ...] = (
    "avoid",
    "watchlist",
    "probe",
    "small",
    "normal",
)

INTAKE_STATES: tuple[str, ...] = (
    "normal",
    "elevated",
    "overloaded",
    "intake_freeze_recommended",
)

# Top-level advisory bias — never a broker order. Mirrors the geometry
# layer's vocabulary plus an explicit ``avoid``.
ADVISORY_BIASES: tuple[str, ...] = (
    "avoid",
    "wait",
    "watchlist",
    "review",
    "probe_candidate",
    "insufficient_data",
)


# ---------------------------------------------------------------------------
# Coercion helpers — never raise on bad input. (Mirrors the geometry layer.)
# ---------------------------------------------------------------------------


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["safety"] = dict(SAFETY_STAMPS)
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    out.setdefault("human_review_required", True)
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if x != x:  # NaN guard
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return x


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _direction(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"up", "bull", "bullish", "long", "+", "1"}:
            return 1
        if lowered in {"down", "bear", "bearish", "short", "-", "-1"}:
            return -1
        return 0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_cluster(signal_or_cluster: Any) -> list[dict[str, Any]]:
    if isinstance(signal_or_cluster, list):
        return [s for s in signal_or_cluster if isinstance(s, dict)]
    if isinstance(signal_or_cluster, dict):
        return [signal_or_cluster]
    return []


def _is_india(signal: dict[str, Any]) -> bool:
    jurisdiction = _str(signal.get("jurisdiction")).upper()
    geography = _str(signal.get("geography")).upper()
    market = _str(signal.get("market")).upper()
    for token in (jurisdiction, geography, market):
        if token in {"IN", "IND", "INDIA", "NSE", "BSE"}:
            return True
    return False


def _first(data: dict[str, Any], *keys: str) -> Any:
    """Return the first key whose value is present (not None/empty-string)."""
    for key in keys:
        if key in data:
            val = data.get(key)
            if val is not None and val != "":
                return val
    return None


def _present(data: dict[str, Any], *keys: str) -> bool:
    """True if any key is present and non-bool, non-None."""
    for key in keys:
        if key in data and data.get(key) is not None and not isinstance(
            data.get(key), bool
        ):
            return True
    return False


def _model_name(row: dict[str, Any]) -> str:
    return _str(
        _first(row, "model", "model_name", "source_name", "source_family",
               "source_type")
    ).lower()


def _catalyst_key(row: dict[str, Any]) -> str:
    blob = _str(
        _first(row, "catalyst", "thesis", "narrative_cluster", "cluster_id",
               "headline", "title")
    ).lower()
    if not blob:
        return ""
    return hashlib.blake2s(blob.encode("utf-8"), digest_size=6).hexdigest()


def _has_citation(row: dict[str, Any]) -> bool:
    cite = _first(row, "citation", "citations", "source_url", "url",
                  "evidence", "evidence_url", "reference")
    if cite is None:
        return False
    if isinstance(cite, (list, tuple, set)):
        return len(cite) > 0
    return bool(_str(cite))


# ---------------------------------------------------------------------------
# 1. Signal Half-Life Engine.
#    S_live = S0 * exp(-lambda * delta_t) + reinforcement - contradiction
# ---------------------------------------------------------------------------


def compute_signal_half_life(signal: Any, *, now_hours: Any = None) -> dict[str, Any]:
    """Decay a signal's strength over time unless reinforced.

    Old signals decay; fresh confirmation reinforces; contradiction
    erodes. Returns ``None`` live score (and ``insufficient_data`` bucket)
    when neither an initial strength nor an age is available — it never
    invents a fresh score from nothing.
    """
    data = signal if isinstance(signal, dict) else {}
    s0_raw = _first(data, "initial_strength", "signal_strength", "intensity",
                    "narrative_intensity", "evidence_strength")
    has_s0 = s0_raw is not None
    s0 = _clamp(s0_raw)

    age_raw = _first(data, "age_hours", "signal_age_hours")
    if age_raw is None and now_hours is not None and _first(data, "timestamp_hours"):
        age_raw = _coerce_float(now_hours) - _coerce_float(data.get("timestamp_hours"))
    has_age = age_raw is not None
    age_hours = max(_coerce_float(age_raw), 0.0)

    half_life = _coerce_float(_first(data, "half_life_hours"), DEFAULT_HALF_LIFE_HOURS)
    if half_life <= 0:
        half_life = DEFAULT_HALF_LIFE_HOURS
    lam = math.log(2.0) / half_life

    freshness_state = _str(data.get("freshness_state")).lower()
    reinforcement_count = _coerce_int(
        _first(data, "reinforcement_count", "confirmation_count",
               "independent_confirmation_count")
    )
    contradiction_count = _coerce_int(_first(data, "contradiction_count"))
    contradiction_score = _clamp(data.get("contradiction_score"))

    if not has_s0 and not has_age:
        return _stamp({
            "live_signal_score": None,
            "initial_strength": None,
            "signal_age_hours": None,
            "half_life_hours": round(half_life, 4),
            "half_life_bucket": "insufficient_data",
            "stale_signal_flag": False,
            "freshness_penalty": None,
            "reinforcement": 0.0,
            "contradiction": 0.0,
            "confidence_note": (
                "Insufficient data: no initial strength and no age. "
                "Cannot compute live decay — treat as INSUFFICIENT_DATA."
            ),
        })

    decay_fraction = math.exp(-lam * age_hours) if has_age else 1.0
    decayed = s0 * decay_fraction
    reinforcement = _clamp(min(0.3, 0.08 * reinforcement_count))
    contradiction = _clamp(max(contradiction_score, 0.1 * contradiction_count))
    live = _clamp(decayed + reinforcement - contradiction)
    freshness_penalty = round(_clamp(1.0 - decay_fraction), 4)

    ratio = age_hours / half_life if has_age else 0.0
    if not has_age:
        bucket = "unknown_age"
    elif ratio < 0.5:
        bucket = "fresh"
    elif ratio < 1.0:
        bucket = "aging"
    elif ratio < 2.0:
        bucket = "stale"
    else:
        bucket = "expired"

    stale_flag = bool(
        bucket in {"stale", "expired"}
        or freshness_state == "stale"
        or (has_s0 and live < 0.15)
    )

    if not has_s0:
        note = "Age known but no initial strength; decay shape only — low confidence."
    elif not has_age:
        note = "Initial strength known but no age; no decay applied — treat as upper bound."
    else:
        note = "Live score = S0*exp(-lambda*age) + reinforcement - contradiction."

    return _stamp({
        "live_signal_score": round(live, 4),
        "initial_strength": round(s0, 4) if has_s0 else None,
        "signal_age_hours": round(age_hours, 4) if has_age else None,
        "half_life_hours": round(half_life, 4),
        "half_life_bucket": bucket,
        "stale_signal_flag": stale_flag,
        "freshness_penalty": freshness_penalty,
        "reinforcement": round(reinforcement, 4),
        "contradiction": round(contradiction, 4),
        "confidence_note": note,
    })


# ---------------------------------------------------------------------------
# 2. Source Independence Tracker.
# ---------------------------------------------------------------------------


def compute_source_independence(signal_or_cluster: Any) -> dict[str, Any]:
    """Distinguish real independent confirmation from echo-chamber repetition.

    Five models repeating one public catalyst is NOT five independent
    confirmations. Missing citations downgrade independence.
    """
    rows = _as_cluster(signal_or_cluster)
    if not rows:
        return _stamp({
            "model_count": 0,
            "unique_catalyst_count": 0,
            "repeated_catalyst_count": 0,
            "independence_score": 0.0,
            "echo_chamber_risk": 0.0,
            "citation_coverage": 0.0,
            "source_overlap_note": "insufficient_data: no sources supplied.",
        })
    models = {m for m in (_model_name(r) for r in rows) if m}
    catalysts = [c for c in (_catalyst_key(r) for r in rows) if c]
    model_count = len(models) if models else len(rows)
    unique_catalysts = len(set(catalysts))
    repeated = max(len(catalysts) - unique_catalysts, 0)
    citation_rows = sum(1 for r in rows if _has_citation(r))
    citation_coverage = _clamp(citation_rows / max(len(rows), 1))

    if not catalysts:
        # No catalyst evidence at all — independence is unknown, lean low.
        independence = round(_clamp(0.2 * citation_coverage), 4)
        note = "No catalyst evidence; independence unknown — downgraded."
    else:
        raw = unique_catalysts / max(model_count, 1)
        # Downgrade for missing citations: uncited claims cannot count as
        # independent verification.
        independence = round(_clamp(raw * (0.5 + 0.5 * citation_coverage)), 4)
        if model_count >= 3 and unique_catalysts <= 1:
            note = (
                f"{model_count} sources collapse to {unique_catalysts} catalyst "
                "— echo chamber, not independent confirmation."
            )
        elif citation_coverage < 0.5:
            note = "Sparse citations; independence downgraded."
        else:
            note = (
                f"{unique_catalysts} distinct catalysts across {model_count} "
                "sources."
            )
    echo_risk = round(_clamp(1.0 - independence), 4)
    return _stamp({
        "model_count": model_count,
        "unique_catalyst_count": unique_catalysts,
        "repeated_catalyst_count": repeated,
        "independence_score": independence,
        "echo_chamber_risk": echo_risk,
        "citation_coverage": round(citation_coverage, 4),
        "source_overlap_note": note,
    })


# ---------------------------------------------------------------------------
# 3. Narrative Cascade Detector.
# ---------------------------------------------------------------------------


def detect_narrative_cascade(
    signal: Any, *, context: Any = None
) -> dict[str, Any]:
    """Detect when a thesis is becoming self-reinforcing.

    Rises with model agreement + momentum + volume; downgrades to a
    *crowded / fragile* reading when source novelty is low (everyone is
    repeating the same thing).
    """
    data = signal if isinstance(signal, dict) else {}
    ctx = context if isinstance(context, dict) else {}

    agreement_raw = _first(data, "model_agreement", "consensus_score",
                           "ai_consensus_score") or _first(ctx, "model_agreement",
                                                            "consensus_score")
    momentum_raw = _first(data, "price_momentum", "momentum",
                          "price_acceleration") or _first(ctx, "price_momentum")
    volume_raw = _first(data, "volume_spike", "flow_proxy",
                        "volume_proxy") or _first(ctx, "volume_spike")
    mention_raw = _first(data, "mention_count") or _first(ctx, "mention_count")
    novelty_raw = _first(data, "source_novelty")
    dup_raw = _first(data, "duplicate_fingerprint_count", "repeated_thesis_count")
    contradiction = _clamp(data.get("contradiction_score"))

    present = [x is not None for x in
               (agreement_raw, momentum_raw, volume_raw, mention_raw)]
    if not any(present):
        return _stamp({
            "cascade_score": 0.0,
            "cascade_state": "insufficient_data",
            "source_novelty": None,
            "advisory_risk_note": "insufficient_data: no cascade inputs present.",
        })

    agreement = _clamp(agreement_raw)
    momentum = _clamp(momentum_raw)
    volume = _clamp(volume_raw)
    mentions = _clamp(_coerce_int(mention_raw) / 10.0)
    has_novelty = novelty_raw is not None
    novelty = _clamp(novelty_raw) if has_novelty else 0.5
    dup = _clamp(_coerce_int(dup_raw) / 5.0)

    base = _clamp(0.35 * agreement + 0.3 * momentum + 0.2 * volume + 0.15 * mentions)
    # Low novelty does not lower the *intensity* of a cascade — a crowded
    # echo is still a cascade — but it pushes the classification toward the
    # dangerous (crowded / fragile) states.
    cascade_score = round(base, 4)

    if base < 0.25:
        state = "no_cascade"
    elif base < 0.45:
        state = "early_feedback"
    elif base >= 0.7 and (novelty < 0.3 or dup >= 0.6):
        state = "crowded_cascade"
    elif base >= 0.6 and (contradiction >= 0.4 or momentum < 0.3):
        state = "fragile_cascade"
    elif base >= 0.7 and contradiction >= 0.4:
        state = "fragile_cascade"
    else:
        state = "self_reinforcing"

    if state == "crowded_cascade":
        note = "Self-reinforcing but crowded with low source novelty — late/echo risk."
    elif state == "fragile_cascade":
        note = "Cascade with contradiction or fading momentum — fragile, can snap."
    elif state == "self_reinforcing":
        note = "Thesis is self-reinforcing; watch for crowding and exhaustion."
    elif state == "early_feedback":
        note = "Early feedback forming; not yet a confirmed cascade."
    else:
        note = "No meaningful cascade detected."

    return _stamp({
        "cascade_score": cascade_score,
        "cascade_state": state,
        "source_novelty": round(novelty, 4) if has_novelty else None,
        "model_agreement": round(agreement, 4),
        "momentum": round(momentum, 4),
        "duplicate_fingerprint_pressure": round(dup, 4),
        "advisory_risk_note": note,
    })


# ---------------------------------------------------------------------------
# 4. Winner's Curse / Crowding Risk Score.
# ---------------------------------------------------------------------------


def compute_winner_curse_risk(
    signal: Any, *, context: Any = None
) -> dict[str, Any]:
    """Penalise late entries after consensus and a price move."""
    data = signal if isinstance(signal, dict) else {}
    ctx = context if isinstance(context, dict) else {}

    unanimity = _clamp(_first(data, "model_unanimity", "model_agreement",
                              "consensus_score", "ai_consensus_score")
                       or _first(ctx, "model_unanimity", "consensus_score"))
    recent_return = _clamp(_first(data, "recent_return", "price_momentum",
                                  "momentum") or _first(ctx, "recent_return"))
    saturation = _clamp(_first(data, "narrative_saturation", "crowding_score")
                        or _first(ctx, "crowding_score"))
    volume_spike = _clamp(_first(data, "volume_spike", "volume_proxy"))
    dup = _clamp(_coerce_int(_first(data, "duplicate_fingerprint_count")) / 5.0)
    late_entry = bool(data.get("late_entry") or data.get("late_entry_marker"))

    winner_curse = _clamp(
        0.28 * unanimity
        + 0.24 * recent_return
        + 0.24 * saturation
        + 0.12 * dup
        + 0.12 * volume_spike
        + (0.2 if late_entry else 0.0)
    )
    crowding_penalty = round(_clamp(0.5 * saturation + 0.5 * unanimity), 4)
    late_warning = bool(
        late_entry or (recent_return >= 0.6 and unanimity >= 0.6)
    )
    # Entry-quality adjustment is a downward nudge in [-1, 0]; it can only
    # *reduce* perceived quality, never add conviction.
    entry_quality_adjustment = round(-winner_curse, 4)
    return _stamp({
        "winner_curse_risk": round(winner_curse, 4),
        "crowding_penalty": crowding_penalty,
        "late_entry_warning": late_warning,
        "entry_quality_adjustment": entry_quality_adjustment,
        "model_unanimity": round(unanimity, 4),
        "recent_return_proxy": round(recent_return, 4),
    })


# ---------------------------------------------------------------------------
# 5. Phase Transition Classifier.
# ---------------------------------------------------------------------------


def classify_phase_transition(
    signal: Any, *, context: Any = None
) -> dict[str, Any]:
    """Classify narrative/market regime — not a binary buy/sell."""
    data = signal if isinstance(signal, dict) else {}
    ctx = context if isinstance(context, dict) else {}

    attention_raw = _first(data, "attention_growth", "attention_score",
                           "mention_growth") or _first(ctx, "attention_growth")
    accel_raw = _first(data, "price_acceleration", "momentum",
                       "price_momentum") or _first(ctx, "price_acceleration")
    chaos_raw = _first(data, "chaos_score", "volatility") or _first(ctx, "chaos_score")
    flow_raw = _first(data, "flow_confirmation", "market_confirmation",
                      "liquidity_confirmation") or _first(ctx, "flow_confirmation")
    contradiction_raw = _first(data, "contradiction_score")
    decay_raw = _first(data, "half_life_decay", "freshness_penalty")
    crowding_raw = _first(data, "crowding_score", "narrative_saturation")

    present = [x is not None for x in
               (attention_raw, accel_raw, flow_raw, chaos_raw)]
    if sum(present) < 2:
        return _stamp({
            "phase_transition_state": "insufficient_data",
            "attention": None,
            "flow_confirmation": None,
            "inputs_present": int(sum(present)),
            "note": "Fewer than two regime inputs present — cannot classify.",
        })

    attention = _clamp(attention_raw)
    accel = _clamp(accel_raw)
    chaos = _clamp(chaos_raw)
    flow = _clamp(flow_raw)
    contradiction = _clamp(contradiction_raw)
    decay = _clamp(decay_raw)
    crowding = _clamp(crowding_raw)

    if decay >= 0.6 and (contradiction >= 0.4 or chaos >= 0.6):
        state = "collapsing"
    elif attention < 0.2 and flow < 0.2:
        state = "ignored"
    elif attention >= 0.4 and flow >= 0.5 and crowding >= 0.6:
        state = "crowded"
    elif attention >= 0.4 and flow >= 0.5 and contradiction < 0.4:
        state = "confirmed"
    elif attention >= 0.4 and (flow < 0.3 or decay >= 0.4):
        state = "exhausted"
    elif attention >= 0.3 and accel >= 0.3:
        state = "forming"
    else:
        state = "forming"

    return _stamp({
        "phase_transition_state": state,
        "attention": round(attention, 4),
        "price_acceleration": round(accel, 4),
        "flow_confirmation": round(flow, 4),
        "chaos": round(chaos, 4),
        "contradiction": round(contradiction, 4),
        "decay": round(decay, 4),
        "inputs_present": int(sum(present)),
    })


# ---------------------------------------------------------------------------
# 6. Ant Mill / Confirmation Loop Breaker.
# ---------------------------------------------------------------------------


def detect_ant_mill(
    signal: Any, *, independence_score: Any = None
) -> dict[str, Any]:
    """Force a contradiction search when conviction is high but independence
    is low (the classic confirmation death-spiral)."""
    data = signal if isinstance(signal, dict) else {}
    agreement = _clamp(_first(data, "model_agreement", "consensus_score",
                              "ai_consensus_score"))
    if independence_score is not None:
        independence = _clamp(independence_score)
    else:
        independence = _clamp(_first(data, "independence_score"))
    contradiction_search = _clamp(_first(data, "contradiction_search_strength",
                                         "contradiction_searched"))
    invalidation_clarity = _clamp(_first(data, "invalidation_clarity",
                                         "invalidation_strength"))
    dup = _clamp(_coerce_int(_first(data, "duplicate_fingerprint_count")) / 5.0)
    stale = bool(data.get("stale_thesis") or
                 _str(data.get("freshness_state")).lower() == "stale")

    ant_mill_risk = _clamp(
        0.4 * agreement * (1.0 - independence)
        + 0.2 * (1.0 - contradiction_search)
        + 0.2 * (1.0 - invalidation_clarity)
        + 0.1 * dup
        + (0.1 if stale else 0.0)
    )
    high_agreement_low_independence = bool(agreement >= 0.7 and independence < 0.4)
    forced_contradiction_required = bool(
        ant_mill_risk >= 0.5 or high_agreement_low_independence
    )
    if high_agreement_low_independence:
        block_reason = "high_agreement_low_independence_requires_contradiction_search"
    elif ant_mill_risk >= 0.5:
        block_reason = "ant_mill_loop_requires_invalidation_search"
    else:
        block_reason = None
    invalidation_question = (
        "What specific, observable event in the next signal half-life would "
        "prove this thesis wrong? If you cannot name one, do not promote."
    )
    return _stamp({
        "ant_mill_risk": round(ant_mill_risk, 4),
        "forced_contradiction_required": forced_contradiction_required,
        "invalidation_question": invalidation_question,
        "promotion_block_reason": block_reason,
        "model_agreement": round(agreement, 4),
        "independence_score": round(independence, 4),
    })


# ---------------------------------------------------------------------------
# 7. Queueing Attention Gate.   rho = arrival_rate / processing_capacity
# ---------------------------------------------------------------------------


def compute_queueing_attention_gate(
    operator_state: Any = None, *, queue_state: Any = None
) -> dict[str, Any]:
    """Prevent operator overload by modelling intake as an M/M/1-style queue."""
    op = operator_state if isinstance(operator_state, dict) else {}
    qs = queue_state if isinstance(queue_state, dict) else {}
    merged = {**op, **qs}

    open_recon = _coerce_int(_first(merged, "open_reconciliation_items",
                                    "open_recon_items", "reconciliation_open"))
    live_signals = _coerce_int(_first(merged, "live_signal_count",
                                      "live_signals"))
    unreconciled = _coerce_int(_first(merged, "unreconciled_manual_trades",
                                      "unreconciled_trades"))
    moltbook_pending = _coerce_int(_first(merged, "moltbook_pending_review",
                                          "moltbook_pending"))
    arrival = open_recon + live_signals + unreconciled + moltbook_pending

    capacity = _coerce_float(_first(merged, "operator_capacity",
                                    "operator_processing_capacity"),
                             DEFAULT_OPERATOR_CAPACITY)
    if capacity <= 0:
        capacity = DEFAULT_OPERATOR_CAPACITY
    rho = arrival / capacity
    operator_load_score = round(_clamp(rho), 4)

    if rho < 0.5:
        intake_state = "normal"
    elif rho < 0.85:
        intake_state = "elevated"
    elif rho < 1.2:
        intake_state = "overloaded"
    else:
        intake_state = "intake_freeze_recommended"
    no_new_risk_flag = bool(rho >= 0.85)

    return _stamp({
        "operator_load_score": operator_load_score,
        "queue_rho": round(rho, 4),
        "arrival_count": arrival,
        "operator_capacity": round(capacity, 4),
        "intake_state": intake_state,
        "no_new_risk_flag": no_new_risk_flag,
        "components": {
            "open_reconciliation_items": open_recon,
            "live_signal_count": live_signals,
            "unreconciled_manual_trades": unreconciled,
            "moltbook_pending_review": moltbook_pending,
        },
        "capacity_was_defaulted": not _present(
            merged, "operator_capacity", "operator_processing_capacity"
        ),
    })


# ---------------------------------------------------------------------------
# 8. Rawlsian Survival Sizer.
# ---------------------------------------------------------------------------


def compute_rawlsian_survival_sizing(
    signal: Any,
    *,
    operator_load: Any = None,
    crowding: Any = None,
    moltbook_repair_state: Any = None,
) -> dict[str, Any]:
    """Year-1 capital allocation under uncertainty — survival first.

    India leverage is a CEILING (4x), never a default. Rest-of-world is
    spot-only. Uncertainty, operator load, crowding, and an unrepaired
    Moltbook all reduce size.
    """
    data = signal if isinstance(signal, dict) else {}
    india = _is_india(data)
    leverage_ceiling = INDIA_LEVERAGE_CEILING if india else ROW_LEVERAGE_CEILING
    leverage_allowed = bool(india)  # only India may exceed 1.0 — and only as a ceiling

    uncertainty = _clamp(
        _first(data, "uncertainty", "chaos_score")
        if _present(data, "uncertainty", "chaos_score")
        else 1.0 - _clamp(_first(data, "evidence_strength", "materiality_score"))
    )
    op_load = _clamp(operator_load if operator_load is not None
                     else _first(data, "operator_load_score"))
    crowd = _clamp(crowding if crowding is not None
                   else _first(data, "crowding_score", "winner_curse_risk"))
    if moltbook_repair_state is not None:
        repair = _clamp(moltbook_repair_state)
    else:
        repair = _clamp(_first(data, "moltbook_repair_score"), 0.0, 1.0)
        if not _present(data, "moltbook_repair_score"):
            repair = 0.5  # unknown — neutral, neither rewarded nor fully penalised

    survival_quality = _clamp(
        1.0
        - 0.3 * uncertainty
        - 0.25 * op_load
        - 0.25 * crowd
        - 0.2 * (1.0 - repair)
    )

    if survival_quality < 0.2:
        band = "avoid"
    elif survival_quality < 0.4:
        band = "watchlist"
    elif survival_quality < 0.6:
        band = "probe"
    elif survival_quality < 0.8:
        band = "small"
    else:
        band = "normal"

    if leverage_allowed:
        leverage_warning = (
            f"India: leverage permitted up to {leverage_ceiling:.0f}x as a "
            "CEILING only — default is 1.0x (spot). High uncertainty/crowding "
            "should pull toward spot."
        )
    else:
        leverage_warning = "Rest-of-world: spot-only. No leverage permitted."

    return _stamp({
        "suggested_size_band": band,
        "leverage_allowed_boolean": leverage_allowed,
        "leverage_ceiling": leverage_ceiling,
        "leverage_is_default": False,
        "leverage_warning": leverage_warning,
        "survival_quality_score": round(survival_quality, 4),
        "india_market": india,
        "spot_only": not india,
        "inputs": {
            "uncertainty": round(uncertainty, 4),
            "operator_load": round(op_load, 4),
            "crowding": round(crowd, 4),
            "moltbook_repair_state": round(repair, 4),
        },
    })


# ---------------------------------------------------------------------------
# 9. Broken Windows Discipline / Moltbook Repair State.
# ---------------------------------------------------------------------------


def compute_broken_windows_discipline(moltbook_state: Any) -> dict[str, Any]:
    """Unlogged losses create system decay. Track repair debt.

    A clean Moltbook (no unrepaired closed losses, no unreviewed items)
    lowers ``discipline_decay_score``; outstanding losses raise it and can
    block promotion.
    """
    state = moltbook_state if isinstance(moltbook_state, dict) else {}
    unrepaired_losses = _coerce_int(_first(state, "closed_losses_without_moltbook",
                                           "unrepaired_loss_count"))
    stale_mismatches = _coerce_int(_first(state, "stale_reconciliation_mismatches",
                                          "stale_recon_mismatches"))
    stop_breaches = _coerce_int(_first(state, "stop_loss_breaches",
                                       "stop_loss_breached_count"))
    tp_breaches = _coerce_int(_first(state, "take_profit_breaches_unacted",
                                     "take_profit_breaches"))
    unreviewed = _coerce_int(_first(state, "unreviewed_moltbook_items",
                                    "duplicate_moltbook_items"))
    bridge_complete = bool(state.get("loss_bridge_complete", True))

    total_issues = (unrepaired_losses + stale_mismatches + stop_breaches
                    + tp_breaches + unreviewed)
    # Each unrepaired loss weighs heaviest (broken window left visible).
    weighted = (2.0 * unrepaired_losses + 1.5 * stop_breaches
                + 1.0 * stale_mismatches + 1.0 * tp_breaches + 0.5 * unreviewed)
    discipline_decay = round(_clamp(weighted / 6.0), 4)

    moltbook_repair_complete = bool(
        unrepaired_losses == 0 and unreviewed == 0 and bridge_complete
    )

    if unrepaired_losses > 0:
        next_action = (
            f"Log {unrepaired_losses} closed loss(es) to Moltbook as advisory-only "
            "entries (e.g. GLD/TSM bridge) before any new promotion."
        )
    elif stop_breaches > 0:
        next_action = f"Document {stop_breaches} stop-loss breach(es) and the lesson."
    elif unreviewed > 0:
        next_action = f"Review {unreviewed} pending/duplicate Moltbook item(s)."
    elif stale_mismatches > 0:
        next_action = f"Resolve {stale_mismatches} stale reconciliation mismatch(es)."
    else:
        next_action = "No repair debt — discipline intact."

    promotion_block = bool(unrepaired_losses > 0 or stop_breaches > 0)

    return _stamp({
        "discipline_decay_score": discipline_decay,
        "unrepaired_loss_count": unrepaired_losses,
        "stale_reconciliation_mismatches": stale_mismatches,
        "stop_loss_breaches": stop_breaches,
        "take_profit_breaches_unacted": tp_breaches,
        "unreviewed_moltbook_items": unreviewed,
        "total_open_issues": total_issues,
        "moltbook_repair_complete_boolean": moltbook_repair_complete,
        "moltbook_repair_score": round(1.0 - discipline_decay, 4),
        "next_repair_action": next_action,
        "promotion_block_if_unrepaired": promotion_block,
        "loss_bridge_complete": bridge_complete,
    })


# ---------------------------------------------------------------------------
# 10. Sector Flocking Map.
# ---------------------------------------------------------------------------


def map_sector_flocking(signal_or_cluster: Any) -> dict[str, Any]:
    """Detect leader/follower sector movement (boids-style flocking)."""
    rows = _as_cluster(signal_or_cluster)
    if not rows:
        return _stamp({
            "flocking_state": "insufficient_data",
            "leader_hint": None,
            "follower_hint": None,
            "lag_note": "insufficient_data: no signals supplied.",
            "sector_distribution": {},
        })
    sector_counts: dict[str, int] = {}
    for r in rows:
        sec = _str(r.get("sector")).lower() or "unknown"
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    dominant_sector, dominant_count = max(sector_counts.items(),
                                          key=lambda kv: kv[1])
    same_sector_rows = [r for r in rows
                        if (_str(r.get("sector")).lower() or "unknown") == dominant_sector]

    def _ticker(r: dict[str, Any]) -> str:
        raw = _first(r, "ticker", "asset_tags", "symbol")
        if isinstance(raw, (list, tuple)) and raw:
            return _str(raw[0]).upper()
        return _str(raw).upper()

    def _strength(r: dict[str, Any]) -> float:
        return _clamp(_first(r, "intensity", "narrative_intensity", "momentum",
                             "signal_strength"))

    crowding = max((_clamp(r.get("crowding_score")) for r in rows), default=0.0)
    directions = {_direction(r.get("direction")) for r in same_sector_rows
                  if _direction(r.get("direction")) != 0}

    leader_hint = None
    follower_hint = None
    if dominant_count >= 2:
        ranked = sorted(same_sector_rows, key=_strength, reverse=True)
        leader_hint = _ticker(ranked[0]) or None
        followers = [t for t in (_ticker(r) for r in ranked[1:]) if t]
        follower_hint = followers[0] if followers else None

    if dominant_count <= 1:
        state = "isolated"
        lag_note = "Single signal in its sector — no flock."
    elif len(directions) >= 2:
        state = "unstable_rotation"
        lag_note = "Conflicting directions within the sector — rotation/instability."
    elif dominant_count >= 4 and crowding >= 0.6:
        state = "crowded_sector_flock"
        lag_note = "Many aligned names in one crowded sector — late-flock risk."
    elif leader_hint and follower_hint:
        state = "leader_follower"
        lag_note = f"{leader_hint} leads; {follower_hint} may lag."
    else:
        state = "weak_cluster"
        lag_note = "Loose cluster; leader/follower structure unclear."

    return _stamp({
        "flocking_state": state,
        "leader_hint": leader_hint,
        "follower_hint": follower_hint,
        "lag_note": lag_note,
        "dominant_sector": dominant_sector,
        "sector_distribution": sector_counts,
    })


# ---------------------------------------------------------------------------
# 11. Keystone Stock Detector.
# ---------------------------------------------------------------------------


def detect_keystone_node(
    signal: Any, *, cluster: Any = None
) -> dict[str, Any]:
    """Identify a stock whose strength/failure drives a whole theme."""
    data = signal if isinstance(signal, dict) else {}
    rows = _as_cluster(cluster) if cluster is not None else []

    def _ticker(r: dict[str, Any]) -> str:
        raw = _first(r, "ticker", "asset_tags", "symbol")
        if isinstance(raw, (list, tuple)) and raw:
            return _str(raw[0]).upper()
        return _str(raw).upper()

    lead_ticker = _ticker(data)
    total = len(rows) if rows else 1
    if rows and lead_ticker:
        references = sum(
            1 for r in rows
            if lead_ticker in _str(_first(r, "ticker", "asset_tags",
                                          "related_tickers", "symbol")).upper()
        )
        centrality = _clamp(references / max(total, 1))
        source_diversity = _clamp(
            len({_model_name(r) for r in rows if _model_name(r)}) / max(total, 1)
        )
    else:
        centrality = _clamp(data.get("centrality_score"))
        source_diversity = _clamp(data.get("source_diversity"))

    liquidity = _clamp(_first(data, "liquidity_confirmation", "liquidity_score"))
    narrative = _clamp(_first(data, "narrative_intensity", "narrative_strength"))
    fragility = _clamp(_first(data, "fragility_score", "crowding_score"))

    keystone_score = round(_clamp(0.6 * centrality + 0.4 * source_diversity), 4)

    if keystone_score < 0.3:
        role = "none"
    elif fragility >= 0.6 and keystone_score >= 0.4:
        role = "fragility_node"
    elif liquidity >= 0.6:
        role = "liquidity_anchor"
    elif narrative >= 0.6 and liquidity < 0.4:
        role = "sentiment_anchor"
    elif keystone_score >= 0.5:
        role = "theme_leader"
    else:
        role = "none"

    dependency_note = {
        "theme_leader": "Theme appears to depend on this node — watch it as the tell.",
        "liquidity_anchor": "Acts as a liquidity anchor; its bid supports the theme.",
        "sentiment_anchor": "Carries the narrative without capital confirmation — fragile.",
        "fragility_node": "High centrality + fragility: its failure could cascade.",
        "none": "Not a keystone for this theme.",
    }[role]

    return _stamp({
        "keystone_score": keystone_score,
        "keystone_role": role,
        "centrality": round(centrality, 4),
        "source_diversity": round(source_diversity, 4),
        "dependency_note": dependency_note,
        "node_ticker": lead_ticker or None,
    })


# ---------------------------------------------------------------------------
# 12. Firebreak / Support Failure Detector.
# ---------------------------------------------------------------------------


def detect_firebreak_support(signal: Any) -> dict[str, Any]:
    """Detect whether a loss cascade has brakes (firebreaks)."""
    data = signal if isinstance(signal, dict) else {}
    stop_distance = _clamp(_first(data, "stop_loss_distance", "stop_distance"))
    invalidation = _clamp(_first(data, "invalidation_strength",
                                 "invalidation_clarity"))
    vol = _clamp(_first(data, "volatility", "chaos_score"))
    liquidity = _clamp(_first(data, "liquidity_confirmation", "liquidity_score"))
    contradiction = _clamp(data.get("contradiction_score"))
    recon_clean = bool(data.get("reconciliation_clean", True))

    has_any = _present(data, "stop_loss_distance", "stop_distance",
                       "invalidation_strength", "invalidation_clarity",
                       "volatility", "chaos_score", "liquidity_confirmation",
                       "liquidity_score")
    if not has_any:
        return _stamp({
            "firebreak_strength": None,
            "support_failure_risk": None,
            "stop_cascade_warning": False,
            "invalidation_clarity_score": None,
            "note": "insufficient_data: no firebreak inputs present.",
        })

    firebreak_strength = _clamp(
        0.4 * invalidation + 0.3 * liquidity + 0.3 * stop_distance
        - (0.0 if recon_clean else 0.1)
    )
    support_failure_risk = _clamp(
        0.5 * (1.0 - firebreak_strength) + 0.3 * vol + 0.2 * contradiction
    )
    stop_cascade_warning = bool(support_failure_risk >= 0.6 and liquidity < 0.4)

    return _stamp({
        "firebreak_strength": round(firebreak_strength, 4),
        "support_failure_risk": round(support_failure_risk, 4),
        "stop_cascade_warning": stop_cascade_warning,
        "invalidation_clarity_score": round(invalidation, 4),
        "liquidity_confirmation": round(liquidity, 4),
    })


# ---------------------------------------------------------------------------
# 13. Voting Aggregator for AI Models.
# ---------------------------------------------------------------------------


def aggregate_model_votes(
    signal_or_cluster: Any, *, independence_score: Any = None
) -> dict[str, Any]:
    """Aggregate AI-model votes without trusting naive majority.

    Adjusts the naive consensus by source independence and by a
    contradiction penalty. Output is a *bias*, never an order.
    """
    rows = _as_cluster(signal_or_cluster)
    if not rows:
        return _stamp({
            "model_vote_summary": {},
            "naive_consensus": 0.0,
            "independence_adjusted_consensus": 0.0,
            "aggregation_warning": "insufficient_data: no model votes supplied.",
            "final_model_signal_bias": "insufficient_data",
        })

    votes: dict[str, int] = {"long": 0, "short": 0, "neutral": 0}
    weighted_long = 0.0
    weighted_short = 0.0
    approval = 0
    contradictions = []
    for r in rows:
        d = _direction(r.get("direction"))
        conf = _clamp(_first(r, "confidence", "conviction", "reliability"))
        if d > 0:
            votes["long"] += 1
            weighted_long += max(conf, 0.1)
        elif d < 0:
            votes["short"] += 1
            weighted_short += max(conf, 0.1)
        else:
            votes["neutral"] += 1
        if conf >= 0.5:
            approval += 1
        contradictions.append(_clamp(r.get("contradiction_score")))

    n = len(rows)
    dominant = max(votes, key=lambda k: votes[k])
    naive_consensus = round(_clamp(votes[dominant] / max(n, 1)), 4)

    if independence_score is not None:
        independence = _clamp(independence_score)
    else:
        independence = compute_source_independence(rows)["independence_score"]
    mean_contradiction = (sum(contradictions) / len(contradictions)
                          if contradictions else 0.0)
    contradiction_penalty = _clamp(mean_contradiction)

    independence_adjusted = round(
        _clamp(naive_consensus * independence * (1.0 - contradiction_penalty)), 4
    )

    if dominant == "neutral" or votes[dominant] == votes.get(
        "short" if dominant == "long" else "long", -1
    ):
        bias = "no_clear_bias"
    elif independence_adjusted < 0.2:
        bias = "no_clear_bias"
    elif dominant == "long":
        bias = "net_long_bias"
    elif dominant == "short":
        bias = "net_short_bias"
    else:
        bias = "no_clear_bias"

    if naive_consensus >= 0.6 and independence < 0.4:
        warning = "naive_consensus_is_echo_not_independent_confirmation"
    elif contradiction_penalty >= 0.4:
        warning = "material_contradiction_present_discount_consensus"
    else:
        warning = "none"

    return _stamp({
        "model_vote_summary": {
            **votes,
            "approval_count": approval,
            "risk_adjusted_long": round(weighted_long, 4),
            "risk_adjusted_short": round(weighted_short, 4),
        },
        "naive_consensus": naive_consensus,
        "independence_adjusted_consensus": independence_adjusted,
        "independence_score": round(independence, 4),
        "contradiction_penalty": round(contradiction_penalty, 4),
        "aggregation_warning": warning,
        "final_model_signal_bias": bias,
    })


# ---------------------------------------------------------------------------
# 14. Narrative Diffusion Map.
# ---------------------------------------------------------------------------


def map_narrative_diffusion(signal_or_cluster: Any) -> dict[str, Any]:
    """Track second-order beneficiaries and the spread of a narrative."""
    rows = _as_cluster(signal_or_cluster)
    if not rows:
        return _stamp({
            "diffusion_score": 0.0,
            "second_order_candidates": [],
            "diffusion_state": "unknown",
            "sectors_touched": 0,
        })
    sectors: set[str] = set()
    tickers: set[str] = set()
    related: set[str] = set()
    crowding = 0.0
    for r in rows:
        sec = _str(r.get("sector")).lower()
        if sec:
            sectors.add(sec)
        raw_t = _first(r, "ticker", "asset_tags", "symbol")
        if isinstance(raw_t, (list, tuple)):
            for t in raw_t:
                if _str(t):
                    tickers.add(_str(t).upper())
        elif _str(raw_t):
            tickers.add(_str(raw_t).upper())
        raw_rel = _first(r, "related_tickers", "second_order_tickers",
                         "downstream_tickers")
        if isinstance(raw_rel, (list, tuple)):
            for t in raw_rel:
                if _str(t):
                    related.add(_str(t).upper())
        elif _str(raw_rel):
            for t in _str(raw_rel).split(","):
                if t.strip():
                    related.add(t.strip().upper())
        crowding = max(crowding, _clamp(r.get("crowding_score")))

    second_order = sorted(related - tickers)
    sectors_touched = len(sectors)
    diffusion_score = round(
        _clamp(0.5 * _clamp(sectors_touched / 3.0)
               + 0.5 * _clamp(len(second_order) / 4.0)), 4
    )

    if sectors_touched == 0 and not second_order:
        state = "unknown"
    elif crowding >= 0.7 and diffusion_score >= 0.5:
        state = "overheated"
    elif sectors_touched >= 3:
        state = "sector_wide"
    elif sectors_touched >= 2 or len(second_order) >= 2:
        state = "spreading"
    else:
        state = "contained"

    return _stamp({
        "diffusion_score": diffusion_score,
        "second_order_candidates": second_order[:25],
        "diffusion_state": state,
        "sectors_touched": sectors_touched,
        "primary_tickers": sorted(tickers)[:25],
    })


# ---------------------------------------------------------------------------
# 15. Chaos / Volatility Regime Detector.
# ---------------------------------------------------------------------------


def classify_chaos_regime(
    signal: Any, *, context: Any = None
) -> dict[str, Any]:
    """Detect nonlinear instability and cap the safe forecast horizon."""
    data = signal if isinstance(signal, dict) else {}
    ctx = context if isinstance(context, dict) else {}

    vol_raw = _first(data, "volatility", "chaos_score") or _first(ctx, "volatility",
                                                                  "chaos_score")
    failed_breakouts = _coerce_int(_first(data, "failed_breakouts"))
    contradiction_raw = _first(data, "contradiction_score")
    whiplash_raw = _first(data, "news_whiplash", "direction_flip_ratio") or \
        _first(ctx, "news_whiplash")
    curl_raw = _first(data, "curl_score", "field_curl_score") or \
        _first(ctx, "curl_score")

    present = [x is not None for x in
               (vol_raw, contradiction_raw, whiplash_raw, curl_raw)]
    if not any(present) and not _present(data, "failed_breakouts"):
        return _stamp({
            "chaos_regime_score": None,
            "chaos_state": "insufficient_data",
            "max_safe_forecast_horizon": None,
            "note": "insufficient_data: no chaos/volatility inputs present.",
        })

    vol = _clamp(vol_raw)
    contradiction = _clamp(contradiction_raw)
    whiplash = _clamp(whiplash_raw)
    curl = _clamp(curl_raw)
    fb = _clamp(failed_breakouts / 3.0)

    chaos_regime_score = round(
        _clamp(0.3 * vol + 0.2 * contradiction + 0.2 * whiplash
               + 0.2 * curl + 0.1 * fb), 4
    )
    max_safe_horizon = round(48.0 * (1.0 - chaos_regime_score), 2)

    if curl >= 0.6 or chaos_regime_score >= 0.75:
        state = "nonlinear"
    elif whiplash >= 0.6:
        state = "whiplash"
    elif chaos_regime_score >= 0.5:
        state = "unstable"
    elif chaos_regime_score < 0.25:
        state = "stable"
    else:
        state = "unstable"

    return _stamp({
        "chaos_regime_score": chaos_regime_score,
        "chaos_state": state,
        "max_safe_forecast_horizon": max_safe_horizon,
        "volatility": round(vol, 4),
        "news_whiplash": round(whiplash, 4),
        "curl_score": round(curl, 4),
    })


# ---------------------------------------------------------------------------
# 16. Final Trade Quality Decomposition.
# ---------------------------------------------------------------------------


def decompose_trade_quality(
    numerator: dict[str, Any],
    denominator: dict[str, Any],
    *,
    confidence: Any = None,
    hard_block: Any = False,
) -> dict[str, Any]:
    """Make the final operating formula visible — diagnostic, not an order.

        Quality = (product of numerator factors) / (sum of denominator factors)

    The literal product/sum is exposed for transparency, but the advisory
    bias is driven by a numerically stable normalised ratio of the factor
    *means* so that one near-zero factor does not silently zero the whole
    score. This is a decomposition for human review — it is NOT an
    execution signal and never returns BUY/SELL.
    """
    num_keys = ("signal_strength", "source_independence", "freshness",
                "narrative_durability", "risk_reward", "learning_value")
    den_keys = ("noise", "crowding", "chaos", "contradiction",
                "invalidation_ambiguity", "operator_load")

    num = {k: _clamp(numerator.get(k)) for k in num_keys}
    den = {k: _clamp(denominator.get(k)) for k in den_keys}

    product = 1.0
    for v in num.values():
        product *= v
    den_sum = sum(den.values())
    raw_trade_quality = round(product / (den_sum + 1e-6), 6)

    num_mean = sum(num.values()) / len(num)
    den_mean = den_sum / len(den)
    ratio = num_mean / (den_mean + 1e-6)
    clipped_trade_quality = round(_clamp(ratio / (ratio + 1.0)), 4)

    conf = _clamp(confidence) if confidence is not None else 0.5

    if conf < 0.34:
        bias = "insufficient_data"
    elif bool(hard_block):
        # A hard block (ant-mill / broken-windows / leverage veto / nonlinear
        # chaos) can never resolve to anything stronger than review.
        bias = "review" if clipped_trade_quality >= 0.45 else "wait"
    elif clipped_trade_quality < 0.3:
        bias = "avoid"
    elif clipped_trade_quality < 0.45:
        bias = "wait"
    elif clipped_trade_quality < 0.55:
        bias = "watchlist"
    elif clipped_trade_quality < 0.7:
        bias = "review"
    else:
        bias = "probe_candidate" if conf >= 0.6 else "review"

    return _stamp({
        "trade_quality_components": {
            "numerator": {k: round(v, 4) for k, v in num.items()},
            "denominator": {k: round(v, 4) for k, v in den.items()},
            "raw_trade_quality": raw_trade_quality,
            "numerator_product": round(product, 6),
            "denominator_sum": round(den_sum, 4),
            "clipped_trade_quality": clipped_trade_quality,
            "confidence": round(conf, 4),
            "advisory_bias": bias,
        },
        "advisory_bias": bias,
        "note": (
            "Diagnostic decomposition for human review only. NOT an execution "
            "signal. Never a broker order."
        ),
    })


# ---------------------------------------------------------------------------
# Top-level orchestrator.
# ---------------------------------------------------------------------------


def build_complex_systems_diagnostics(
    signal_or_cluster: Any,
    *,
    context: Any = None,
    operator_state: Any = None,
    moltbook_state: Any = None,
    queue_state: Any = None,
    history: Any = None,
    seen_fingerprints: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Run every complex-systems diagnostic for one signal or cluster.

    All sub-components degrade safely on missing inputs. The orchestrator
    never raises; if a sub-component fails internally it is recorded as a
    safety-stamped error dict rather than propagating. The roll-up
    ``advisory_decision_bias`` is one of :data:`ADVISORY_BIASES` — never a
    broker order.
    """
    cluster = _as_cluster(signal_or_cluster)
    lead = cluster[0] if cluster else {}
    ctx = context if isinstance(context, dict) else {}
    op_state = operator_state if isinstance(operator_state, dict) else {}
    history = history if isinstance(history, dict) else {}

    def _safe(fn, *args, **kwargs) -> dict[str, Any]:
        try:
            res = fn(*args, **kwargs)
        except Exception:
            return _stamp({"error": "sub_component_failed",
                           "component": getattr(fn, "__name__", "unknown")})
        return res if isinstance(res, dict) else _stamp({"error": "non_dict"})

    half_life = _safe(compute_signal_half_life, lead)
    independence = _safe(compute_source_independence, cluster)
    independence_score = independence.get("independence_score", 0.0)
    cascade = _safe(detect_narrative_cascade, lead, context=ctx)
    winner_curse = _safe(compute_winner_curse_risk, lead, context=ctx)
    phase = _safe(classify_phase_transition, lead, context=ctx)
    ant_mill = _safe(detect_ant_mill, lead, independence_score=independence_score)
    queue_gate = _safe(compute_queueing_attention_gate, op_state,
                       queue_state=queue_state)
    broken_windows = _safe(compute_broken_windows_discipline, moltbook_state)
    moltbook_repair_score = broken_windows.get("moltbook_repair_score", 0.5)
    rawlsian = _safe(
        compute_rawlsian_survival_sizing, lead,
        operator_load=queue_gate.get("operator_load_score"),
        crowding=winner_curse.get("winner_curse_risk"),
        moltbook_repair_state=moltbook_repair_score,
    )
    flocking = _safe(map_sector_flocking, cluster)
    keystone = _safe(detect_keystone_node, lead, cluster=cluster)
    firebreak = _safe(detect_firebreak_support, lead)
    voting = _safe(aggregate_model_votes, cluster,
                   independence_score=independence_score)
    diffusion = _safe(map_narrative_diffusion, cluster)
    chaos = _safe(classify_chaos_regime, lead, context=ctx)

    # ---- Assemble the final trade-quality numerator / denominator. ----
    live_signal = half_life.get("live_signal_score")
    signal_strength = _clamp(live_signal) if live_signal is not None else _clamp(
        _first(lead, "intensity", "narrative_intensity", "signal_strength")
    )
    freshness = _clamp(1.0 - _clamp(half_life.get("freshness_penalty"))) \
        if half_life.get("freshness_penalty") is not None else _clamp(
        lead.get("freshness_score")
    )
    risk_reward = _clamp(_first(lead, "risk_reward", "risk_reward_ratio",
                                "reward_risk_ratio"))
    learning_value = _clamp(_first(lead, "learning_value",
                                   "moltbook_feedback_value"))
    narrative_durability = _clamp(_first(lead, "narrative_durability",
                                         "durability_score"))

    numerator = {
        "signal_strength": signal_strength,
        "source_independence": independence_score,
        "freshness": freshness,
        "narrative_durability": narrative_durability,
        "risk_reward": risk_reward,
        "learning_value": learning_value,
    }
    denominator = {
        "noise": _clamp(_first(lead, "echo_risk_score", "noise_score")),
        "crowding": _clamp(winner_curse.get("crowding_penalty")),
        "chaos": _clamp(chaos.get("chaos_regime_score")),
        "contradiction": _clamp(lead.get("contradiction_score")),
        "invalidation_ambiguity": _clamp(
            1.0 - _clamp(firebreak.get("invalidation_clarity_score"))
        ) if firebreak.get("invalidation_clarity_score") is not None else 0.5,
        "operator_load": _clamp(queue_gate.get("operator_load_score")),
    }

    # Confidence = fraction of numerator factors that came from real input.
    present_factors = 0
    if half_life.get("live_signal_score") is not None:
        present_factors += 1
    if independence.get("model_count"):
        present_factors += 1
    if half_life.get("freshness_penalty") is not None or _present(
        lead, "freshness_score"
    ):
        present_factors += 1
    if _present(lead, "narrative_durability", "durability_score"):
        present_factors += 1
    if _present(lead, "risk_reward", "risk_reward_ratio", "reward_risk_ratio"):
        present_factors += 1
    if _present(lead, "learning_value", "moltbook_feedback_value"):
        present_factors += 1
    confidence = _clamp(present_factors / len(numerator))

    # Hard blocks: any of these caps the bias at review/wait.
    hard_blocks: list[str] = []
    if ant_mill.get("promotion_block_reason"):
        hard_blocks.append(ant_mill["promotion_block_reason"])
    if broken_windows.get("promotion_block_if_unrepaired"):
        hard_blocks.append("moltbook_repair_incomplete")
    if chaos.get("chaos_state") == "nonlinear":
        hard_blocks.append("chaos_nonlinear")
    if queue_gate.get("intake_state") == "intake_freeze_recommended":
        hard_blocks.append("operator_intake_freeze")
    if rawlsian.get("suggested_size_band") == "avoid":
        hard_blocks.append("survival_sizing_avoid")

    trade_quality = _safe(
        decompose_trade_quality, numerator, denominator,
        confidence=confidence, hard_block=bool(hard_blocks),
    )
    advisory_bias = trade_quality.get("advisory_bias", "insufficient_data")

    if not cluster:
        advisory_bias = "insufficient_data"

    # ---- Feedback multiplier (loop gain) — honest, bounded scalar. ----
    feedback_multiplier = round(_clamp(
        0.5
        + 0.3 * _clamp(cascade.get("cascade_score"))
        + 0.2 * _clamp(half_life.get("reinforcement"))
        - 0.3 * _clamp(half_life.get("contradiction")),
        0.0, 1.5,
    ), 4)

    # ---- State update model descriptor: X_{t+1} = F(X_t, A_t, E_t, G, theta). ----
    state_update_model = {
        "equation": "X_{t+1} = F(X_t, A_t, E_t, G, theta)",
        "X_t_state": {
            "live_signal_score": half_life.get("live_signal_score"),
            "phase_transition_state": phase.get("phase_transition_state"),
        },
        "A_t_actions": {
            "advisory_bias": advisory_bias,
            "size_band": rawlsian.get("suggested_size_band"),
        },
        "E_t_environment": {
            "chaos_state": chaos.get("chaos_state"),
            "intake_state": queue_gate.get("intake_state"),
        },
        "G_structure": {
            "flocking_state": flocking.get("flocking_state"),
            "keystone_role": keystone.get("keystone_role"),
            "diffusion_state": diffusion.get("diffusion_state"),
        },
        "theta_parameters": {
            "half_life_hours": half_life.get("half_life_hours"),
            "operator_capacity": queue_gate.get("operator_capacity"),
            "leverage_ceiling": rawlsian.get("leverage_ceiling"),
        },
        "F_update_rule": "deterministic advisory diagnostics (no prediction, no execution)",
        "feedback_multiplier": feedback_multiplier,
        "note": (
            "Descriptive decomposition of the operating loop. F does not "
            "forecast price and does not execute — it routes to human review."
        ),
    }

    diagnostics = {
        "state_update_model": state_update_model,
        "feedback_multiplier": feedback_multiplier,
        "signal_half_life": half_life,
        "source_independence": independence,
        "narrative_cascade": cascade,
        "winner_curse_risk": winner_curse,
        "phase_transition_state": phase,
        "ant_mill_confirmation_loop": ant_mill,
        "queueing_attention_gate": queue_gate,
        "rawlsian_survival_sizing": rawlsian,
        "broken_windows_discipline": broken_windows,
        "moltbook_repair_state": {
            "moltbook_repair_complete_boolean":
                broken_windows.get("moltbook_repair_complete_boolean"),
            "moltbook_repair_score": broken_windows.get("moltbook_repair_score"),
            "discipline_decay_score": broken_windows.get("discipline_decay_score"),
            "next_repair_action": broken_windows.get("next_repair_action"),
        },
        "sector_flocking_state": flocking,
        "keystone_node_hint": keystone,
        "firebreak_support_state": firebreak,
        "voting_aggregation_diagnostics": voting,
        "narrative_diffusion_state": diffusion,
        "chaos_regime_state": chaos,
        "final_trade_quality_components": trade_quality.get(
            "trade_quality_components"
        ),
        "advisory_decision_bias": advisory_bias,
        "advisory_only": True,
        "human_review_required": True,
        "ai_execution_count": 0,
    }

    return _stamp({
        "complex_systems_diagnostics": diagnostics,
        "signal_count": len(cluster),
        "advisory_decision_bias": advisory_bias,
        "hard_blocks": hard_blocks,
        "operator_action": advisory_bias,
        "doctrine": "Survive first. Learn second. Scale later.",
        "human_review_required": True,
        "canonical_truth_source": "sqlite",
        "jsonl_role": "audit_fallback_only",
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "INDIA_LEVERAGE_CEILING",
    "ROW_LEVERAGE_CEILING",
    "DEFAULT_LEVERAGE",
    "DEFAULT_OPERATOR_CAPACITY",
    "DEFAULT_HALF_LIFE_HOURS",
    "CASCADE_STATES",
    "PHASE_TRANSITION_STATES",
    "FLOCKING_STATES",
    "KEYSTONE_ROLES",
    "DIFFUSION_STATES",
    "CHAOS_STATES",
    "SIZE_BANDS",
    "INTAKE_STATES",
    "ADVISORY_BIASES",
    "compute_signal_half_life",
    "compute_source_independence",
    "detect_narrative_cascade",
    "compute_winner_curse_risk",
    "classify_phase_transition",
    "detect_ant_mill",
    "compute_queueing_attention_gate",
    "compute_rawlsian_survival_sizing",
    "compute_broken_windows_discipline",
    "map_sector_flocking",
    "detect_keystone_node",
    "detect_firebreak_support",
    "aggregate_model_votes",
    "map_narrative_diffusion",
    "classify_chaos_regime",
    "decompose_trade_quality",
    "build_complex_systems_diagnostics",
]
