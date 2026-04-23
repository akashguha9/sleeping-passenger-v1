from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import log10
from pathlib import Path
import re
from typing import Any

try:
    from scripts.runtime_common import (
        ATTENTION_PROXY_REPORT_PATH,
        get_run_started_at,
        get_source_mode,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        ATTENTION_PROXY_REPORT_PATH,
        get_run_started_at,
        get_source_mode,
        write_json_atomic,
    )


INPUT_SIGNAL_FIELDS = (
    "text_signal",
    "source_type",
    "sentiment_score",
    "novelty_score",
    "engagement_count",
    "engagement_velocity",
    "engagement_acceleration",
    "source_credibility",
    "content_modality",
    "network_spread_proxy",
    "trend_persistence_proxy",
    "event_alignment_score",
    "market_theme_alignment",
    "time_since_first_observed_minutes",
)
TELEMETRY_FIELDS = (
    "engagement_count",
    "engagement_velocity",
    "engagement_acceleration",
    "network_spread_proxy",
    "trend_persistence_proxy",
)
CONFIDENCE_SENSITIVE_FIELDS = (
    "engagement_count",
    "engagement_velocity",
    "engagement_acceleration",
    "network_spread_proxy",
    "trend_persistence_proxy",
    "event_alignment_score",
    "market_theme_alignment",
    "novelty_score",
)
STATE_DERIVED_INFERENCE_FIELDS = (
    "engagement_velocity",
    "engagement_acceleration",
    "network_spread_proxy",
    "event_alignment_score",
    "market_theme_alignment",
    "novelty_score",
)
SOURCE_TYPE_PROFILES = {
    "official": {"credibility": 0.9, "spreadability": 0.52},
    "market": {"credibility": 0.82, "spreadability": 0.62},
    "news": {"credibility": 0.74, "spreadability": 0.58},
    "social": {"credibility": 0.52, "spreadability": 0.8},
    "forum": {"credibility": 0.44, "spreadability": 0.76},
    "internal": {"credibility": 0.42, "spreadability": 0.34},
    "other": {"credibility": 0.5, "spreadability": 0.5},
}
MODALITY_SCORES = {
    "text": 0.56,
    "image": 0.72,
    "video": 0.8,
    "audio": 0.64,
    "mixed": 0.84,
    "unknown": 0.5,
}
DEFAULT_ATTENTION_PROXY_WEIGHTS: dict[str, dict[str, float]] = {
    "attention_capture": {
        "text_eventfulness": 0.24,
        "engagement_velocity": 0.22,
        "positive_acceleration": 0.2,
        "modality_hook": 0.12,
        "engagement_count": 0.1,
        "freshness": 0.07,
        "sentiment_intensity": 0.05,
    },
    "narrative_cohesion": {
        "text_cohesion": 0.35,
        "event_alignment": 0.2,
        "market_theme_alignment": 0.2,
        "source_credibility": 0.15,
        "persistence": 0.1,
    },
    "spreadability": {
        "network_spread": 0.3,
        "text_spreadability": 0.2,
        "engagement_velocity": 0.18,
        "positive_acceleration": 0.15,
        "modality_hook": 0.1,
        "source_spreadability": 0.07,
    },
    "persistence": {
        "trend_persistence": 0.45,
        "source_credibility": 0.18,
        "event_alignment": 0.15,
        "engagement_count": 0.12,
        "velocity_minus_decay": 0.1,
    },
    "novelty": {
        "explicit_novelty": 0.6,
        "text_novelty": 0.2,
        "freshness": 0.12,
        "anti_persistence": 0.08,
    },
    "saturation_risk": {
        "age_maturity": 0.35,
        "trend_persistence": 0.25,
        "engagement_count": 0.2,
        "novelty_deficit": 0.2,
    },
    "decay_risk": {
        "deceleration": 0.4,
        "saturation_risk": 0.25,
        "age_maturity": 0.15,
        "novelty_deficit": 0.12,
        "credibility_deficit": 0.08,
    },
    "capital_relevance": {
        "event_alignment": 0.35,
        "market_theme_alignment": 0.25,
        "text_capital_relevance": 0.25,
        "source_credibility": 0.15,
    },
    "overall": {
        "attention_capture_score": 0.22,
        "narrative_cohesion_score": 0.18,
        "spreadability_score": 0.12,
        "persistence_score": 0.16,
        "novelty_score": 0.1,
        "capital_relevance_score": 0.22,
        "saturation_risk_score": -0.05,
        "decay_risk_score": -0.05,
    },
}
DEFAULT_GOVERNANCE_NOTES = [
    "Attention proxy is a research and diagnostic score, not a virality predictor.",
    "This output is advisory only and must not be treated as predictive truth.",
    "This layer does not authorize capital deployment or live execution.",
]
EVENT_KEYWORDS = {
    "approval",
    "ban",
    "beat",
    "breach",
    "delay",
    "earnings",
    "filing",
    "guidance",
    "hack",
    "investigation",
    "launch",
    "merger",
    "outage",
    "partnership",
    "recall",
    "regulator",
    "surprise",
    "tariff",
    "upgrade",
}
CAPITAL_KEYWORDS = {
    "bond",
    "capital",
    "credit",
    "demand",
    "equity",
    "etf",
    "flow",
    "funding",
    "liquidity",
    "macro",
    "margin",
    "market",
    "price",
    "pricing",
    "rate",
    "repricing",
    "revenue",
    "spread",
    "volatility",
    "yield",
}
NOVELTY_KEYWORDS = {
    "breakout",
    "first",
    "new",
    "rare",
    "shock",
    "unexpected",
    "unusual",
}
FATIGUE_KEYWORDS = {
    "again",
    "already",
    "consensus",
    "expected",
    "priced",
    "recycled",
    "repeat",
    "stale",
}
TEXT_TOKEN_RE = re.compile(r"[A-Za-z0-9%$+-]+")


