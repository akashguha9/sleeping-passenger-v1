"""Signal geometry reflection layer — pure, deterministic, advisory-only.

This module is the engineering translation of the "mathematical reflection"
described in ``docs/SIGNAL_GEOMETRY_REFLECTION_LAYER.md``. It collapses
eighteen reflection concepts (spatial index, duplicate veto, feature
extractor, decision partition, risk router, constrained-first queue,
invariant ratio, derivative engine, phase alignment, regime composition,
Monte Carlo survival, field diagnostics, thermodynamic exposure, hidden
macro driver, recursive Moltbook, noise taxonomy, chaos attractor,
Möbius inversion) into a single deterministic diagnostic payload.

Hard contract — every public output:

    output["safety"]["advisory_status"]      == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]       == "LOCKED"
    output["safety"]["broker_api_called"]    is False
    output["safety"]["ai_execution_count"]   == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]          is False
    output["safety"]["broker_order_id"]      == "NONE"
    output["safety"]["human_review_required"] is True

The module is pure: no DB writes, no live API, no filesystem writes,
no broker calls, no AI execution. It never returns ``BUY`` / ``SELL`` /
``EXECUTE``. The strongest positive recommendation it can produce is
``review_candidate``, which still requires the operator to act.

Public API:

    build_signal_geometry_diagnostics(
        signal_or_cluster,
        *,
        context=None,
        operator_state=None,
        moltbook_state=None,
        leverage_hint=None,
        seen_fingerprints=None,
        history=None,
    ) -> dict

All sub-helpers are also exported for direct use (and tested):

    build_signal_cell
    classify_duplicate_stale_pre_veto
    extract_narrative_features
    classify_decision_partition
    compute_risk_route
    compute_constrained_first_priority
    compute_invariant_ratio
    compute_signal_derivatives
    compute_phase_alignment_state
    compute_regime_composition
    monte_carlo_survival_stub
    compute_field_diagnostics
    classify_thermodynamic_exposure
    detect_hidden_macro_driver
    summarize_moltbook_recursive_state
    classify_noise_taxonomy
    classify_chaos_attractor
    classify_mobius_inversion
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

DECISION_PARTITIONS: tuple[str, ...] = (
    "macro",
    "micro_company",
    "geopolitical",
    "regulatory",
    "earnings_filings",
    "flow_market_structure",
    "prediction_market",
    "ai_report",
    "on_chain",
    "manual_trade_reconciliation",
    "unclassified",
)

NOISE_CLASSES: tuple[str, ...] = (
    "normal_noise",
    "fat_tail_shock_risk",
    "oscillatory_cancellation",
    "stale_echo_noise",
    "ai_echo_noise",
    "source_repetition_noise",
)

PHASE_STATES: tuple[str, ...] = (
    "aligned_confirming",
    "narrative_leads_capital",
    "capital_leads_narrative",
    "out_of_phase",
    "dangerous_desync",
    "insufficient_data",
)

THERMO_MODES: tuple[str, ...] = (
    "isothermal",
    "isobaric",
    "isochoric",
    "adiabatic",
    "insufficient_data",
)

ADVISORY_RECOMMENDATIONS: tuple[str, ...] = (
    "observe",
    "watch",
    "review_later",
    "review_candidate",
    "decay_archive",
    "human_review_only",
    "wait_insufficient_data",
)


# ---------------------------------------------------------------------------
# Coercion helpers — never raise on bad input.
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


# ---------------------------------------------------------------------------
# 1. Signal Spatial Index (H3 / R-tree / BSP / Hilbert curve inspiration).
# ---------------------------------------------------------------------------


def _time_bucket(timestamp: Any) -> str:
    """Map a timestamp into a coarse, deterministic bucket label.

    Avoids real datetime parsing; we just hash to keep the index stable
    even when timestamp formats are inconsistent across sources.
    """
    raw = _str(timestamp)
    if not raw:
        return "unknown"
    digest = hashlib.blake2s(raw.encode("utf-8"), digest_size=4).hexdigest()
    return f"tb_{digest}"


def build_signal_cell(signal: Any) -> dict[str, Any]:
    """Map a single signal to a structured ``SignalCell``.

    The cell is a coarse, searchable index — not a prediction. Every cell
    carries the advisory safety stamps.
    """
    data = signal if isinstance(signal, dict) else {}
    source_type = _str(data.get("source_type") or data.get("source_family") or
                       data.get("source_name") or "unknown")
    jurisdiction = _str(data.get("jurisdiction") or "unknown").upper()
    geography = _str(data.get("geography") or "unknown").upper()
    sector = _str(data.get("sector") or "unknown").lower()
    raw_assets = data.get("asset_tags") or data.get("tickers") or data.get("ticker")
    if isinstance(raw_assets, str):
        asset_tags = [a.strip().upper() for a in raw_assets.split(",") if a.strip()]
    elif isinstance(raw_assets, (list, tuple, set)):
        asset_tags = [str(a).strip().upper() for a in raw_assets if str(a).strip()]
    else:
        asset_tags = []
    event_type = _str(data.get("event_type") or data.get("signal_type") or "unknown")
    time_bucket = _time_bucket(
        data.get("timestamp") or data.get("event_time") or data.get("occurred_at")
    )
    narrative_cluster = _str(data.get("narrative_cluster") or data.get("cluster_id")
                              or data.get("narrative_id") or "unclustered")
    freshness_state = _str(data.get("freshness_state"))
    if not freshness_state:
        freshness = _clamp(data.get("freshness_score"), 0.0, 1.0)
        if freshness >= 0.7:
            freshness_state = "fresh"
        elif freshness >= 0.3:
            freshness_state = "aging"
        elif freshness > 0:
            freshness_state = "stale"
        else:
            freshness_state = "unknown"
    chaos_score = round(_clamp(data.get("chaos_score")), 4)
    mvp_state = _str(data.get("mvp_state") or "candidate")
    cell_key = "|".join([
        source_type or "unknown",
        jurisdiction or "unknown",
        geography or "unknown",
        sector or "unknown",
        event_type or "unknown",
        narrative_cluster or "unclustered",
        time_bucket,
    ])
    return _stamp({
        "source_type": source_type,
        "jurisdiction": jurisdiction,
        "geography": geography,
        "sector": sector,
        "asset_tags": asset_tags,
        "event_type": event_type,
        "time_bucket": time_bucket,
        "narrative_cluster": narrative_cluster,
        "freshness_state": freshness_state,
        "chaos_score": chaos_score,
        "mvp_state": mvp_state,
        "cell_key": cell_key,
    })


# ---------------------------------------------------------------------------
# 2. Duplicate / Stale Pre-Veto (Bloom-style — PROBABILISTIC HINT ONLY).
# ---------------------------------------------------------------------------


def _signal_fingerprint(signal: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("event_id", "headline", "title", "narrative_cluster",
                "source_name", "thesis"):
        parts.append(_str(signal.get(key)).lower())
    parts.append(_str(signal.get("ticker") or signal.get("asset_tags") or "").lower())
    raw = "|".join(parts)
    return hashlib.blake2s(raw.encode("utf-8"), digest_size=8).hexdigest()


def classify_duplicate_stale_pre_veto(
    signal: Any,
    *,
    seen_fingerprints: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Cheap probabilistic hint for duplicate / stale narratives.

    Returns ``probably_seen`` or ``definitely_new``. **Never** treated as
    canonical: SQLite/Moltbook remain the only truth source. The hint is
    advisory; the caller must verify against the canonical store before
    promoting the signal.
    """
    data = signal if isinstance(signal, dict) else {}
    fingerprint = _signal_fingerprint(data)
    seen_set = set(seen_fingerprints or [])
    stale_flag = bool(data.get("stale_signal")) or _str(
        data.get("freshness_state")
    ).lower() == "stale"
    age_hours = _coerce_float(data.get("age_hours"))
    freshness = _clamp(data.get("freshness_score"), 0.0, 1.0)
    duplicate_hint = fingerprint in seen_set
    if duplicate_hint:
        verdict = "probably_seen"
    elif stale_flag or (age_hours and age_hours > 72) or freshness < 0.1:
        verdict = "probably_stale"
    else:
        verdict = "definitely_new"
    confidence = 0.6 if duplicate_hint else 0.3
    return _stamp({
        "signal_fingerprint": fingerprint,
        "duplicate_stale_verdict": verdict,
        "duplicate_hint": duplicate_hint,
        "stale_flag": bool(stale_flag),
        "age_hours": round(age_hours, 4),
        "freshness_score": round(freshness, 4),
        "confidence_in_hint": confidence,
        "canonical_source": "sqlite",
        "verification_required": True,
        "note": (
            "Probabilistic hint only. SQLite/Moltbook must confirm before "
            "promotion. Never canonical."
        ),
    })


