"""Distribution Amplification Detector (DA) — P2 interpretation-defense module.

Ships the reflection thesis "distribution can make weak substance look powerful"
(see docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md). Detects when visibility /
attention is driving perceived value more than substance. Conceptual lineage:
scripts/propagation_spread_estimator.py (spread probability) and
scripts/echo_risk_engine.py (independent confirmation vs echo amplification); DA
is the candidate-level "attention vs fundamentals" ratio on the clean payload.

    DA_raw = attention_growth / max(fundamental_improvement, eps)
    score  = 100 * clamp(log1p(DA_raw) / log1p(max_da), 0, 1)

Data honesty: attention / fundamentals feeds are usually absent for fresh
discovery. DA does not fabricate them — it derives weak proxies from
evidence_type and marks missing fields. A non-live candidate is NOT scored as
live. The module can only warn / demote; it never promotes. Advisory-only.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import VERIFIED_LIVE


GRADE_LOW = "LOW"
GRADE_MEDIUM = "MEDIUM"
GRADE_HIGH = "HIGH"
GRADE_HYPE_LED = "HYPE_LED"

_EPS = 1e-6
_MAX_DA = 20.0

_ATTENTION_FIELDS = ("social_velocity", "news_velocity", "search_spike", "price_move", "volume_move")
_FUNDAMENTAL_FIELDS = ("earnings_growth", "revenue_growth", "margin_improvement", "filing_materiality")


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _mean_present(data: dict[str, Any], fields: tuple[str, ...]) -> tuple[float, bool]:
    vals = [_clamp01(float(data[f])) for f in fields if data.get(f) is not None]
    return (sum(vals) / len(vals), True) if vals else (0.0, False)


def _is_live(candidate: dict[str, Any]) -> bool:
    return candidate.get("is_live") is True and candidate.get("source_health") == VERIFIED_LIVE


def score_distribution_amplification(
    candidate: dict[str, Any],
    *,
    attention: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the DA record for one clean fresh-discovery candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    flags: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []

    if not _is_live(candidate):
        return {
            "ticker": ticker,
            "distribution_amplification_score": 0.0,
            "grade": GRADE_LOW,
            "attention_growth": 0.0,
            "fundamental_improvement": 0.0,
            "organic_vs_paid_confidence": "MISSING",
            "attention_quality": "MISSING",
            "amplification_flags": ["not_live_not_scored"],
            "missing_fields": ["live_evidence"],
            "warnings": ["candidate is not live; not scored as live distribution"],
            "advisory_only": True,
        }

    attention = dict(attention or {})
    fundamentals = dict(fundamentals or {})
    evidence_type = candidate.get("evidence_type")

    # Attention growth — real feed if present, else a weak evidence-type proxy.
    att, att_present = _mean_present(attention, _ATTENTION_FIELDS)
    if not att_present:
        att = {"LIVE_PRICE_MOVER": 0.6, "LIVE_NEWS_EVENT": 0.5, "LIVE_FILING_EVENT": 0.4}.get(evidence_type, 0.3)
        if int(candidate.get("live_evidence_count") or 0) >= 2:
            att = min(1.0, att + 0.1)
        missing.append("attention_feed")
        warnings.append("no attention feed; using evidence-type proxy")
    attention_growth = _clamp01(att)

    # Fundamental improvement — real feed if present, else weak evidence proxy.
    fund, fund_present = _mean_present(fundamentals, _FUNDAMENTAL_FIELDS)
    if not fund_present:
        fund = {"LIVE_FILING_EVENT": 0.5, "LIVE_NEWS_EVENT": 0.3, "LIVE_PRICE_MOVER": 0.1}.get(evidence_type, 0.1)
        missing.append("fundamental_improvement")
        warnings.append("no fundamentals feed; substance under-evidenced")
    fundamental_improvement = _clamp01(fund)

    da_raw = attention_growth / max(fundamental_improvement, _EPS)
    score = round(100.0 * _clamp01(math.log1p(da_raw) / math.log1p(_MAX_DA)), 4)

    organic_conf = "HIGH" if attention.get("organic_ratio") is not None else "MISSING"
    att_quality = str(attention.get("quality") or "MISSING").upper()
    if att_quality not in ("HIGH", "MEDIUM", "LOW"):
        att_quality = "MISSING"

    # Grade — HYPE_LED when attention runs ahead with little/no substance.
    hype_led = attention_growth >= 0.5 and fundamental_improvement < 0.25
    if hype_led:
        grade = GRADE_HYPE_LED
        score = max(score, 76.0)
        flags.append("attention_ahead_of_substance")
    else:
        grade = _grade(score)
    if not fund_present:
        flags.append("substance_unevidenced")

    return {
        "ticker": ticker,
        "distribution_amplification_score": round(score, 4),
        "grade": grade,
        "attention_growth": round(attention_growth, 6),
        "fundamental_improvement": round(fundamental_improvement, 6),
        "organic_vs_paid_confidence": organic_conf,
        "attention_quality": att_quality,
        "amplification_flags": flags,
        "missing_fields": missing,
        "warnings": warnings,
        "advisory_only": True,
    }


def _grade(score: float) -> str:
    if score <= 25:
        return GRADE_LOW
    if score <= 50:
        return GRADE_MEDIUM
    if score <= 75:
        return GRADE_HIGH
    return GRADE_HYPE_LED


__all__ = [
    "GRADE_LOW",
    "GRADE_MEDIUM",
    "GRADE_HIGH",
    "GRADE_HYPE_LED",
    "score_distribution_amplification",
]
