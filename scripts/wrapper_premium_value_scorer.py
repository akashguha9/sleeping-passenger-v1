"""Wrapper-Premium / Value-Layer Company Scorer (WPVS).

Ships the 2026-06-09 "core utility is cheap; the wrapper creates the premium"
reflection (Haagen-Dazs / Nike x Ben & Jerry's / Pokemon / patented medicine /
music hooks / Akon ringtones / Ryanair) as an *implementable* advisory scoring
layer rather than prose.

The reflection's load-bearing idea:

    Market Value = Core Utility Value + Wrapper Premium

…and its corollaries (protected premium, cultural-asset resale, IP-to-commodity
decay, format-market fit, ante/arbitrage, measurement contamination, and the
opposite "brutal-utility / customer-ROI" engine) become **seven conceptual
segments** (A-G). Each segment is a composite of the reflection's named modules,
scored 0-100, with confidence, evidence status, drivers, risks and missing
fields. The layer produces:

    legacy_pre_score   — the existing/legacy pipeline score (or a clearly-marked
                         synthetic baseline derived from existing fundamentals)
    upgraded_post_score — pre-score adjusted by the seven reflection segments,
                         damped by evidence confidence, penalised by bias risk
    delta              — post - pre, with an auditable per-segment driver table

Design rules honoured (same DNA as the interpretation-defense engine):
  * Pure module — no DB, no filesystem, no network, no broker calls.
  * Advisory-only — NEVER places a trade, never authorises execution.
  * Explainable — every score carries drivers, risks, evidence status.
  * Honest under missing data — absent evidence defaults to a NEUTRAL 0.5
    (so it neither helps nor hurts) and is surfaced as "missing", never guessed.
  * Deterministic — same input → same output (no clock/RNG in the math).

Segments (A-G) and the reflection modules they fold in
------------------------------------------------------
A core_utility_wrapper_premium   : Core Utility Floor, Wrapper Premium,
                                    Protected Premium, Segment-Coded Naming,
                                    Narrative Asset Premium
B cultural_asset_resale_scarcity  : Collab Multiplier, Cultural Liquidity,
                                    Visual Virality, IP Memory Bank,
                                    Copycat Demand, Prestige Dilution Risk
C ip_legal_protection_decay       : IP Protection, Commodity-Decay Risk,
                                    Substitution Pressure, Catalog Optionality,
                                    Hook/IP Reusability
D format_market_fit_distribution  : Format-Market Fit, Platform Fit,
                                    Distribution Optionality, Monetization Eff.
E ante_arbitrage_mispricing       : Ante Filter, Arbitrage Gap, Market
                                    Misframing, Capability-to-Exploit, Catalyst
F bias_measurement_contamination  : Blind Utility Gap, Demand Authenticity,
                                    Measurement Contamination, Placebo Power,
                                    False Pattern, Survivorship, Anchoring,
                                    Confirmation (this segment also emits a
                                    risk_score and is the only NET DEMOTER)
G brutal_utility_customer_roi     : Brutal Utility Engine, Customer ROI, Price
                                    Compression, Behaviour Expansion,
                                    Friction-to-Meme, Brand-Model Alignment,
                                    Constraint-as-Brand-Asset
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
    from scripts.daily_payload import normalize_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from daily_payload import normalize_ticker


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

REC_BUY = "BUY"
REC_WATCH = "WATCH"
REC_AVOID = "AVOID"
REC_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

EV_DIRECT = "direct"
EV_PROXY = "proxy"
EV_MISSING = "missing"

EQ_HIGH = "high"
EQ_MEDIUM = "medium"
EQ_LOW = "low"
EQ_MISSING = "missing"

# Segment keys — the public JSON contract order.
SEG_A = "core_utility_wrapper_premium"
SEG_B = "cultural_asset_resale_scarcity"
SEG_C = "ip_legal_protection_decay"
SEG_D = "format_market_fit_distribution"
SEG_E = "ante_arbitrage_mispricing"
SEG_F = "bias_measurement_contamination"
SEG_G = "brutal_utility_customer_roi"

SEGMENT_KEYS: tuple[str, ...] = (SEG_A, SEG_B, SEG_C, SEG_D, SEG_E, SEG_F, SEG_G)

# Default segment weights (reflection spec). Legacy carries 0.45; the six
# *positive* segments carry 0.52; the bias segment is a -0.07 risk penalty.
LEGACY_WEIGHT = 0.45
BIAS_PENALTY_WEIGHT = 0.07
DEFAULT_POSITIVE_WEIGHTS: dict[str, float] = {
    SEG_A: 0.10,
    SEG_B: 0.10,
    SEG_C: 0.08,
    SEG_D: 0.08,
    SEG_E: 0.09,
    SEG_G: 0.07,
}
_POSITIVE_WEIGHT_TOTAL = sum(DEFAULT_POSITIVE_WEIGHTS.values())  # 0.52

# Sector tilts — multipliers applied to the six positive segment weights, then
# renormalised back to the same total so magnitudes stay comparable.
SECTOR_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "pharma": {SEG_C: 2.2, SEG_A: 1.2},
    "biotech": {SEG_C: 2.2, SEG_A: 1.2},
    "consumer": {SEG_A: 1.6, SEG_B: 1.8},
    "luxury": {SEG_A: 1.8, SEG_B: 1.8},
    "apparel": {SEG_A: 1.5, SEG_B: 1.8},
    "media": {SEG_B: 1.6, SEG_C: 1.5, SEG_D: 1.6},
    "music": {SEG_B: 1.6, SEG_C: 1.6, SEG_D: 1.6},
    "gaming": {SEG_B: 1.8, SEG_C: 1.4, SEG_D: 1.5},
    "airline": {SEG_G: 2.4, SEG_A: 0.6},
    "discount_retail": {SEG_G: 2.2, SEG_A: 0.7},
    "marketplace": {SEG_G: 1.6, SEG_D: 1.6},
    "software": {SEG_D: 1.7, SEG_C: 1.3},
    "ai": {SEG_D: 1.7, SEG_C: 1.3},
    "platform": {SEG_D: 1.8, SEG_B: 1.2},
}


# ---------------------------------------------------------------------------
# Typed models
# ---------------------------------------------------------------------------


class EvidenceStatus:
    """Evidence-status vocabulary + coverage→status helper (no hidden state)."""

    DIRECT = EV_DIRECT
    PROXY = EV_PROXY
    MISSING = EV_MISSING

    @staticmethod
    def from_coverage(coverage: float) -> str:
        if coverage >= 0.60:
            return EV_DIRECT
        if coverage >= 0.25:
            return EV_PROXY
        return EV_MISSING


@dataclass
class RiskPenalty:
    """A single named penalty applied to the post-score (always subtractive)."""

    name: str
    points: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "points": round(self.points, 4), "reason": self.reason}


@dataclass
class SegmentScore:
    """One conceptual segment's composite score + full explanation surface."""

    key: str
    score: float
    confidence: float
    evidence_status: str
    drivers: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    modules: dict[str, float] = field(default_factory=dict)
    risk_score: float | None = None  # only the bias segment populates this

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "evidence_status": self.evidence_status,
            "drivers": list(self.drivers),
            "risks": list(self.risks),
            "modules": {k: round(v, 2) for k, v in self.modules.items()},
            "missing_evidence": list(self.missing),
        }
        if self.risk_score is not None:
            out["risk_score"] = round(self.risk_score, 2)
        return out