# ---------------------------------------------------------------------------
# 3. Narrative Feature Extractor (CNN-style — but explicit deterministic).
# ---------------------------------------------------------------------------


def extract_narrative_features(signal: Any) -> dict[str, Any]:
    """Turn a raw signal into a deterministic feature vector.

    Every feature is in [0, 1]; missing inputs degrade safely to 0.
    ``feature_extraction_quality`` is the fraction of features that were
    derivable from real input — low quality must propagate downstream.
    """
    data = signal if isinstance(signal, dict) else {}
    features: dict[str, float] = {
        "source_reliability": _clamp(data.get("source_reliability") or
                                      data.get("reliability")),
        "freshness": _clamp(data.get("freshness_score")),
        "materiality": _clamp(data.get("materiality_score") or
                              data.get("evidence_strength")),
        "narrative_intensity": _clamp(data.get("narrative_intensity")),
        "jurisdiction_strength": _clamp(data.get("jurisdiction_strength") or
                                         data.get("regulatory_relevance")),
        "sector_linkage": _clamp(data.get("sector_linkage")),
        "asset_linkage": _clamp(data.get("asset_linkage")),
        "contradiction_score": _clamp(data.get("contradiction_score")),
        "liquidity_confirmation": _clamp(data.get("liquidity_confirmation") or
                                          data.get("market_confirmation")),
        "regulatory_relevance": _clamp(data.get("regulatory_relevance")),
        "earnings_filings_relevance": _clamp(data.get("earnings_filings_relevance")),
        "chaos_risk": _clamp(data.get("chaos_score") or data.get("chaos_risk")),
        "operator_heat": _clamp(data.get("operator_heat") or
                                 data.get("operator_heat_score")),
    }
    # quality = fraction of features that had a real, non-zero, non-default
    # input present. We don't penalise legitimate zeros (e.g. "no
    # contradiction"), but we do penalise blanket missing inputs.
    present_keys = ("source_reliability", "freshness_score", "reliability",
                    "narrative_intensity", "materiality_score",
                    "evidence_strength", "market_confirmation",
                    "liquidity_confirmation", "regulatory_relevance",
                    "chaos_score", "asset_linkage", "sector_linkage")
    present_count = sum(1 for k in present_keys if k in data and
                        data.get(k) is not None and not isinstance(data.get(k), bool))
    quality = _clamp(present_count / max(len(present_keys), 1))
    return _stamp({
        "features": features,
        "feature_extraction_quality": round(quality, 4),
        "feature_count": len(features),
        "raw_field_count_present": present_count,
    })


# ---------------------------------------------------------------------------
# 4. Decision BSP Tree (partition event-space before interpretation).
# ---------------------------------------------------------------------------


_PARTITION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "macro": ("macro", "cpi", "rate", "fed", "ecb", "rbi", "inflation",
              "gdp", "yield", "currency"),
    "micro_company": ("earnings", "guidance", "ceo", "downgrade", "upgrade",
                       "company", "ticker", "stock", "issuer"),
    "geopolitical": ("war", "sanction", "election", "geopolitical",
                      "treaty", "conflict", "tariff"),
    "regulatory": ("sec", "sebi", "regulator", "regulatory", "compliance",
                    "filing", "lawsuit", "fine", "enforce"),
    "earnings_filings": ("earnings", "filing", "10-q", "10-k", "8-k",
                          "edinet", "opendart", "annual_report"),
    "flow_market_structure": ("flow", "options", "gamma", "volume",
                               "liquidity", "order_book", "market_structure"),
    "prediction_market": ("polymarket", "kalshi", "prediction", "clob",
                           "manifold"),
    "ai_report": ("grok", "gemini", "deepseek", "mistral", "claude",
                   "ai_report", "ai_summary", "llm"),
    "on_chain": ("on_chain", "etherscan", "wallet", "tx_hash", "defi",
                  "blockscout", "evm"),
    "manual_trade_reconciliation": ("manual_trade", "reconciliation",
                                     "user_manual", "trade_log", "operator_log"),
}


def classify_decision_partition(signal: Any) -> dict[str, Any]:
    """Classify a signal into one of the BSP partitions.

    The partition is a hint, not a verdict. A signal can belong to
    multiple partitions; we return the dominant one plus the matches.
    """
    data = signal if isinstance(signal, dict) else {}
    explicit = _str(data.get("decision_partition") or data.get("partition"))
    if explicit in DECISION_PARTITIONS:
        return _stamp({
            "decision_partition": explicit,
            "matched_partitions": [explicit],
            "match_confidence": 0.9,
            "source": "explicit",
        })
    blob_parts: list[str] = []
    for key in ("headline", "title", "thesis", "notes", "event_type",
                "narrative_cluster", "signal_type", "source_name",
                "source_family", "source_type", "sector"):
        blob_parts.append(_str(data.get(key)).lower())
    blob = " ".join(blob_parts)
    matched: list[tuple[str, int]] = []
    for partition, keywords in _PARTITION_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in blob)
        if hits:
            matched.append((partition, hits))
    if not matched:
        return _stamp({
            "decision_partition": "unclassified",
            "matched_partitions": [],
            "match_confidence": 0.0,
            "source": "no_match",
        })
    matched.sort(key=lambda kv: kv[1], reverse=True)
    primary = matched[0][0]
    total_hits = sum(h for _, h in matched)
    confidence = _clamp(matched[0][1] / max(total_hits, 1))
    return _stamp({
        "decision_partition": primary,
        "matched_partitions": [p for p, _ in matched],
        "match_confidence": round(confidence, 4),
        "source": "keyword_match",
    })


