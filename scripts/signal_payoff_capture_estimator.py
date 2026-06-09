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
            "diagnostic": payoff_capture_diagnostic(None, None, live=False),
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
        "diagnostic": payoff_capture_diagnostic(fundamentals, structure, live=True),
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


# ---------------------------------------------------------------------------
# Auditable Payoff-Capture Diagnostic (2026-06-09 reflection)
#
# "Move from 'score says weak capture' to 'here is exactly where value leaks
# before it reaches the owner, how confident we are, and what would falsify it.'"
#
# This layer is EXPLANATORY-ONLY. It never changes payoff_capture_risk or
# capture_grade and never makes demotion more aggressive — it decomposes the
# existing demoter into auditable sub-captures, attributes the primary value
# leak, states evidence confidence, and emits a falsification hint. When data is
# absent it returns unknown / insufficient_evidence rather than guessing.
# ---------------------------------------------------------------------------

BAND_STRONG = "strong"
BAND_MEDIUM = "medium"
BAND_WEAK = "weak"
BAND_UNKNOWN = "unknown"

LEAK_NONE = "none_detected"
LEAK_MARGIN = "weak_margin_capture"
LEAK_CASH = "weak_cash_conversion"
LEAK_WORKING_CAPITAL = "working_capital_drag"
LEAK_CAPEX = "capex_burden"
LEAK_DEBT = "debt_or_interest_burden"
LEAK_PLATFORM = "platform_or_intermediary_toll"
LEAK_SUPPLIER = "supplier_power"
LEAK_CUSTOMER = "customer_power"
LEAK_DILUTION = "dilution_or_minority_leakage"
LEAK_INSUFFICIENT = "insufficient_evidence"

CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"

FALSE_HOUSE_HIGH = "high"
FALSE_HOUSE_LOW = "low"
FALSE_HOUSE_NOT_EVAL = "not_evaluated"

_FALSIFICATION = {
    LEAK_MARGIN: "Operating margin rises and holds for 2 consecutive periods.",
    LEAK_CASH: "OCF/Net Income > 0.8 for 2 consecutive periods.",
    LEAK_WORKING_CAPITAL: "Receivable days AND inventory days both decline.",
    LEAK_CAPEX: "FCF margin turns positive while capex intensity falls.",
    LEAK_DEBT: "Debt/EBITDA falls and interest coverage rises.",
    LEAK_PLATFORM: "Take-rate rises without rising incentives/subsidies.",
    LEAK_SUPPLIER: "Gross margin stays stable through an input-cost shock.",
    LEAK_CUSTOMER: "Revenue concentration falls while gross margin holds.",
    LEAK_DILUTION: "Share count stays flat and minority share of profit falls.",
    LEAK_NONE: "Capture already evidenced as adequate; watch for margin/cash deterioration.",
    LEAK_INSUFFICIENT: "Provide FCF, working-capital and margin-trend evidence to evaluate capture.",
}


def _num(d: dict[str, Any], key: str) -> float | None:
    """Raw float read (NOT clamped — capture ratios legitimately exceed 1 or go negative)."""
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _band(value: float | None, strong: float, medium: float) -> str:
    if value is None:
        return BAND_UNKNOWN
    if value >= strong:
        return BAND_STRONG
    if value >= medium:
        return BAND_MEDIUM
    return BAND_WEAK


def _cash_capture_ratio(fundamentals: dict[str, Any]) -> float | None:
    r = _num(fundamentals, "ocf_to_net_income")
    if r is not None:
        return r
    ocf = _num(fundamentals, "operating_cash_flow")
    ni = _num(fundamentals, "net_income")
    if ocf is not None and ni is not None and ni > 0:
        return ocf / ni
    return None


def _owner_capture_ratio(fundamentals: dict[str, Any]) -> float | None:
    r = _num(fundamentals, "fcfe_to_net_income")
    if r is not None:
        return r
    fcfe = _num(fundamentals, "free_cash_flow_to_equity")
    ni = _num(fundamentals, "net_income")
    if fcfe is not None and ni is not None and ni > 0:
        return fcfe / ni
    return None


def _bargaining_capture(structure: dict[str, Any], fundamentals: dict[str, Any]) -> tuple[str, float | None]:
    pricing = _num(structure, "pricing_power")
    cust = _num(structure, "customer_concentration")
    supp = _num(structure, "supplier_power")
    plat = _num(structure, "platform_fee_dependence")
    if pricing is None and cust is None and supp is None and plat is None:
        return BAND_UNKNOWN, None
    base = pricing if pricing is not None else (_num(fundamentals, "gross_margin") or 0.4)
    score = base - 0.5 * (cust or 0.0) - 0.5 * (supp or 0.0) - 0.5 * (plat or 0.0)
    score = _clamp01(score)
    return _band(score, 0.55, 0.30), score