@dataclass
class DeltaExplanation:
    positive_delta_drivers: list[str] = field(default_factory=list)
    negative_delta_drivers: list[str] = field(default_factory=list)
    largest_segment_contributors: list[dict[str, Any]] = field(default_factory=list)
    model_interpretation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "positive_delta_drivers": list(self.positive_delta_drivers),
            "negative_delta_drivers": list(self.negative_delta_drivers),
            "largest_segment_contributors": list(self.largest_segment_contributors),
            "model_interpretation": self.model_interpretation,
        }


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _clamp100(v: float) -> float:
    return 0.0 if v < 0.0 else 100.0 if v > 100.0 else v


def _norm(value: Any) -> float | None:
    """Normalise an input proxy to 0..1.

    Accepts a 0..1 fraction or a 0..100 score (anything >1 is treated as /100).
    Returns None for absent/uninterpretable values so the caller can mark it
    missing rather than guess.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 1.0:
        v = v / 100.0
    return _clamp01(v)


def _pretty(key: str) -> str:
    return key.replace("_", " ")


@dataclass
class _Reading:
    vals: dict[str, float]
    present: dict[str, bool]
    coverage: float


def _read(evidence: dict[str, Any], keys: tuple[str, ...]) -> _Reading:
    """Read a group of proxy keys; absent → neutral 0.5 and flagged not-present."""
    vals: dict[str, float] = {}
    present: dict[str, bool] = {}
    hits = 0
    for k in keys:
        nv = _norm(evidence.get(k))
        if nv is None:
            vals[k] = 0.5
            present[k] = False
        else:
            vals[k] = nv
            present[k] = True
            hits += 1
    coverage = hits / len(keys) if keys else 0.0
    return _Reading(vals=vals, present=present, coverage=coverage)


def _drivers_and_risks(
    reading: _Reading,
    *,
    risk_keys: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Strong present signals → drivers; weak present signals → risks.

    For ``risk_keys`` the polarity flips: a HIGH value is the risk.
    """
    drivers: list[str] = []
    risks: list[str] = []
    for k, v in reading.vals.items():
        if not reading.present[k]:
            continue
        pct = int(round(v * 100))
        if k in risk_keys:
            if v >= 0.60:
                risks.append(f"{_pretty(k)} elevated ({pct})")
            elif v <= 0.30:
                drivers.append(f"{_pretty(k)} contained ({pct})")
        else:
            if v >= 0.60:
                drivers.append(f"{_pretty(k)} strong ({pct})")
            elif v <= 0.35:
                risks.append(f"{_pretty(k)} weak ({pct})")
    return drivers, risks


def _confidence(coverage: float) -> float:
    # A floor of 10 keeps a fully-missing segment from claiming zero confidence
    # while still reading as "missing" via evidence_status.
    return max(10.0, round(100.0 * coverage, 2))


def _missing(reading: _Reading) -> list[str]:
    return sorted(k for k, ok in reading.present.items() if not ok)


# ---------------------------------------------------------------------------
# Segment scorers  (A-G)
# ---------------------------------------------------------------------------

# Expected proxy keys per segment. All optional; absent → neutral.
_A_WRAPPER = ("price_premium_vs_substitute", "gross_margin_premium", "resale_premium", "brand_search_index")
_A_NAMING = ("perceived_origin_strength", "luxury_name_codes")
_A_NARRATIVE = ("narrative_story_strength", "scarcity", "community", "liquidity")
_A_PROTECT = ("protection_durability",)
_A_FLOOR = ("blind_valuation_ratio",)  # V_blind / V_branded ; LOW => big wrapper


