"""Interpretation Quality Score (IQS) — P1 interpretation-defense module.

Ships the reflection thesis "data is not truth until interpreted correctly"
(see docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md) as real advisory code. IQS
scores whether a *clean fresh-discovery* candidate is being interpreted cleanly
or trashily — not whether to trade it.

    IQS = w_P*P + w_C*C + w_R*R - w_A*A - w_X*X      (clamped to [0,1], ×100)

      P = provenance quality          C = context completeness
      R = source reliability          A = ambiguity risk
      X = contradiction intensity

Weight note: the reflection suggests positive weights 0.30/0.25/0.20 (sum 0.75)
and penalties 0.15/0.10. Taken literally the score could never exceed 75, so the
80–100 HIGH band would be unreachable. We therefore RENORMALIZE the positive
weights to sum to 1.0 while preserving their 6:5:4 ratio (provenance > context >
reliability) and keep the penalty magnitudes as given. This is a disclosed,
deliberate adjustment so the grade bands are coherent.

Inputs come ONLY from clean Fresh-Discovery provenance (plus optional model-lane
/ aggregator contradiction signals). This module never invents a candidate and
never authorises execution. Advisory-only. Pure module.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import LIVE_EVIDENCE_TYPES, VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import LIVE_EVIDENCE_TYPES, VERIFIED_LIVE


# Positive weights renormalised to sum 1.0 (ratio 6:5:4); penalties as given.
IQS_WEIGHTS = {
    "provenance": 0.40,
    "context": 0.3333,
    "reliability": 0.2667,
    "ambiguity": 0.15,
    "contradiction": 0.10,
}

GRADE_HIGH = "HIGH"
GRADE_MEDIUM = "MEDIUM"
GRADE_LOW = "LOW"
GRADE_TRASHY = "TRASHY_INTERPRETATION_RISK"

_PROVENANCE_FLAGS = ("from_cache", "from_fallback", "from_moltbook", "from_trade_log")

# Context fields whose presence makes interpretation cleaner.
_CONTEXT_FIELDS = (
    "country", "sector", "theme", "source_payload", "evidence_type",
    "generated_at", "last_live_seen_date", "live_evidence_count",
    "catalyst", "invalidation_condition",
)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _known(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and text not in {"UNKNOWN", "NONE", "MISSING / NOT PROVIDED", "MISSING"}


def _is_revalidated_today(candidate: dict[str, Any], run_date: str | None) -> bool:
    return (
        candidate.get("source_health") == VERIFIED_LIVE
        and candidate.get("is_live") is True
        and candidate.get("evidence_type") in LIVE_EVIDENCE_TYPES
        and bool(run_date)
        and str(candidate.get("last_live_seen_date")) == str(run_date)
    )


def _catalyst_value(candidate: dict[str, Any]) -> Any:
    return candidate.get("catalyst") or candidate.get("why_today")


def _provenance_quality(candidate: dict[str, Any]) -> float:
    if int(candidate.get("live_evidence_count") or 0) <= 0:
        return 0.0
    p = 1.0
    if candidate.get("source_health") != VERIFIED_LIVE:
        p -= 0.6
    if candidate.get("is_live") is not True:
        p -= 0.6
    if candidate.get("evidence_type") not in LIVE_EVIDENCE_TYPES:
        p -= 0.4
    for flag in _PROVENANCE_FLAGS:
        if candidate.get(flag) is True:
            p -= 0.5
    return _clamp01(p)


def _context_completeness(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    present = 0
    missing: list[str] = []
    for field in _CONTEXT_FIELDS:
        if field == "catalyst":
            ok = _known(_catalyst_value(candidate))
        elif field == "live_evidence_count":
            ok = int(candidate.get("live_evidence_count") or 0) >= 1
        elif field == "evidence_type":
            ok = candidate.get("evidence_type") in LIVE_EVIDENCE_TYPES
        else:
            ok = _known(candidate.get(field))
        if ok:
            present += 1
        else:
            missing.append(field)
    return round(present / len(_CONTEXT_FIELDS), 6), missing


def _source_reliability(candidate: dict[str, Any], reliability_hint: float | None) -> float:
    if reliability_hint is not None:
        return _clamp01(float(reliability_hint))
    r = 0.8 if candidate.get("source_health") == VERIFIED_LIVE else 0.25
    if int(candidate.get("live_evidence_count") or 0) >= 2:
        r += 0.2
    if candidate.get("evidence_type") == "LIVE_FILING_EVENT":
        r += 0.05
    return _clamp01(r)


def _ambiguity_risk(candidate: dict[str, Any], split_vote: bool) -> tuple[float, list[str]]:
    a = 0.0
    warnings: list[str] = []
    evidence_type = candidate.get("evidence_type")
    has_catalyst = _known(_catalyst_value(candidate))
    if evidence_type == "LIVE_PRICE_MOVER" and not has_catalyst:
        a += 0.25
        warnings.append("generic_price_mover_without_named_catalyst")
    if not _known(candidate.get("theme")):
        a += 0.20
        warnings.append("vague_or_missing_theme")
    if not has_catalyst:
        a += 0.20
        warnings.append("missing_why_today")
    if not _known(candidate.get("source_payload")):
        a += 0.15
        warnings.append("missing_source_payload")
    if split_vote:
        a += 0.20
        warnings.append("model_lanes_disagree")
    return _clamp01(a), warnings


def _contradiction_from_models(ticker: str, model_outputs: list[dict[str, Any]] | None) -> tuple[float, list[str]]:
    if not model_outputs:
        return 0.0, []
    ticker = normalize_ticker(ticker)
    positive = avoid = rejected = violations = 0
    for out in model_outputs:
        for key in ("manual_consideration", "watch"):
            if any(normalize_ticker(i.get("ticker")) == ticker for i in out.get(key, [])):
                positive += 1
                break
        for key in ("avoid", "risk_blocks"):
            if any(normalize_ticker(i.get("ticker")) == ticker for i in out.get(key, [])):
                avoid += 1
                break
        if any(
            normalize_ticker(i.get("ticker") if isinstance(i, dict) else i) == ticker
            for i in out.get("rejected_due_to_missing_evidence", [])
        ):
            rejected += 1
        if any(v.get("ticker") == ticker for v in out.get("provenance_violations_detected", [])):
            violations += 1
    n = max(len(model_outputs), 1)
    split = 1.0 if (positive and avoid) else 0.0
    x = 0.5 * split + 0.3 * (rejected / n) + 0.2 * (1.0 if violations else 0.0)
    flags: list[str] = []
    if split:
        flags.append("split_vote_manual_vs_avoid")
    if rejected:
        flags.append("models_flagged_missing_evidence")
    if violations:
        flags.append("model_output_provenance_violation")
    return _clamp01(x), flags


def score_interpretation_quality(
    candidate: dict[str, Any],
    *,
    run_date: str | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
    aggregator_row: dict[str, Any] | None = None,
    reliability_hint: float | None = None,
) -> dict[str, Any]:
    """Return the IQS record for one clean fresh-discovery candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    run_date = run_date or candidate.get("last_live_seen_date")

    split_vote = bool(aggregator_row.get("split_vote")) if aggregator_row else False
    x_models, contradiction_flags = _contradiction_from_models(ticker, model_outputs)
    if aggregator_row:
        x = _clamp01(max(x_models, 0.5 * float(aggregator_row.get("avg_contradiction_risk") or 0.0)
                         + (0.3 if split_vote else 0.0)))
    else:
        x = x_models

    p = _provenance_quality(candidate)
    c, missing_context = _context_completeness(candidate)
    r = _source_reliability(candidate, reliability_hint)
    a, ambiguity_warnings = _ambiguity_risk(candidate, split_vote)

    w = IQS_WEIGHTS
    raw = (
        w["provenance"] * p
        + w["context"] * c
        + w["reliability"] * r
        - w["ambiguity"] * a
        - w["contradiction"] * x
    )
    score = round(100.0 * _clamp01(raw), 4)

    # ----- Hard caps (fail-closed) -----
    warnings = list(ambiguity_warnings)
    revalidated = _is_revalidated_today(candidate, run_date)
    if candidate.get("source_health") != VERIFIED_LIVE:
        score = min(score, 25.0)
        warnings.append("source_health_not_verified_live")
    if candidate.get("is_live") is not True:
        score = min(score, 25.0)
        warnings.append("not_live")
    if any(candidate.get(flag) is True for flag in _PROVENANCE_FLAGS) and not revalidated:
        score = min(score, 20.0)
        warnings.append("non_live_provenance_without_revalidation")
    if candidate.get("evidence_type") not in LIVE_EVIDENCE_TYPES:
        score = min(score, 25.0)
        warnings.append("evidence_type_not_live")
    if int(candidate.get("live_evidence_count") or 0) == 0:
        score = 0.0
        warnings.append("no_live_evidence")

    grade = _grade(score)

    return {
        "ticker": ticker,
        "interpretation_quality_score": round(score, 4),
        "grade": grade,
        "provenance_quality": round(p, 6),
        "context_completeness": round(c, 6),
        "source_reliability": round(r, 6),
        "ambiguity_risk": round(a, 6),
        "contradiction_intensity": round(x, 6),
        "missing_context_fields": missing_context,
        "contradiction_flags": contradiction_flags,
        "interpretation_warnings": warnings,
        "advisory_only": True,
    }


def _grade(score: float) -> str:
    if score >= 80:
        return GRADE_HIGH
    if score >= 60:
        return GRADE_MEDIUM
    if score >= 40:
        return GRADE_LOW
    return GRADE_TRASHY


__all__ = [
    "IQS_WEIGHTS",
    "GRADE_HIGH",
    "GRADE_MEDIUM",
    "GRADE_LOW",
    "GRADE_TRASHY",
    "score_interpretation_quality",
]