@dataclass(frozen=True)
class AttentionProxyInput:
    signal_id: str = ""
    ticker: str = ""
    text_signal: str | None = None
    source_type: str | None = None
    sentiment_score: float | None = None
    novelty_score: float | None = None
    engagement_count: float | None = None
    engagement_velocity: float | None = None
    engagement_acceleration: float | None = None
    source_credibility: float | None = None
    content_modality: str | None = None
    network_spread_proxy: float | None = None
    trend_persistence_proxy: float | None = None
    event_alignment_score: float | None = None
    market_theme_alignment: float | None = None
    time_since_first_observed_minutes: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttentionProxyResult:
    signal_id: str
    ticker: str
    input_mode: str
    attention_capture_score: float
    narrative_cohesion_score: float
    spreadability_score: float
    persistence_score: float
    novelty_score: float
    saturation_risk_score: float
    decay_risk_score: float
    capital_relevance_score: float
    overall_attention_proxy_score: float
    attention_state: str
    narrative_state: str
    proxy_confidence: float
    confidence_band: str
    proxy_advisory: str
    recommended_interpretation: str
    narrative_heat_score: float
    narrative_exhaustion_score: float
    reasons: list[str]
    risks: list[str]
    missing_inputs: list[str]
    assumptions: list[str]
    governance_notes: list[str]
    score_inputs: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _safe_round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _modality_score(value: str | None) -> float:
    key = _text(value).lower()
    if key in MODALITY_SCORES:
        return MODALITY_SCORES[key]
    return MODALITY_SCORES["unknown"]


def _source_profile(source_type: str | None) -> dict[str, float]:
    key = _text(source_type).lower()
    if key in SOURCE_TYPE_PROFILES:
        return SOURCE_TYPE_PROFILES[key]
    return SOURCE_TYPE_PROFILES["other"]


def _normalize_probability(value: float | None, default: float = 0.5) -> float:
    if value is None:
        return default
    return _clamp(float(value))


def _normalize_sentiment_intensity(value: float | None) -> float:
    if value is None:
        return 0.35
    raw = _coerce_float(value)
    if raw is None:
        return 0.35
    return _clamp(abs(raw), lower=0.0, upper=1.0)


def _normalize_engagement_count(value: float | None) -> float:
    raw = _coerce_float(value)
    if raw is None or raw <= 0:
        return 0.35
    return _clamp(log10(raw + 1.0) / 4.0)


def _freshness_score(minutes_since_first_observed: float | None) -> float:
    minutes = _coerce_float(minutes_since_first_observed)
    if minutes is None or minutes < 0:
        return 0.5
    if minutes <= 60:
        return 0.95
    if minutes <= 6 * 60:
        return 0.82
    if minutes <= 24 * 60:
        return 0.68
    if minutes <= 3 * 24 * 60:
        return 0.54
    if minutes <= 7 * 24 * 60:
        return 0.42
    return 0.3


def _parse_signal_emergence_ts(signal_id: str | None) -> datetime | None:
    text = _text(signal_id)
    parts = text.split("_")
    if len(parts) < 4:
        return None
    try:
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _minutes_since_signal(signal_id: str | None, as_of: datetime) -> float | None:
    emergence = _parse_signal_emergence_ts(signal_id)
    if emergence is None:
        return None
    return max(0.0, (as_of - emergence).total_seconds() / 60.0)


def _infer_source_type(row: dict[str, Any]) -> str:
    source_name = _text(row.get("source_name")).lower()
    signal_origin = _text(row.get("signal_origin")).lower()
    if any(source_name.startswith(prefix) for prefix in ("polymarket", "kalshi")):
        return "market"
    if source_name in {"reuters", "ap", "bloomberg", "sec"}:
        return "official"
    if source_name in {"reddit", "twitter", "x", "discord"}:
        return "social"
    if signal_origin == "external":
        return "market"
    if source_name == "signal_ledger" or signal_origin in {
        "seeded_runtime",
        "synthetic_runtime_fallback",
        "seeded",
    }:
        return "internal"
    return "other"