# ---------------------------------------------------------------------------
# 5. Dijkstra Risk Router (lowest-risk advisory route).
# ---------------------------------------------------------------------------


_RISK_EDGES: tuple[str, ...] = (
    "source_uncertainty",
    "freshness_decay",
    "liquidity_risk",
    "leverage_risk",
    "contradiction_risk",
    "crowding_risk",
    "chaos_risk",
    "operator_heat",
    "invalidation_weakness",
    "missing_data_penalty",
)


def compute_risk_route(signal: Any, context: Any = None) -> dict[str, Any]:
    """Compute a lowest-risk advisory route as a sum of weighted edges.

    Edge costs live in [0, 1]. The total ``route_cost`` is the mean of
    present edges; missing edges are *added* as a separate
    ``missing_data_penalty`` so the result degrades safely toward
    ``WAIT`` / ``INSUFFICIENT_DATA`` rather than ``GO`` when inputs are
    sparse.
    """
    data = signal if isinstance(signal, dict) else {}
    ctx = context if isinstance(context, dict) else {}
    edges: dict[str, float] = {}
    edges["source_uncertainty"] = _clamp(
        1.0 - _clamp(data.get("source_reliability") or data.get("reliability"))
    )
    edges["freshness_decay"] = _clamp(1.0 - _clamp(data.get("freshness_score")))
    edges["liquidity_risk"] = _clamp(
        1.0 - _clamp(data.get("liquidity_score") or
                     data.get("liquidity_confirmation"))
    )
    edges["leverage_risk"] = _clamp(
        _coerce_float(data.get("leverage"), DEFAULT_LEVERAGE) /
        max(INDIA_LEVERAGE_CEILING, 1.0)
    )
    edges["contradiction_risk"] = _clamp(data.get("contradiction_score"))
    edges["crowding_risk"] = _clamp(data.get("crowding_score") or
                                     ctx.get("crowding_score"))
    edges["chaos_risk"] = _clamp(data.get("chaos_score") or
                                  data.get("chaos_risk") or
                                  ctx.get("chaos_score"))
    edges["operator_heat"] = _clamp(data.get("operator_heat") or
                                     data.get("operator_heat_score") or
                                     ctx.get("operator_heat"))
    edges["invalidation_weakness"] = _clamp(
        1.0 - _clamp(data.get("invalidation_strength") or
                     data.get("invalidation_level"))
    )
    # Missing-data penalty: count keys that were truly absent.
    expected_keys = ("source_reliability", "freshness_score", "liquidity_score",
                      "liquidity_confirmation", "contradiction_score",
                      "chaos_score", "invalidation_strength", "leverage")
    missing = sum(1 for k in expected_keys
                  if k not in data and k not in ctx)
    missing_penalty = _clamp(missing / max(len(expected_keys), 1))
    edges["missing_data_penalty"] = missing_penalty

    route_cost = _clamp(sum(edges.values()) / max(len(edges), 1))
    sorted_edges = sorted(edges.items(), key=lambda kv: kv[1], reverse=True)
    dominant = [name for name, cost in sorted_edges if cost >= 0.5]
    if route_cost <= 0.25 and missing_penalty < 0.4:
        decision = "review_candidate"
    elif route_cost <= 0.5 and missing_penalty < 0.5:
        decision = "watch"
    elif missing_penalty >= 0.5:
        decision = "wait_insufficient_data"
    else:
        decision = "decay_archive"
    return _stamp({
        "route_cost": round(route_cost, 4),
        "route_penalties": {k: round(v, 4) for k, v in edges.items()},
        "dominant_risks": dominant,
        "missing_data_penalty": round(missing_penalty, 4),
        "lowest_risk_route": decision,
        "advisory_decision": decision,
    })


# ---------------------------------------------------------------------------
# 6. Constrained-First Queue (Warnsdorf / Knight's Tour).
# ---------------------------------------------------------------------------


def compute_constrained_first_priority(signal: Any) -> dict[str, Any]:
    """Score how fragile a signal is. Higher = handle sooner."""
    data = signal if isinstance(signal, dict) else {}
    freshness = _clamp(data.get("freshness_score"))
    short_window = _clamp(1.0 - freshness)
    ambiguity = _clamp(data.get("contradiction_score") or
                        data.get("ambiguity_score"))
    chaos = _clamp(data.get("chaos_score") or data.get("chaos_risk"))
    exit_options = _clamp(data.get("exit_options_score") or
                           data.get("liquidity_confirmation"))
    few_exits_penalty = _clamp(1.0 - exit_options)
    leverage = _coerce_float(data.get("leverage"), DEFAULT_LEVERAGE)
    leverage_pressure = _clamp((leverage - 1.0) / max(INDIA_LEVERAGE_CEILING - 1.0, 0.1))
    stop_loss_breach = 1.0 if bool(data.get("stop_loss_breached")) else 0.0
    take_profit_breach = 1.0 if bool(data.get("take_profit_breached")) else 0.0
    reconciliation_mismatch = 1.0 if bool(data.get("reconciliation_mismatch")) else 0.0

    components = {
        "short_freshness_window": short_window,
        "ambiguity": ambiguity,
        "chaos_risk": chaos,
        "few_exits_penalty": few_exits_penalty,
        "leverage_pressure": leverage_pressure,
        "stop_loss_breach": stop_loss_breach,
        "take_profit_breach": take_profit_breach,
        "reconciliation_mismatch": reconciliation_mismatch,
    }
    priority = _clamp(sum(components.values()) / max(len(components), 1))
    if priority >= 0.7:
        bucket = "handle_now"
    elif priority >= 0.4:
        bucket = "handle_soon"
    else:
        bucket = "handle_later"
    return _stamp({
        "constrained_first_priority": round(priority, 4),
        "priority_bucket": bucket,
        "components": {k: round(v, 4) for k, v in components.items()},
    })


# ---------------------------------------------------------------------------
# 7. Invariant Ratio Monitor (Marion / Viviani-inspired balance check).
# ---------------------------------------------------------------------------