def payoff_capture_diagnostic(
    fundamentals: dict[str, Any] | None,
    structure: dict[str, Any] | None,
    *,
    live: bool = True,
) -> dict[str, Any]:
    """Auditable decomposition of the payoff-capture demoter. Explanatory-only."""
    if not live:
        return {
            "gross_to_margin_capture": BAND_UNKNOWN,
            "profit_to_cash_capture": BAND_UNKNOWN,
            "cash_to_owner_capture": BAND_UNKNOWN,
            "bargaining_capture": BAND_UNKNOWN,
            "primary_value_leak": LEAK_INSUFFICIENT,
            "owner_capture_confidence": CONF_LOW,
            "false_house_risk": FALSE_HOUSE_NOT_EVAL,
            "falsification_hint": _FALSIFICATION[LEAK_INSUFFICIENT],
            "advisory_only": True,
            "explanatory_only": True,
        }

    fundamentals = dict(fundamentals or {})
    structure = dict(structure or {})

    om = _num(fundamentals, "operating_margin")
    margin_band = _band(om, 0.18, 0.07)
    cash_ratio = _cash_capture_ratio(fundamentals)
    cash_band = _band(cash_ratio, 0.90, 0.60)
    owner_ratio = _owner_capture_ratio(fundamentals)
    owner_band = _band(owner_ratio, 0.70, 0.40)
    bargain_band, _bargain_score = _bargaining_capture(structure, fundamentals)

    # Confidence — how many real (non-proxy) evidence points are present.
    present = sum(
        1 for b in (margin_band, cash_band, owner_band, bargain_band) if b != BAND_UNKNOWN
    )
    confidence = CONF_HIGH if present >= 3 else CONF_MEDIUM if present == 2 else CONF_LOW

    # Primary value leak — upstream-to-downstream priority; first weak wins.
    leak = LEAK_NONE
    if present == 0:
        leak = LEAK_INSUFFICIENT
    elif margin_band == BAND_WEAK:
        leak = LEAK_MARGIN
    elif cash_band == BAND_WEAK:
        rec = _num(fundamentals, "receivable_days_change")
        inv = _num(fundamentals, "inventory_days_change")
        rising_wc = (rec is not None and rec > 0) or (inv is not None and inv > 0)
        leak = LEAK_WORKING_CAPITAL if rising_wc else LEAK_CASH
    elif owner_band == BAND_WEAK:
        capex = _num(structure, "capex_intensity")
        if capex is None:
            capex = _num(fundamentals, "capex_intensity")
        dte = _num(fundamentals, "debt_to_equity")
        icov = _num(fundamentals, "interest_coverage")
        share_chg = _num(fundamentals, "share_count_change")
        minority = _num(fundamentals, "minority_interest_share")
        if capex is not None and capex >= 0.5:
            leak = LEAK_CAPEX
        elif (dte is not None and dte >= 0.6) or (icov is not None and icov < 3):
            leak = LEAK_DEBT
        elif (share_chg is not None and share_chg > 0) or (minority is not None and minority >= 0.2):
            leak = LEAK_DILUTION
        else:
            leak = LEAK_CAPEX
    elif bargain_band == BAND_WEAK:
        plat = _num(structure, "platform_fee_dependence")
        supp = _num(structure, "supplier_power")
        cust = _num(structure, "customer_concentration")
        if plat is not None and plat >= 0.5:
            leak = LEAK_PLATFORM
        elif supp is not None and supp >= 0.5:
            leak = LEAK_SUPPLIER
        elif cust is not None and cust >= 0.5:
            leak = LEAK_CUSTOMER
        else:
            leak = LEAK_PLATFORM

    return {
        "gross_to_margin_capture": margin_band,
        "profit_to_cash_capture": cash_band,
        "cash_to_owner_capture": owner_band,
        "bargaining_capture": bargain_band,
        "primary_value_leak": leak,
        "owner_capture_confidence": confidence,
        "false_house_risk": _false_house_risk(fundamentals, structure, margin_band, cash_band),
        "falsification_hint": _FALSIFICATION[leak],
        "advisory_only": True,
        "explanatory_only": True,
    }


def _false_house_risk(
    fundamentals: dict[str, Any], structure: dict[str, Any], margin_band: str, cash_band: str
) -> str:
    """A 'player wearing a house costume' — big reach, weak toll economics."""
    reach_vals = [
        _num(structure, k) for k in ("gmv", "distribution_control", "brand_recall", "market_reach")
    ]
    reach = max((v for v in reach_vals if v is not None), default=None)
    if reach is None:
        return FALSE_HOUSE_NOT_EVAL
    take_rate = _num(structure, "take_rate")
    incentive = _num(structure, "incentive_intensity")
    churn = _num(structure, "churn")
    weak_econ = (
        (take_rate is not None and take_rate < 0.10)
        or margin_band == BAND_WEAK
        or cash_band == BAND_WEAK
        or (incentive is not None and incentive >= 0.5)
        or (churn is not None and churn >= 0.5)
    )
    if reach >= 0.6 and weak_econ:
        return FALSE_HOUSE_HIGH
    return FALSE_HOUSE_LOW


__all__ = [
    "GRADE_STRONG",
    "GRADE_MODERATE",
    "GRADE_WEAK",
    "score_signal_payoff_capture",
    "payoff_capture_diagnostic",
]