def score_segment_core_utility_wrapper(evidence: dict[str, Any]) -> SegmentScore:
    keys = _A_WRAPPER + _A_NAMING + _A_NARRATIVE + _A_PROTECT + _A_FLOOR
    r = _read(evidence, keys)
    wrapper = sum(r.vals[k] for k in _A_WRAPPER) / len(_A_WRAPPER)
    naming = sum(r.vals[k] for k in _A_NAMING) / len(_A_NAMING)
    narrative = sum(r.vals[k] for k in _A_NARRATIVE) / len(_A_NARRATIVE)
    protected = wrapper * r.vals["protection_durability"]  # Premium × Durability
    blind_ratio = r.vals["blind_valuation_ratio"]
    wrapper_gap = _clamp01(1.0 - blind_ratio)  # Branded - Blind, normalised

    composite = (
        0.30 * wrapper
        + 0.28 * protected
        + 0.14 * naming
        + 0.18 * narrative
        + 0.10 * wrapper_gap
    )
    drivers, risks = _drivers_and_risks(r)
    if r.present["blind_valuation_ratio"] and blind_ratio >= 0.8:
        risks.append("wrapper thin under blind test (utility floor ~ price)")
    return SegmentScore(
        key=SEG_A,
        score=_clamp100(100.0 * composite),
        confidence=_confidence(r.coverage),
        evidence_status=EvidenceStatus.from_coverage(r.coverage),
        drivers=drivers,
        risks=risks,
        missing=_missing(r),
        modules={
            "wrapper_premium": round(100 * wrapper, 2),
            "protected_premium": round(100 * protected, 2),
            "segment_coded_naming": round(100 * naming, 2),
            "narrative_asset_premium": round(100 * narrative, 2),
            "wrapper_premium_gap": round(100 * wrapper_gap, 2),
        },
    )


_B_COLLAB = ("partner_brand_heat", "collab_history_perf", "sellout_speed", "cultural_novelty")
_B_LIQ = ("resale_volume", "bid_ask_tightness", "authentication")
_B_VISUAL = ("visual_recognition", "memeability", "photo_impact")
_B_IP = ("ip_nostalgia", "licensing_revenue", "fan_community_persistence")
_B_COPY = ("replica_volume", "replica_price_gap")
_B_DILUTION = ("prestige_dilution", "brand_enforcement_weakness")


def score_segment_cultural_asset(evidence: dict[str, Any]) -> SegmentScore:
    keys = _B_COLLAB + _B_LIQ + _B_VISUAL + _B_IP + _B_COPY + _B_DILUTION
    r = _read(evidence, keys)
    collab = sum(r.vals[k] for k in _B_COLLAB) / len(_B_COLLAB)
    liq = sum(r.vals[k] for k in _B_LIQ) / len(_B_LIQ)
    visual = sum(r.vals[k] for k in _B_VISUAL) / len(_B_VISUAL)
    ip_mem = sum(r.vals[k] for k in _B_IP) / len(_B_IP)
    # Copycat demand is a *signal* of brand heat (validation) but the dilution
    # sub-module nets against prestige (Net Copy Effect = heat - dilution).
    copy_signal = r.vals["replica_volume"] * r.vals["replica_price_gap"]
    dilution = sum(r.vals[k] for k in _B_DILUTION) / len(_B_DILUTION)

    composite = (
        0.25 * collab + 0.20 * liq + 0.15 * visual + 0.20 * ip_mem + 0.20 * copy_signal
    )
    composite = _clamp01(composite - 0.15 * dilution)
    drivers, risks = _drivers_and_risks(r, risk_keys=frozenset(_B_DILUTION))
    return SegmentScore(
        key=SEG_B,
        score=_clamp100(100.0 * composite),
        confidence=_confidence(r.coverage),
        evidence_status=EvidenceStatus.from_coverage(r.coverage),
        drivers=drivers,
        risks=risks,
        missing=_missing(r),
        modules={
            "collab_multiplier": round(100 * collab, 2),
            "cultural_liquidity": round(100 * liq, 2),
            "visual_virality": round(100 * visual, 2),
            "ip_memory_bank": round(100 * ip_mem, 2),
            "copycat_demand_signal": round(100 * copy_signal, 2),
            "prestige_dilution_risk": round(100 * dilution, 2),
        },
    )


_C_PROTECT = ("patent_protection", "regulatory_exclusivity", "clinical_trust", "distribution_strength")
_C_DECAY = ("generic_threat", "private_label_penetration", "open_source_threat")
_C_REMAIN = ("remaining_protection",)  # 1.0 = long runway, 0.0 = at the cliff
_C_CATALOG = ("catalog_size", "licensing_optionality")
_C_HOOK = ("hook_recognizability", "reuse_frequency", "licensability")


