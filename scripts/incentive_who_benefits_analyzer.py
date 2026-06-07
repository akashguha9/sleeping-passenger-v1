"""Incentive / Who-Benefits Analyzer — P2 interpretation-defense module.

Ships the reflection's firewall question: "who profits if I believe this signal?"
(see docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md). Conceptual lineage:
scripts/asymmetry_survival_scorer.py. Flags when a signal looks structured to
transfer value from the operator (late/retail) to insiders / promoters /
distributors — i.e. exit-liquidity risk.

Data honesty: ownership / insider / liquidity facts are usually absent. This
module NEVER fabricates ownership facts — it marks them unknown and falls back to
weak heuristic warnings (high amplification + high narrative gap + low substance
+ missing ownership context). Can only warn / demote. Advisory-only.
"""
from __future__ import annotations

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
GRADE_EXIT_LIQUIDITY = "EXIT_LIQUIDITY_RISK"

_CROWDED = ("AI", "MEME", "HYPE", "CRYPTO", "QUANTUM")


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def score_incentive_who_benefits(
    candidate: dict[str, Any],
    *,
    ownership: dict[str, Any] | None = None,
    distribution: dict[str, Any] | None = None,
    narrative_gap: dict[str, Any] | None = None,
    liquidity: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the incentive-risk record for one clean candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    asymmetry_flags: list[str] = []
    exit_flags: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []

    if candidate.get("is_live") is not True or candidate.get("source_health") != VERIFIED_LIVE:
        return _blocked(ticker)

    ownership = ownership or {}
    distribution = distribution or {}
    narrative_gap = narrative_gap or {}
    liquidity = liquidity or {}

    da_score = float(distribution.get("distribution_amplification_score") or 0.0) / 100.0
    nsg = float(narrative_gap.get("narrative_substance_gap") or 0.0)
    nsg_pos = max(nsg, 0.0) / 100.0
    substance = float(narrative_gap.get("substance_strength") or 0.0)
    blob = " ".join(str(candidate.get(k) or "").upper() for k in ("sector", "theme"))

    risk = 0.0
    risk += 0.30 * da_score
    risk += 0.25 * nsg_pos
    risk += 0.20 * (1.0 - substance)

    # Ownership context — never fabricated.
    insider = ownership.get("insider_concentration")
    if insider is None:
        missing.append("ownership_insider_data")
        warnings.append("no ownership/insider data; using weak heuristics only")
        risk += 0.10  # missing context is itself a mild risk
    else:
        ic = _clamp01(float(insider))
        risk += 0.20 * ic
        if ic >= 0.6:
            asymmetry_flags.append("high_insider_concentration")

    # Liquidity fragility.
    frag = liquidity.get("fragility")
    if frag is None:
        missing.append("liquidity_data")
    else:
        f = _clamp01(float(frag))
        risk += 0.15 * f
        if f >= 0.6:
            exit_flags.append("fragile_liquidity")

    if any(t in blob for t in _CROWDED):
        risk += 0.10
        asymmetry_flags.append("retail_facing_hype_theme")

    risk = round(100.0 * _clamp01(risk), 4)

    # Exit-liquidity risk: hype ahead of substance with no/weak ownership context.
    exit_liquidity = (da_score >= 0.6 and substance < 0.3) or "fragile_liquidity" in exit_flags
    if exit_liquidity:
        exit_flags.append("hype_ahead_of_substance_exit_liquidity")
        risk = max(risk, 76.0)
        grade = GRADE_EXIT_LIQUIDITY
    else:
        grade = _grade(risk)

    beneficiary_map = {
        "company": "possible (capital access)" if substance >= 0.5 else "unknown",
        "insiders": "elevated" if "high_insider_concentration" in asymmetry_flags else "unknown",
        "promoters": "elevated" if da_score >= 0.6 else "unknown",
        "institutions": "unknown",
        "retail": "at_risk" if exit_liquidity else "unknown",
        "media_or_distributors": "elevated" if da_score >= 0.5 else "unknown",
    }

    return {
        "ticker": ticker,
        "incentive_risk_score": risk,
        "grade": grade,
        "beneficiary_map": beneficiary_map,
        "asymmetry_flags": asymmetry_flags,
        "exit_liquidity_flags": exit_flags,
        "missing_fields": missing,
        "warnings": warnings,
        "advisory_only": True,
    }


def _blocked(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "incentive_risk_score": 0.0,
        "grade": GRADE_LOW,
        "beneficiary_map": {k: "unknown" for k in
                            ("company", "insiders", "promoters", "institutions", "retail", "media_or_distributors")},
        "asymmetry_flags": ["not_live_not_scored"],
        "exit_liquidity_flags": [],
        "missing_fields": ["live_evidence"],
        "warnings": ["candidate is not live; not scored"],
        "advisory_only": True,
    }


def _grade(risk: float) -> str:
    if risk <= 25:
        return GRADE_LOW
    if risk <= 50:
        return GRADE_MEDIUM
    if risk <= 75:
        return GRADE_HIGH
    return GRADE_EXIT_LIQUIDITY


__all__ = [
    "GRADE_LOW",
    "GRADE_MEDIUM",
    "GRADE_HIGH",
    "GRADE_EXIT_LIQUIDITY",
    "score_incentive_who_benefits",
]