def compute_invariant_ratio(signal: Any) -> dict[str, Any]:
    """Check whether narrative / capital / risk-control are in balance."""
    data = signal if isinstance(signal, dict) else {}
    narrative = _clamp(data.get("narrative_intensity") or
                        data.get("narrative_strength"))
    capital = _clamp(data.get("liquidity_confirmation") or
                      data.get("capital_flow_strength") or
                      data.get("market_confirmation"))
    risk_control = _clamp(data.get("invalidation_strength") or
                           data.get("risk_control_strength"))
    leverage = _coerce_float(data.get("leverage"), DEFAULT_LEVERAGE)
    leverage_excess = _clamp((leverage - 1.0) / max(INDIA_LEVERAGE_CEILING - 1.0, 0.1))
    signal_mass = round(narrative + capital + risk_control, 4)
    flags: list[str] = []
    if narrative >= 0.5 and capital < 0.3:
        flags.append("narrative_without_capital")
    if capital >= 0.5 and narrative < 0.3:
        flags.append("capital_without_narrative")
    if (narrative + capital) >= 0.8 and risk_control < 0.3:
        flags.append("signal_without_risk_control")
    if leverage_excess >= 0.5 and risk_control < 0.3:
        flags.append("leverage_without_survival_quality")
    balance = 1.0 - (abs(narrative - capital) + abs(capital - risk_control)) / 2.0
    return _stamp({
        "signal_mass": signal_mass,
        "narrative_strength": round(narrative, 4),
        "capital_flow_strength": round(capital, 4),
        "risk_control_strength": round(risk_control, 4),
        "leverage_excess": round(leverage_excess, 4),
        "balance_score": round(_clamp(balance), 4),
        "invariant_flags": flags,
        "invariant_state": "balanced" if not flags else "imbalanced",
    })


# ---------------------------------------------------------------------------
# 8. Signal Derivative Engine (Taylor-series-inspired direction/curvature).
# ---------------------------------------------------------------------------


def compute_signal_derivatives(
    score_t: Any,
    *,
    score_t_minus_1: Any = None,
    score_t_minus_2: Any = None,
    forecast_horizon_hours: Any = None,
) -> dict[str, Any]:
    """Compute first/second-order signal derivatives from a tiny history."""
    s_t = _clamp(score_t)
    s_t1 = _clamp(score_t_minus_1) if score_t_minus_1 is not None else None
    s_t2 = _clamp(score_t_minus_2) if score_t_minus_2 is not None else None
    momentum = (s_t - s_t1) if s_t1 is not None else None
    curvature = None
    if s_t1 is not None and s_t2 is not None:
        curvature = (s_t - 2 * s_t1 + s_t2)
    horizon = _coerce_float(forecast_horizon_hours, 0.0)
    decay = math.exp(-horizon / 48.0) if horizon > 0 else 1.0
    chaos_acceleration = None
    if curvature is not None and momentum is not None:
        chaos_acceleration = round(abs(curvature) * (1.0 - decay), 4)
    return _stamp({
        "score_t": round(s_t, 4),
        "score_t_minus_1": (round(s_t1, 4) if s_t1 is not None else None),
        "score_t_minus_2": (round(s_t2, 4) if s_t2 is not None else None),
        "momentum": (round(momentum, 4) if momentum is not None else None),
        "curvature": (round(curvature, 4) if curvature is not None else None),
        "chaos_acceleration": chaos_acceleration,
        "forecast_horizon_hours": round(horizon, 4),
        "forecast_horizon_decay": round(decay, 4),
        "history_completeness": (
            1.0 if s_t2 is not None else
            0.66 if s_t1 is not None else
            0.33
        ),
    })


# ---------------------------------------------------------------------------
# 9. Narrative–Liquidity Phase Alignment (Lissajous-inspired).
# ---------------------------------------------------------------------------


def compute_phase_alignment_state(signal: Any) -> dict[str, Any]:
    """Classify narrative vs liquidity phase relationship."""
    data = signal if isinstance(signal, dict) else {}
    narrative = _clamp(data.get("narrative_intensity") or
                        data.get("narrative_strength"))
    liquidity = _clamp(data.get("liquidity_confirmation") or
                        data.get("capital_flow_strength") or
                        data.get("market_confirmation"))
    if narrative == 0.0 and liquidity == 0.0:
        state = "insufficient_data"
        gap = 0.0
    else:
        gap = abs(narrative - liquidity)
        if narrative < 0.05 and liquidity < 0.05:
            state = "insufficient_data"
        elif gap <= 0.15 and (narrative + liquidity) >= 0.6:
            state = "aligned_confirming"
        elif narrative - liquidity >= 0.3:
            state = "narrative_leads_capital"
        elif liquidity - narrative >= 0.3:
            state = "capital_leads_narrative"
        elif gap >= 0.5:
            state = "dangerous_desync"
        else:
            state = "out_of_phase"
    return _stamp({
        "narrative_phase": round(narrative, 4),
        "liquidity_phase": round(liquidity, 4),
        "phase_gap": round(gap, 4),
        "phase_alignment_state": state,
    })


# ---------------------------------------------------------------------------
# 10. Regime Composition Analytics (Riemann vs Lebesgue inspired).
# ---------------------------------------------------------------------------


def compute_regime_composition(cluster: Any) -> dict[str, Any]:
    """Summarise the intensity-state occupancy of a cluster."""
    rows = _as_cluster(cluster)
    if not rows:
        return _stamp({
            "signal_count": 0,
            "percent_durable": 0.0,
            "percent_noisy": 0.0,
            "percent_contradictory": 0.0,
            "percent_actionable": 0.0,
            "percent_stale": 0.0,
            "percent_diablo": 0.0,
            "percent_moltbook_feedback_value": 0.0,
            "regime_state": "insufficient_data",
        })
    n = len(rows)
    durable = noisy = contradictory = actionable = stale = diablo = moltbook = 0
    for r in rows:
        freshness = _clamp(r.get("freshness_score"))
        reliability = _clamp(r.get("source_reliability") or r.get("reliability"))
        contradiction = _clamp(r.get("contradiction_score"))
        chaos = _clamp(r.get("chaos_score"))
        moltbook_value = _clamp(r.get("moltbook_feedback_value"))
        if reliability >= 0.7 and freshness >= 0.5:
            durable += 1
        if reliability < 0.4 or _clamp(r.get("echo_risk_score")) >= 0.6:
            noisy += 1
        if contradiction >= 0.5:
            contradictory += 1
        if (reliability >= 0.6 and freshness >= 0.5 and contradiction < 0.4
                and chaos < 0.5):
            actionable += 1
        if freshness < 0.2 or _str(r.get("freshness_state")).lower() == "stale":
            stale += 1
        if chaos >= 0.7:
            diablo += 1
        if moltbook_value > 0:
            moltbook += 1
    pct = lambda c: round(c / n, 4) if n else 0.0
    regime_state = "mixed"
    if pct(stale) >= 0.5:
        regime_state = "stale_dominant"
    elif pct(diablo) >= 0.5:
        regime_state = "chaotic_dominant"
    elif pct(noisy) >= 0.5:
        regime_state = "noisy_dominant"
    elif pct(durable) >= 0.5:
        regime_state = "durable_dominant"
    return _stamp({
        "signal_count": n,
        "percent_durable": pct(durable),
        "percent_noisy": pct(noisy),
        "percent_contradictory": pct(contradictory),
        "percent_actionable": pct(actionable),
        "percent_stale": pct(stale),
        "percent_diablo": pct(diablo),
        "percent_moltbook_feedback_value": pct(moltbook),
        "regime_state": regime_state,
    })


