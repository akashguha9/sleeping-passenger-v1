"""Additive signal-vocoder layer for narrative compression and market alignment.

This module does not replace the canonical diagnostics pipeline. It provides a
repo-native bridge from ETIL-normalized public signals to:
  1. explicit vocoder-style feature bands,
  2. a market-structure carrier layer,
  3. artist-mode interpretation scores,
  4. a compressed decision-ready output schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence

try:
    from scripts.external_tool_integration_layer import (
        ETILSignal,
        etil_to_snc_input,
        normalise_tool_output,
        resolve_tool_name,
    )
    from scripts.pendentive_engine import (
        pe_full_pipeline,
        pe_prediction_market,
        pe_price_action,
    )
    from scripts.runtime_common import policy_state_score
    from scripts.runtime_common import (
        SIGNAL_VOCODER_ETIL_INPUT_PATH,
        SIGNAL_VOCODER_REPORT_PATH,
        load_json_file,
        load_open_positions,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from external_tool_integration_layer import (
        ETILSignal,
        etil_to_snc_input,
        normalise_tool_output,
        resolve_tool_name,
    )
    from pendentive_engine import (
        pe_full_pipeline,
        pe_prediction_market,
        pe_price_action,
    )
    from runtime_common import policy_state_score
    from runtime_common import (
        SIGNAL_VOCODER_ETIL_INPUT_PATH,
        SIGNAL_VOCODER_REPORT_PATH,
        load_json_file,
        load_open_positions,
        write_json_atomic,
    )


TEXT_FIELDS = ("text", "title", "summary", "question")
ENTITY_FIELDS = ("ticker", "symbol", "topic", "market_id", "condition_id")
PROBABILITY_FIELDS = ("yes_price", "probability", "implied_probability", "baseline_probability")
PROBABILITY_DELTA_FIELDS = (
    "probability_change",
    "delta_probability",
    "delta_odds_7d",
    "b_change",
)
PRICE_CHANGE_FIELDS = ("price_change_pct", "price_return_pct", "price_velocity_pct")
VOLUME_FIELDS = ("volume_ratio", "volume", "engagement", "score", "num_comments")
VOLATILITY_FIELDS = ("volatility", "volatility_ratio", "implied_volatility")
EVENT_TIME_FIELDS = ("event_time", "close_time", "end_date", "publish_date", "published")
SENTIMENT_LABEL_MAP = {"positive": 0.75, "negative": -0.75, "neutral": 0.0}

POSITIVE_TERMS = {
    "beat", "beats", "rebound", "upgrade", "upside", "support", "strength",
    "bullish", "approval", "recover", "surge", "win",
}
NEGATIVE_TERMS = {
    "panic", "selloff", "crash", "downgrade", "miss", "fraud", "scandal",
    "collapse", "fear", "warning", "loss", "fall",
}
NARRATIVE_PATTERNS = {
    "hype": {"moon", "parabolic", "unstoppable", "massive", "explosive"},
    "panic": {"panic", "capitulation", "bloodbath", "fear", "collapse"},
    "reversal": {"reversal", "flip", "turnaround", "mean reversion"},
    "inevitability": {"inevitable", "certain", "locked", "guaranteed"},
    "comeback": {"comeback", "rebound", "recovery", "bounce"},
    "scandal": {"scandal", "fraud", "probe", "lawsuit", "investigation"},
    "trap": {"trap", "bull trap", "bear trap", "fakeout"},
    "squeeze": {"squeeze", "short squeeze", "gamma squeeze"},
    "exhaustion": {"exhaustion", "overbought", "blowoff", "spent"},
}
POSITIVE_PATTERNS = {"inevitability", "comeback", "squeeze"}
NEGATIVE_PATTERNS = {"panic", "scandal", "trap", "exhaustion"}
SIGNAL_VOCODER_SCHEMA_VERSION = "v1"
CORE_BAND_SEQUENCE = (
    "sentiment",
    "velocity",
    "divergence",
    "entity",
    "confidence",
    "timing",
    "narrative_structure",
)
ARTIST_MODE_SEQUENCE = (
    "DAFT_PUNK",
    "HBFS",
    "TAME_IMPALA",
    "KANYE",
    "TRAVIS",
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _weighted_average(pairs: Sequence[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in pairs if weight > 0)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in pairs if weight > 0) / total_weight


def _to_plain_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": str(signal.get("source") or "").strip().lower(),
        "signal_type": str(signal.get("signal_type") or "").strip().upper(),
        "content": dict(signal.get("content") or {}),
        "reliability_prior": _safe_float(signal.get("reliability_prior")) or 0.0,
        "timestamp": str(signal.get("timestamp") or ""),
        "freshness_remaining": _safe_float(signal.get("freshness_remaining")) or 1.0,
        "raw_output": signal.get("raw_output"),
    }


def _normalise_etil_signal(
    signal: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    if not isinstance(signal, Mapping):
        return None

    source_value = signal.get("source")
    if source_value is None:
        return None

    try:
        source = resolve_tool_name(str(source_value))
    except ValueError:
        return None

    content = signal.get("content") if isinstance(signal.get("content"), Mapping) else {}
    timestamp = str(signal.get("timestamp") or now.isoformat())
    raw_output = signal.get("raw_output")
    template = normalise_tool_output(
        source,
        dict(raw_output) if isinstance(raw_output, Mapping) else dict(content),
        timestamp=timestamp,
    )
    plain = _to_plain_signal(template)
    reliability_prior = _safe_float(signal.get("reliability_prior"))
    freshness_remaining = _safe_float(signal.get("freshness_remaining"))
    signal_type = str(signal.get("signal_type") or plain["signal_type"]).strip().upper()

    plain["content"] = dict(content) if content else dict(plain["content"])
    plain["signal_type"] = signal_type or plain["signal_type"]
    plain["reliability_prior"] = (
        reliability_prior if reliability_prior is not None else plain["reliability_prior"]
    )
    plain["freshness_remaining"] = (
        freshness_remaining if freshness_remaining is not None else plain["freshness_remaining"]
    )
    plain["timestamp"] = timestamp
    plain["raw_output"] = raw_output if raw_output is not None else signal.get("content")
    return plain


def normalise_vocoder_etil_signals(
    etil_signals: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    resolved_now = now or datetime.now(timezone.utc)
    signals: list[dict[str, Any]] = []
    for signal in etil_signals:
        normalised = _normalise_etil_signal(signal, now=resolved_now)
        if normalised is not None:
            signals.append(normalised)
    return signals


def normalise_vocoder_inputs(
    tool_payloads: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    resolved_now = now or datetime.now(timezone.utc)
    signals: list[dict[str, Any]] = []
    for payload in tool_payloads:
        tool_name = str(payload.get("tool") or payload.get("source") or "").strip()
        raw_output = payload.get("raw_output") or payload.get("content") or {}
        timestamp = payload.get("timestamp") or resolved_now.isoformat()
        normalised = normalise_tool_output(tool_name, raw_output, timestamp=timestamp)
        signals.append(_to_plain_signal(normalised))
    return signals


def load_runtime_vocoder_etil_signals(
    *,
    path=None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    payload = load_json_file(path or SIGNAL_VOCODER_ETIL_INPUT_PATH, default=[])
    if not isinstance(payload, list):
        return []
    return normalise_vocoder_etil_signals(payload, now=now)


def _canonical_signals(
    signals: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    resolved_now = now or datetime.now(timezone.utc)
    canonical: list[dict[str, Any]] = []
    for signal in signals:
        plain = _to_plain_signal(signal)
        timestamp = _parse_datetime(plain["timestamp"]) or resolved_now
        hours_elapsed = max(0.0, (resolved_now - timestamp).total_seconds() / 3600.0)
        snc_ready = etil_to_snc_input(plain, hours_elapsed=hours_elapsed)
        plain["effective_reliability"] = _safe_float(snc_ready.get("effective_reliability")) or 0.0
        plain["freshness"] = _safe_float(snc_ready.get("freshness")) or plain["freshness_remaining"]
        plain["ready_for_snc"] = bool(snc_ready.get("ready_for_snc"))
        plain["timestamp"] = timestamp.isoformat()
        canonical.append(plain)
    return canonical


def _signal_texts(signal: Mapping[str, Any]) -> list[str]:
    content = signal.get("content") or {}
    texts: list[str] = []
    for field in TEXT_FIELDS:
        value = content.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            texts.append(text)
    return texts


def _text_sentiment_score(text: str) -> float:
    lowered = text.lower()
    positive_hits = sum(1 for word in POSITIVE_TERMS if word in lowered)
    negative_hits = sum(1 for word in NEGATIVE_TERMS if word in lowered)
    total_hits = positive_hits + negative_hits
    if total_hits == 0:
        return 0.0
    return (positive_hits - negative_hits) / total_hits


def _signal_sentiment(signal: Mapping[str, Any]) -> float:
    content = signal.get("content") or {}
    explicit = _safe_float(content.get("sentiment"))
    if explicit is None:
        label = str(content.get("label") or "").strip().lower()
        explicit = SENTIMENT_LABEL_MAP.get(label)
    text_scores = [_text_sentiment_score(text) for text in _signal_texts(signal)]
    candidates = [score for score in [explicit, *text_scores] if score is not None]
    return _average(candidates)


def _extract_probability_from_outcomes(value: Any) -> float | None:
    if isinstance(value, dict):
        for key in ("yes", "YES", "Yes", "probability", "prob"):
            if key in value:
                return _safe_float(value.get(key))
        numeric_values = [_safe_float(item) for item in value.values()]
        numeric_values = [item for item in numeric_values if item is not None]
        return _average(numeric_values) if numeric_values else None
    if isinstance(value, list):
        numeric_values = [_safe_float(item) for item in value]
        numeric_values = [item for item in numeric_values if item is not None]
        return _average(numeric_values) if numeric_values else None
    return None


def _signal_probability(signal: Mapping[str, Any]) -> float | None:
    content = signal.get("content") or {}
    for field in PROBABILITY_FIELDS:
        value = _safe_float(content.get(field))
        if value is not None:
            return _clamp(value)
    return _extract_probability_from_outcomes(content.get("outcome_prices"))


def _signal_probability_delta(signal: Mapping[str, Any]) -> float:
    content = signal.get("content") or {}
    for field in PROBABILITY_DELTA_FIELDS:
        value = _safe_float(content.get(field))
        if value is not None:
            return value
    probability = _signal_probability(signal)
    baseline = _safe_float((signal.get("content") or {}).get("baseline_probability"))
    if probability is not None and baseline is not None:
        return probability - baseline
    return 0.0


def _signal_price_change(signal: Mapping[str, Any]) -> float:
    content = signal.get("content") or {}
    for field in PRICE_CHANGE_FIELDS:
        value = _safe_float(content.get(field))
        if value is not None:
            return value
    velocity_z = _safe_float(content.get("velocity_z"))
    if velocity_z is not None:
        return velocity_z / 5.0
    return 0.0


def _signal_volume(signal: Mapping[str, Any]) -> float:
    content = signal.get("content") or {}
    if _safe_float(content.get("volume_ratio")) is not None:
        return _clamp(_safe_float(content.get("volume_ratio")) or 0.0)
    volume = _safe_float(content.get("volume")) or 0.0
    engagement = _safe_float(content.get("engagement")) or 0.0
    score = _safe_float(content.get("score")) or 0.0
    comments = _safe_float(content.get("num_comments")) or 0.0
    composite = max(volume / 10000.0, engagement / 10000.0, score / 1000.0, comments / 500.0)
    return _clamp(composite)


def _signal_volatility(signal: Mapping[str, Any]) -> float:
    content = signal.get("content") or {}
    for field in VOLATILITY_FIELDS:
        value = _safe_float(content.get(field))
        if value is not None:
            return _clamp(value if value <= 1.0 else value / 100.0)
    return 0.0


def _signal_event_time(signal: Mapping[str, Any]) -> datetime | None:
    content = signal.get("content") or {}
    for field in EVENT_TIME_FIELDS:
        parsed = _parse_datetime(content.get(field))
        if parsed is not None:
            return parsed
    return _parse_datetime(signal.get("timestamp"))


def _signal_entities(signal: Mapping[str, Any]) -> list[str]:
    content = signal.get("content") or {}
    entities: list[str] = []
    for field in ENTITY_FIELDS:
        value = content.get(field)
        if value is None:
            continue
        text = str(value).strip().upper()
        if text and text not in entities:
            entities.append(text)
    for text in _signal_texts(signal):
        for match in re.findall(r"\$?[A-Z]{2,5}", text):
            cleaned = match.replace("$", "")
            if cleaned not in entities and cleaned not in {"HTTP", "HTTPS"}:
                entities.append(cleaned)
    return entities


def _signal_direction(signal: Mapping[str, Any]) -> float:
    sentiment = _signal_sentiment(signal)
    probability = _signal_probability(signal)
    price_change = _signal_price_change(signal)
    if abs(sentiment) > 0.05:
        return _clamp(sentiment, -1.0, 1.0)
    if probability is not None:
        return _clamp((probability - 0.5) * 2.0, -1.0, 1.0)
    if price_change != 0:
        return _clamp(price_change, -1.0, 1.0)
    return 0.0


@dataclass(frozen=True)
class VocoderBand:
    band: str
    magnitude: float
    bias: float
    confidence: float
    dominant_label: str
    source_count: int
    components: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CarrierState:
    symbol: str
    anchor_probability: float | None
    probability_delta: float
    price_change_pct: float
    volume_ratio: float
    volatility: float
    event_hours_to_resolution: float | None
    policy_state: str
    active_blockers: list[str]
    scm_state: str
    execution_readiness: float | None
    carrier_score: float
    anchor_bias: float
    blocker_pressure: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModeScore:
    mode: str
    score: float
    rationale: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompressedSignal:
    schema_version: str
    generated_at: str
    entity_id: str
    source_summary: dict[str, Any]
    carrier: CarrierState
    bands: dict[str, VocoderBand]
    mode_scores: list[ModeScore]
    dominant_mode: str
    compressed_bias: float
    compressed_conviction: float
    directional_bias: str
    signal_grade: str
    deployment_posture: str
    decision_signal: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["carrier"] = self.carrier.to_dict()
        payload["bands"] = {name: band.to_dict() for name, band in self.bands.items()}
        payload["mode_scores"] = [item.to_dict() for item in self.mode_scores]
        return payload


def _weighted_signal_metrics(
    signals: Sequence[Mapping[str, Any]],
) -> tuple[list[tuple[dict[str, Any], float]], float]:
    weighted = []
    for signal in signals:
        weight = _safe_float(signal.get("effective_reliability")) or _safe_float(signal.get("reliability_prior")) or 0.0
        if weight <= 0:
            continue
        weighted.append((dict(signal), weight))
    total_weight = sum(weight for _, weight in weighted)
    return weighted, total_weight


def extract_band(
    band_name: str,
    signals: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    carrier: CarrierState | None = None,
) -> VocoderBand:
    resolved_band = str(band_name or "").strip().lower()
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_band == "sentiment":
        return extract_sentiment_band(signals)
    if resolved_band == "velocity":
        return extract_velocity_band(signals, now=resolved_now)
    if resolved_band == "divergence":
        return extract_divergence_band(signals)
    if resolved_band == "entity":
        return extract_entity_band(signals)
    if resolved_band == "confidence":
        return extract_confidence_band(signals)
    if resolved_band == "timing":
        return extract_timing_band(signals, now=resolved_now)
    if resolved_band == "narrative_structure":
        return extract_narrative_structure_band(signals)
    if resolved_band == "market_translation":
        if carrier is None:
            raise ValueError("carrier is required to extract the market_translation band")
        dependency_bands = {
            "sentiment": extract_sentiment_band(signals),
            "confidence": extract_confidence_band(signals),
            "timing": extract_timing_band(signals, now=resolved_now),
            "narrative_structure": extract_narrative_structure_band(signals),
        }
        return extract_market_translation_band(dependency_bands, carrier)
    raise ValueError(f"Unknown vocoder band: {band_name}")


def extract_sentiment_band(signals: Sequence[Mapping[str, Any]]) -> VocoderBand:
    weighted, _ = _weighted_signal_metrics(signals)
    sentiment_pairs = [(_signal_sentiment(signal), weight) for signal, weight in weighted]
    bias = _clamp(_weighted_average(sentiment_pairs), -1.0, 1.0)
    avg_abs = _average([abs(score) for score, _ in sentiment_pairs])
    crowd_emotion = _average([_signal_volume(signal) * abs(_signal_sentiment(signal)) for signal, _ in weighted])
    magnitude = _clamp((avg_abs * 0.5) + (abs(bias) * 0.3) + (crowd_emotion * 0.2))
    confidence = _clamp(_average([weight for _, weight in weighted]))
    label = "positive" if bias > 0.15 else "negative" if bias < -0.15 else "neutral"
    return VocoderBand(
        band="sentiment",
        magnitude=round(magnitude, 3),
        bias=round(bias, 3),
        confidence=round(confidence, 3),
        dominant_label=label,
        source_count=len(weighted),
        components={
            "polarity": round(bias, 3),
            "intensity": round(avg_abs, 3),
            "asymmetry": round(abs(bias), 3),
            "crowd_emotion": round(_clamp(crowd_emotion), 3),
        },
    )


def extract_velocity_band(signals: Sequence[Mapping[str, Any]], *, now: datetime) -> VocoderBand:
    weighted, _ = _weighted_signal_metrics(signals)
    timestamps = [_parse_datetime(signal.get("timestamp")) for signal, _ in weighted]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    ages_hours = [max(0.0, (now - timestamp).total_seconds() / 3600.0) for timestamp in timestamps]
    recent_count = sum(1 for age in ages_hours if age <= 6)
    prior_count = sum(1 for age in ages_hours if 6 < age <= 24)
    mention_rate = _clamp(len(weighted) / 6.0)
    acceleration = 0.0 if not weighted else (recent_count - prior_count) / max(len(weighted), 1)
    burstiness = _clamp(recent_count / max(len(weighted), 1))
    persistence = 0.0
    if len(timestamps) >= 2:
        window_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0
        persistence = _clamp(window_hours / 72.0)
    avg_direction = _weighted_average([(_signal_direction(signal), weight) for signal, weight in weighted])
    magnitude = _clamp((mention_rate * 0.35) + (abs(acceleration) * 0.25) + (burstiness * 0.2) + (persistence * 0.2))
    label = "burst" if burstiness > persistence + 0.1 else "persistent" if persistence > burstiness + 0.1 else "balanced"
    return VocoderBand(
        band="velocity",
        magnitude=round(magnitude, 3),
        bias=round(_clamp(avg_direction, -1.0, 1.0), 3),
        confidence=round(_clamp(_average([weight for _, weight in weighted])), 3),
        dominant_label=label,
        source_count=len(weighted),
        components={
            "mention_rate": round(mention_rate, 3),
            "acceleration": round(_clamp((acceleration + 1.0) / 2.0), 3),
            "burstiness": round(burstiness, 3),
            "persistence": round(persistence, 3),
        },
    )


def extract_divergence_band(signals: Sequence[Mapping[str, Any]]) -> VocoderBand:
    weighted, _ = _weighted_signal_metrics(signals)
    directions = [_signal_direction(signal) for signal, _ in weighted]
    if not directions:
        disagreement = 0.0
        consensus = 0.0
    else:
        avg_direction = _weighted_average([(direction, weight) for direction, (_, weight) in zip(directions, weighted)])
        consensus = abs(avg_direction)
        disagreement = _clamp(_average([abs(direction - avg_direction) for direction in directions]))
    fragmentation = _clamp((disagreement + (1.0 - consensus)) / 2.0)
    label = "fragmented" if fragmentation > 0.55 else "consensus" if consensus > 0.55 else "mixed"
    return VocoderBand(
        band="divergence",
        magnitude=round(max(disagreement, fragmentation), 3),
        bias=round(_clamp(consensus - fragmentation, -1.0, 1.0), 3),
        confidence=round(_clamp(_average([weight for _, weight in weighted])), 3),
        dominant_label=label,
        source_count=len(weighted),
        components={
            "source_disagreement": round(disagreement, 3),
            "consensus": round(consensus, 3),
            "fragmentation": round(fragmentation, 3),
        },
    )


def extract_entity_band(signals: Sequence[Mapping[str, Any]]) -> VocoderBand:
    weighted, _ = _weighted_signal_metrics(signals)
    entity_counts: dict[str, float] = {}
    for signal, weight in weighted:
        for entity in _signal_entities(signal):
            entity_counts[entity] = entity_counts.get(entity, 0.0) + weight
    if not entity_counts:
        return VocoderBand(
            band="entity",
            magnitude=0.0,
            bias=0.0,
            confidence=0.0,
            dominant_label="broad",
            source_count=0,
            components={"focus": 0.0, "entity_count": 0.0},
        )
    dominant_entity, dominant_weight = max(entity_counts.items(), key=lambda item: (item[1], item[0]))
    total_weight = sum(entity_counts.values())
    focus = dominant_weight / total_weight if total_weight > 0 else 0.0
    return VocoderBand(
        band="entity",
        magnitude=round(_clamp(focus), 3),
        bias=0.0,
        confidence=round(_clamp(dominant_weight / max(len(weighted), 1)), 3),
        dominant_label=dominant_entity,
        source_count=len(weighted),
        components={
            "focus": round(_clamp(focus), 3),
            "entity_count": round(float(len(entity_counts)), 3),
        },
    )


def extract_confidence_band(signals: Sequence[Mapping[str, Any]]) -> VocoderBand:
    weighted, _ = _weighted_signal_metrics(signals)
    distinct_sources = len({signal.get("source") for signal, _ in weighted})
    directions = [_signal_direction(signal) for signal, _ in weighted]
    agreement = abs(_weighted_average([(direction, weight) for direction, (_, weight) in zip(directions, weighted)]))
    source_credibility = _clamp(_average([weight for _, weight in weighted]))
    cross_source_confirmation = _clamp((distinct_sources / 4.0) * agreement)
    substantiated = 0
    for signal, _ in weighted:
        content = signal.get("content") or {}
        if (
            _signal_probability(signal) is not None
            or _safe_float(content.get("price")) is not None
            or any(content.get(field) for field in ("link", "source_url"))
        ):
            substantiated += 1
    substantiation = _clamp(substantiated / max(len(weighted), 1))
    noise = _clamp(1.0 - substantiation)
    magnitude = _clamp((source_credibility * 0.4) + (cross_source_confirmation * 0.4) + (substantiation * 0.2))
    label = "high_confidence" if magnitude >= 0.65 else "moderate_confidence" if magnitude >= 0.4 else "low_confidence"
    return VocoderBand(
        band="confidence",
        magnitude=round(magnitude, 3),
        bias=round(_clamp(cross_source_confirmation - noise, -1.0, 1.0), 3),
        confidence=round(source_credibility, 3),
        dominant_label=label,
        source_count=len(weighted),
        components={
            "source_credibility": round(source_credibility, 3),
            "cross_source_confirmation": round(cross_source_confirmation, 3),
            "noise_vs_substantiation": round(_clamp(substantiation - noise, -1.0, 1.0), 3),
        },
    )


def extract_timing_band(signals: Sequence[Mapping[str, Any]], *, now: datetime) -> VocoderBand:
    weighted, _ = _weighted_signal_metrics(signals)
    timestamps = [_parse_datetime(signal.get("timestamp")) for signal, _ in weighted]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    event_times = [_signal_event_time(signal) for signal, _ in weighted]
    event_times = [timestamp for timestamp in event_times if timestamp is not None]
    ages = [max(0.0, (now - timestamp).total_seconds() / 3600.0) for timestamp in timestamps]
    avg_age = _average(ages)
    freshness = _clamp(1.0 - (avg_age / 72.0))
    lag = _clamp(avg_age / 48.0)
    if event_times:
        future_offsets = sorted((event_time - now).total_seconds() / 3600.0 for event_time in event_times)
        event_hours = future_offsets[0]
    else:
        event_hours = None
    if event_hours is None:
        phase = "live" if freshness >= 0.5 else "lagged"
        phase_bias = 0.1 if freshness >= 0.5 else -0.4
    elif event_hours > 6:
        phase = "pre_event"
        phase_bias = 0.6
    elif event_hours >= -6:
        phase = "in_event"
        phase_bias = 0.3
    else:
        phase = "post_event"
        phase_bias = -0.3
    second_order = 1.0 if phase == "post_event" and freshness >= 0.5 else 0.0
    persistence = 0.0
    if len(timestamps) >= 2:
        persistence = _clamp((max(timestamps) - min(timestamps)).total_seconds() / 3600.0 / 72.0)
    magnitude = _clamp((freshness * 0.4) + ((1.0 - lag) * 0.35) + ((1.0 if phase in {"pre_event", "in_event"} else 0.4) * 0.25))
    return VocoderBand(
        band="timing",
        magnitude=round(magnitude, 3),
        bias=round(_clamp(phase_bias, -1.0, 1.0), 3),
        confidence=round(_clamp(_average([weight for _, weight in weighted])), 3),
        dominant_label=phase,
        source_count=len(weighted),
        components={
            "pre_event": round(1.0 if phase == "pre_event" else 0.0, 3),
            "in_event": round(1.0 if phase == "in_event" else 0.0, 3),
            "post_event": round(1.0 if phase == "post_event" else 0.0, 3),
            "lag": round(lag, 3),
            "second_order": round(second_order, 3),
        },
    )


def extract_narrative_structure_band(signals: Sequence[Mapping[str, Any]]) -> VocoderBand:
    weighted, _ = _weighted_signal_metrics(signals)
    pattern_scores = {pattern: 0.0 for pattern in NARRATIVE_PATTERNS}
    for signal, weight in weighted:
        text_blob = " ".join(_signal_texts(signal)).lower()
        for pattern, terms in NARRATIVE_PATTERNS.items():
            hits = sum(1 for term in terms if term in text_blob)
            pattern_scores[pattern] += hits * weight
    total_pattern_weight = sum(pattern_scores.values())
    if total_pattern_weight <= 0:
        return VocoderBand(
            band="narrative_structure",
            magnitude=0.0,
            bias=0.0,
            confidence=0.0,
            dominant_label="flat",
            source_count=len(weighted),
            components={pattern: 0.0 for pattern in NARRATIVE_PATTERNS},
        )
    normalised_scores = {
        pattern: _clamp(score / max(total_pattern_weight, 1.0))
        for pattern, score in pattern_scores.items()
    }
    dominant_label = max(normalised_scores, key=normalised_scores.get)
    positive_weight = sum(normalised_scores[pattern] for pattern in POSITIVE_PATTERNS)
    negative_weight = sum(normalised_scores[pattern] for pattern in NEGATIVE_PATTERNS)
    magnitude = _clamp(max(normalised_scores.values()) + (sum(normalised_scores.values()) / max(len(normalised_scores), 1)))
    bias = _clamp(positive_weight - negative_weight, -1.0, 1.0)
    confidence = _clamp(_average([weight for _, weight in weighted]) * min(total_pattern_weight, 1.0))
    return VocoderBand(
        band="narrative_structure",
        magnitude=round(magnitude, 3),
        bias=round(bias, 3),
        confidence=round(confidence, 3),
        dominant_label=dominant_label,
        source_count=len(weighted),
        components={pattern: round(score, 3) for pattern, score in normalised_scores.items()},
    )


def build_market_carrier(
    signals: Sequence[Mapping[str, Any]],
    *,
    runtime_state: Mapping[str, Any] | None = None,
    health_report: Mapping[str, Any] | None = None,
    entity_id: str | None = None,
    now: datetime | None = None,
) -> CarrierState:
    resolved_now = now or datetime.now(timezone.utc)
    weighted, _ = _weighted_signal_metrics(signals)
    probability_pairs = []
    price_pairs = []
    probability_delta_pairs = []
    volume_pairs = []
    volatility_pairs = []
    event_offsets: list[float] = []

    for signal, weight in weighted:
        probability = _signal_probability(signal)
        if probability is not None:
            probability_pairs.append((probability, weight))
            probability_delta_pairs.append((_signal_probability_delta(signal), weight))
        price_pairs.append((_signal_price_change(signal), weight))
        volume_pairs.append((_signal_volume(signal), weight))
        volatility_pairs.append((_signal_volatility(signal), weight))
        event_time = _signal_event_time(signal)
        if event_time is not None:
            event_offsets.append((event_time - resolved_now).total_seconds() / 3600.0)

    anchor_probability = _weighted_average(probability_pairs) if probability_pairs else None
    probability_delta = _weighted_average(probability_delta_pairs) if probability_delta_pairs else 0.0
    price_change_pct = _weighted_average(price_pairs) if price_pairs else 0.0
    volume_ratio = _clamp(_weighted_average(volume_pairs) if volume_pairs else 0.0)
    volatility = _clamp(_weighted_average(volatility_pairs) if volatility_pairs else 0.0)
    event_hours_to_resolution = min(event_offsets) if event_offsets else None

    runtime_policy = {}
    runtime_blockers: list[str] = []
    scm_state = "UNKNOWN"
    if isinstance(runtime_state, Mapping):
        runtime_policy = dict(runtime_state.get("execution_policy") or {})
        runtime_blockers = sorted({str(blocker).upper() for blocker in runtime_state.get("active_blockers") or []})
        scm_state = str((runtime_state.get("scm_review") or {}).get("scm_state") or scm_state).upper()
    if isinstance(health_report, Mapping):
        policy_payload = health_report.get("policy") or health_report.get("execution_policy") or {}
        if isinstance(policy_payload, Mapping) and policy_payload:
            runtime_policy = dict(policy_payload)
        health_blockers = health_report.get("active_blockers")
        if isinstance(health_blockers, list) and health_blockers:
            runtime_blockers = sorted({str(blocker).upper() for blocker in health_blockers})
        scm_state = str((health_report.get("scm") or {}).get("scm_state") or scm_state).upper()

    policy_state = str(runtime_policy.get("policy_state") or "UNKNOWN").upper()
    policy_norm = policy_state_score(policy_state) / 3.0 if policy_state != "UNKNOWN" else 0.5
    blocker_pressure = _clamp(len(runtime_blockers) * 0.25)
    execution_readiness = None
    if isinstance(health_report, Mapping):
        scorecard = health_report.get("scorecard") or {}
        if isinstance(scorecard, Mapping):
            execution_readiness = _safe_float(
                ((scorecard.get("execution_readiness") or {}).get("score"))
            )
        if execution_readiness is None:
            breakdown = health_report.get("execution_readiness_breakdown") or {}
            if isinstance(breakdown, Mapping):
                execution_readiness = _safe_float(breakdown.get("final_score"))
        if execution_readiness is not None:
            execution_readiness = _clamp(execution_readiness / 10.0)

    domain_outputs = []
    anchor_bias = 0.0
    if anchor_probability is not None:
        anchor_bias = _clamp((anchor_probability - 0.5) * 2.0, -1.0, 1.0)
        domain_outputs.append(
            pe_prediction_market(
                anchor_probability,
                liquidity_score=max(volume_ratio, 0.3),
                source_reliability=_clamp(_average([weight for _, weight in weighted]), 0.0, 1.0),
            )
        )
    if price_change_pct != 0.0 or volatility > 0.0:
        domain_outputs.append(
            pe_price_action(
                current_velocity=price_change_pct,
                mean_velocity=0.0,
                std_velocity=max(volatility, 0.05),
                volume_ratio=max(volume_ratio, 0.3),
                freshness_factor=max(policy_norm, 0.3),
            )
        )
    pe_surface = pe_full_pipeline(domain_outputs)
    carrier_score = _clamp(
        (pe_surface.get("pe_coherent_avg") or 0.5)
        * (0.6 + (policy_norm * 0.4))
        * (1.0 - (blocker_pressure * 0.35))
    )

    return CarrierState(
        symbol=(entity_id or "").upper(),
        anchor_probability=round(anchor_probability, 3) if anchor_probability is not None else None,
        probability_delta=round(probability_delta, 3),
        price_change_pct=round(price_change_pct, 3),
        volume_ratio=round(volume_ratio, 3),
        volatility=round(volatility, 3),
        event_hours_to_resolution=round(event_hours_to_resolution, 3) if event_hours_to_resolution is not None else None,
        policy_state=policy_state,
        active_blockers=runtime_blockers,
        scm_state=scm_state,
        execution_readiness=round(execution_readiness, 3) if execution_readiness is not None else None,
        carrier_score=round(carrier_score, 3),
        anchor_bias=round(anchor_bias, 3),
        blocker_pressure=round(blocker_pressure, 3),
    )


def extract_market_translation_band(
    bands: Mapping[str, VocoderBand],
    carrier: CarrierState,
) -> VocoderBand:
    sentiment = bands["sentiment"]
    narrative = bands["narrative_structure"]
    confidence = bands["confidence"]
    timing = bands["timing"]

    narrative_bias = (sentiment.bias * 0.55) + (narrative.bias * 0.45)
    carrier_bias = carrier.anchor_bias
    price_bias = _clamp(carrier.price_change_pct, -1.0, 1.0)
    alignment = _clamp(1.0 - (abs(narrative_bias - carrier_bias) / 2.0))
    price_confirmation = 1.0 if (narrative_bias == 0 and price_bias == 0) or (narrative_bias * price_bias > 0) else 0.2
    dislocation = _clamp(abs(carrier_bias - price_bias))
    runtime_drag = _clamp(carrier.blocker_pressure + (1.0 - (policy_state_score(carrier.policy_state) / 3.0 if carrier.policy_state != "UNKNOWN" else 0.5)))
    magnitude = _clamp(
        (alignment * 0.4)
        + (price_confirmation * 0.2)
        + (carrier.carrier_score * 0.2)
        + (confidence.magnitude * 0.1)
        + (timing.magnitude * 0.1)
    )
    bias = _clamp((carrier_bias * 0.6) + (price_bias * 0.4), -1.0, 1.0)
    if alignment >= 0.65 and runtime_drag < 0.6:
        label = "aligned"
    elif dislocation >= 0.45 or alignment <= 0.35:
        label = "dislocated"
    else:
        label = "mixed"
    return VocoderBand(
        band="market_translation",
        magnitude=round(magnitude, 3),
        bias=round(bias, 3),
        confidence=round(_clamp((confidence.magnitude * 0.5) + (carrier.carrier_score * 0.5)), 3),
        dominant_label=label,
        source_count=1 if (carrier.anchor_probability is not None or carrier.price_change_pct != 0.0) else 0,
        components={
            "alignment": round(alignment, 3),
            "odds_price_link": round(price_confirmation, 3),
            "vol_translation": round(_clamp(1.0 - carrier.volatility), 3),
            "implied_probability_shift": round(_clamp(abs(carrier.probability_delta) * 4.0), 3),
            "dislocation": round(dislocation, 3),
        },
    )


def _extract_signal_bands_from_canonical(
    canonical: Sequence[Mapping[str, Any]],
    *,
    runtime_state: Mapping[str, Any] | None = None,
    health_report: Mapping[str, Any] | None = None,
    entity_id: str | None = None,
    now: datetime,
) -> tuple[dict[str, VocoderBand], CarrierState]:
    bands = {
        band_name: extract_band(band_name, canonical, now=now)
        for band_name in CORE_BAND_SEQUENCE
    }
    resolved_entity = entity_id or bands["entity"].dominant_label
    carrier = build_market_carrier(
        canonical,
        runtime_state=runtime_state,
        health_report=health_report,
        entity_id=resolved_entity,
        now=now,
    )
    bands["market_translation"] = extract_market_translation_band(bands, carrier)
    return bands, carrier


def extract_signal_bands(
    signals: Sequence[Mapping[str, Any]],
    *,
    runtime_state: Mapping[str, Any] | None = None,
    health_report: Mapping[str, Any] | None = None,
    entity_id: str | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, VocoderBand], CarrierState]:
    resolved_now = now or datetime.now(timezone.utc)
    canonical = _canonical_signals(signals, now=resolved_now)
    return _extract_signal_bands_from_canonical(
        canonical,
        runtime_state=runtime_state,
        health_report=health_report,
        entity_id=entity_id,
        now=resolved_now,
    )


def score_artist_modes(
    bands: Mapping[str, VocoderBand],
    carrier: CarrierState,
) -> list[ModeScore]:
    sentiment = bands["sentiment"]
    velocity = bands["velocity"]
    divergence = bands["divergence"]
    entity = bands["entity"]
    confidence = bands["confidence"]
    timing = bands["timing"]
    narrative = bands["narrative_structure"]
    translation = bands["market_translation"]

    consensus = _clamp((divergence.bias + 1.0) / 2.0)
    overshoot = max(
        narrative.components.get("hype", 0.0),
        narrative.components.get("panic", 0.0),
        narrative.components.get("trap", 0.0),
        narrative.components.get("exhaustion", 0.0),
    )
    velocity_impulse = _clamp((velocity.components.get("mention_rate", 0.0) * 0.5) + (velocity.components.get("burstiness", 0.0) * 0.5))
    velocity_persistence = velocity.components.get("persistence", 0.0)
    timing_lead = _clamp((timing.bias + 1.0) / 2.0)
    ambient_stack = _average([velocity.magnitude, confidence.magnitude, timing.magnitude, carrier.carrier_score])
    market_dislocation = translation.components.get("dislocation", 0.0)
    emotion_extremity = _clamp((sentiment.components.get("crowd_emotion", 0.0) * 0.5) + (abs(sentiment.bias) * 0.5))

    raw_scores = {
        "DAFT_PUNK": (
            confidence.magnitude * 0.25
            + translation.magnitude * 0.25
            + carrier.carrier_score * 0.20
            + consensus * 0.15
            + entity.magnitude * 0.10
            + (1.0 - overshoot) * 0.05
        ),
        "HBFS": (
            velocity_impulse * 0.25
            + timing.magnitude * 0.25
            + translation.magnitude * 0.20
            + confidence.magnitude * 0.15
            + carrier.carrier_score * 0.15
        ),
        "TAME_IMPALA": (
            velocity_persistence * 0.30
            + timing_lead * 0.20
            + confidence.magnitude * 0.20
            + carrier.carrier_score * 0.15
            + entity.magnitude * 0.15
        ),
        "KANYE": (
            emotion_extremity * 0.35
            + velocity_impulse * 0.20
            + overshoot * 0.15
            + market_dislocation * 0.15
            + abs(sentiment.bias) * 0.15
        ),
        "TRAVIS": (
            ambient_stack * 0.25
            + _average([sentiment.magnitude, velocity.magnitude, narrative.magnitude]) * 0.20
            + carrier.carrier_score * 0.20
            + confidence.magnitude * 0.20
            + timing.magnitude * 0.15
        ),
    }
    rationales = {
        "DAFT_PUNK": [
            "smooth fusion",
            f"consensus={consensus:.2f}",
            f"translation={translation.magnitude:.2f}",
        ],
        "HBFS": [
            "fast event precision",
            f"velocity_impulse={velocity_impulse:.2f}",
            f"timing={timing.magnitude:.2f}",
        ],
        "TAME_IMPALA": [
            "ambient drift",
            f"persistence={velocity_persistence:.2f}",
            f"timing_lead={timing_lead:.2f}",
        ],
        "KANYE": [
            "emotional amplification",
            f"emotion={emotion_extremity:.2f}",
            f"overshoot={overshoot:.2f}",
        ],
        "TRAVIS": [
            "stacked context",
            f"ambient_stack={ambient_stack:.2f}",
            f"carrier={carrier.carrier_score:.2f}",
        ],
    }
    results = [
        ModeScore(mode=mode, score=round(_clamp(score), 3), rationale=rationales[mode])
        for mode in ARTIST_MODE_SEQUENCE
        for score in [raw_scores[mode]]
    ]
    results.sort(key=lambda item: (-item.score, item.mode))
    return results


def build_signal_vocoder_output(
    signals: Sequence[Mapping[str, Any]],
    *,
    runtime_state: Mapping[str, Any] | None = None,
    health_report: Mapping[str, Any] | None = None,
    entity_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_now = now or datetime.now(timezone.utc)
    canonical = _canonical_signals(signals, now=resolved_now)
    bands, carrier = _extract_signal_bands_from_canonical(
        canonical,
        runtime_state=runtime_state,
        health_report=health_report,
        entity_id=entity_id,
        now=resolved_now,
    )
    mode_scores = score_artist_modes(bands, carrier)
    dominant_mode = mode_scores[0].mode if mode_scores else "DAFT_PUNK"

    compressed_bias = _clamp(
        (bands["sentiment"].bias * 0.25)
        + (bands["narrative_structure"].bias * 0.15)
        + (bands["market_translation"].bias * 0.40)
        + (carrier.anchor_bias * 0.20),
        -1.0,
        1.0,
    )
    compressed_conviction = _clamp(
        (bands["confidence"].magnitude * 0.20)
        + (bands["velocity"].magnitude * 0.10)
        + (bands["timing"].magnitude * 0.10)
        + (bands["narrative_structure"].magnitude * 0.15)
        + (bands["market_translation"].magnitude * 0.25)
        + (carrier.carrier_score * 0.20),
    )
    if compressed_bias > 0.2:
        directional_bias = "BULLISH"
    elif compressed_bias < -0.2:
        directional_bias = "BEARISH"
    else:
        directional_bias = "NEUTRAL"

    if compressed_conviction >= 0.75 and bands["confidence"].magnitude >= 0.60:
        signal_grade = "ACTION_GRADE"
    elif compressed_conviction >= 0.50:
        signal_grade = "WATCH_GRADE"
    else:
        signal_grade = "NOISE_GRADE"

    policy_norm = policy_state_score(carrier.policy_state) / 3.0 if carrier.policy_state != "UNKNOWN" else 0.5
    if carrier.blocker_pressure >= 0.5 or policy_norm <= (1 / 3):
        deployment_posture = "BLOCKED"
    elif signal_grade == "ACTION_GRADE":
        deployment_posture = "REVIEW"
    elif signal_grade == "WATCH_GRADE":
        deployment_posture = "MONITOR"
    else:
        deployment_posture = "IGNORE"

    if deployment_posture == "BLOCKED":
        decision_signal = f"BLOCKED_{directional_bias}"
    elif signal_grade == "ACTION_GRADE":
        decision_signal = f"ACTIONABLE_{directional_bias}"
    elif signal_grade == "WATCH_GRADE":
        decision_signal = f"WATCH_{directional_bias}"
    else:
        decision_signal = "NOISE"

    source_counts: dict[str, int] = {}
    for signal in canonical:
        source = str(signal.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

    reasons = [
        f"dominant_mode={dominant_mode}",
        f"translation={bands['market_translation'].dominant_label}",
        f"policy_state={carrier.policy_state}",
    ]
    if carrier.active_blockers:
        reasons.append("active_blockers=" + ",".join(carrier.active_blockers))

    resolved_entity = entity_id or bands["entity"].dominant_label or carrier.symbol or "BROAD"
    compressed = CompressedSignal(
        schema_version=SIGNAL_VOCODER_SCHEMA_VERSION,
        generated_at=resolved_now.isoformat(),
        entity_id=str(resolved_entity).upper(),
        source_summary={
            "source_count": len(canonical),
            "sources": source_counts,
        },
        carrier=carrier,
        bands=bands,
        mode_scores=mode_scores,
        dominant_mode=dominant_mode,
        compressed_bias=round(compressed_bias, 3),
        compressed_conviction=round(compressed_conviction, 3),
        directional_bias=directional_bias,
        signal_grade=signal_grade,
        deployment_posture=deployment_posture,
        decision_signal=decision_signal,
        reasons=reasons,
    )
    return compressed.to_dict()


def _runtime_vocoder_context(
    row: Mapping[str, Any],
    position: Mapping[str, Any] | None,
    health_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    policy_payload = {}
    if isinstance(health_report, Mapping):
        policy_payload = health_report.get("policy") or health_report.get("execution_policy") or {}
    policy_state = str((policy_payload or {}).get("policy_state") or "UNKNOWN").upper()
    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "signal_id": str(row.get("signal_id") or ""),
        "signal_state": str(row.get("signal_state") or row.get("status") or "UNKNOWN").upper(),
        "status": str(row.get("status") or "").upper(),
        "watchlist_tier": str(row.get("watchlist_tier") or "NONE").upper(),
        "candidate_conversion_state": str(row.get("candidate_conversion_state") or "NONE").upper(),
        "pre_entry_state": str(row.get("pre_entry_state") or "NONE").upper(),
        "blocker_attribution": str(row.get("blocker_attribution") or "NONE").upper(),
        "policy_state": policy_state,
        "has_open_position": position is not None,
        "position_state": str((position or {}).get("state") or "NONE").upper(),
        "entry_type": str((position or {}).get("entry_type") or row.get("entry_type") or "UNKNOWN").upper(),
        "priority_score": round(_safe_float(row.get("priority_score")) or 0.0, 3),
        "ce_score": round(_safe_float(row.get("ce_score")) or 0.0, 3),
    }


def _fallback_runtime_summary_text(
    row: Mapping[str, Any],
    position: Mapping[str, Any] | None,
    health_report: Mapping[str, Any] | None,
) -> str:
    context = _runtime_vocoder_context(row, position, health_report)
    parts = [
        f"{context['ticker']} is {context['status'].lower()} under {context['policy_state'].lower()} policy",
    ]
    if context["watchlist_tier"] != "NONE":
        parts.append(f"watchlist tier {context['watchlist_tier'].lower()}")
    if context["candidate_conversion_state"] != "NONE":
        parts.append(f"candidate conversion {context['candidate_conversion_state'].lower()}")
    if context["pre_entry_state"] != "NONE":
        parts.append(f"pre-entry state {context['pre_entry_state'].lower()}")
    if context["blocker_attribution"] != "NONE":
        parts.append(f"blocked by {context['blocker_attribution'].lower()}")
    if position:
        parts.append(
            "open position "
            f"{context['position_state'].lower()} "
            f"{context['entry_type'].lower()} "
            f"pnl {(_safe_float(position.get('pnl_pct')) or 0.0):+.3f}"
        )
    if isinstance(health_report, Mapping) and health_report.get("what_should_i_do_next"):
        parts.append(str(health_report["what_should_i_do_next"]))
    return ". ".join(parts)


def _build_runtime_fallback_tool_payloads(
    row: Mapping[str, Any],
    *,
    health_report: Mapping[str, Any] | None = None,
    position: Mapping[str, Any] | None = None,
    now: datetime,
) -> list[dict[str, Any]]:
    ticker = str(row.get("ticker") or "").upper()
    status = str(row.get("status") or row.get("signal_state") or "UNKNOWN").upper()
    policy_payload = {}
    if isinstance(health_report, Mapping):
        policy_payload = health_report.get("policy") or health_report.get("execution_policy") or {}
    policy_state = str((policy_payload or {}).get("policy_state") or "UNKNOWN").upper()
    summary_text = _fallback_runtime_summary_text(row, position, health_report)

    payloads: list[dict[str, Any]] = [
        {
            "tool": "rss",
            "timestamp": now.isoformat(),
            "raw_output": {
                "title": f"{ticker} {status} under {policy_state}",
                "summary": summary_text,
                "published": now.isoformat(),
                "source": "runtime_state",
                "link": f"runtime://{ticker.lower()}",
            },
        }
    ]
    if position is not None:
        payloads.append(
            {
                "tool": "market_data",
                "timestamp": now.isoformat(),
                "raw_output": {
                    "symbol": ticker,
                    "price": _safe_float(position.get("current_price")),
                    "price_change_pct": _safe_float(position.get("pnl_pct")),
                    "volume_ratio": 1.0,
                    "volatility": 0.35 if bool(position.get("chaos_flag")) else 0.15,
                },
            }
        )
    return payloads


def _group_vocoder_signals_by_entity(
    signals: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        entities = _signal_entities(signal)
        if not entities:
            entities = ["BROAD"]
        for entity in entities:
            grouped.setdefault(entity, []).append(dict(signal))
    return grouped


def _count_values(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def build_runtime_vocoder_artifact(
    *,
    runtime_state: Mapping[str, Any],
    health_report: Mapping[str, Any],
    etil_signals: Sequence[Mapping[str, Any]] | None = None,
    tool_payloads: Sequence[Mapping[str, Any]] | None = None,
    open_positions: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_now = now or datetime.now(timezone.utc)
    scenario = str(
        (health_report or {}).get("simulation_mode")
        or (runtime_state or {}).get("simulation_context", {}).get("scenario")
        or "LIVE"
    ).upper()
    runtime_rows = list((runtime_state or {}).get("per_signal_attribution") or [])
    positions = list(open_positions) if open_positions is not None else load_open_positions()[0]
    positions_by_ticker = {
        str(position.get("ticker") or "").upper(): dict(position)
        for position in positions
        if str(position.get("ticker") or "").strip()
    }
    rows_by_ticker = {
        str(row.get("ticker") or "").upper(): dict(row)
        for row in runtime_rows
        if str(row.get("ticker") or "").strip()
    }

    normalized_live_signals = []
    if etil_signals:
        normalized_live_signals = normalise_vocoder_etil_signals(etil_signals, now=resolved_now)
    elif tool_payloads:
        normalized_live_signals = normalise_vocoder_inputs(tool_payloads, now=resolved_now)
    live_groups = _group_vocoder_signals_by_entity(normalized_live_signals) if normalized_live_signals else {}
    source_mode = "LIVE_ETIL" if live_groups else "SYNTHETIC_RUNTIME_FALLBACK"

    entities_payload: list[dict[str, Any]] = []
    entity_ids = sorted(set(rows_by_ticker) or set(live_groups))
    for entity_id in entity_ids:
        row = rows_by_ticker.get(entity_id, {"ticker": entity_id})
        position = positions_by_ticker.get(entity_id)
        entity_signals = live_groups.get(entity_id)
        input_origin = "live_etil"
        if not entity_signals:
            input_origin = "synthetic_runtime_fallback"
            entity_signals = normalise_vocoder_inputs(
                _build_runtime_fallback_tool_payloads(
                    row,
                    health_report=health_report,
                    position=position,
                    now=resolved_now,
                ),
                now=resolved_now,
            )
        compressed_signal = build_signal_vocoder_output(
            entity_signals,
            runtime_state=runtime_state,
            health_report=health_report,
            entity_id=entity_id,
            now=resolved_now,
        )
        entities_payload.append(
            {
                "entity_id": entity_id,
                "input_origin": input_origin,
                "input_payload_count": len(entity_signals),
                "runtime_context": _runtime_vocoder_context(row, position, health_report),
                "compressed_signal": compressed_signal,
            }
        )

    entities_payload.sort(key=lambda item: item["entity_id"])
    summary_rows = [item["compressed_signal"] for item in entities_payload]
    return {
        "artifact_kind": "signal_vocoder_runtime_artifact",
        "schema_version": SIGNAL_VOCODER_SCHEMA_VERSION,
        "generated_at": resolved_now.isoformat(),
        "scenario": scenario,
        "source_mode": source_mode,
        "entity_count": len(entities_payload),
        "summary": {
            "dominant_modes": _count_values(summary_rows, "dominant_mode"),
            "signal_grades": _count_values(summary_rows, "signal_grade"),
            "deployment_postures": _count_values(summary_rows, "deployment_posture"),
            "decision_signals": _count_values(summary_rows, "decision_signal"),
            "blocked_entities": [
                item["entity_id"]
                for item in entities_payload
                if str(item["compressed_signal"].get("deployment_posture") or "").upper() == "BLOCKED"
            ],
        },
        "entities": entities_payload,
    }


def persist_runtime_vocoder_artifact(
    artifact: Mapping[str, Any],
    *,
    path=None,
) -> None:
    write_json_atomic(path or SIGNAL_VOCODER_REPORT_PATH, dict(artifact))