def _persistence_by_ticker(trend_report: dict[str, Any] | None) -> dict[str, int]:
    report = trend_report if isinstance(trend_report, dict) else {}
    keys = (
        "blocked_promotable_transition_streak",
        "clean_ready_pending_transition_streak",
        "clean_entry_eligible_transition_streak",
        "entry_review_candidate_streak",
        "transition_review_candidate_streak",
    )
    mapping: dict[str, int] = {}
    for key in keys:
        block = report.get(key, {})
        rows = block.get("persistent_names", []) if isinstance(block, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = _text(row.get("ticker")).upper()
            count = int(_coerce_float(row.get("consecutive_snapshots")) or 0)
            if ticker:
                mapping[ticker] = max(mapping.get(ticker, 0), count)
    return mapping


def _extract_text_features(text_signal: str | None) -> dict[str, float]:
    text = _text(text_signal).lower()
    tokens = TEXT_TOKEN_RE.findall(text)
    if not tokens:
        return {
            "eventfulness": 0.28,
            "cohesion": 0.26,
            "novelty": 0.3,
            "capital_relevance": 0.24,
            "spreadability": 0.26,
        }

    token_count = len(tokens)
    unique_ratio = len(set(tokens)) / token_count
    event_hits = sum(1 for token in tokens if token in EVENT_KEYWORDS)
    capital_hits = sum(1 for token in tokens if token in CAPITAL_KEYWORDS)
    novelty_hits = sum(1 for token in tokens if token in NOVELTY_KEYWORDS)
    fatigue_hits = sum(1 for token in tokens if token in FATIGUE_KEYWORDS)
    event_density = min(event_hits / 3.0, 1.0)
    capital_density = min(capital_hits / 3.0, 1.0)
    novelty_density = min(novelty_hits / 2.0, 1.0)
    fatigue_density = min(fatigue_hits / 2.0, 1.0)
    compactness = 1.0 if 4 <= token_count <= 20 else 0.65
    numerical_hook = 1.0 if any(char.isdigit() for char in text) else 0.0

    eventfulness = _clamp(
        0.3 + (0.35 * event_density) + (0.15 * capital_density) + (0.2 * compactness)
    )
    cohesion = _clamp(
        0.25
        + (0.25 * min(token_count / 12.0, 1.0))
        + (0.25 * unique_ratio)
        + (0.15 * event_density)
        + (0.1 * capital_density)
    )
    novelty = _clamp(
        0.25
        + (0.4 * novelty_density)
        + (0.15 * event_density)
        - (0.2 * fatigue_density)
    )
    capital_relevance = _clamp(
        0.2
        + (0.5 * capital_density)
        + (0.15 * numerical_hook)
        + (0.1 if "$" in text or "%" in text else 0.0)
    )
    spreadability = _clamp(
        0.25
        + (0.25 * event_density)
        + (0.2 * novelty_density)
        + (0.15 * compactness)
        + (0.15 * numerical_hook)
    )
    return {
        "eventfulness": eventfulness,
        "cohesion": cohesion,
        "novelty": novelty,
        "capital_relevance": capital_relevance,
        "spreadability": spreadability,
    }


def _confidence_band(value: float) -> str:
    if value >= 0.75:
        return "HIGH"
    if value >= 0.55:
        return "MEDIUM"
    return "LOW"


def _derive_attention_state(
    attention_capture_score: float,
    narrative_heat_score: float,
    overall_attention_proxy_score: float,
) -> str:
    if attention_capture_score >= 0.72 and narrative_heat_score >= 0.68:
        return "HIGH_HEAT"
    if overall_attention_proxy_score >= 0.58 and attention_capture_score >= 0.6:
        return "ATTENTION_BEARING"
    if overall_attention_proxy_score >= 0.4:
        return "EMERGING"
    return "LOW_VISIBILITY"


def _derive_narrative_state(
    narrative_cohesion_score: float,
    persistence_score: float,
    saturation_risk_score: float,
    decay_risk_score: float,
) -> str:
    if saturation_risk_score >= 0.75 and decay_risk_score >= 0.6:
        return "EXHAUSTING"
    if saturation_risk_score >= 0.75:
        return "SATURATED"
    if narrative_cohesion_score >= 0.7 and persistence_score >= 0.62:
        return "TRACTION_FORMING"
    if narrative_cohesion_score >= 0.55:
        return "FORMING"
    return "FRAGMENTED"


def _derive_proxy_advisory(
    *,
    attention_capture_score: float,
    narrative_cohesion_score: float,
    persistence_score: float,
    novelty_score: float,
    saturation_risk_score: float,
    decay_risk_score: float,
    capital_relevance_score: float,
    overall_attention_proxy_score: float,
) -> str:
    if attention_capture_score >= 0.62 and capital_relevance_score < 0.42:
        return "attention strong, capital relevance weak"
    if saturation_risk_score >= 0.72 and decay_risk_score >= 0.62:
        return "transient spike risk"
    if novelty_score >= 0.68 and persistence_score < 0.45:
        return "high novelty, low persistence"
    if overall_attention_proxy_score >= 0.68 and capital_relevance_score >= 0.62:
        return "possible ignition candidate, monitor for validation"
    if narrative_cohesion_score >= 0.68 and persistence_score >= 0.6:
        return "narrative traction forming"
    if attention_capture_score >= 0.6:
        return "attention-bearing but unvalidated"
    return "monitor only; insufficient attention evidence"


def _derive_reasons(
    *,
    attention_capture_score: float,
    narrative_cohesion_score: float,
    spreadability_score: float,
    persistence_score: float,
    capital_relevance_score: float,
) -> list[str]:
    reasons: list[str] = []
    if attention_capture_score >= 0.6:
        reasons.append("Attention capture is supported by velocity or content hooks.")
    if narrative_cohesion_score >= 0.6:
        reasons.append("Narrative proxy shows coherent alignment across text, event, and theme.")
    if spreadability_score >= 0.6:
        reasons.append("Spreadability proxy is elevated relative to the current source/network profile.")
    if persistence_score >= 0.6:
        reasons.append("Persistence proxy suggests the signal can hold beyond a one-bar spike.")
    if capital_relevance_score >= 0.6:
        reasons.append("Capital relevance proxy indicates repricing attention could matter if validation follows.")
    if not reasons:
        reasons.append("Signal remains below strong attention-proxy thresholds.")
    return reasons


def _derive_risks(
    *,
    saturation_risk_score: float,
    decay_risk_score: float,
    capital_relevance_score: float,
    proxy_confidence: float,
    input_mode: str,
) -> list[str]:
    risks: list[str] = []
    if saturation_risk_score >= 0.6:
        risks.append("Narrative saturation risk is elevated.")
    if decay_risk_score >= 0.6:
        risks.append("Decay risk is elevated.")
    if capital_relevance_score < 0.45:
        risks.append("Capital relevance remains weak.")
    if proxy_confidence < 0.55:
        risks.append("Confidence is constrained by sparse or inferred inputs.")
    if input_mode == "seeded_demo":
        risks.append(
            "Seeded/demo input lacks live engagement telemetry; missing fields fall back to conservative heuristics."
        )
    return risks


def _score_inputs(input_data: AttentionProxyInput) -> tuple[dict[str, Any], list[str]]:
    metadata = input_data.metadata if isinstance(input_data.metadata, dict) else {}
    assumptions = [str(value) for value in metadata.get("preseed_assumptions", []) if _text(value)]

    text_features = _extract_text_features(input_data.text_signal)
    source_profile = _source_profile(input_data.source_type)
    modality_hook = _modality_score(input_data.content_modality)
    explicit_novelty = _normalize_probability(input_data.novelty_score, default=text_features["novelty"])
    engagement_count_score = _normalize_engagement_count(input_data.engagement_count)
    engagement_velocity = _normalize_probability(input_data.engagement_velocity, default=0.3)
    raw_acceleration = _coerce_float(input_data.engagement_acceleration)
    if raw_acceleration is None:
        raw_acceleration = 0.0
    raw_acceleration = max(-1.0, min(1.0, raw_acceleration))
    positive_acceleration = max(0.0, raw_acceleration)
    deceleration = max(0.0, -raw_acceleration)
    source_credibility = _normalize_probability(
        input_data.source_credibility,
        default=source_profile["credibility"],
    )
    network_spread = _normalize_probability(
        input_data.network_spread_proxy,
        default=source_profile["spreadability"],
    )
    trend_persistence = _normalize_probability(input_data.trend_persistence_proxy, default=0.32)
    event_alignment = _normalize_probability(
        input_data.event_alignment_score,
        default=max(0.28, text_features["eventfulness"]),
    )
    market_theme_alignment = _normalize_probability(
        input_data.market_theme_alignment,
        default=max(0.28, text_features["capital_relevance"]),
    )
    freshness = _freshness_score(input_data.time_since_first_observed_minutes)
    age_maturity = _clamp(1.0 - freshness)
    sentiment_intensity = _normalize_sentiment_intensity(input_data.sentiment_score)

    score_inputs = {
        "text_eventfulness": text_features["eventfulness"],
        "text_cohesion": text_features["cohesion"],
        "text_novelty": text_features["novelty"],
        "text_capital_relevance": text_features["capital_relevance"],
        "text_spreadability": text_features["spreadability"],
        "source_spreadability": source_profile["spreadability"],
        "modality_hook": modality_hook,
        "explicit_novelty": explicit_novelty,
        "engagement_count_score": engagement_count_score,
        "engagement_velocity": engagement_velocity,
        "positive_acceleration": positive_acceleration,
        "deceleration": deceleration,
        "source_credibility": source_credibility,
        "network_spread": network_spread,
        "trend_persistence": trend_persistence,
        "event_alignment": event_alignment,
        "market_theme_alignment": market_theme_alignment,
        "freshness": freshness,
        "age_maturity": age_maturity,
        "sentiment_intensity": sentiment_intensity,
    }
    return score_inputs, assumptions


def _score_confidence(
    input_data: AttentionProxyInput,
    *,
    missing_inputs: list[str],
) -> float:
    metadata = input_data.metadata if isinstance(input_data.metadata, dict) else {}
    input_mode = _text(metadata.get("input_mode")).lower() or "direct_input"
    inferred_fields = {
        _text(value)
        for value in metadata.get("inferred_fields", [])
        if _text(value)
    }
    measured_fields = {
        _text(value)
        for value in metadata.get("measured_fields", [])
        if _text(value)
    }

    coverage = (
        (len(INPUT_SIGNAL_FIELDS) - len(missing_inputs)) / len(INPUT_SIGNAL_FIELDS)
        if INPUT_SIGNAL_FIELDS
        else 0.0
    )
    telemetry_coverage = len(measured_fields.intersection(TELEMETRY_FIELDS)) / len(TELEMETRY_FIELDS)
    text_grounding = 1.0 if _text(input_data.text_signal) else 0.15
    directness = {
        "external_augmented": 0.78,
        "offline_inferred": 0.45,
        "seeded_demo": 0.18,
        "direct_input": 0.72,
    }.get(input_mode, 0.45)
    inferred_ratio = len(inferred_fields.intersection(CONFIDENCE_SENSITIVE_FIELDS)) / len(
        CONFIDENCE_SENSITIVE_FIELDS
    )
    confidence = _clamp(
        0.08
        + (0.26 * coverage)
        + (0.24 * telemetry_coverage)
        + (0.14 * text_grounding)
        + (0.14 * directness)
        - (0.22 * inferred_ratio)
    )
    mode_cap = {
        "seeded_demo": 0.39,
        "offline_inferred": 0.54,
        "external_augmented": 0.86,
        "direct_input": 0.82,
    }.get(input_mode, 0.54)
    confidence = min(confidence, mode_cap)
    if telemetry_coverage == 0.0 and not _text(input_data.text_signal):
        confidence = min(confidence, 0.34)
    if inferred_ratio >= 0.3:
        confidence = min(confidence, 0.49)
    return _clamp(confidence)


def _apply_honesty_overrides(
    *,
    input_mode: str,
    attention_state: str,
    narrative_state: str,
    proxy_advisory: str,
    proxy_confidence: float,
) -> tuple[str, str, str, list[str], list[str]]:
    adjusted_attention_state = attention_state
    adjusted_narrative_state = narrative_state
    adjusted_proxy_advisory = proxy_advisory
    additional_risks: list[str] = []
    additional_governance_notes: list[str] = []

    if input_mode == "seeded_demo":
        if adjusted_attention_state in {"HIGH_HEAT", "ATTENTION_BEARING"}:
            adjusted_attention_state = "EMERGING"
        if adjusted_narrative_state == "TRACTION_FORMING":
            adjusted_narrative_state = "FORMING"
        if adjusted_proxy_advisory not in {"transient spike risk", "high novelty, low persistence"}:
            adjusted_proxy_advisory = "monitor only; inferred attention cues from seeded runtime"
        additional_risks.append(
            "Seeded/demo rows are intentionally capped because no measured attention telemetry is attached."
        )
        additional_governance_notes.append(
            "Seeded/demo rows cannot graduate beyond EMERGING attention state without telemetry-backed inputs."
        )
    elif input_mode == "offline_inferred":
        if proxy_confidence < 0.55 and adjusted_attention_state in {"HIGH_HEAT", "ATTENTION_BEARING"}:
            adjusted_attention_state = "EMERGING"
        if proxy_confidence < 0.55 and adjusted_narrative_state == "TRACTION_FORMING":
            adjusted_narrative_state = "FORMING"
        if adjusted_proxy_advisory == "possible ignition candidate, monitor for validation":
            adjusted_proxy_advisory = "attention-bearing but unvalidated"
        elif proxy_confidence < 0.55 and adjusted_proxy_advisory == "narrative traction forming":
            adjusted_proxy_advisory = "attention-bearing but unvalidated"
        additional_risks.append(
            "Telemetry is absent; text and offline heuristics can only suggest attention cues, not confirm them."
        )
        additional_governance_notes.append(
            "Offline-inferred rows should be interpreted as heuristic monitoring cues until telemetry is attached."
        )

    if proxy_confidence < 0.55 and adjusted_proxy_advisory == "possible ignition candidate, monitor for validation":
        adjusted_proxy_advisory = "attention-bearing but unvalidated"

    return (
        adjusted_attention_state,
        adjusted_narrative_state,
        adjusted_proxy_advisory,
        additional_risks,
        additional_governance_notes,
    )


def build_attention_proxy_result(
    input_data: AttentionProxyInput,
    weights: dict[str, dict[str, float]] | None = None,
) -> AttentionProxyResult:
    resolved_weights = weights or DEFAULT_ATTENTION_PROXY_WEIGHTS
    metadata = dict(input_data.metadata) if isinstance(input_data.metadata, dict) else {}
    input_mode = _text(metadata.get("input_mode")) or "direct_input"
    missing_inputs = [
        field
        for field in INPUT_SIGNAL_FIELDS
        if getattr(input_data, field) is None or getattr(input_data, field) == ""
    ]
    score_inputs, assumptions = _score_inputs(input_data)

    attention_capture_weights = resolved_weights["attention_capture"]
    attention_capture_score = _clamp(
        (score_inputs["text_eventfulness"] * attention_capture_weights["text_eventfulness"])
        + (score_inputs["engagement_velocity"] * attention_capture_weights["engagement_velocity"])
        + (score_inputs["positive_acceleration"] * attention_capture_weights["positive_acceleration"])
        + (score_inputs["modality_hook"] * attention_capture_weights["modality_hook"])
        + (score_inputs["engagement_count_score"] * attention_capture_weights["engagement_count"])
        + (score_inputs["freshness"] * attention_capture_weights["freshness"])
        + (score_inputs["sentiment_intensity"] * attention_capture_weights["sentiment_intensity"])
    )
    narrative_cohesion_weights = resolved_weights["narrative_cohesion"]
    narrative_cohesion_score = _clamp(
        (score_inputs["text_cohesion"] * narrative_cohesion_weights["text_cohesion"])
        + (score_inputs["event_alignment"] * narrative_cohesion_weights["event_alignment"])
        + (
            score_inputs["market_theme_alignment"]
            * narrative_cohesion_weights["market_theme_alignment"]
        )
        + (
            score_inputs["source_credibility"]
            * narrative_cohesion_weights["source_credibility"]
        )
        + (score_inputs["trend_persistence"] * narrative_cohesion_weights["persistence"])
    )
    spreadability_weights = resolved_weights["spreadability"]
    spreadability_score = _clamp(
        (score_inputs["network_spread"] * spreadability_weights["network_spread"])
        + (
            score_inputs["text_spreadability"]
            * spreadability_weights["text_spreadability"]
        )
        + (
            score_inputs["engagement_velocity"]
            * spreadability_weights["engagement_velocity"]
        )
        + (
            score_inputs["positive_acceleration"]
            * spreadability_weights["positive_acceleration"]
        )
        + (score_inputs["modality_hook"] * spreadability_weights["modality_hook"])
        + (
            score_inputs["source_spreadability"]
            * spreadability_weights["source_spreadability"]
        )
    )
    persistence_weights = resolved_weights["persistence"]
    persistence_score = _clamp(
        (score_inputs["trend_persistence"] * persistence_weights["trend_persistence"])
        + (
            score_inputs["source_credibility"]
            * persistence_weights["source_credibility"]
        )
        + (score_inputs["event_alignment"] * persistence_weights["event_alignment"])
        + (score_inputs["engagement_count_score"] * persistence_weights["engagement_count"])
        + (
            max(
                0.0,
                score_inputs["engagement_velocity"] - score_inputs["deceleration"],
            )
            * persistence_weights["velocity_minus_decay"]
        )
    )
    novelty_weights = resolved_weights["novelty"]
    novelty_score = _clamp(
        (score_inputs["explicit_novelty"] * novelty_weights["explicit_novelty"])
        + (score_inputs["text_novelty"] * novelty_weights["text_novelty"])
        + (score_inputs["freshness"] * novelty_weights["freshness"])
        + (
            (1.0 - score_inputs["trend_persistence"])
            * novelty_weights["anti_persistence"]
        )
    )
    saturation_weights = resolved_weights["saturation_risk"]
    saturation_risk_score = _clamp(
        (score_inputs["age_maturity"] * saturation_weights["age_maturity"])
        + (
            score_inputs["trend_persistence"] * saturation_weights["trend_persistence"]
        )
        + (
            score_inputs["engagement_count_score"] * saturation_weights["engagement_count"]
        )
        + (
            (1.0 - score_inputs["explicit_novelty"])
            * saturation_weights["novelty_deficit"]
        )
    )
    decay_weights = resolved_weights["decay_risk"]
    decay_risk_score = _clamp(
        (score_inputs["deceleration"] * decay_weights["deceleration"])
        + (saturation_risk_score * decay_weights["saturation_risk"])
        + (score_inputs["age_maturity"] * decay_weights["age_maturity"])
        + (
            (1.0 - novelty_score)
            * decay_weights["novelty_deficit"]
        )
        + (
            (1.0 - score_inputs["source_credibility"])
            * decay_weights["credibility_deficit"]
        )
    )
    capital_weights = resolved_weights["capital_relevance"]
    capital_relevance_score = _clamp(
        (score_inputs["event_alignment"] * capital_weights["event_alignment"])
        + (
            score_inputs["market_theme_alignment"]
            * capital_weights["market_theme_alignment"]
        )
        + (
            score_inputs["text_capital_relevance"]
            * capital_weights["text_capital_relevance"]
        )
        + (
            score_inputs["source_credibility"]
            * capital_weights["source_credibility"]
        )
    )
    overall_weights = resolved_weights["overall"]
    overall_attention_proxy_score = _clamp(
        (
            (attention_capture_score * overall_weights["attention_capture_score"])
            + (
                narrative_cohesion_score
                * overall_weights["narrative_cohesion_score"]
            )
            + (spreadability_score * overall_weights["spreadability_score"])
            + (persistence_score * overall_weights["persistence_score"])
            + (novelty_score * overall_weights["novelty_score"])
            + (capital_relevance_score * overall_weights["capital_relevance_score"])
            + (saturation_risk_score * overall_weights["saturation_risk_score"])
            + (decay_risk_score * overall_weights["decay_risk_score"])
        )
        * (0.85 + (0.15 * capital_relevance_score))
    )
    narrative_heat_score = _clamp(
        (0.4 * score_inputs["engagement_velocity"])
        + (0.25 * score_inputs["positive_acceleration"])
        + (0.2 * spreadability_score)
        + (0.15 * score_inputs["text_eventfulness"])
    )
    narrative_exhaustion_score = _clamp(
        (0.4 * saturation_risk_score)
        + (0.25 * score_inputs["deceleration"])
        + (0.2 * score_inputs["age_maturity"])
        + (0.15 * (1.0 - novelty_score))
    )
    proxy_confidence = _score_confidence(input_data, missing_inputs=missing_inputs)
    confidence_band = _confidence_band(proxy_confidence)
    attention_state = _derive_attention_state(
        attention_capture_score=attention_capture_score,
        narrative_heat_score=narrative_heat_score,
        overall_attention_proxy_score=overall_attention_proxy_score,
    )
    narrative_state = _derive_narrative_state(
        narrative_cohesion_score=narrative_cohesion_score,
        persistence_score=persistence_score,
        saturation_risk_score=saturation_risk_score,
        decay_risk_score=decay_risk_score,
    )
    proxy_advisory = _derive_proxy_advisory(
        attention_capture_score=attention_capture_score,
        narrative_cohesion_score=narrative_cohesion_score,
        persistence_score=persistence_score,
        novelty_score=novelty_score,
        saturation_risk_score=saturation_risk_score,
        decay_risk_score=decay_risk_score,
        capital_relevance_score=capital_relevance_score,
        overall_attention_proxy_score=overall_attention_proxy_score,
    )
    (
        attention_state,
        narrative_state,
        proxy_advisory,
        additional_risks,
        additional_governance_notes,
    ) = _apply_honesty_overrides(
        input_mode=input_mode.lower(),
        attention_state=attention_state,
        narrative_state=narrative_state,
        proxy_advisory=proxy_advisory,
        proxy_confidence=proxy_confidence,
    )
    reasons = _derive_reasons(
        attention_capture_score=attention_capture_score,
        narrative_cohesion_score=narrative_cohesion_score,
        spreadability_score=spreadability_score,
        persistence_score=persistence_score,
        capital_relevance_score=capital_relevance_score,
    )
    risks = _derive_risks(
        saturation_risk_score=saturation_risk_score,
        decay_risk_score=decay_risk_score,
        capital_relevance_score=capital_relevance_score,
        proxy_confidence=proxy_confidence,
        input_mode=input_mode.lower(),
    )
    for risk in additional_risks:
        _append_unique(risks, risk)
    governance_notes = list(DEFAULT_GOVERNANCE_NOTES)
    if input_mode.lower() == "seeded_demo":
        governance_notes.append(
            "Current result uses seeded/demo heuristics and local runtime context where live engagement telemetry is absent."
        )
    for note in additional_governance_notes:
        _append_unique(governance_notes, note)
    recommended_interpretation = (
        f"{proxy_advisory}. Treat this as a monitoring input before validation, tagging, or action."
    )

    enriched_score_inputs = dict(score_inputs)
    enriched_score_inputs["input_mode"] = input_mode
    enriched_score_inputs["missing_input_count"] = len(missing_inputs)

    return AttentionProxyResult(
        signal_id=_text(input_data.signal_id),
        ticker=_text(input_data.ticker).upper(),
        input_mode=input_mode,
        attention_capture_score=_safe_round(attention_capture_score),
        narrative_cohesion_score=_safe_round(narrative_cohesion_score),
        spreadability_score=_safe_round(spreadability_score),
        persistence_score=_safe_round(persistence_score),
        novelty_score=_safe_round(novelty_score),
        saturation_risk_score=_safe_round(saturation_risk_score),
        decay_risk_score=_safe_round(decay_risk_score),
        capital_relevance_score=_safe_round(capital_relevance_score),
        overall_attention_proxy_score=_safe_round(overall_attention_proxy_score),
        attention_state=attention_state,
        narrative_state=narrative_state,
        proxy_confidence=_safe_round(proxy_confidence),
        confidence_band=confidence_band,
        proxy_advisory=proxy_advisory,
        recommended_interpretation=recommended_interpretation,
        narrative_heat_score=_safe_round(narrative_heat_score),
        narrative_exhaustion_score=_safe_round(narrative_exhaustion_score),
        reasons=reasons,
        risks=risks,
        missing_inputs=sorted(missing_inputs),
        assumptions=assumptions,
        governance_notes=governance_notes,
        score_inputs={
            key: (_safe_round(value) if isinstance(value, (int, float)) else value)
            for key, value in enriched_score_inputs.items()
        },
        metadata=metadata,
    )


def _as_of_datetime(as_of: datetime | None = None) -> datetime:
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            return as_of.replace(tzinfo=timezone.utc)
        return as_of
    run_started_at = _text(get_run_started_at())
    if run_started_at:
        try:
            return datetime.fromisoformat(run_started_at)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def build_attention_proxy_inputs_from_runtime(
    runtime_state: dict[str, Any] | None,
    *,
    trend_report: dict[str, Any] | None = None,
    as_of: datetime | None = None,
) -> list[AttentionProxyInput]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    rows = state.get("per_signal_attribution", [])
    if not isinstance(rows, list):
        return []

    as_of_dt = _as_of_datetime(as_of)
    persistence_map = _persistence_by_ticker(trend_report)
    inputs: list[AttentionProxyInput] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _text(row.get("ticker")).upper()
        signal_id = _text(row.get("signal_id"))
        if not ticker:
            continue

        source_type = _infer_source_type(row)
        source_profile = _source_profile(source_type)
        persistence_count = persistence_map.get(ticker, 0)
        text_signal = _text(row.get("text_signal") or row.get("question")) or None
        content_modality = _text(row.get("content_modality")).lower() or None
        provided_fields = [
            field
            for field in INPUT_SIGNAL_FIELDS
            if getattr(
                AttentionProxyInput(
                    text_signal=text_signal,
                    source_type=source_type,
                    sentiment_score=_coerce_float(row.get("sentiment_score")),
                    novelty_score=_coerce_float(row.get("novelty_score")),
                    engagement_count=_coerce_float(row.get("engagement_count")),
                    engagement_velocity=_coerce_float(row.get("engagement_velocity")),
                    engagement_acceleration=_coerce_float(
                        row.get("engagement_acceleration")
                    ),
                    source_credibility=_coerce_float(row.get("source_credibility")),
                    content_modality=content_modality,
                    network_spread_proxy=_coerce_float(row.get("network_spread_proxy")),
                    trend_persistence_proxy=_coerce_float(
                        row.get("trend_persistence_proxy")
                    ),
                    event_alignment_score=_coerce_float(
                        row.get("event_alignment_score")
                    ),
                    market_theme_alignment=_coerce_float(
                        row.get("market_theme_alignment")
                    ),
                    time_since_first_observed_minutes=_coerce_float(
                        row.get("time_since_first_observed_minutes")
                    ),
                ),
                field,
            )
            not in {None, ""}
        ]

        inferred_fields: list[str] = []
        assumptions: list[str] = []

        def infer_if_missing(
            field_name: str,
            current_value: float | str | None,
            new_value: Any,
            note: str,
        ) -> Any:
            if current_value not in {None, ""}:
                return current_value
            if new_value in {None, ""}:
                return current_value
            _append_unique(inferred_fields, field_name)
            _append_unique(assumptions, note)
            return new_value

        source_credibility = infer_if_missing(
            "source_credibility",
            _coerce_float(row.get("source_credibility")),
            source_profile["credibility"],
            "source_credibility inferred from source_type classification.",
        )
        trend_persistence = infer_if_missing(
            "trend_persistence_proxy",
            _coerce_float(row.get("trend_persistence_proxy")),
            _clamp(persistence_count / 6.0) if persistence_count > 0 else 0.32,
            "trend_persistence_proxy inferred from local snapshot streaks.",
        )
        time_since_first_observed_minutes = infer_if_missing(
            "time_since_first_observed_minutes",
            _coerce_float(row.get("time_since_first_observed_minutes")),
            _minutes_since_signal(signal_id, as_of_dt),
            "time_since_first_observed_minutes estimated from signal_id clock heuristic.",
        )
        if content_modality is None:
            content_modality = infer_if_missing(
                "content_modality",
                content_modality,
                "text" if text_signal else "unknown",
                "content_modality defaulted because no media metadata hook is attached.",
            )
        if text_signal is None:
            _append_unique(
                assumptions,
                "No external text signal is attached; text-derived features use neutral baselines.",
            )

        telemetry_measured = [
            field for field in TELEMETRY_FIELDS if field in provided_fields
        ]
        input_mode = "external_augmented" if telemetry_measured else "seeded_demo"
        if text_signal is not None and input_mode == "seeded_demo":
            input_mode = "offline_inferred"

        telemetry_coverage = len(telemetry_measured) / len(TELEMETRY_FIELDS)
        inferred_input_ratio = len(inferred_fields) / len(INPUT_SIGNAL_FIELDS)
        state_overlap_fields = sorted(
            set(inferred_fields).intersection(STATE_DERIVED_INFERENCE_FIELDS)
        )

        metadata = {
            "source_name": _text(row.get("source_name")),
            "signal_origin": _text(row.get("signal_origin")),
            "origin_label": _text(row.get("origin_label")),
            "condition_id": _text(row.get("condition_id")),
            "question": _text(row.get("question")),
            "status": _text(row.get("status")).upper(),
            "watchlist_tier": _text(row.get("watchlist_tier")).upper(),
            "pre_entry_state": _text(row.get("pre_entry_state")).upper(),
            "candidate_conversion_state": _text(
                row.get("candidate_conversion_state")
            ).upper(),
            "simulation_scenario": _text(
                state.get("simulation_context", {}).get("scenario")
            ).upper()
            or "LIVE",
            "input_mode": input_mode,
            "provided_fields": sorted(provided_fields),
            "inferred_fields": sorted(inferred_fields),
            "measured_fields": sorted(telemetry_measured),
            "telemetry_coverage": _safe_round(telemetry_coverage),
            "inferred_input_ratio": _safe_round(inferred_input_ratio),
            "state_overlap_fields": state_overlap_fields,
            "preseed_assumptions": assumptions,
        }
        inputs.append(
            AttentionProxyInput(
                signal_id=signal_id,
                ticker=ticker,
                text_signal=text_signal,
                source_type=source_type,
                sentiment_score=_coerce_float(row.get("sentiment_score")),
                novelty_score=_coerce_float(row.get("novelty_score")),
                engagement_count=_coerce_float(row.get("engagement_count")),
                engagement_velocity=_coerce_float(row.get("engagement_velocity")),
                engagement_acceleration=_coerce_float(
                    row.get("engagement_acceleration")
                ),
                source_credibility=_coerce_float(source_credibility),
                content_modality=content_modality,
                network_spread_proxy=_coerce_float(row.get("network_spread_proxy")),
                trend_persistence_proxy=_coerce_float(trend_persistence),
                event_alignment_score=_coerce_float(row.get("event_alignment_score")),
                market_theme_alignment=_coerce_float(
                    row.get("market_theme_alignment")
                ),
                time_since_first_observed_minutes=_coerce_float(
                    time_since_first_observed_minutes
                ),
                metadata=metadata,
            )
        )

    return inputs


def build_attention_proxy_report(
    runtime_state: dict[str, Any] | None,
    *,
    trend_report: dict[str, Any] | None = None,
    attention_inputs: list[AttentionProxyInput] | None = None,
    weights: dict[str, dict[str, float]] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = False,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    resolved_inputs = (
        attention_inputs
        if isinstance(attention_inputs, list)
        else build_attention_proxy_inputs_from_runtime(
            state,
            trend_report=trend_report,
            as_of=as_of,
        )
    )
    results = [
        build_attention_proxy_result(item, weights=weights).to_dict()
        for item in resolved_inputs
    ]
    results.sort(
        key=lambda item: (
            -float(item["overall_attention_proxy_score"]),
            -float(item["capital_relevance_score"]),
            item["ticker"],
        )
    )
    attention_state_counts: dict[str, int] = {}
    narrative_state_counts: dict[str, int] = {}
    confidence_band_counts: dict[str, int] = {}
    input_mode_counts: dict[str, int] = {}
    for row in results:
        attention_state = _text(row.get("attention_state"))
        narrative_state = _text(row.get("narrative_state"))
        confidence_band = _text(row.get("confidence_band"))
        input_mode = _text(row.get("input_mode"))
        if attention_state:
            attention_state_counts[attention_state] = attention_state_counts.get(
                attention_state, 0
            ) + 1
        if narrative_state:
            narrative_state_counts[narrative_state] = narrative_state_counts.get(
                narrative_state, 0
            ) + 1
        if confidence_band:
            confidence_band_counts[confidence_band] = confidence_band_counts.get(
                confidence_band, 0
            ) + 1
        if input_mode:
            input_mode_counts[input_mode] = input_mode_counts.get(input_mode, 0) + 1

    top = results[0] if results else None
    top_attention_candidates = [
        {
            "ticker": row["ticker"],
            "signal_id": row["signal_id"],
            "overall_attention_proxy_score": row["overall_attention_proxy_score"],
            "attention_state": row["attention_state"],
            "narrative_state": row["narrative_state"],
            "confidence_band": row["confidence_band"],
            "proxy_advisory": row["proxy_advisory"],
        }
        for row in results[:5]
    ]
    telemetry_backed_signal_count = sum(
        1
        for row in results
        if isinstance(row.get("metadata"), dict)
        and row["metadata"].get("measured_fields")
    )
    inferred_signal_count = sum(
        1
        for row in results
        if isinstance(row.get("metadata"), dict)
        and row["metadata"].get("inferred_fields")
    )
    state_overlap_signal_count = sum(
        1
        for row in results
        if isinstance(row.get("metadata"), dict)
        and row["metadata"].get("state_overlap_fields")
    )
    observability = {
        "telemetry_backed_signal_count": telemetry_backed_signal_count,
        "inferred_signal_count": inferred_signal_count,
        "state_overlap_signal_count": state_overlap_signal_count,
        "low_confidence_signal_count": confidence_band_counts.get("LOW", 0),
        "telemetry_backed_ratio": _safe_round(
            telemetry_backed_signal_count / len(results)
        )
        if results
        else 0.0,
        "note": (
            "Telemetry-backed inputs are preferred. Inferred fields should reduce confidence "
            "and should not be read as independent evidence."
        ),
    }
    governance_notes = list(DEFAULT_GOVERNANCE_NOTES)
    if telemetry_backed_signal_count == 0 and results:
        governance_notes.append(
            "No telemetry-backed rows are present in this report; attention states remain heuristic monitoring labels."
        )
    if state_overlap_signal_count > 0:
        governance_notes.append(
            "Some rows rely on state-derived proxy inputs; treat those rows as lower-integrity diagnostics."
        )
    report = {
        "artifact_kind": "attention_proxy_report",
        "generated_at": _as_of_datetime(as_of).isoformat(timespec="seconds"),
        "source_mode": get_source_mode(),
        "attention_proxy_state": top["attention_state"] if top else "UNAVAILABLE",
        "attention_proxy_score": top["overall_attention_proxy_score"] if top else None,
        "attention_proxy_confidence": top["confidence_band"] if top else "LOW",
        "attention_proxy_confidence_score": top["proxy_confidence"] if top else 0.0,
        "narrative_proxy_advisory": top["proxy_advisory"] if top else "no_attention_inputs_scored",
        "recommended_interpretation": (
            top["recommended_interpretation"]
            if top
            else "No signal rows were available for attention proxy scoring."
        ),
        "scored_signal_count": len(results),
        "high_attention_candidate_count": sum(
            1
            for row in results
            if row["attention_state"] in {"HIGH_HEAT", "ATTENTION_BEARING"}
        ),
        "attention_state_counts": dict(sorted(attention_state_counts.items())),
        "narrative_state_counts": dict(sorted(narrative_state_counts.items())),
        "confidence_band_counts": dict(sorted(confidence_band_counts.items())),
        "input_mode_counts": dict(sorted(input_mode_counts.items())),
        "observability": observability,
        "top_attention_candidates": top_attention_candidates,
        "signals": results,
        "governance_notes": governance_notes,
        "note": (
            "Attention proxy is an offline-first scoring layer that estimates attention-bearing, "
            "narrative-forming, spreadable, persistent, and capital-relevant conditions. "
            "It is not a live virality claim and it does not trigger execution."
        ),
    }
    if write_runtime:
        write_json_atomic(output_path or ATTENTION_PROXY_REPORT_PATH, report)
    return report
