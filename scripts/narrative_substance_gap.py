"""Narrative-Substance Gap (NSG) — P2 interpretation-defense module.

Ships the reflection thesis "narrative without proof" — separate the story being
sold from the underlying economic/technical reality (see
docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md). Conceptual lineage:
scripts/narrative_structure_divergence.py (NS − SS) and
scripts/expectation_divergence_signal.py; NSG is the candidate-level analog on
the clean fresh-discovery payload.

    NSG = 100 * clamp(narrative_strength - substance_strength, -1, 1)

Negative = substance-led; positive = narrative-led. Data-honest: missing
fundamentals lower substance and are flagged, never invented. Can only warn /
demote. Advisory-only.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import VERIFIED_LIVE


GRADE_SUBSTANCE_LED = "SUBSTANCE_LED"
GRADE_BALANCED = "BALANCED"
GRADE_NARRATIVE_RICH = "NARRATIVE_RICH"
GRADE_NARRATIVE_OVERHANG = "NARRATIVE_OVERHANG"


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _known(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and text not in {"UNKNOWN", "NONE", "MISSING"}


def _catalyst(candidate: dict[str, Any]) -> Any:
    return candidate.get("catalyst") or candidate.get("why_today")


def _model_promotion(ticker: str, model_outputs: list[dict[str, Any]] | None) -> float:
    if not model_outputs:
        return 0.0
    ticker = normalize_ticker(ticker)
    promoted = 0
    for out in model_outputs:
        for key in ("manual_consideration", "watch"):
            if any(normalize_ticker(i.get("ticker")) == ticker for i in out.get(key, [])):
                promoted += 1
                break
    return promoted / max(len(model_outputs), 1)


def score_narrative_substance_gap(
    candidate: dict[str, Any],
    *,
    distribution: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
    p1: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the NSG record for one clean fresh-discovery candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    narrative_flags: list[str] = []
    substance_flags: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []

    if candidate.get("is_live") is not True or candidate.get("source_health") != VERIFIED_LIVE:
        return {
            "ticker": ticker,
            "narrative_substance_gap": 0.0,
            "grade": GRADE_BALANCED,
            "narrative_strength": 0.0,
            "substance_strength": 0.0,
            "narrative_flags": ["not_live_not_scored"],
            "substance_flags": [],
            "missing_fields": ["live_evidence"],
            "warnings": ["candidate is not live; not scored"],
            "advisory_only": True,
        }

    evidence_type = candidate.get("evidence_type")
    distribution = distribution or {}

    # Narrative strength — model promotion + attention + catalyst rhetoric.
    model_promo = _model_promotion(ticker, model_outputs)
    attention = float(distribution.get("attention_growth") or 0.0)
    narrative = 0.45 * model_promo + 0.35 * attention
    if not _known(_catalyst(candidate)):
        narrative += 0.20
        narrative_flags.append("narrative_without_named_catalyst")
    narrative_strength = _clamp01(narrative)

    # Substance strength — filing/fundamentals/evidence depth.
    substance_base = {"LIVE_FILING_EVENT": 0.7, "LIVE_NEWS_EVENT": 0.45, "LIVE_PRICE_MOVER": 0.25}.get(evidence_type, 0.1)
    fund_improve = float((distribution or {}).get("fundamental_improvement") or 0.0)
    fundamentals = fundamentals or {}
    has_fund = any(fundamentals.get(k) is not None for k in
                   ("earnings_growth", "revenue_growth", "margin_improvement", "filing_materiality"))
    substance = substance_base
    if has_fund:
        substance = 0.5 * substance_base + 0.5 * fund_improve
        substance_flags.append("fundamentals_present")
    else:
        missing.append("fundamentals")
        warnings.append("no fundamentals feed; substance under-evidenced")
    if int(candidate.get("live_evidence_count") or 0) >= 2:
        substance += 0.1
    # IQS provenance reinforces substance.
    if p1:
        iqs = (p1.get("interpretation_quality") or {}).get("provenance_quality")
        if iqs is not None:
            substance = 0.7 * substance + 0.3 * float(iqs)
    substance_strength = _clamp01(substance)

    nsg = round(100.0 * max(-1.0, min(1.0, narrative_strength - substance_strength)), 4)
    grade = _grade(nsg)
    if grade in (GRADE_NARRATIVE_RICH, GRADE_NARRATIVE_OVERHANG):
        narrative_flags.append("narrative_ahead_of_substance")

    return {
        "ticker": ticker,
        "narrative_substance_gap": nsg,
        "grade": grade,
        "narrative_strength": round(narrative_strength, 6),
        "substance_strength": round(substance_strength, 6),
        "narrative_flags": narrative_flags,
        "substance_flags": substance_flags,
        "missing_fields": missing,
        "warnings": warnings,
        "advisory_only": True,
    }


def _grade(nsg: float) -> str:
    if nsg <= -25:
        return GRADE_SUBSTANCE_LED
    if nsg < 25:
        return GRADE_BALANCED
    if nsg <= 60:
        return GRADE_NARRATIVE_RICH
    return GRADE_NARRATIVE_OVERHANG


__all__ = [
    "GRADE_SUBSTANCE_LED",
    "GRADE_BALANCED",
    "GRADE_NARRATIVE_RICH",
    "GRADE_NARRATIVE_OVERHANG",
    "score_narrative_substance_gap",
]