# ---------------------------------------------------------------------------
# 11. Monte Carlo Trade Survival (deterministic stub — advisory only).
# ---------------------------------------------------------------------------


def monte_carlo_survival_stub(
    signal: Any,
    *,
    iterations: int = 256,
    drawdown_threshold: float = 0.10,
) -> dict[str, Any]:
    """Deterministic survival diagnostic stub.

    We do **not** seed a real PRNG — instead we use a hashed, deterministic
    pseudo-random walk derived from the signal's fingerprint. This means
    the output is reproducible and cannot be mistaken for a true MC trade
    sim; it is a *diagnostic stub* that surfaces shape, not certainty.
    Real MC simulation would require capital, executed prices, and
    survivorship-corrected backtest data — none of which the MVP has.
    """
    data = signal if isinstance(signal, dict) else {}
    n = max(int(_coerce_int(iterations, 256)), 1)
    # If we don't have enough signal context, return an explicit
    # INSUFFICIENT_DATA payload instead of pretending the deterministic
    # walk says anything meaningful.
    has_enough = any(
        k in data for k in (
            "evidence_strength", "materiality_score", "chaos_score",
            "chaos_risk", "leverage", "take_profit_pct", "stop_loss_pct",
        )
    )
    if not has_enough:
        return _stamp({
            "simulated_survival_probability": None,
            "probability_stop_loss_hit": None,
            "probability_take_profit_hit": None,
            "drawdown_breach_probability": None,
            "expected_feedback_value": None,
            "risk_of_ruin_flag": False,
            "iterations": 0,
            "is_real_monte_carlo": False,
            "method": "insufficient_data",
            "note": (
                "Insufficient signal context to run even the diagnostic stub."
            ),
        })
    fp = _signal_fingerprint(data)
    seed = int(fp[:8], 16)
    edge = _clamp(data.get("evidence_strength") or
                   data.get("materiality_score")) - 0.5
    vol = _clamp(data.get("chaos_score") or data.get("chaos_risk"), 0.0, 1.0) + 0.05
    leverage = _coerce_float(data.get("leverage"), DEFAULT_LEVERAGE)
    leverage = max(leverage, 0.0)
    survived = 0
    sl_hits = 0
    tp_hits = 0
    drawdown_breaches = 0
    pnl_samples: list[float] = []
    state = seed
    take_profit = float(data.get("take_profit_pct") or 0.15)
    stop_loss = float(data.get("stop_loss_pct") or 0.07)
    for _ in range(n):
        state = (state * 1103515245 + 12345) & 0x7fffffff
        # Map state to [-1, 1].
        u = (state / 0x7fffffff) * 2.0 - 1.0
        step = edge + u * vol
        pnl = step * leverage
        pnl_samples.append(pnl)
        if pnl <= -stop_loss * leverage:
            sl_hits += 1
        elif pnl >= take_profit * leverage:
            tp_hits += 1
        if pnl > -drawdown_threshold * leverage:
            survived += 1
        if pnl < -drawdown_threshold * leverage:
            drawdown_breaches += 1
    pnl_mean = sum(pnl_samples) / max(len(pnl_samples), 1)
    expected_feedback_value = round(pnl_mean, 4)
    survival_prob = round(survived / n, 4)
    sl_prob = round(sl_hits / n, 4)
    tp_prob = round(tp_hits / n, 4)
    dd_prob = round(drawdown_breaches / n, 4)
    risk_of_ruin = bool(survival_prob < 0.5 or dd_prob >= 0.3)
    return _stamp({
        "simulated_survival_probability": survival_prob,
        "probability_stop_loss_hit": sl_prob,
        "probability_take_profit_hit": tp_prob,
        "drawdown_breach_probability": dd_prob,
        "expected_feedback_value": expected_feedback_value,
        "risk_of_ruin_flag": risk_of_ruin,
        "iterations": n,
        "is_real_monte_carlo": False,
        "method": "deterministic_diagnostic_stub",
        "note": (
            "Diagnostic stub only. Not a real trade simulator. Advisory; "
            "must not be confused with executed PnL."
        ),
    })


# ---------------------------------------------------------------------------
# 12. Signal Field Diagnostics (vector calculus — gradient/div/curl).
# ---------------------------------------------------------------------------


def compute_field_diagnostics(cluster: Any) -> dict[str, Any]:
    """Compute gradient / divergence / curl proxies for a signal cluster."""
    rows = _as_cluster(cluster)
    if not rows:
        return _stamp({
            "gradient_score": 0.0,
            "divergence_score": 0.0,
            "curl_score": 0.0,
            "signal_count": 0,
            "field_interpretation": "insufficient_data",
        })
    intensities = [_clamp(r.get("intensity") or r.get("narrative_intensity"))
                   for r in rows]
    confirmations = [_clamp(r.get("market_confirmation") or
                             r.get("liquidity_confirmation"))
                     for r in rows]
    directions = [_direction(r.get("direction")) for r in rows]
    contradictions = [_clamp(r.get("contradiction_score")) for r in rows]
    # gradient: how much intensity is increasing toward the latest entries
    if len(intensities) >= 2:
        gradient = sum(intensities[-3:]) / min(len(intensities), 3) - \
                   sum(intensities[:3]) / min(len(intensities), 3)
    else:
        gradient = 0.0
    # divergence: spread of confirmations (high = capital spreading thin)
    if confirmations:
        mean_conf = sum(confirmations) / len(confirmations)
        divergence = sum(abs(c - mean_conf) for c in confirmations) / len(confirmations)
    else:
        divergence = 0.0
    # curl: contradiction + direction flips
    flips = sum(1 for a, b in zip(directions, directions[1:]) if a and b and a != b)
    flip_ratio = flips / max(len(directions) - 1, 1)
    mean_contradiction = (sum(contradictions) / len(contradictions)) if contradictions else 0.0
    curl = _clamp(0.5 * flip_ratio + 0.5 * mean_contradiction)
    gradient_score = _clamp(0.5 + gradient)  # shift to [0,1]
    divergence_score = _clamp(divergence * 2.0)
    interpretation = "balanced"
    if curl >= 0.6:
        interpretation = "contradiction_chaos_risk"
    elif divergence_score >= 0.6 and gradient_score < 0.4:
        interpretation = "attention_spreading_thinly"
    elif gradient_score >= 0.7 and divergence_score < 0.3:
        interpretation = "strengthening_concentrating"
    return _stamp({
        "gradient_score": round(gradient_score, 4),
        "divergence_score": round(divergence_score, 4),
        "curl_score": round(curl, 4),
        "direction_flip_ratio": round(flip_ratio, 4),
        "mean_contradiction": round(mean_contradiction, 4),
        "signal_count": len(rows),
        "field_interpretation": interpretation,
    })