def score_segment_ip_protection(evidence: dict[str, Any]) -> SegmentScore:
    keys = _C_PROTECT + _C_DECAY + _C_REMAIN + _C_CATALOG + _C_HOOK
    r = _read(evidence, keys)
    protection = sum(r.vals[k] for k in _C_PROTECT) / len(_C_PROTECT)
    # Substitution *readiness* leans on the strongest substitute path (one
    # dominant threat — e.g. generics for pharma — is enough to commoditise),
    # not the mean, which would dilute it against weaker paths.
    decay_vals = [r.vals[k] for k in _C_DECAY]
    substitution = 0.6 * max(decay_vals) + 0.4 * (sum(decay_vals) / len(decay_vals))
    remaining = r.vals["remaining_protection"]
    catalog = sum(r.vals[k] for k in _C_CATALOG) / len(_C_CATALOG)
    hook = sum(r.vals[k] for k in _C_HOOK) / len(_C_HOOK)
    # IP-to-Commodity Decay Risk ≈ (1 - remaining runway) × substitution readiness
    decay_risk = (1.0 - remaining) * substitution

    composite = 0.50 * protection + 0.25 * catalog + 0.25 * hook
    composite = _clamp01(composite - 0.30 * decay_risk - 0.10 * substitution)
    drivers, risks = _drivers_and_risks(
        r, risk_keys=frozenset(_C_DECAY)
    )
    if r.present["remaining_protection"] and remaining <= 0.25:
        risks.append("near protection cliff (IP→commodity decay imminent)")
    return SegmentScore(
        key=SEG_C,
        score=_clamp100(100.0 * composite),
        confidence=_confidence(r.coverage),
        evidence_status=EvidenceStatus.from_coverage(r.coverage),
        drivers=drivers,
        risks=risks,
        missing=_missing(r),
        modules={
            "ip_protection": round(100 * protection, 2),
            "commodity_decay_risk": round(100 * decay_risk, 2),
            "substitution_pressure": round(100 * substitution, 2),
            "catalog_optionality": round(100 * catalog, 2),
            "hook_reusability": round(100 * hook, 2),
        },
    )


_D_KEYS = ("format_market_fit", "platform_fit", "distribution_optionality", "monetization_efficiency")


def score_segment_format_fit(evidence: dict[str, Any]) -> SegmentScore:
    r = _read(evidence, _D_KEYS)
    fmf = r.vals["format_market_fit"]
    plat = r.vals["platform_fit"]
    dist = r.vals["distribution_optionality"]
    mon = r.vals["monetization_efficiency"]
    composite = 0.35 * fmf + 0.25 * plat + 0.20 * dist + 0.20 * mon
    drivers, risks = _drivers_and_risks(r)
    return SegmentScore(
        key=SEG_D,
        score=_clamp100(100.0 * composite),
        confidence=_confidence(r.coverage),
        evidence_status=EvidenceStatus.from_coverage(r.coverage),
        drivers=drivers,
        risks=risks,
        missing=_missing(r),
        modules={
            "format_market_fit": round(100 * fmf, 2),
            "platform_fit": round(100 * plat, 2),
            "distribution_optionality": round(100 * dist, 2),
            "monetization_efficiency": round(100 * mon, 2),
        },
    )


_E_ANTE = ("patents_present", "regulatory_approvals", "brand_equity", "distribution_scale", "capital_access", "network_assets")
_E_REST = ("arbitrage_gap", "market_misframing", "capability_to_exploit", "catalyst_visibility")


def score_segment_ante_arbitrage(evidence: dict[str, Any]) -> SegmentScore:
    keys = _E_ANTE + _E_REST
    r = _read(evidence, keys)
    ante = sum(r.vals[k] for k in _E_ANTE) / len(_E_ANTE)  # capability present
    arb = r.vals["arbitrage_gap"]
    misframe = r.vals["market_misframing"]
    capability = r.vals["capability_to_exploit"]
    catalyst = r.vals["catalyst_visibility"]
    # Playable Opportunity = Arbitrage - Ante Cost; here ante is capability
    # PRESENT (higher = lower ante cost), so we reward arbitrage gated by ante.
    composite = (
        0.30 * arb + 0.25 * ante + 0.20 * capability + 0.15 * misframe + 0.10 * catalyst
    )
    drivers, risks = _drivers_and_risks(r)
    if r.present["arbitrage_gap"] and arb >= 0.6 and r.coverage > 0 and ante <= 0.35:
        risks.append("arbitrage visible but ante (capability to exploit) is thin")
    return SegmentScore(
        key=SEG_E,
        score=_clamp100(100.0 * composite),
        confidence=_confidence(r.coverage),
        evidence_status=EvidenceStatus.from_coverage(r.coverage),
        drivers=drivers,
        risks=risks,
        missing=_missing(r),
        modules={
            "ante_filter": round(100 * ante, 2),
            "arbitrage_gap": round(100 * arb, 2),
            "market_misframing": round(100 * misframe, 2),
            "capability_to_exploit": round(100 * capability, 2),
            "catalyst_visibility": round(100 * catalyst, 2),
        },
    )


# Segment F — the contamination segment. These are RISK proxies (high = worse),
# except demand_authenticity and placebo_pricing_power (high = good/durable).
_F_RISKY = (
    "measurement_contamination",
    "false_pattern_risk",
    "survivorship_bias_risk",
    "anchoring_risk",
    "confirmation_bias_risk",
    "blind_utility_gap",
    "paid_promo_intensity",
)
_F_GOOD = ("demand_authenticity", "placebo_pricing_power")


