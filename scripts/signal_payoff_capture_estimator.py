"""Signal Payoff-Capture Estimator (PC) — P3 interpretation-defense module.

Ships the 2026-06-08 "meal box / casino / toll-gate" reflection's load-bearing
new variable (see docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md and
docs/reflections/2026-06-08_payoff_capture_reflection.md): **gross is not net**.

The existing demoters ask whether the thesis is *real* (provenance, quality,
regime, stress), whether attention runs ahead of substance (DA), whether the
story exceeds the facts (NSG), who profits if you believe it (incentive), who
might misread it (audience), and how fast the edge decays (half-life). NONE asks
the orthogonal structural question this reflection foregrounds:

    "Even if the thesis is true, does the EQUITY HOLDER actually capture the
     value — or is it diluted away by commodity competition, too many prior
     claimants, capex/working-capital drag, or weak market structure?"

A real catalyst on a commodity/price-taking business with thin residual
economics (gross corpus large, owner earnings thin — the "Berlin club payoff
stack") is a structurally weak holding even when the narrative is correct. PC
scores value-capture and emits a `payoff_capture_risk` (high = weak capture =
diluted) plus a `capture_grade` in {STRONG_CAPTURE, MODERATE_CAPTURE,
WEAK_CAPTURE}.

    value_capture = 0.30·structural_position + 0.30·margin_capture
                    + 0.20·pricing_power − 0.20·claimant_dilution
    payoff_capture_risk = 100·(1 − value_capture)        # high = diluted
    capture_grade ∈ {STRONG, MODERATE, WEAK}

Conceptual lineage: scripts/incentive_who_benefits_analyzer.py (who profits),
scripts/false_negative_casino_monopoly_layer.py (house/monopoly framing),
scripts/asymmetry_survival_scorer.py. PC is the candidate-level "does the slice
reach the owner" scorer on the clean fresh-discovery payload.

Data honesty: market-structure / supplier-power / capex feeds are usually absent
for fresh discovery, so PC derives weak proxies from fundamentals (margins, debt)
and evidence_type, and marks missing fields. A non-live candidate is NOT scored
as live. The module can only warn / demote; it never promotes, never invents a
candidate, never unlocks execution. Advisory-only. Pure module.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import VERIFIED_LIVE


GRADE_STRONG = "STRONG_CAPTURE"
GRADE_MODERATE = "MODERATE_CAPTURE"
GRADE_WEAK = "WEAK_CAPTURE"

# Market structure → structural pricing/capture power (1.0 = strongest).
_MARKET_STRUCTURE_POWER = {
    "monopoly": 0.95,
    "platform_monopoly": 0.92,
    "mental_monopoly": 0.82,
    "duopoly": 0.78,
    "oligopoly": 0.68,
    "local_monopoly": 0.60,
    "monopolistic_competition": 0.45,
    "commodity": 0.15,
    "commodity_competition": 0.15,
}

# Evidence-type → weak structural-position prior when no market-structure feed.
_STRUCTURE_PRIOR = {
    "LIVE_FILING_EVENT": 0.45,
    "LIVE_NEWS_EVENT": 0.40,
    "LIVE_PRICE_MOVER": 0.30,
}


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _is_live(candidate: dict[str, Any]) -> bool:
    return candidate.get("is_live") is True and candidate.get("source_health") == VERIFIED_LIVE


def _opt(d: dict[str, Any], key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    try:
        return _clamp01(float(v))
    except (TypeError, ValueError):
        return None


def score_signal_payoff_capture(
    candidate: dict[str, Any],
    *,
    fundamentals: dict[str, Any] | None = None,
    structure: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the payoff-capture / value-capture record for one clean candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    flags: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []

    if not _is_live(candidate):
        return {
            "ticker": ticker,
            "payoff_capture_risk": 0.0,
            "capture_grade": GRADE_WEAK,
            "value_capture": 0.0,
            "structural_position": 0.0,
            "margin_capture": 0.0,
            "pricing_power": 0.0,
            "claimant_dilution": 0.0,
            "capture_flags": ["not_live_not_scored"],
            "missing_fields": ["live_evidence"],
            "warnings": ["candidate is not live; not scored as live payoff capture"],
            "advisory_only": True,
        }

    fundamentals = dict(fundamentals or {})
    structure = dict(structure or {})
    evidence_type = candidate.get("evidence_type")

    # Structural position — real market-structure feed if present, else proxy.
    ms = str(structure.get("market_structure") or "").strip().lower().replace(" ", "_")
    if ms in _MARKET_STRUCTURE_POWER:
        structural_position = _MARKET_STRUCTURE_POWER[ms]
        if ms in ("commodity", "commodity_competition"):
            flags.append("commodity_structure")
    else:
        structural_position = _STRUCTURE_PRIOR.get(evidence_type, 0.30)
        missing.append("market_structure")
        warnings.append("no market-structure feed; using evidence-type proxy")
    # Toll-gate signals lift structural position when present.
    for key in ("switching_costs", "distribution_control", "toll_gate_position"):
        bump = _opt(structure, key)
        if bump is not None:
            structural_position = _clamp01(structural_position + 0.15 * bump)
            flags.append(f"toll_gate:{key}")

    # Margin capture — the residual that actually reaches the owner.
    gm = _opt(fundamentals, "gross_margin")
    om = _opt(fundamentals, "operating_margin")
    margins = [m for m in (gm, om) if m is not None]
    if margins:
        margin_capture = sum(margins) / len(margins)
    else:
        margin_capture = {"LIVE_FILING_EVENT": 0.4, "LIVE_NEWS_EVENT": 0.3, "LIVE_PRICE_MOVER": 0.2}.get(evidence_type, 0.25)
        missing.append("margins")
        warnings.append("no margin feed; residual capture under-evidenced")

    # Pricing power — high, stable margins imply pricing power.
    stability = _opt(fundamentals, "earnings_stability")
    pricing_power = margin_capture if stability is None else (0.5 * margin_capture + 0.5 * stability)

    # Claimant dilution — prior claims ahead of equity (debt, suppliers, fees,
    # capex/working-capital drag). High = the slice gets eaten before the owner.
    dilution_parts: list[float] = []
    dte = _opt(fundamentals, "debt_to_equity")
    if dte is not None:
        dilution_parts.append(dte)  # already 0..1-clamped; >1 leverage saturates at 1
    for key in ("supplier_power", "platform_fee_dependence", "capex_intensity", "working_capital_drag"):
        v = _opt(structure, key)
        if v is not None:
            dilution_parts.append(v)
    if dilution_parts:
        claimant_dilution = sum(dilution_parts) / len(dilution_parts)
    else:
        claimant_dilution = 0.4
        missing.append("claimant_structure")
        warnings.append("no claimant/dilution feed; using neutral prior")

    value_capture = _clamp01(
        0.30 * structural_position
        + 0.30 * margin_capture
        + 0.20 * pricing_power
        - 0.20 * claimant_dilution
    )
    payoff_capture_risk = round(100.0 * (1.0 - value_capture), 4)
    capture_grade = _grade(payoff_capture_risk)

    if capture_grade == GRADE_WEAK:
        flags.append("weak_payoff_capture")
    if margin_capture < 0.2 and claimant_dilution >= 0.5:
        flags.append("gross_not_net")  # large corpus, thin owner residual

    return {
        "ticker": ticker,
        "payoff_capture_risk": payoff_capture_risk,
        "capture_grade": capture_grade,
        "value_capture": round(value_capture, 6),
        "structural_position": round(structural_position, 6),
        "margin_capture": round(margin_capture, 6),
        "pricing_power": round(pricing_power, 6),
        "claimant_dilution": round(claimant_dilution, 6),
        "capture_flags": flags,
        "missing_fields": missing,
        "warnings": warnings,
        "advisory_only": True,
    }


def _grade(risk: float) -> str:
    # STRONG band is wide because margin_capture averages gross+operating margin
    # (so even a monopoly at 85% gross / 45% operating lands ~40 risk), and WEAK
    # is reserved for genuine commodity / high-dilution structures (risk > 72).
    if risk <= 45.0:
        return GRADE_STRONG
    if risk <= 72.0:
        return GRADE_MODERATE
    return GRADE_WEAK


__all__ = [
    "GRADE_STRONG",
    "GRADE_MODERATE",
    "GRADE_WEAK",
    "score_signal_payoff_capture",
]