# ---------------------------------------------------------------------------
# 13. Thermodynamic Exposure Layer.
# ---------------------------------------------------------------------------


def classify_thermodynamic_exposure(
    operator_state: Any,
    cluster: Any = None,
) -> dict[str, Any]:
    """Classify portfolio heat / exposure / pressure into a thermo mode."""
    op = operator_state if isinstance(operator_state, dict) else {}
    rows = _as_cluster(cluster)
    portfolio_heat = _clamp(op.get("portfolio_heat") or
                             op.get("operator_heat") or
                             op.get("operator_heat_score"))
    exposure_volume = _clamp(op.get("exposure_volume") or
                              op.get("net_exposure"))
    market_pressure = 0.0
    if rows:
        chaos_vals = [_clamp(r.get("chaos_score")) for r in rows]
        narrative_vals = [_clamp(r.get("narrative_intensity")) for r in rows]
        if chaos_vals:
            market_pressure = max(market_pressure,
                                   sum(chaos_vals) / len(chaos_vals))
        if narrative_vals:
            market_pressure = max(market_pressure,
                                   sum(narrative_vals) / len(narrative_vals))
    external_confirmation = 0.0
    if rows:
        confirmations = [_clamp(r.get("market_confirmation") or
                                 r.get("liquidity_confirmation"))
                         for r in rows]
        external_confirmation = (
            sum(confirmations) / len(confirmations) if confirmations else 0.0
        )
    if portfolio_heat == 0.0 and exposure_volume == 0.0 and not rows:
        mode = "insufficient_data"
        heat_dissipation_state = "unknown"
    elif external_confirmation < 0.2 and portfolio_heat >= 0.5:
        mode = "adiabatic"
        heat_dissipation_state = "trapped_dangerous"
    elif exposure_volume >= 0.6 and external_confirmation >= 0.5:
        mode = "isobaric"
        heat_dissipation_state = "expand_carefully"
    elif portfolio_heat >= 0.5 and exposure_volume <= 0.3:
        mode = "isothermal"
        heat_dissipation_state = "steady"
    elif exposure_volume >= 0.4 and market_pressure >= 0.6:
        mode = "isochoric"
        heat_dissipation_state = "no_expansion_allowed"
    else:
        mode = "isothermal"
        heat_dissipation_state = "steady"
    return _stamp({
        "portfolio_heat": round(portfolio_heat, 4),
        "exposure_volume": round(exposure_volume, 4),
        "market_pressure": round(market_pressure, 4),
        "external_confirmation": round(external_confirmation, 4),
        "heat_dissipation_state": heat_dissipation_state,
        "thermo_mode": mode,
    })


# ---------------------------------------------------------------------------
# 14. Hidden Macro Driver Detector.
# ---------------------------------------------------------------------------


