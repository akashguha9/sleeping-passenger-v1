"""Static prior reliabilities by source_type.

These are conservative seed values used by the scoring layer. They reflect
machine readability + legal ingestion + timestamp quality + predictive value
priors for each class of source. They are *not* live calibrations.
"""
from __future__ import annotations

PRIOR_RELIABILITY: dict[str, float] = {
    "official_filing": 0.95,
    "regulator_disclosure": 0.92,
    "prediction_market": 0.65,
    "onchain": 0.75,
    "market_data": 0.80,
    "news_event": 0.55,
    "interpretation": 0.40,
    "portfolio_truth": 1.0,
    "unknown": 0.30,
}


def reliability_for(source_type: str) -> float:
    return PRIOR_RELIABILITY.get(source_type, PRIOR_RELIABILITY["unknown"])
