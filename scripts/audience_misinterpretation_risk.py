"""Audience Misinterpretation Risk (AMR) — P2 interpretation-defense module.

Ships the reflection thesis "a signal can be real and still mean the wrong thing"
(see docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md). Estimates how likely a stock
signal / thesis / metric is to be MISREAD across audiences (retail,
institutional, media, operator, model lanes).

    AMR = w1*ambiguity + w2*narrative_gap + w3*amplification
        + w4*model_agreement_without_live_evidence + w5*vague_term_load

Higher = more likely to be misunderstood. Can only warn / demote. Pure module,
advisory-only.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import LIVE_EVIDENCE_TYPES, VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import LIVE_EVIDENCE_TYPES, VERIFIED_LIVE


GRADE_LOW = "LOW"
GRADE_MEDIUM = "MEDIUM"
GRADE_HIGH = "HIGH"
GRADE_MISREAD = "MISREAD_LIKELY"

# Vague rhetoric that invites misreading when not backed by precise evidence.
_VAGUE_TERMS = (
    "AI", "DEFENSE BOOM", "REARMAMENT", "CLOUD", "BREAKOUT", "STRUCTURAL WINNER",
    "QUALITY COMPOUNDER", "CHEAP", "OVERSOLD", "MOMENTUM", "GEOPOLITICAL HEDGE",
    "MULTIBAGGER", "NEXT BIG", "THEME PLAY",
)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _known(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and text not in {"UNKNOWN", "NONE", "MISSING"}


def _thesis_blob(candidate: dict[str, Any], model_outputs: list[dict[str, Any]] | None) -> str:
    parts = [str(candidate.get(k) or "") for k in ("catalyst", "why_today", "theme", "sector")]
    ticker = normalize_ticker(candidate.get("ticker"))
    for out in model_outputs or []:
        for key in ("manual_consideration", "watch", "wait", "avoid", "risk_blocks"):
            for item in out.get(key, []):
                if normalize_ticker(item.get("ticker")) == ticker:
                    parts.append(str(item.get("reason") or ""))
    return " ".join(parts).upper()


def _model_agreement_without_live(ticker: str, candidate: dict[str, Any],
                                  model_outputs: list[dict[str, Any]] | None) -> float:
    """High when models promote but the live evidence is thin (price-mover only,
    no named catalyst) — agreement mistaken for truth."""
    if not model_outputs:
        return 0.0
    ticker = normalize_ticker(ticker)
    promoted = sum(
        1 for out in model_outputs
        if any(normalize_ticker(i.get("ticker")) == ticker
               for k in ("manual_consideration", "watch") for i in out.get(k, []))
    )
    agree = promoted / max(len(model_outputs), 1)
    thin_evidence = (
        candidate.get("evidence_type") == "LIVE_PRICE_MOVER"
        and not _known(candidate.get("catalyst") or candidate.get("why_today"))
    ) or int(candidate.get("live_evidence_count") or 0) < 1
    return agree if thin_evidence else 0.0


def score_audience_misinterpretation(
    candidate: dict[str, Any],
    *,
    p1: dict[str, Any] | None = None,
    narrative_gap: dict[str, Any] | None = None,
    distribution: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the AMR record for one clean fresh-discovery candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    misread_flags: list[str] = []
    missing_context: list[str] = []
    warnings: list[str] = []

    if candidate.get("is_live") is not True or candidate.get("source_health") != VERIFIED_LIVE:
        misread_flags.append("static_or_stale_could_be_mistaken_for_fresh")

    # Ambiguity — reuse IQS ambiguity if available, else infer.
    ambiguity = 0.0
    if p1:
        ambiguity = float((p1.get("interpretation_quality") or {}).get("ambiguity_risk") or 0.0)
        for w in (p1.get("interpretation_quality") or {}).get("missing_context_fields", []):
            missing_context.append(w)
    if not _known(candidate.get("catalyst") or candidate.get("why_today")):
        ambiguity = max(ambiguity, 0.5)
        misread_flags.append("missing_catalyst_invites_misread")

    nsg_pos = max(float((narrative_gap or {}).get("narrative_substance_gap") or 0.0), 0.0) / 100.0
    da = float((distribution or {}).get("distribution_amplification_score") or 0.0) / 100.0
    agree_without_live = _model_agreement_without_live(ticker, candidate, model_outputs)
    if agree_without_live > 0:
        misread_flags.append("model_agreement_without_strong_live_evidence")

    blob = _thesis_blob(candidate, model_outputs)
    ambiguous_terms = sorted({t for t in _VAGUE_TERMS if t in blob})
    vague_load = _clamp01(len(ambiguous_terms) / 3.0)
    # Vague terms only count against you when evidence is not specific.
    specific = candidate.get("evidence_type") == "LIVE_FILING_EVENT" and _known(candidate.get("catalyst"))
    if specific:
        vague_load *= 0.3

    amr = (
        0.25 * ambiguity
        + 0.20 * nsg_pos
        + 0.15 * da
        + 0.20 * agree_without_live
        + 0.20 * vague_load
    )
    score = round(100.0 * _clamp01(amr), 4)
    grade = _grade(score)

    audience_risks = {
        "retail": "HIGH" if (da >= 0.5 or vague_load >= 0.5) else "MEDIUM" if score >= 40 else "LOW",
        "institutional": "MEDIUM" if nsg_pos >= 0.4 else "LOW",
        "media": "HIGH" if da >= 0.5 else "LOW",
        "operator": "HIGH" if (candidate.get("is_live") is True and ambiguity >= 0.5) else "MEDIUM" if score >= 40 else "LOW",
        "model": "HIGH" if agree_without_live > 0 else "LOW",
    }
    # Operator misread risk is explicit when the signal is live but incomplete.
    if candidate.get("is_live") is True and (ambiguity >= 0.5 or missing_context):
        misread_flags.append("operator_misread_risk_live_but_incomplete")

    return {
        "ticker": ticker,
        "audience_misinterpretation_risk": score,
        "grade": grade,
        "audience_risks": audience_risks,
        "ambiguous_terms": ambiguous_terms,
        "misread_flags": misread_flags,
        "missing_context_fields": sorted(set(missing_context)),
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
    return GRADE_MISREAD


__all__ = [
    "GRADE_LOW",
    "GRADE_MEDIUM",
    "GRADE_HIGH",
    "GRADE_MISREAD",
    "score_audience_misinterpretation",
]