def detect_hidden_macro_driver(cluster: Any) -> dict[str, Any]:
    """Look for shared macro driver in pairwise asset/sector links."""
    rows = _as_cluster(cluster)
    if len(rows) < 2:
        return _stamp({
            "pairwise_asset_links": [],
            "inferred_macro_driver": None,
            "driver_confidence": 0.0,
            "driver_contradictions": [],
        })
    pairs: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}
    jurisdiction_counts: dict[str, int] = {}
    contradictions: list[str] = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            assets_a = _str(a.get("ticker") or a.get("asset_tags") or "").upper()
            assets_b = _str(b.get("ticker") or b.get("asset_tags") or "").upper()
            if not assets_a or not assets_b:
                continue
            shared_sector = (_str(a.get("sector")).lower() ==
                              _str(b.get("sector")).lower() and
                              _str(a.get("sector")) != "")
            shared_jurisdiction = (_str(a.get("jurisdiction")).upper() ==
                                    _str(b.get("jurisdiction")).upper() and
                                    _str(a.get("jurisdiction")) != "")
            dir_a = _direction(a.get("direction"))
            dir_b = _direction(b.get("direction"))
            link_strength = 0.0
            if shared_sector:
                link_strength += 0.4
            if shared_jurisdiction:
                link_strength += 0.3
            if dir_a and dir_b and dir_a == dir_b:
                link_strength += 0.3
            elif dir_a and dir_b and dir_a != dir_b:
                contradictions.append(f"{assets_a}/{assets_b}_direction_split")
            if link_strength > 0:
                pairs.append({
                    "asset_a": assets_a,
                    "asset_b": assets_b,
                    "link_strength": round(_clamp(link_strength), 4),
                    "shared_sector": shared_sector,
                    "shared_jurisdiction": shared_jurisdiction,
                })
        sec = _str(a.get("sector")).lower()
        jur = _str(a.get("jurisdiction")).upper()
        if sec:
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
        if jur:
            jurisdiction_counts[jur] = jurisdiction_counts.get(jur, 0) + 1
    driver = None
    confidence = 0.0
    if sector_counts:
        sec, count = max(sector_counts.items(), key=lambda kv: kv[1])
        if count >= max(2, len(rows) // 2):
            driver = f"sector:{sec}"
            confidence = max(confidence, _clamp(count / len(rows)))
    if jurisdiction_counts:
        jur, count = max(jurisdiction_counts.items(), key=lambda kv: kv[1])
        if count >= max(2, len(rows) // 2):
            cand = f"jurisdiction:{jur}"
            cand_conf = _clamp(count / len(rows))
            if cand_conf > confidence:
                driver = cand
                confidence = cand_conf
    return _stamp({
        "pairwise_asset_links": pairs[:50],
        "inferred_macro_driver": driver,
        "driver_confidence": round(confidence, 4),
        "driver_contradictions": contradictions[:50],
    })


# ---------------------------------------------------------------------------
# 15. Recursive Moltbook Engine (advisory state — never auto-applied).
# ---------------------------------------------------------------------------


def summarize_moltbook_recursive_state(moltbook_state: Any) -> dict[str, Any]:
    """Compute recursive-feedback advisory state.

    Critically, this returns a *candidate* weight adjustment that is
    explicitly **not** auto-applied. The operator must approve any
    weight adjustment via the Moltbook review flow.
    """
    state = moltbook_state if isinstance(moltbook_state, dict) else {}
    validated_events = _coerce_int(state.get("validated_events_count"))
    feedback_value = _clamp(state.get("moltbook_feedback_value"))
    correction_applied = bool(state.get("correction_applied"))
    learning_radius = round(math.sqrt(max(validated_events, 0)), 4)
    # Candidate weight adjustment scales with feedback_value but is capped
    # and gated.
    weight_adjustment_candidate = round(
        _clamp(feedback_value * 0.1) if validated_events >= 5 else 0.0,
        4,
    )
    return _stamp({
        "validated_events_count": validated_events,
        "moltbook_feedback_value": round(feedback_value, 4),
        "correction_applied": correction_applied,
        "learning_radius": learning_radius,
        "recursive_weight_adjustment_candidate": weight_adjustment_candidate,
        "not_auto_applied_without_human_review": True,
    })


# ---------------------------------------------------------------------------
# 16. Noise Taxonomy Classifier.
# ---------------------------------------------------------------------------


def classify_noise_taxonomy(signal: Any) -> dict[str, Any]:
    """Classify the dominant noise type for a signal."""
    data = signal if isinstance(signal, dict) else {}
    echo_risk = _clamp(data.get("echo_risk_score"))
    repetition = _clamp(data.get("repetition_ratio"))
    chaos = _clamp(data.get("chaos_score") or data.get("chaos_risk"))
    freshness = _clamp(data.get("freshness_score"))
    contradiction = _clamp(data.get("contradiction_score"))
    source_family = _str(data.get("source_family") or
                          data.get("source_type")).lower()
    ai_source = source_family in {"ai_report", "ai", "llm", "grok", "gemini",
                                    "deepseek", "mistral", "claude"}
    # We only call "stale" when there's positive evidence (state or age),
    # not the mere absence of freshness data — empty input must not
    # automatically claim stale noise.
    is_stale = (_str(data.get("freshness_state")).lower() == "stale" or
                _coerce_float(data.get("age_hours")) > 24
                or (freshness > 0.0 and freshness < 0.2))
    classes_present: list[str] = []
    if chaos >= 0.7:
        classes_present.append("fat_tail_shock_risk")
    if contradiction >= 0.5 and chaos < 0.7:
        classes_present.append("oscillatory_cancellation")
    if is_stale:
        classes_present.append("stale_echo_noise")
    if ai_source and (echo_risk >= 0.4 or repetition >= 0.4):
        classes_present.append("ai_echo_noise")
    if echo_risk >= 0.5 or repetition >= 0.5:
        classes_present.append("source_repetition_noise")
    if not classes_present:
        classes_present.append("normal_noise")
    dominant = classes_present[0]
    return _stamp({
        "noise_classes_present": classes_present,
        "dominant_noise_class": dominant,
        "echo_risk": round(echo_risk, 4),
        "repetition_ratio": round(repetition, 4),
        "ai_source": ai_source,
    })


# ---------------------------------------------------------------------------
# 17. Chaos Attractor Detector (Lorenz/Aizawa inspired sensitivity).
# ---------------------------------------------------------------------------


def classify_chaos_attractor(signal: Any) -> dict[str, Any]:
    """Detect chaotic-regime sensitivity and forecast-horizon decay."""
    data = signal if isinstance(signal, dict) else {}
    sensitivity = _clamp(data.get("sensitivity_score") or
                          data.get("classification_flip_rate"))
    regime_instability = _clamp(data.get("regime_instability") or
                                  data.get("chaos_score"))
    chaos = _clamp(data.get("chaos_score") or data.get("chaos_risk"))
    # forecast decay: faster decay when sensitivity & chaos are high
    decay_rate = round(_clamp(0.5 * sensitivity + 0.5 * chaos), 4)
    # max safe horizon in hours: shrinks as decay grows
    max_horizon = round(48.0 * (1.0 - decay_rate), 2)
    flag = bool(decay_rate >= 0.6 or sensitivity >= 0.7)
    return _stamp({
        "sensitivity_score": round(sensitivity, 4),
        "regime_instability": round(regime_instability, 4),
        "forecast_decay_rate": decay_rate,
        "chaos_attractor_flag": flag,
        "max_safe_forecast_horizon_hours": max_horizon,
    })


# ---------------------------------------------------------------------------
# 18. Möbius Inversion Detector (crowding / false-confidence twist).
# ---------------------------------------------------------------------------


def classify_mobius_inversion(signal: Any) -> dict[str, Any]:
    """Detect risk/opportunity twist patterns.

    Heuristic-only. The point is to *flag* the possibility of inversion,
    not to predict price. Outputs feed risk-vetoes, never BUY recs.
    """
    data = signal if isinstance(signal, dict) else {}
    crowding = _clamp(data.get("crowding_score"))
    consensus = _clamp(data.get("ai_consensus_score") or
                        data.get("consensus_score"))
    narrative = _clamp(data.get("narrative_intensity"))
    confirmation = _clamp(data.get("market_confirmation") or
                           data.get("liquidity_confirmation"))
    contradiction = _clamp(data.get("contradiction_score"))
    direction = _direction(data.get("direction"))
    fragility = _clamp(data.get("fragility_score"))
    inversion_types: list[str] = []
    if direction > 0 and crowding >= 0.6 and fragility >= 0.5:
        inversion_types.append("bullish_crowded_fragile")
    if direction < 0 and confirmation < 0.3 and narrative >= 0.6:
        inversion_types.append("bearish_narrative_no_capital")
    if consensus >= 0.7 and contradiction >= 0.4:
        inversion_types.append("ai_consensus_echo_chamber")
    if narrative >= 0.7 and confirmation < 0.3:
        inversion_types.append("strong_narrative_false_confidence")
    crowding_penalty = round(_clamp(crowding * 0.6 + consensus * 0.4), 4)
    false_confidence_penalty = round(
        _clamp(narrative * 0.5 + consensus * 0.3 - confirmation * 0.4 + 0.4),
        4,
    )
    if inversion_types:
        risk_score = round(
            _clamp(0.5 * crowding_penalty + 0.5 * false_confidence_penalty),
            4,
        )
    else:
        risk_score = round(_clamp(0.3 * crowding_penalty +
                                   0.3 * false_confidence_penalty), 4)
    return _stamp({
        "mobius_inversion_risk": risk_score,
        "inversion_types": inversion_types,
        "crowding_penalty": crowding_penalty,
        "false_confidence_penalty": false_confidence_penalty,
        "advisory_only": True,
    })


# ---------------------------------------------------------------------------
# Leverage policy summary (India ceiling + ROW spot-only).
# ---------------------------------------------------------------------------


def summarize_leverage_policy(signal: Any) -> dict[str, Any]:
    """Return the leverage envelope applied to this signal.

    India: ceiling 4.0x (NOT a default). ROW: spot-only (ceiling 1.0).
    """
    data = signal if isinstance(signal, dict) else {}
    leverage_requested = _coerce_float(data.get("leverage"), DEFAULT_LEVERAGE)
    india = _is_india(data)
    ceiling = INDIA_LEVERAGE_CEILING if india else ROW_LEVERAGE_CEILING
    spot_only = not india
    within_ceiling = leverage_requested <= ceiling + 1e-9
    if not within_ceiling:
        capped_leverage = ceiling
        veto = True
        reason = "leverage_exceeds_ceiling"
    elif spot_only and leverage_requested > 1.0 + 1e-9:
        capped_leverage = 1.0
        veto = True
        reason = "row_spot_only"
    else:
        capped_leverage = leverage_requested
        veto = False
        reason = "within_policy"
    return _stamp({
        "india_market": india,
        "spot_only": spot_only,
        "leverage_ceiling": ceiling,
        "leverage_requested": round(leverage_requested, 4),
        "leverage_capped": round(capped_leverage, 4),
        "leverage_within_policy": bool(within_ceiling and
                                         not (spot_only and
                                              leverage_requested > 1.0 + 1e-9)),
        "leverage_veto": bool(veto),
        "leverage_policy_reason": reason,
        "leverage_is_default": not india,
    })


# ---------------------------------------------------------------------------
# Top-level orchestrator.
# ---------------------------------------------------------------------------


def build_signal_geometry_diagnostics(
    signal_or_cluster: Any,
    *,
    context: Any = None,
    operator_state: Any = None,
    moltbook_state: Any = None,
    leverage_hint: Any = None,
    seen_fingerprints: Iterable[str] | None = None,
    history: Any = None,
) -> dict[str, Any]:
    """Run every reflection diagnostic for one signal or cluster.

    All sub-components degrade safely on missing inputs. The orchestrator
    never raises; if a sub-component fails internally, it is recorded as
    an empty dict in the output rather than propagating.
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

    signal_cell = _safe(build_signal_cell, lead)
    pre_veto = _safe(classify_duplicate_stale_pre_veto, lead,
                     seen_fingerprints=seen_fingerprints)
    feature_extraction = _safe(extract_narrative_features, lead)
    decision_partition = _safe(classify_decision_partition, lead)
    risk_route = _safe(compute_risk_route, lead, ctx)
    constrained_priority = _safe(compute_constrained_first_priority, lead)
    invariant_ratio = _safe(compute_invariant_ratio, lead)
    derivatives = _safe(
        compute_signal_derivatives,
        history.get("score_t", lead.get("intensity") or lead.get("narrative_intensity") or 0.0),
        score_t_minus_1=history.get("score_t_minus_1"),
        score_t_minus_2=history.get("score_t_minus_2"),
        forecast_horizon_hours=history.get("forecast_horizon_hours"),
    )
    phase_alignment = _safe(compute_phase_alignment_state, lead)
    regime_composition = _safe(compute_regime_composition, cluster)
    monte_carlo = _safe(monte_carlo_survival_stub, lead)
    field_diagnostics = _safe(compute_field_diagnostics, cluster)
    thermodynamic = _safe(classify_thermodynamic_exposure, op_state, cluster)
    hidden_macro = _safe(detect_hidden_macro_driver, cluster)
    moltbook_recursive = _safe(summarize_moltbook_recursive_state, moltbook_state)
    noise = _safe(classify_noise_taxonomy, lead)
    chaos_attractor = _safe(classify_chaos_attractor, lead)
    mobius = _safe(classify_mobius_inversion, lead)
    leverage_policy = _safe(summarize_leverage_policy,
                            lead if leverage_hint is None else {**lead,
                                                                 "leverage": leverage_hint})

    # Roll-up recommendation. The orchestrator never returns BUY/SELL.
    # It returns one of the advisory recommendations only.
    vetoes: list[str] = []
    if risk_route.get("missing_data_penalty", 0.0) >= 0.5:
        vetoes.append("insufficient_data")
    if mobius.get("mobius_inversion_risk", 0.0) >= 0.6:
        vetoes.append("mobius_inversion_risk_high")
    if chaos_attractor.get("chaos_attractor_flag"):
        vetoes.append("chaos_attractor_active")
    if field_diagnostics.get("curl_score", 0.0) >= 0.6:
        vetoes.append("field_curl_high")
    if noise.get("dominant_noise_class") in {"ai_echo_noise",
                                                "source_repetition_noise",
                                                "stale_echo_noise"}:
        vetoes.append("dominant_noise_lowers_confidence")
    if pre_veto.get("duplicate_stale_verdict") == "probably_seen":
        vetoes.append("probable_duplicate")
    if monte_carlo.get("risk_of_ruin_flag"):
        vetoes.append("monte_carlo_risk_of_ruin")
    if leverage_policy.get("leverage_veto"):
        vetoes.append("leverage_policy_veto")
    if invariant_ratio.get("invariant_state") == "imbalanced":
        vetoes.append("invariant_imbalance")

    if not cluster:
        recommendation = "observe"
    elif "insufficient_data" in vetoes:
        recommendation = "wait_insufficient_data"
    elif vetoes:
        # Any active veto downgrades to no stronger than "watch"
        if monte_carlo.get("risk_of_ruin_flag") or "mobius_inversion_risk_high" in vetoes:
            recommendation = "decay_archive"
        else:
            recommendation = "watch"
    elif (risk_route.get("advisory_decision") == "review_candidate"
            and feature_extraction.get("feature_extraction_quality", 0.0) >= 0.5):
        recommendation = "review_candidate"
    else:
        recommendation = risk_route.get("advisory_decision", "observe")

    diagnostics = {
        "signal_cell_index": signal_cell,
        "duplicate_stale_pre_veto": pre_veto,
        "feature_extraction": feature_extraction,
        "decision_partition": decision_partition,
        "risk_route": risk_route,
        "constrained_first_priority": constrained_priority,
        "invariant_ratio": invariant_ratio,
        "signal_derivatives": derivatives,
        "phase_alignment": phase_alignment,
        "regime_composition": regime_composition,
        "monte_carlo_survival": monte_carlo,
        "field_diagnostics": field_diagnostics,
        "thermodynamic_exposure": thermodynamic,
        "hidden_macro_driver": hidden_macro,
        "moltbook_recursive_state": moltbook_recursive,
        "noise_taxonomy": noise,
        "chaos_attractor": chaos_attractor,
        "mobius_inversion": mobius,
        "leverage_policy": leverage_policy,
    }
    return _stamp({
        "signal_geometry_diagnostics": diagnostics,
        "signal_count": len(cluster),
        "vetoes": vetoes,
        "recommendation": recommendation,
        "operator_action": recommendation,
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
    "DECISION_PARTITIONS",
    "NOISE_CLASSES",
    "PHASE_STATES",
    "THERMO_MODES",
    "ADVISORY_RECOMMENDATIONS",
    "build_signal_cell",
    "classify_duplicate_stale_pre_veto",
    "extract_narrative_features",
    "classify_decision_partition",
    "compute_risk_route",
    "compute_constrained_first_priority",
    "compute_invariant_ratio",
    "compute_signal_derivatives",
    "compute_phase_alignment_state",
    "compute_regime_composition",
    "monte_carlo_survival_stub",
    "compute_field_diagnostics",
    "classify_thermodynamic_exposure",
    "detect_hidden_macro_driver",
    "summarize_moltbook_recursive_state",
    "classify_noise_taxonomy",
    "classify_chaos_attractor",
    "classify_mobius_inversion",
    "summarize_leverage_policy",
    "build_signal_geometry_diagnostics",
]
