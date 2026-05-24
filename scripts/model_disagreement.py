"""Model disagreement value — use cross-model spread intelligently.

Five independent models (GPT, Claude, Gemini, Grok, Mistral) may each score a
ticker. Fake consensus is dangerous; honest disagreement is information. For a
ticker t with the available model scores:

    mu(t)                   = mean(scores)
    DisagreementScore(t)    = variance(scores)            (population variance)
    DisagreementStd(t)      = sqrt(variance)
    NormalizedDisagreement  = min(1, std / 0.50)

Interpretation:
    < 0.15  low      0.15..0.35  medium      >= 0.35  high

Consensus quality:
    high mean + low disagreement   -> CLEAN_CONSENSUS
    high mean + high disagreement  -> HIGH_CONVICTION_DISAGREEMENT (research)
    low mean  + high disagreement  -> UNCERTAIN_OR_CONFLICTED (wait/avoid)
    fewer than 2 scores            -> INSUFFICIENT_CROSS_MODEL_COVERAGE

Pure module: no I/O.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.daily_discovery_config import load_discovery_thresholds
    from scripts.daily_payload import normalize_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_discovery_config import load_discovery_thresholds
    from daily_payload import normalize_ticker


MODELS = ("gpt", "claude", "gemini", "grok", "mistral")
DISAGREEMENT_STD_SCALE = 0.50


def _clean_scores(model_scores: dict[str, Any] | None) -> dict[str, float]:
    """Keep only models that actually produced a numeric score for t."""
    out: dict[str, float] = {}
    for model, value in (model_scores or {}).items():
        if value is None:
            continue
        try:
            out[str(model).strip().lower()] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _variance(values: list[float], mean: float) -> float:
    if not values:
        return 0.0
    return sum((v - mean) ** 2 for v in values) / len(values)


def classify_consensus(
    mean_score: float,
    normalized_disagreement: float,
    n: int,
    *,
    thresholds: dict[str, Any] | None = None,
) -> str:
    """Return the model_consensus_quality label."""
    if n < 2:
        return "INSUFFICIENT_CROSS_MODEL_COVERAGE"
    table = thresholds or load_discovery_thresholds()
    low_max = float(table.get("disagreement_low_max", 0.15))
    high_min = float(table.get("disagreement_high_min", 0.35))
    cqs_min = float(table.get("cqs_min", 0.70))
    low_mean = 0.55

    if mean_score >= cqs_min and normalized_disagreement < low_max:
        return "CLEAN_CONSENSUS"
    if mean_score >= cqs_min and normalized_disagreement >= high_min:
        return "HIGH_CONVICTION_DISAGREEMENT"
    if mean_score < low_mean and normalized_disagreement >= high_min:
        return "UNCERTAIN_OR_CONFLICTED"
    if normalized_disagreement < low_max:
        return "LOW_DISAGREEMENT"
    if normalized_disagreement >= high_min:
        return "HIGH_DISAGREEMENT"
    return "MEDIUM_DISAGREEMENT"


def compute_model_disagreement(
    ticker: str,
    model_scores: dict[str, Any] | None,
    *,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the full disagreement record for one ticker."""
    scores_map = _clean_scores(model_scores)
    values = list(scores_map.values())
    n = len(values)
    mean = round(sum(values) / n, 4) if n else 0.0
    variance = _variance(values, sum(values) / n if n else 0.0)
    std = math.sqrt(variance)
    normalized = min(1.0, std / DISAGREEMENT_STD_SCALE) if n else 0.0
    quality = classify_consensus(mean, normalized, n, thresholds=thresholds)
    return {
        "ticker": normalize_ticker(ticker),
        "model_scores": scores_map,
        "n_models": n,
        "mean_model_score": mean,
        "disagreement_variance": round(variance, 6),
        "disagreement_std": round(std, 4),
        "normalized_disagreement": round(normalized, 4),
        "model_consensus_quality": quality,
    }


def cross_model_agreement(model_scores: dict[str, Any] | None, total_models: int = 5) -> float:
    """models_mentioning_t / total_models."""
    n = len(_clean_scores(model_scores))
    return round(n / max(1, total_models), 4)


__all__ = [
    "MODELS",
    "DISAGREEMENT_STD_SCALE",
    "classify_consensus",
    "compute_model_disagreement",
    "cross_model_agreement",
]