def score_segment_bias_contamination(evidence: dict[str, Any]) -> SegmentScore:
    keys = _F_RISKY + _F_GOOD
    r = _read(evidence, keys)
    contamination = r.vals["measurement_contamination"]
    false_pattern = r.vals["false_pattern_risk"]
    survivorship = r.vals["survivorship_bias_risk"]
    anchoring = r.vals["anchoring_risk"]
    confirmation = r.vals["confirmation_bias_risk"]
    blind_gap = r.vals["blind_utility_gap"]
    paid_promo = r.vals["paid_promo_intensity"]
    authenticity = r.vals["demand_authenticity"]
    placebo = r.vals["placebo_pricing_power"]

    # Aggregate risk: contamination + extrapolation/anchoring biases + manufactured
    # demand (1 - authenticity) + paid promo + fragility under blind test. Placebo
    # that *retains* pricing power slightly reduces fragility (belief→cash flow).
    risk = (
        0.20 * contamination
        + 0.15 * false_pattern
        + 0.12 * survivorship
        + 0.10 * anchoring
        + 0.10 * confirmation
        + 0.13 * blind_gap
        + 0.10 * paid_promo
        + 0.10 * (1.0 - authenticity)
    )
    risk = _clamp01(risk - 0.08 * placebo)
    risk_score = 100.0 * risk
    clean_score = 100.0 - risk_score

    drivers, risks = _drivers_and_risks(r, risk_keys=frozenset(_F_RISKY))
    return SegmentScore(
        key=SEG_F,
        score=_clamp100(clean_score),
        confidence=_confidence(r.coverage),
        evidence_status=EvidenceStatus.from_coverage(r.coverage),
        drivers=drivers,
        risks=risks,
        missing=_missing(r),
        modules={
            "blind_utility_gap": round(100 * blind_gap, 2),
            "demand_authenticity": round(100 * authenticity, 2),
            "measurement_contamination_risk": round(100 * contamination, 2),
            "placebo_pricing_power": round(100 * placebo, 2),
            "false_pattern_penalty": round(100 * false_pattern, 2),
            "survivorship_bias_penalty": round(100 * survivorship, 2),
            "anchoring_risk": round(100 * anchoring, 2),
            "confirmation_bias_risk": round(100 * confirmation, 2),
        },
        risk_score=_clamp100(risk_score),
    )


_G_KEYS = (
    "brutal_utility",
    "customer_roi",
    "price_compression",
    "behavior_expansion",
    "friction_to_meme",
    "brand_model_alignment",
    "constraint_as_brand_asset",
)


def score_segment_brutal_utility(evidence: dict[str, Any]) -> SegmentScore:
    r = _read(evidence, _G_KEYS)
    v = r.vals
    composite = (
        0.25 * v["brutal_utility"]
        + 0.25 * v["customer_roi"]
        + 0.10 * v["price_compression"]
        + 0.10 * v["behavior_expansion"]
        + 0.10 * v["friction_to_meme"]
        + 0.10 * v["brand_model_alignment"]
        + 0.10 * v["constraint_as_brand_asset"]
    )
    drivers, risks = _drivers_and_risks(r)
    return SegmentScore(
        key=SEG_G,
        score=_clamp100(100.0 * composite),
        confidence=_confidence(r.coverage),
        evidence_status=EvidenceStatus.from_coverage(r.coverage),
        drivers=drivers,
        risks=risks,
        missing=_missing(r),
        modules={k: round(100 * v[k], 2) for k in _G_KEYS},
    )


_SEGMENT_FUNCS = {
    SEG_A: score_segment_core_utility_wrapper,
    SEG_B: score_segment_cultural_asset,
    SEG_C: score_segment_ip_protection,
    SEG_D: score_segment_format_fit,
    SEG_E: score_segment_ante_arbitrage,
    SEG_F: score_segment_bias_contamination,
    SEG_G: score_segment_brutal_utility,
}


# ---------------------------------------------------------------------------
# Legacy (pre) score
# ---------------------------------------------------------------------------


def score_company_legacy(company_input: dict[str, Any]) -> dict[str, Any]:
    """Return the legacy pre-score.

    If ``legacy_score`` (0-100) is provided, use it directly (evidence: direct).
    Otherwise synthesise a backward-compatible baseline from any available
    fundamentals and clearly mark it ``synthetic_pre_score_from_existing_inputs``.
    """
    legacy = company_input.get("legacy_score")
    if legacy is None:
        legacy = company_input.get("pre_score")
    if legacy is not None:
        try:
            value = _clamp100(float(legacy))
        except (TypeError, ValueError):
            value = None
        if value is not None:
            return {
                "legacy_pre_score": round(value, 2),
                "source": "legacy_pipeline_score",
                "synthetic": False,
                "evidence_quality": EQ_HIGH,
                "drivers": ["provided legacy/fundamental pipeline score"],
            }

    # Synthetic baseline from fundamentals, centred on 50 (neutral).
    f = dict(company_input.get("fundamentals") or {})
    om = _norm(f.get("operating_margin"))
    growth = _norm(f.get("revenue_growth"))
    dte = _norm(f.get("debt_to_equity"))
    fcf = _norm(f.get("fcf_margin"))
    present = [x for x in (om, growth, dte, fcf) if x is not None]
    if not present:
        return {
            "legacy_pre_score": 50.0,
            "source": "synthetic_pre_score_from_existing_inputs",
            "synthetic": True,
            "evidence_quality": EQ_MISSING,
            "drivers": ["no legacy score and no fundamentals; neutral 50 baseline"],
        }
    score = 50.0
    drivers: list[str] = []
    if om is not None:
        score += 25.0 * (om - 0.10) / 0.20
        drivers.append(f"operating margin {int(om * 100)}%")
    if growth is not None:
        score += 15.0 * (growth - 0.10) / 0.20
        drivers.append(f"revenue growth proxy {int(growth * 100)}")
    if fcf is not None:
        score += 15.0 * (fcf - 0.10) / 0.20
        drivers.append(f"fcf margin {int(fcf * 100)}%")
    if dte is not None:
        score -= 10.0 * dte
        drivers.append(f"leverage proxy {int(dte * 100)}")
    quality = EQ_HIGH if len(present) >= 3 else EQ_MEDIUM if len(present) == 2 else EQ_LOW
    return {
        "legacy_pre_score": round(_clamp100(score), 2),
        "source": "synthetic_pre_score_from_existing_inputs",
        "synthetic": True,
        "evidence_quality": quality,
        "drivers": drivers,
    }


