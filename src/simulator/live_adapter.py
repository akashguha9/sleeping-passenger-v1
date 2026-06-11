"""Live signal adapter: ingestion outputs -> simulator inputs.

Pure, deterministic transforms from the shapes the existing ingestion
layer already produces (``scripts/persistence.py`` ``signal_events`` rows
whose ``raw_payload`` follows the Polymarket/Kalshi normalized market
shape, plus news/source clusters) into the payload sections the simulator
pipeline consumes. No network calls live here — tests run on fixtures, and
the refresh job can call these adapters on rows it already stores.

    prediction-market snapshot pair  -> "prediction_market" radar section
    clustered source mentions        -> "narrative" tracker section
    market snapshot                  -> "signals" tyre entries
    security metadata + theme graph  -> "exposure" / "circuit" sections
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.utils.math_utils import clamp01
from src.utils.validation_utils import coerce_float, normalized_score

# Liquidity normalization scale for prediction markets (matches the
# ingestion layer's 0–100k liquidity scale).
PREDICTION_MARKET_LIQUIDITY_SCALE = 100_000.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    """signal_events rows carry the market dict under raw_payload."""
    raw = event.get("raw_payload")
    return raw if isinstance(raw, dict) else dict(event)


def _hours_between(earlier: Any, later: Any) -> float:
    try:
        start = datetime.fromisoformat(str(earlier))
        end = datetime.fromisoformat(str(later))
    except (TypeError, ValueError):
        return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max((end - start).total_seconds() / 3600.0, 0.0)


def prediction_pair_to_radar_input(
    earlier_event: dict[str, Any],
    later_event: dict[str, Any],
    *,
    market_importance: float = 0.5,
    affected_themes: list[str] | None = None,
) -> dict[str, Any]:
    """Two snapshots of the same market -> narrative radar section.

    Velocity is the probability move per day, capped at 1.0 (a full move
    within a day is maximal urgency).
    """
    earlier = _payload(earlier_event)
    later = _payload(later_event)
    before = clamp01(coerce_float(earlier.get("implied_probability")))
    after = clamp01(coerce_float(later.get("implied_probability")))
    hours = _hours_between(earlier.get("fetched_at"), later.get("fetched_at"))
    move_per_day = abs(after - before) / max(hours / 24.0, 1e-9) if hours else 0.0
    velocity = clamp01(move_per_day)
    liquidity = clamp01(
        coerce_float(later.get("liquidity")) / PREDICTION_MARKET_LIQUIDITY_SCALE
    )
    confirmation = clamp01(coerce_float(later.get("cross_source_confirmation")))

    return {
        "market_name": str(
            later.get("question") or later.get("market_id") or "unnamed_market"
        ),
        "probability_before": before,
        "probability_after": after,
        "velocity": velocity,
        "market_importance": normalized_score(market_importance),
        "market_liquidity": liquidity,
        "cross_source_confirmation": confirmation,
        "affected_themes": list(affected_themes or []),
    }


def source_cluster_to_narrative_input(
    mentions: list[dict[str, Any]],
    *,
    narrative: str = "",
    velocity_window_mentions: int | None = None,
    previous_velocity: float = 0.0,
) -> dict[str, Any]:
    """A cluster of news/source mention rows -> narrative tracker section.

    Each mention row needs ``source`` (outlet/feed id) and optionally
    ``origin`` (the originating wire/author) and ``contradicts`` (bool).
    Origin diversity is counted from distinct origins, falling back to
    distinct sources — count origins, not echoes.
    """
    mention_count = len(mentions)
    sources = {str(m.get("source", "")).strip().lower() for m in mentions if m.get("source")}
    origins = {
        str(m.get("origin", "")).strip().lower() for m in mentions if m.get("origin")
    }
    independent = len(origins) if origins else len(sources)
    contradictions = sum(1 for m in mentions if bool(m.get("contradicts")))
    qualities = [
        normalized_score(m.get("source_credibility", 0.5)) for m in mentions
    ]
    source_quality = sum(qualities) / len(qualities) if qualities else 0.0

    recent = velocity_window_mentions
    velocity = (
        clamp01(recent / max(mention_count, 1)) if recent is not None else 0.0
    )

    return {
        "narrative": narrative
        or str(mentions[0].get("topic", "unnamed_narrative") if mentions else "unnamed_narrative"),
        "mention_count": mention_count,
        "origin_count": independent,
        "independent_origin_count": independent,
        "source_quality": source_quality,
        "narrative_velocity": velocity,
        "narrative_acceleration": velocity - clamp01(previous_velocity),
        "contradiction_count": contradictions,
    }


# Ingestion narrative_type / category labels -> simulator signal types.
_SIGNAL_TYPE_MAP: dict[str, str] = {
    "headline": "breaking_headline",
    "viral": "viral_article",
    "social": "social_spike",
    "earnings": "earnings_beat",
    "contract": "contract_win",
    "analyst": "analyst_revision",
    "filing": "backlog",
    "fundamental": "free_cash_flow",
    "turnaround": "early_turnaround",
    "discovery": "newspaper_discovery",
    "defensive": "defensive_balance_sheet",
}


def market_snapshot_to_signal_input(
    event: dict[str, Any],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """One stored market/news snapshot -> one tyre entry for the pipeline.

    Signal age comes from the payload's own fetched_at; detection lag from
    fetched_at -> as_of (now). Strength blends evidence density with
    primary-source weight — virality alone earns no strength here.
    """
    payload = _payload(event)
    now = as_of or datetime.now(timezone.utc).isoformat()
    age_hours = _hours_between(payload.get("fetched_at"), now)

    narrative_type = str(payload.get("narrative_type", "")).strip().lower()
    signal_type = _SIGNAL_TYPE_MAP.get(narrative_type, "social_spike")

    evidence = normalized_score(payload.get("evidence_density", 0.0))
    primary = normalized_score(payload.get("primary_source_weight", 0.0))
    raw_strength = clamp01(0.6 * evidence + 0.4 * primary) * 100.0

    return {
        "signal_type": signal_type,
        "raw_strength": raw_strength,
        "signal_age_hours": age_hours,
        "reaction_lag_hours": age_hours,  # detection == now for stored rows
        "source_quality": normalized_score(payload.get("source_credibility", 0.5)),
        "confirmation_multiplier": 0.8
        + 0.4 * normalized_score(payload.get("cross_source_confirmation", 0.0)),
    }


def security_metadata_to_circuit_input(metadata: dict[str, Any]) -> dict[str, Any]:
    """Security-master style metadata -> circuit classifier section."""
    return {
        "market_cap_usd": coerce_float(metadata.get("market_cap_usd")),
        "sector": str(metadata.get("sector", "")),
        "is_biotech_event_driven": bool(metadata.get("is_biotech_event_driven", False)),
        "annualized_volatility": coerce_float(metadata.get("annualized_volatility")),
        "policy_dependent": bool(metadata.get("policy_dependent", False)),
    }


def assemble_payload_from_ingestion(
    *,
    ticker: str,
    theme: str,
    market_events: list[dict[str, Any]],
    mention_cluster: list[dict[str, Any]] | None = None,
    security_metadata: dict[str, Any] | None = None,
    prediction_pair: tuple[dict[str, Any], dict[str, Any]] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Assemble a full simulator payload from stored ingestion artifacts.

    Sections the ingestion layer cannot supply (meal box, driver process
    scores, opportunity quality) are left absent on purpose: the simulator
    stays stingy and the human supplies their own thesis. ADVISORY_ONLY.
    """
    payload: dict[str, Any] = {
        "ticker": str(ticker),
        "theme": str(theme),
        "data_source": "ingestion_adapter",
        "signals": [
            market_snapshot_to_signal_input(e, as_of=as_of) for e in market_events
        ],
    }
    if prediction_pair is not None:
        payload["prediction_market"] = prediction_pair_to_radar_input(
            prediction_pair[0], prediction_pair[1], affected_themes=[str(theme)]
        )
    if mention_cluster:
        payload["narrative"] = source_cluster_to_narrative_input(
            mention_cluster, narrative=str(theme)
        )
    if security_metadata:
        payload["circuit"] = security_metadata_to_circuit_input(security_metadata)
    return payload