# ---------------------------------------------------------------------------
# Sector weighting
# ---------------------------------------------------------------------------


def resolve_weights(sector: str | None) -> dict[str, float]:
    """Return the six positive-segment weights, sector-tilted + renormalised."""
    weights = dict(DEFAULT_POSITIVE_WEIGHTS)
    if sector:
        profile = SECTOR_WEIGHT_PROFILES.get(str(sector).strip().lower())
        if profile:
            for seg, mult in profile.items():
                if seg in weights:
                    weights[seg] = weights[seg] * mult
            total = sum(weights.values())
            if total > 0:
                weights = {k: v * _POSITIVE_WEIGHT_TOTAL / total for k, v in weights.items()}
    return weights


# ---------------------------------------------------------------------------
# Upgraded (post) score
# ---------------------------------------------------------------------------


def score_company_upgraded(
    company_input: dict[str, Any],
    *,
    reflection_model: bool = True,
    legacy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the seven segment scores and the upgraded post-score.

    post = clamp( pre + confidence_factor · ( Σ w_seg·(seg-50) − 0.07·bias_risk ) )

    Movement is centred on a neutral 50 so a segment with no/neutral evidence
    contributes ~0 (no hindsight invention). ``confidence_factor`` damps the
    whole adjustment when evidence is thin. If ``reflection_model`` is False the
    post-score equals the pre-score (legacy passthrough).
    """
    legacy = legacy or score_company_legacy(company_input)
    pre = legacy["legacy_pre_score"]
    evidence = dict(company_input.get("evidence") or {})
    sector = company_input.get("sector")

    segments: dict[str, SegmentScore] = {
        key: func(evidence) for key, func in _SEGMENT_FUNCS.items()
    }

    if not reflection_model:
        return {
            "upgraded_post_score": pre,
            "segments": segments,
            "weights": {},
            "confidence_factor": 0.0,
            "bias_penalty": RiskPenalty("bias_measurement_contamination", 0.0, "reflection model disabled"),
            "segment_contributions": {},
            "overall_confidence": 0.0,
            "evidence_quality": EQ_MISSING,
        }

    weights = resolve_weights(sector)
    bias_seg = segments[SEG_F]

    # Overall confidence = weight-blended segment confidence (positive segments +
    # bias). Drives the damping factor + reported confidence/evidence quality.
    conf_weights = dict(weights)
    conf_weights[SEG_F] = BIAS_PENALTY_WEIGHT
    total_w = sum(conf_weights.values())
    overall_conf = sum(segments[k].confidence * w for k, w in conf_weights.items()) / total_w
    avg_coverage = overall_conf / 100.0
    confidence_factor = round(0.40 + 0.60 * avg_coverage, 4)

    contributions: dict[str, float] = {}
    for seg_key, w in weights.items():
        contributions[seg_key] = round(confidence_factor * w * (segments[seg_key].score - 50.0), 4)
    bias_points = round(confidence_factor * BIAS_PENALTY_WEIGHT * bias_seg.risk_score, 4)
    contributions[SEG_F] = round(-bias_points, 4)

    post = _clamp100(pre + sum(contributions.values()))

    return {
        "upgraded_post_score": round(post, 2),
        "segments": segments,
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "confidence_factor": confidence_factor,
        "bias_penalty": RiskPenalty(
            "bias_measurement_contamination",
            bias_points,
            f"bias/measurement risk_score={round(bias_seg.risk_score, 1)} damped by confidence",
        ),
        "segment_contributions": contributions,
        "overall_confidence": round(overall_conf, 2),
        "evidence_quality": _overall_evidence_quality(avg_coverage),
    }


def _overall_evidence_quality(avg_coverage: float) -> str:
    if avg_coverage >= 0.60:
        return EQ_HIGH
    if avg_coverage >= 0.35:
        return EQ_MEDIUM
    if avg_coverage >= 0.15:
        return EQ_LOW
    return EQ_MISSING


# ---------------------------------------------------------------------------
# Delta
# ---------------------------------------------------------------------------


def compute_delta(
    pre: float,
    post: float,
    segment_pre_map: dict[str, float | None],
    segment_post_map: dict[str, float],
    *,
    contributions: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build the auditable pre/post/delta table.

    The legacy pipeline has no per-segment scores, so each segment's ``pre`` is
    null (net-new interpretive layer); the OVERALL row carries pre=legacy.
    """
    contributions = contributions or {}
    table: list[dict[str, Any]] = [
        {
            "segment": "OVERALL",
            "pre": round(pre, 2),
            "post": round(post, 2),
            "delta": round(post - pre, 2),
            "reason": "legacy pre-score adjusted by reflection segments (confidence-damped)",
        }
    ]
    for seg in SEGMENT_KEYS:
        seg_pre = segment_pre_map.get(seg)
        seg_post = segment_post_map.get(seg, 0.0)
        contrib = contributions.get(seg)
        if seg_pre is None:
            reason = "net-new interpretive layer (no legacy equivalent)"
            if contrib is not None:
                reason += f"; contributes {contrib:+.2f} to post-score"
            table.append(
                {
                    "segment": seg,
                    "pre": None,
                    "post": round(seg_post, 2),
                    "delta": None,
                    "reason": reason,
                }
            )
        else:
            table.append(
                {
                    "segment": seg,
                    "pre": round(seg_pre, 2),
                    "post": round(seg_post, 2),
                    "delta": round(seg_post - seg_pre, 2),
                    "reason": "segment present in both pre and post",
                }
            )
    return table


# ---------------------------------------------------------------------------
# Recommendation + red flags
# ---------------------------------------------------------------------------


def _recommendation(post: float, evidence_quality: str, bias_risk: float, overall_conf: float) -> str:
    if evidence_quality == EQ_MISSING or overall_conf < 25.0:
        return REC_INSUFFICIENT
    if post >= 65.0 and bias_risk < 60.0:
        return REC_BUY
    if post >= 45.0:
        return REC_WATCH
    return REC_AVOID


def _collect_red_flags(segments: dict[str, SegmentScore]) -> list[str]:
    flags: list[str] = []
    bias = segments[SEG_F]
    if bias.risk_score is not None and bias.risk_score >= 70.0:
        flags.append(f"severe measurement/bias contamination (risk {round(bias.risk_score)})")
    c = segments[SEG_C]
    if c.modules.get("commodity_decay_risk", 0) >= 60.0:
        flags.append("high IP→commodity decay risk (protection eroding)")
    b = segments[SEG_B]
    if b.modules.get("prestige_dilution_risk", 0) >= 60.0:
        flags.append("prestige dilution risk (copies eroding scarcity)")
    if bias.modules.get("false_pattern_penalty", 0) >= 60.0:
        flags.append("false-pattern risk (lazy analogy to a famous winner)")
    if bias.modules.get("blind_utility_gap", 0) >= 70.0:
        flags.append("wrapper fragile under blind test (premium may not survive)")
    return flags


_NEXT_EVIDENCE_HINTS: dict[str, str] = {
    "blind_valuation_ratio": "Run a blind (de-branded) valuation / generic-equivalent comparison.",
    "resale_premium": "Pull resale-platform (StockX/eBay/auction) price vs retail.",
    "resale_volume": "Pull resale marketplace depth + bid-ask spreads.",
    "remaining_protection": "Confirm patent-expiry / exclusivity end dates.",
    "generic_threat": "Check generic/biosimilar approvals & private-label penetration.",
    "demand_authenticity": "Audit sell-through, repeat purchase, paid-promo intensity.",
    "measurement_contamination": "Map metric incentives & cross-platform independence.",
    "format_market_fit": "Assess fit to the dominant monetization format of the era.",
    "customer_roi": "Estimate customer outcome value per total cost paid.",
    "arbitrage_gap": "Compare market narrative to the hidden multilayer value.",
}


def _next_evidence(missing: list[str]) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    for m in missing:
        hint = _NEXT_EVIDENCE_HINTS.get(m)
        if hint and hint not in seen:
            seen.add(hint)
            hints.append(hint)
    return hints


# ---------------------------------------------------------------------------
# Top-level analysis (the JSON contract) + report
# ---------------------------------------------------------------------------


def analyze_company(
    company_input: dict[str, Any],
    *,
    reflection_model: bool = True,
    analysis_timestamp: str | None = None,
) -> dict[str, Any]:
    """Full pre/post/delta analysis for one company → machine-readable dict."""
    ticker = normalize_ticker(company_input.get("ticker"))
    name = company_input.get("company_name") or company_input.get("name") or ticker
    ts = analysis_timestamp or datetime.now(timezone.utc).isoformat()

    legacy = score_company_legacy(company_input)
    pre = legacy["legacy_pre_score"]
    upgraded = score_company_upgraded(
        company_input, reflection_model=reflection_model, legacy=legacy
    )
    post = upgraded["upgraded_post_score"]
    segments: dict[str, SegmentScore] = upgraded["segments"]
    contributions: dict[str, float] = upgraded["segment_contributions"]

    segment_post_map = {k: s.score for k, s in segments.items()}
    delta_table = compute_delta(
        pre, post, {k: None for k in SEGMENT_KEYS}, segment_post_map, contributions=contributions
    )

    # Delta explanation.
    pos = sorted(
        ((k, v) for k, v in contributions.items() if v > 0.01), key=lambda kv: -kv[1]
    )
    neg = sorted(
        ((k, v) for k, v in contributions.items() if v < -0.01), key=lambda kv: kv[1]
    )
    largest = sorted(contributions.items(), key=lambda kv: -abs(kv[1]))[:3]
    bias_risk = segments[SEG_F].risk_score or 0.0
    rec = _recommendation(post, upgraded["evidence_quality"], bias_risk, upgraded["overall_confidence"])
    delta_value = round(post - pre, 2)

    interp = (
        f"Reflection segments moved the score {delta_value:+.2f} "
        f"({'up' if delta_value > 0 else 'down' if delta_value < 0 else 'flat'}) "
        f"from legacy {pre:.1f} to {post:.1f}. "
        f"Adjustment damped by confidence factor {upgraded['confidence_factor']} "
        f"(evidence: {upgraded['evidence_quality']}). "
        f"Bias/measurement penalty: {upgraded['bias_penalty'].points:+.2f}."
    )
    delta_expl = DeltaExplanation(
        positive_delta_drivers=[f"{k} (+{v:.2f})" for k, v in pos],
        negative_delta_drivers=[f"{k} ({v:.2f})" for k, v in neg],
        largest_segment_contributors=[
            {"segment": k, "contribution": round(v, 2)} for k, v in largest
        ],
        model_interpretation=interp,
    )

    all_missing = sorted({m for s in segments.values() for m in s.missing})
    all_red_flags = _collect_red_flags(segments)

    return {
        "ticker": ticker,
        "company_name": name,
        "sector": company_input.get("sector"),
        "analysis_timestamp": ts,
        "legacy_pre_score": pre,
        "legacy_pre_score_source": legacy["source"],
        "synthetic_pre_score_from_existing_inputs": legacy["synthetic"],
        "upgraded_post_score": post,
        "delta": delta_value,
        "recommendation": rec,
        "confidence": upgraded["overall_confidence"],
        "evidence_quality": upgraded["evidence_quality"],
        "confidence_factor": upgraded["confidence_factor"],
        "weights": upgraded["weights"],
        "segmented_scores": {k: segments[k].to_dict() for k in SEGMENT_KEYS},
        "delta_explanation": delta_expl.to_dict(),
        "bias_penalty": upgraded["bias_penalty"].to_dict(),
        "pre_post_delta_table": delta_table,
        "red_flags": all_red_flags,
        "missing_evidence": all_missing,
        "next_evidence_to_collect": _next_evidence(all_missing),
        "reflection_source": "2026-06-09 wrapper-premium / brutal-utility reflection",
        "advisory_only": True,
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


def render_report(result: dict[str, Any]) -> str:
    """Human-readable Markdown summary of an :func:`analyze_company` result."""
    lines: list[str] = []
    lines.append(f"# Wrapper-Premium Value Analysis — {result['company_name']} ({result['ticker']})")
    lines.append("")
    lines.append(f"_Advisory-only. Generated {result['analysis_timestamp']}._")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"| --- | --- |")
    lines.append(f"| Sector | {result.get('sector') or 'n/a'} |")
    src = "synthetic (from fundamentals)" if result["synthetic_pre_score_from_existing_inputs"] else "legacy pipeline"
    lines.append(f"| Legacy pre-score | {result['legacy_pre_score']} ({src}) |")
    lines.append(f"| Upgraded post-score | {result['upgraded_post_score']} |")
    lines.append(f"| Delta | {result['delta']:+.2f} |")
    lines.append(f"| Recommendation | {result['recommendation']} |")
    lines.append(f"| Confidence | {result['confidence']} ({result['evidence_quality']}) |")
    lines.append("")
    lines.append("## Segmented scores")
    lines.append("")
    lines.append("| Segment | Score | Conf | Evidence | Risk |")
    lines.append("| --- | --- | --- | --- | --- |")
    for seg in SEGMENT_KEYS:
        s = result["segmented_scores"][seg]
        risk = s.get("risk_score", "")
        lines.append(f"| {seg} | {s['score']} | {s['confidence']} | {s['evidence_status']} | {risk} |")
    lines.append("")
    lines.append("## Pre / Post / Delta")
    lines.append("")
    lines.append("| Segment | Pre | Post | Delta | Reason |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in result["pre_post_delta_table"]:
        pre = "—" if row["pre"] is None else row["pre"]
        delta = "—" if row["delta"] is None else f"{row['delta']:+.2f}"
        lines.append(f"| {row['segment']} | {pre} | {row['post']} | {delta} | {row['reason']} |")
    lines.append("")
    lines.append("## What drove the delta")
    lines.append("")
    de = result["delta_explanation"]
    lines.append(de["model_interpretation"])
    lines.append("")
    if de["positive_delta_drivers"]:
        lines.append("**Positive:** " + ", ".join(de["positive_delta_drivers"]))
    if de["negative_delta_drivers"]:
        lines.append("**Negative:** " + ", ".join(de["negative_delta_drivers"]))
    lines.append("")
    if result["red_flags"]:
        lines.append("## Red flags")
        lines.append("")
        for f in result["red_flags"]:
            lines.append(f"- {f}")
        lines.append("")
    if result["next_evidence_to_collect"]:
        lines.append("## Next evidence to collect")
        lines.append("")
        for e in result["next_evidence_to_collect"]:
            lines.append(f"- {e}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "REC_BUY",
    "REC_WATCH",
    "REC_AVOID",
    "REC_INSUFFICIENT",
    "SEGMENT_KEYS",
    "DEFAULT_POSITIVE_WEIGHTS",
    "SECTOR_WEIGHT_PROFILES",
    "EvidenceStatus",
    "RiskPenalty",
    "SegmentScore",
    "DeltaExplanation",
    "score_company_legacy",
    "score_company_upgraded",
    "resolve_weights",
    "compute_delta",
    "analyze_company",
    "render_report",
]
