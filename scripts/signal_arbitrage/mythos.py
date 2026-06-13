"""Mythos — the meaning-routing interpretation engine.

A map app is not a map; it is a movement-decision system.  Mythos is not a
sentiment parser; it is a *meaning-routing* system.  It turns a raw observation
into an interpretation, checks that interpretation against reality, and routes
it to a strategy — capping confidence by the integrity of every layer it passed
through.

    Observation -> Interpretation -> Routing -> Feedback -> Repricing
    Raw Signal  -> Meaning -> Beholder Lens -> Strategy Route -> Reality Check
                -> Confidence Update

It is the interpretation FRONT-END that feeds Fable 5 (the casino/food-chain
scorer).  It never weakens Fable's fraud gates: it only hands over an advisory
payload and a confidence cap.  Everything here is pure, deterministic
(integer-day timestamps, no wall clock), dependency-free, ADVISORY_ONLY.

Layers (all in this module):
  1  observation intake + quality
  2  source governance classifier
  3  provider worldview / cost-function engine
  4  interpretation (multi-beholder meaning + gap)
  5  map-matching / explanation correction
  6  reality-check ledger (trust survival)
  7  routing / strategy implication
  8  ETA / thesis timing
  9  two-map model (economic reality vs narrative belief)
 10  casino x food-chain bridge -> Fable 5 payload
 11  layer integrity / strategy eligibility
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3, mean, weighted
from .tokenizer import extract_tokens
from .interpretation_gap import interpret_beholders
from .opportunity import SignalDossier, score_opportunity

ADVISORY = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"


# ==========================================================================
# Observation intake
# ==========================================================================
@dataclass(frozen=True)
class MythosObservation:
    """A raw observation — explicitly NOT truth until it survives reality."""
    source: str                       # e.g. "sec_filing", "reddit", "x"
    entity: str
    raw_text: str = ""
    claim: str = ""                   # extracted claim; derived if empty
    claim_type: str = "generic"       # routes map-matching catalog
    day: int = 0
    # observation-quality inputs (0..1)
    recency: float = 0.5
    reliability: float = 0.5
    independence: float = 0.5
    coverage: float = 0.5
    noise_level: float = 0.3
    confidence_prior: float = 0.5
    # economic-map inputs (0..1, None = unobserved)
    demand: float | None = None
    revenue_growth: float | None = None
    margin_trend: float | None = None
    retention: float | None = None
    pricing_power: float | None = None
    customer_adoption: float | None = None
    capex_burden: float | None = None
    regulation_risk: float | None = None
    # narrative-map inputs (0..1)
    attention: float = 0.0
    mentions_velocity: float = 0.0
    sentiment: float = 0.5            # 0 very negative .. 1 very positive
    amplification: float = 0.0
    prediction_odds: float | None = None
    saturation: float = 0.0
    consensus: float = 0.4
    # food-chain inputs (0..1)
    flow_growth: float | None = None
    capture_rate: float | None = None
    leakage: float | None = None
    dependency: float | None = None
    # map-matching corroboration flags
    discount_flag: bool = False
    acquisition_flag: bool = False
    fx_flag: bool = False
    one_time_flag: bool = False
    accounting_flag: bool = False
    # ETA inputs
    catalyst_eta_days: float | None = None
    catalyst_elapsed_days: float | None = None
    execution_lag_days: float = 5.0
    # reality-check feedback events: list of {day, supports, weight, independent}
    evidence_events: tuple = ()

    def resolved_claim(self) -> str:
        if self.claim:
            return self.claim
        # naive: first sentence of raw text
        for sep in (".", "!", "?", "\n"):
            if sep in self.raw_text:
                return self.raw_text.split(sep, 1)[0].strip()
        return self.raw_text.strip() or f"{self.entity} signal"


def observation_quality(obs: MythosObservation) -> dict[str, Any]:
    score = clamp(0.30 * obs.reliability + 0.20 * obs.recency
                  + 0.20 * obs.independence + 0.15 * obs.coverage
                  + 0.15 * (1.0 - obs.noise_level))
    reasons: list[str] = []
    if obs.noise_level >= 0.6:
        reasons.append("NOISY_SOURCE")
    if obs.independence < 0.4:
        reasons.append("LOW_INDEPENDENCE")
    if obs.recency < 0.3:
        reasons.append("STALE_OBSERVATION")
    if obs.coverage < 0.4:
        reasons.append("THIN_COVERAGE")
    if score >= 0.7:
        reasons.append("HIGH_QUALITY_OBSERVATION")
    initial = clamp(obs.confidence_prior * (0.5 + 0.5 * score))
    return {
        "observation_quality_score": r3(score),
        "observation_reason_codes": reasons,
        "initial_claim_confidence": r3(initial),
    }


# ==========================================================================
# Source governance classifier
# ==========================================================================
GOVERNANCE_PROFILES: dict[str, dict[str, Any]] = {
    "OFFICIAL_SOURCE": {"trust": 0.90, "validation": "audited/regulatory",
                        "distortion": "legalese; lagging", "review": "regulated filing",
                        "conf_adj": 0.10},
    "PREDICTION_MARKET": {"trust": 0.70, "validation": "priced belief / liquidity",
                          "distortion": "thin-liquidity noise", "review": "market settlement",
                          "conf_adj": 0.0},
    "INTERNAL_LEDGER": {"trust": 0.80, "validation": "model memory / provenance",
                        "distortion": "self-confirmation", "review": "hash-chained",
                        "conf_adj": 0.05},
    "COMMERCIAL_DATA_VENDOR": {"trust": 0.62, "validation": "vendor methodology",
                               "distortion": "sampling/black-box", "review": "vendor QA",
                               "conf_adj": 0.0},
    "CLOSED_PLATFORM": {"trust": 0.65, "validation": "platform-internal",
                        "distortion": "platform incentives", "review": "platform moderation",
                        "conf_adj": 0.0},
    "NEWS_MEDIA": {"trust": 0.55, "validation": "editorial",
                   "distortion": "agenda; repetition", "review": "editor",
                   "conf_adj": 0.0},
    "OPEN_COMMUNITY": {"trust": 0.52, "validation": "community consensus",
                       "distortion": "niche selection; brigading", "review": "upvotes/mods",
                       "conf_adj": -0.05},
    "USER_GENERATED": {"trust": 0.48, "validation": "crowd / review aggregation",
                       "distortion": "selection; astroturf", "review": "platform flags",
                       "conf_adj": -0.05},
    "SOCIAL_FEED": {"trust": 0.40, "validation": "virality",
                    "distortion": "outrage; bots; velocity!=truth", "review": "none/weak",
                    "conf_adj": -0.10},
    "EXPERIMENTAL_OR_UNKNOWN": {"trust": 0.30, "validation": "unknown",
                                "distortion": "unclassified", "review": "none",
                                "conf_adj": -0.15},
}

_SOURCE_TO_GOVERNANCE: dict[str, str] = {
    "sec_filing": "OFFICIAL_SOURCE", "filing": "OFFICIAL_SOURCE",
    "earnings_call": "OFFICIAL_SOURCE", "regulatory": "OFFICIAL_SOURCE",
    "prediction_market": "PREDICTION_MARKET", "polymarket": "PREDICTION_MARKET",
    "kalshi": "PREDICTION_MARKET",
    "internal_ledger": "INTERNAL_LEDGER", "provenance": "INTERNAL_LEDGER",
    "web_traffic": "COMMERCIAL_DATA_VENDOR", "data_vendor": "COMMERCIAL_DATA_VENDOR",
    "analyst": "COMMERCIAL_DATA_VENDOR",
    "google": "CLOSED_PLATFORM", "apple": "CLOSED_PLATFORM",
    "news": "NEWS_MEDIA", "rss": "NEWS_MEDIA", "media": "NEWS_MEDIA",
    "reddit": "OPEN_COMMUNITY", "forum": "OPEN_COMMUNITY",
    "app_reviews": "USER_GENERATED", "customer_reviews": "USER_GENERATED",
    "reviews": "USER_GENERATED", "job_postings": "USER_GENERATED",
    "product_page": "USER_GENERATED",
    "x": "SOCIAL_FEED", "twitter": "SOCIAL_FEED", "grok": "SOCIAL_FEED",
    "social": "SOCIAL_FEED",
}


def classify_governance(obs: MythosObservation) -> dict[str, Any]:
    gov = _SOURCE_TO_GOVERNANCE.get(obs.source.strip().lower(), "EXPERIMENTAL_OR_UNKNOWN")
    p = GOVERNANCE_PROFILES[gov]
    # Trust blends the governance prior with the observation's own reliability.
    trust = clamp(0.7 * p["trust"] + 0.3 * obs.reliability)
    return {
        "governance_type": gov,
        "governance_trust_score": r3(trust),
        "expected_validation_mode": p["validation"],
        "likely_distortion": p["distortion"],
        "review_process": p["review"],
        "confidence_adjustment": p["conf_adj"],
    }


# ==========================================================================
# Provider worldview / cost-function engine
# ==========================================================================
# Each worldview reads the SAME feature vector through a different signed weight
# set (its cost function), producing a different interpretation direction.
WORLDVIEWS: dict[str, dict[str, Any]] = {
    "MOMENTUM_OPTIMIZER": {
        "objective": "ride attention velocity before it peaks",
        "weights": {"momentum": 1.0, "sentiment": 0.6, "saturation": -0.7, "margin": 0.0},
        "preferred": "mentions velocity, amplification", "ignored": "margins, retention",
        "risk_tolerance": 0.8, "half_life": "days", "bias": "chases narrative",
        "blind_spot": "fundamentals, saturation", "route": "ROUTE_TO_CASINO_ODDS"},
    "VALUE_CAPTURE_OPTIMIZER": {
        "objective": "own the tollbooth; price power x flow minus leakage",
        "weights": {"capture": 1.0, "pricing": 0.7, "capex": -0.6, "growth": 0.2},
        "preferred": "capture rate, pricing power", "ignored": "buzz",
        "risk_tolerance": 0.4, "half_life": "years", "bias": "demands moat",
        "blind_spot": "early pre-revenue winners", "route": "ROUTE_TO_FOOD_CHAIN_ANALYSIS"},
    "QUALITY_COMPOUNDER_OPTIMIZER": {
        "objective": "durable retention + adoption compounding",
        "weights": {"retention": 1.0, "adoption": 0.7, "margin": 0.5, "saturation": -0.2},
        "preferred": "retention, adoption", "ignored": "short-term price",
        "risk_tolerance": 0.5, "half_life": "years", "bias": "pays up for quality",
        "blind_spot": "valuation/timing", "route": "ROUTE_TO_FABLE5"},
    "SHORT_SELLER_OPTIMIZER": {
        "objective": "find stress, leakage, contradiction",
        "weights": {"capex": 0.8, "regulation": 0.7, "contamination": 0.9,
                    "retention": -0.8, "margin": -0.7, "momentum": 0.3},
        "preferred": "leakage, churn, fraud", "ignored": "upside narrative",
        "risk_tolerance": 0.6, "half_life": "months", "bias": "skeptical",
        "blind_spot": "real turnarounds", "route": "ROUTE_TO_REALITY_CHECK"},
    "RISK_FIRST_OPTIMIZER": {
        "objective": "minimize downside / regulatory / leverage risk",
        "weights": {"regulation": -0.9, "capex": -0.7, "contamination": -0.6,
                    "retention": 0.4},
        "preferred": "balance-sheet, regulation", "ignored": "momentum",
        "risk_tolerance": 0.2, "half_life": "years", "bias": "avoids fragility",
        "blind_spot": "high-vol winners", "route": "ROUTE_TO_REALITY_CHECK"},
    "CONTRARIAN_OPTIMIZER": {
        "objective": "buy reality the crowd hasn't priced",
        "weights": {"contrarian": 1.0, "retention": 0.5, "margin": 0.4,
                    "consensus": -0.6, "sentiment": -0.4},
        "preferred": "reality vs sentiment gap", "ignored": "consensus",
        "risk_tolerance": 0.6, "half_life": "months", "bias": "fades crowd",
        "blind_spot": "value traps", "route": "ROUTE_TO_FABLE5"},
    "REGULATORY_RISK_OPTIMIZER": {
        "objective": "weight policy/regulatory exposure first",
        "weights": {"regulation": -1.0, "capture": 0.3},
        "preferred": "regulatory filings", "ignored": "buzz",
        "risk_tolerance": 0.3, "half_life": "years", "bias": "policy-anchored",
        "blind_spot": "deregulation upside", "route": "ROUTE_TO_REALITY_CHECK"},
    "CUSTOMER_REALITY_OPTIMIZER": {
        "objective": "trust ground-truth customer behavior",
        "weights": {"retention": 0.9, "adoption": 0.8, "sentiment": 0.3,
                    "contamination": -0.5},
        "preferred": "reviews, retention, churn", "ignored": "management spin",
        "risk_tolerance": 0.5, "half_life": "months", "bias": "bottom-up",
        "blind_spot": "macro/valuation", "route": "ROUTE_TO_REALITY_CHECK"},
    "MONETIZATION_OPTIMIZER": {
        "objective": "maximize pricing power / monetization",
        "weights": {"pricing": 1.0, "margin": 0.6, "growth": 0.3},
        "preferred": "pricing, margin", "ignored": "volume vanity",
        "risk_tolerance": 0.5, "half_life": "years", "bias": "margin-led",
        "blind_spot": "land-grab phase", "route": "ROUTE_TO_FOOD_CHAIN_ANALYSIS"},
    "SPEED_OPTIMIZER": {
        "objective": "fastest path to a tradeable signal",
        "weights": {"momentum": 0.9, "growth": 0.5, "saturation": -0.4},
        "preferred": "velocity", "ignored": "diligence",
        "risk_tolerance": 0.8, "half_life": "days", "bias": "acts early",
        "blind_spot": "false starts", "route": "ROUTE_TO_CASINO_ODDS"},
    "SAFETY_OPTIMIZER": {
        "objective": "only act on confirmed, low-ambiguity signals",
        "weights": {"retention": 0.6, "margin": 0.5, "contamination": -0.8,
                    "regulation": -0.5},
        "preferred": "confirmed fundamentals", "ignored": "rumor",
        "risk_tolerance": 0.2, "half_life": "years", "bias": "waits for proof",
        "blind_spot": "misses early edge", "route": "ROUTE_TO_REALITY_CHECK"},
    "PRIVACY_OPTIMIZER": {
        "objective": "discount data of dubious provenance",
        "weights": {"contamination": -0.9, "growth": 0.3},
        "preferred": "first-party data", "ignored": "scraped buzz",
        "risk_tolerance": 0.4, "half_life": "months", "bias": "provenance-strict",
        "blind_spot": "useful public signal", "route": "ROUTE_TO_REALITY_CHECK"},
    "OPENNESS_OPTIMIZER": {
        "objective": "value transparent, verifiable signals",
        "weights": {"adoption": 0.6, "retention": 0.5, "contamination": -0.4},
        "preferred": "open/auditable evidence", "ignored": "closed black boxes",
        "risk_tolerance": 0.5, "half_life": "months", "bias": "transparency-led",
        "blind_spot": "proprietary moats", "route": "ROUTE_TO_FABLE5"},
    "ENTERPRISE_RELIABILITY_OPTIMIZER": {
        "objective": "weight durable B2B adoption",
        "weights": {"adoption": 0.9, "retention": 0.7, "regulation": -0.3},
        "preferred": "enterprise adoption", "ignored": "consumer fads",
        "risk_tolerance": 0.4, "half_life": "years", "bias": "institutional",
        "blind_spot": "consumer virality", "route": "ROUTE_TO_FABLE5"},
    "FLEET_EFFICIENCY_OPTIMIZER": {
        "objective": "optimize aggregate portfolio flow, not one road",
        "weights": {"capture": 0.6, "growth": 0.4, "capex": -0.4},
        "preferred": "system-level capture", "ignored": "single-name story",
        "risk_tolerance": 0.4, "half_life": "years", "bias": "portfolio-level",
        "blind_spot": "idiosyncratic alpha", "route": "ROUTE_TO_FOOD_CHAIN_ANALYSIS"},
}


def _feature_vector(obs: MythosObservation, econ: dict[str, Any],
                    narr: dict[str, Any]) -> dict[str, float]:
    def d(x, default):
        return default if x is None else clamp(x)
    capture = clamp((d(obs.capture_rate, 0.4)) * d(obs.pricing_power, 0.5)
                    - d(obs.leakage, 0.2))
    contrarian = clamp(econ["economic_reality_score"] - narr["narrative_belief_score"] + 0.5)
    return {
        "growth": d(obs.demand, 0.5) * 0.5 + d(obs.revenue_growth, 0.5) * 0.5,
        "margin": d(obs.margin_trend, 0.5),
        "retention": d(obs.retention, 0.5),
        "pricing": d(obs.pricing_power, 0.5),
        "adoption": d(obs.customer_adoption, 0.5),
        "capex": d(obs.capex_burden, 0.3),
        "regulation": d(obs.regulation_risk, 0.2),
        "momentum": clamp(0.5 * obs.attention + 0.5 * obs.mentions_velocity),
        "sentiment": clamp(obs.sentiment),
        "saturation": clamp(obs.saturation),
        "consensus": clamp(obs.consensus),
        "capture": capture,
        "contamination": clamp(obs.noise_level),
        "contrarian": clamp(contrarian),
    }


def _worldview_read(name: str, features: dict[str, float]) -> dict[str, Any]:
    prof = WORLDVIEWS[name]
    # signed score over centered axes
    s = 0.0
    for axis, w in prof["weights"].items():
        s += w * (features.get(axis, 0.5) - 0.5)
    score = clamp(2.0 * s, -1.0, 1.0)
    direction = "BULLISH" if score >= 0.12 else ("BEARISH" if score <= -0.12 else "NEUTRAL")
    return {
        "worldview_used": name,
        "worldview_cost_function": prof["objective"],
        "implied_interpretation": direction,
        "interpretation_score": round(score, 3),
        "likely_bias": prof["bias"],
        "blind_spot": prof["blind_spot"],
        "route_recommendation": prof["route"],
    }


# ==========================================================================
# Map-matching / explanation correction
# ==========================================================================
EXPLANATION_CATALOG: dict[str, list[str]] = {
    "revenue_growth": ["organic_demand", "pricing_increase", "subsidy_discount",
                       "acquisition", "channel_stuffing", "fx_tailwind",
                       "one_time_event", "accounting_change"],
    "cost_cutting": ["efficiency_reset", "growth_slowing", "distress",
                     "margin_discipline", "restructuring"],
    "narrative_buzz": ["real_breakthrough", "hype_cycle", "coordinated_promo",
                       "squeeze_chatter", "genuine_early_adoption"],
    "retention_up": ["product_improvement", "switching_costs",
                     "lack_of_alternatives", "discount_lock_in"],
    "generic": ["signal_is_real", "signal_is_noise", "signal_misattributed"],
}


def match_explanations(obs: MythosObservation) -> dict[str, Any]:
    ct = obs.claim_type if obs.claim_type in EXPLANATION_CATALOG else "generic"
    cands = EXPLANATION_CATALOG[ct]
    n = len(cands)
    base = {c: 1.0 / n for c in cands}

    def g(x, default):
        return default if x is None else clamp(x)

    if ct == "revenue_growth":
        # Unobserved corroboration counts as ZERO evidence (not neutral 0.5),
        # so an uncorroborated growth claim stays genuinely unresolved.
        margin = g(obs.margin_trend, 0.0)
        retention = g(obs.retention, 0.0)
        volume = g(obs.demand, 0.0)
        pricing = g(obs.pricing_power, 0.0)
        base["organic_demand"] += 0.35 * margin + 0.35 * retention + 0.25 * volume
        base["pricing_increase"] += 0.40 * pricing
        base["subsidy_discount"] += 0.5 if obs.discount_flag else 0.0
        base["acquisition"] += 0.6 if obs.acquisition_flag else 0.0
        base["channel_stuffing"] += 0.3 * clamp(volume - retention)
        base["fx_tailwind"] += 0.6 if obs.fx_flag else 0.0
        base["one_time_event"] += 0.6 if obs.one_time_flag else 0.0
        base["accounting_change"] += 0.6 if obs.accounting_flag else 0.0
    elif ct == "narrative_buzz":
        # real breakthrough needs economic corroboration; else hype.
        econ_present = any(v is not None for v in
                          (obs.revenue_growth, obs.margin_trend, obs.retention))
        base["real_breakthrough"] += 0.4 * g(obs.retention, 0.0) + 0.3 * g(obs.revenue_growth, 0.0)
        base["genuine_early_adoption"] += 0.3 * g(obs.customer_adoption, 0.0)
        base["hype_cycle"] += 0.4 * obs.saturation + 0.3 * clamp(obs.noise_level)
        base["coordinated_promo"] += 0.5 * clamp(obs.noise_level)
        base["squeeze_chatter"] += 0.3 * obs.mentions_velocity * (0.0 if econ_present else 1.0)
    elif ct == "cost_cutting":
        base["margin_discipline"] += 0.4 * g(obs.margin_trend, 0.5)
        base["growth_slowing"] += 0.4 * (1.0 - g(obs.revenue_growth, 0.5))
        base["distress"] += 0.4 * g(obs.capex_burden, 0.3) + 0.3 * g(obs.regulation_risk, 0.2)
    elif ct == "retention_up":
        base["product_improvement"] += 0.4 * g(obs.customer_adoption, 0.3)
        base["discount_lock_in"] += 0.5 if obs.discount_flag else 0.0

    # clamp + normalize
    for c in base:
        base[c] = max(0.0, base[c])
    total = sum(base.values()) or 1.0
    probs = {c: r3(base[c] / total) for c in base}
    best = max(probs, key=probs.get)
    best_p = probs[best]
    resolved = best_p >= 0.40
    required = []
    if ct == "revenue_growth":
        required = ["margin trend", "cohort retention", "unit volume",
                    "segment/acquisition disclosure"]
    elif ct == "narrative_buzz":
        required = ["revenue/usage data", "retention", "independent confirmation"]
    disconf = []
    if ct == "revenue_growth":
        disconf = ["if margin fell while revenue rose -> not organic/pricing-led",
                   "if retention flat/down -> demand not durable"]
    return {
        "candidate_explanations": list(cands),
        "explanation_probabilities": probs,
        "best_explanation": best if resolved else None,
        "best_explanation_probability": best_p,
        "unresolved_alternatives": [c for c in probs if probs[c] >= 0.15] if not resolved else [],
        "required_corroboration": required,
        "disconfirmation_tests": disconf,
        "resolved": resolved,
    }


# ==========================================================================
# Two-map model: economic reality vs narrative belief
# ==========================================================================
def _economic_map(obs: MythosObservation) -> dict[str, Any]:
    fields = {"demand": obs.demand, "revenue_growth": obs.revenue_growth,
              "margin_trend": obs.margin_trend, "retention": obs.retention,
              "pricing_power": obs.pricing_power, "customer_adoption": obs.customer_adoption}
    present = {k: v for k, v in fields.items() if v is not None}
    coverage = len(present) / len(fields)
    pos = mean([clamp(v) for v in present.values()], 0.0) if present else 0.0
    penalty = 0.15 * clamp(obs.capex_burden or 0.0) + 0.10 * clamp(obs.regulation_risk or 0.0)
    score = clamp(pos - penalty)
    return {"economic_reality_score": r3(score), "economic_coverage": r3(coverage)}


def _narrative_map(obs: MythosObservation) -> dict[str, Any]:
    odds = obs.prediction_odds if obs.prediction_odds is not None else 0.0
    score = clamp(0.25 * obs.attention + 0.25 * obs.mentions_velocity
                  + 0.20 * obs.sentiment + 0.15 * obs.amplification + 0.15 * odds)
    return {"narrative_belief_score": r3(score)}


def two_map_model(obs: MythosObservation) -> dict[str, Any]:
    econ = _economic_map(obs)
    narr = _narrative_map(obs)
    e, nval = econ["economic_reality_score"], narr["narrative_belief_score"]
    cov = econ["economic_coverage"]
    hi, lo = 0.55, 0.40
    if cov < 0.3 and nval >= hi:
        dtype = "NARRATIVE_UP_REALITY_DOWN"
    elif e >= hi and nval >= hi and obs.saturation >= 0.6:
        dtype = "REALITY_CONFIRMED_NARRATIVE_SATURATED"
    elif e >= hi and nval >= hi:
        dtype = "BOTH_UP"
    elif e < lo and nval < lo:
        dtype = "BOTH_DOWN"
    elif nval >= hi and e < lo:
        dtype = "NARRATIVE_UP_REALITY_DOWN"
    elif e >= hi and nval < lo:
        dtype = "REALITY_UP_NARRATIVE_DOWN"
    elif nval >= hi and lo <= e < hi:
        dtype = "NARRATIVE_EARLY_REALITY_FORMING"
    else:
        dtype = "NO_EDGE"
    raw_div = e - nval
    edge = clamp(abs(raw_div) * (1.0 - 0.5 * obs.saturation))
    return {
        "economic_reality_score": e,
        "economic_coverage": cov,
        "narrative_belief_score": nval,
        "reality_narrative_divergence": r3(raw_div),
        "divergence_type": dtype,
        "mispricing_edge": r3(edge),
    }


# ==========================================================================
# Reality-check ledger
# ==========================================================================
@dataclass
class ClaimRecord:
    claim: str
    interpretation: str
    governance: str
    confidence_before: float
    confidence_after: float
    survival_count: int
    contradiction_count: int
    expected_check_day: int
    next_reality_check: int
    status: str
    evidence_stack: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence_before"] = r3(self.confidence_before)
        d["confidence_after"] = r3(self.confidence_after)
        return d


_ALPHA = 0.15   # confirming-evidence learning rate
_BETA = 0.22    # disconfirming-evidence rate (asymmetric: contradictions hurt more)

# Governed sources earn a validation window even at low prior (PROVISIONAL);
# only ungoverned social / unknown sources start UNTESTED.
_GOVERNED = frozenset({
    "OFFICIAL_SOURCE", "INTERNAL_LEDGER", "OPEN_COMMUNITY", "USER_GENERATED",
    "NEWS_MEDIA", "PREDICTION_MARKET", "COMMERCIAL_DATA_VENDOR", "CLOSED_PLATFORM",
})


def evidence_effect(weight: float, independent: float) -> float:
    """Effective strength of one evidence event (independent counts more)."""
    return clamp(weight) * (0.6 + 0.4 * clamp(independent))


def apply_trust(trust: float, supports: bool, weight: float, independent: float) -> float:
    """Single source of truth for the trust update (used in-call and in the
    persistent ledger).  Trust_{t+1} = Trust_t + a*confirm - b*contradict."""
    eff = evidence_effect(weight, independent)
    if supports:
        return clamp(trust + _ALPHA * eff)
    return clamp(trust - _BETA * eff)


def derive_claim_status(*, survival: int, contradiction: int, prior_conf: float,
                        governance_type: str, eta_error: bool = False,
                        window_overdue: bool = False) -> str:
    """Cross-run status machine.  Shared by run_reality_check and the ledger."""
    if eta_error or window_overdue:
        return "STALE" if contradiction == 0 else "CONTESTED"
    if contradiction >= 2 and contradiction > survival:
        return "DISCONFIRMED"
    if contradiction >= 1 and survival >= 1:
        return "CONTESTED"
    if survival >= 3 and contradiction == 0:
        return "HIGH_CONFIDENCE"
    if survival >= 1:
        return "SUPPORTED"
    if prior_conf >= 0.4 or governance_type in _GOVERNED:
        return "PROVISIONAL"
    return "UNTESTED"


def run_reality_check(obs: MythosObservation, governance: dict[str, Any],
                      interpretation: str, prior_conf: float) -> ClaimRecord:
    trust = clamp(prior_conf)
    before = trust
    survival = 0
    contradiction = 0
    stack: list[dict[str, Any]] = []
    for ev in obs.evidence_events:
        supports = bool(ev.get("supports", True))
        w = clamp(ev.get("weight", 0.5))
        indep = clamp(ev.get("independent", 0.5))
        trust = apply_trust(trust, supports, w, indep)
        if supports:
            survival += 1
        else:
            contradiction += 1
        stack.append({"day": ev.get("day", obs.day), "supports": supports,
                      "weight": r3(w), "trust_after": r3(trust)})

    expected_check = obs.day + 30
    if obs.catalyst_eta_days is not None:
        expected_check = obs.day + int(obs.catalyst_eta_days)

    # ETA error: catalyst overdue -> stale/contested.
    eta_error = (obs.catalyst_eta_days is not None
                 and obs.catalyst_elapsed_days is not None
                 and obs.catalyst_elapsed_days > obs.catalyst_eta_days * 1.5)
    if eta_error:
        trust = clamp(trust - 0.2)
    status = derive_claim_status(
        survival=survival, contradiction=contradiction, prior_conf=prior_conf,
        governance_type=governance["governance_type"], eta_error=eta_error)

    return ClaimRecord(
        claim=obs.resolved_claim(), interpretation=interpretation,
        governance=governance["governance_type"],
        confidence_before=before, confidence_after=trust,
        survival_count=survival, contradiction_count=contradiction,
        expected_check_day=expected_check, next_reality_check=expected_check,
        status=status, evidence_stack=stack,
    )


_STATUS_SCORE = {
    "DISCONFIRMED": 0.05, "STALE": 0.15, "CONTESTED": 0.30, "UNTESTED": 0.30,
    "PROVISIONAL": 0.45, "SUPPORTED": 0.70, "HIGH_CONFIDENCE": 0.90,
}


# ==========================================================================
# ETA / thesis timing
# ==========================================================================
def thesis_eta(obs: MythosObservation, governance: dict[str, Any]) -> dict[str, Any]:
    t_catalyst = obs.catalyst_eta_days if obs.catalyst_eta_days is not None else 30.0
    t_recognition = 20.0 + 30.0 * (1.0 - governance["governance_trust_score"])
    eta = t_catalyst + t_recognition + obs.execution_lag_days
    buffer = round(0.3 * eta + 10.0 * (1.0 - governance["governance_trust_score"]), 1)
    eta_error = (obs.catalyst_eta_days is not None
                 and obs.catalyst_elapsed_days is not None
                 and obs.catalyst_elapsed_days > obs.catalyst_eta_days * 1.5)
    timing_risk = clamp(0.4 + 0.4 * (1.0 - governance["governance_trust_score"])
                        + (0.3 if eta_error else 0.0))
    if eta_error:
        quality = "ETA_MISSED"
    elif buffer / max(1.0, eta) >= 0.5:
        quality = "WIDE_UNCERTAINTY"
    else:
        quality = "BOUNDED"
    return {
        "thesis_eta_days": round(eta, 1),
        "thesis_eta_range": [round(max(0.0, eta - buffer), 1), round(eta + buffer, 1)],
        "uncertainty_buffer": buffer,
        "timing_quality": quality,
        "timing_risk": r3(timing_risk),
        "eta_error": eta_error,
        "timing_integrity": r3(clamp(1.0 - timing_risk)),
    }


# ==========================================================================
# Casino x food-chain bridge -> Fable 5 payload
# ==========================================================================
def _food_chain(obs: MythosObservation) -> dict[str, Any]:
    flow = clamp(obs.flow_growth if obs.flow_growth is not None else (obs.demand or 0.0))
    capture_rate = clamp(obs.capture_rate if obs.capture_rate is not None else 0.4)
    pricing = clamp(obs.pricing_power if obs.pricing_power is not None else 0.5)
    leakage = clamp(obs.leakage if obs.leakage is not None
                    else (obs.capex_burden if obs.capex_burden is not None else 0.2))
    dependency = clamp(obs.dependency if obs.dependency is not None else 0.3)
    capture_power = clamp(capture_rate * pricing)
    value_capture = clamp(flow * capture_rate * pricing - leakage)
    # role classification
    if capture_power >= 0.5 and dependency < 0.5:
        role = "PREDATOR"
    elif dependency >= 0.6 and capture_power < 0.4:
        role = "PREY"
    elif capture_power >= 0.45 and flow >= 0.5 and leakage < 0.4:
        role = "HABITAT"
    elif capture_power < 0.35 and flow >= 0.5:
        role = "PARASITE_RISK"  # rides flow without capturing
    else:
        role = "UNDIFFERENTIATED"
    if capture_power >= 0.5 and leakage < 0.3:
        toll = "TOLLBOOTH"
    elif leakage >= 0.5:
        toll = "LEAKY"
    else:
        toll = "COMMODITY"
    return {
        "value_capture_role": role,
        "capture_power": r3(capture_power),
        "food_chain_capture_score": r3(value_capture),
        "leakage_risk": r3(leakage),
        "dependency_risk": r3(dependency),
        "tollbooth_status": toll,
    }


def _casino(obs: MythosObservation, two_map: dict[str, Any],
            reality_score: float) -> dict[str, Any]:
    model_p = clamp(0.5 * two_map["economic_reality_score"] + 0.5 * reality_score)
    market_p = (clamp(obs.prediction_odds) if obs.prediction_odds is not None
                else two_map["narrative_belief_score"])
    odds_edge = r3(model_p - market_p)
    priced_in = clamp(0.6 * obs.saturation + 0.4 * obs.consensus)
    return {
        "model_probability": r3(model_p),
        "market_implied_probability": r3(market_p),
        "odds_edge": odds_edge,
        "expected_value_hint": odds_edge,
        "priced_in_risk": r3(priced_in),
        "casino_odds_integrity": r3(clamp(0.5 * (1.0 - priced_in) + 0.5 * abs(odds_edge) * 2.0)),
    }


# Mythos source -> a REAL Fable platform ecology (never "unknown").  Each maps
# to the ecology whose half-life / trust / sovereignty best matches the source.
MYTHOS_SOURCE_TO_ECOLOGY: dict[str, str] = {
    "sec_filing": "linkedin", "filing": "linkedin", "earnings_call": "linkedin",
    "regulatory": "linkedin", "analyst": "linkedin", "job_postings": "linkedin",
    "web_traffic": "youtube", "data_vendor": "youtube", "google": "youtube",
    "apple": "youtube",
    "internal_ledger": "substack", "provenance": "substack",
    "prediction_market": "x", "polymarket": "x", "kalshi": "x",
    "news": "x", "rss": "x", "media": "x", "x": "x", "twitter": "x",
    "grok": "x", "social": "x",
    "reddit": "reddit", "forum": "reddit", "app_reviews": "reddit",
    "customer_reviews": "reddit", "reviews": "reddit", "product_page": "reddit",
}
# Governance fallback so even an unmapped source lands on a real ecology.
_GOVERNANCE_TO_ECOLOGY: dict[str, str] = {
    "OFFICIAL_SOURCE": "linkedin", "INTERNAL_LEDGER": "substack",
    "PREDICTION_MARKET": "x", "NEWS_MEDIA": "x", "OPEN_COMMUNITY": "reddit",
    "USER_GENERATED": "reddit", "SOCIAL_FEED": "x",
    "COMMERCIAL_DATA_VENDOR": "youtube", "CLOSED_PLATFORM": "youtube",
    "EXPERIMENTAL_OR_UNKNOWN": "x",
}

# Claim-type-specific validation windows (days) — a TikTok fad and an
# infrastructure thesis should not share a 30-day clock.
CLAIM_TYPE_WINDOWS: dict[str, int] = {
    "narrative_buzz": 14, "retention_up": 60, "revenue_growth": 90,
    "cost_cutting": 90, "theme_sector": 90, "generic": 30,
}


def validation_window_for(claim_type: str) -> int:
    return CLAIM_TYPE_WINDOWS.get(claim_type, 30)


def source_to_ecology(source: str, governance_type: str = "EXPERIMENTAL_OR_UNKNOWN") -> str:
    """Map a Mythos source -> a real Fable platform ecology (never 'unknown')."""
    return (MYTHOS_SOURCE_TO_ECOLOGY.get((source or "").strip().lower())
            or _GOVERNANCE_TO_ECOLOGY.get(governance_type, "x"))


def build_fable5_dossier(obs: MythosObservation,
                         mythos: dict[str, Any] | None = None) -> SignalDossier:
    """Translate a Mythos observation + interpretation into a Fable 5 dossier.

    Rich translation (not a proxy stub): Mythos's economic-reality map becomes
    Fable's fundamental confirmation; the reality-vs-narrative divergence sets
    the blind score (so perception-dependent signals fail Fable's purity gate);
    governance/source picks a real platform ecology; value-capture role adds an
    owned-demand (sovereignty) ecology.  Fable's fraud gates apply unchanged.
    """
    m = mythos if mythos is not None else run_mythos(obs)
    econ = clamp(m["economic_reality_score"])
    narr = clamp(m["narrative_belief_score"])
    fc = m["food_chain"]
    rc_conf = clamp(m["reality_check"]["confidence_after"])
    priced_in = clamp(m["casino"]["priced_in_risk"])
    saturation = clamp(obs.saturation)
    consensus = clamp(obs.consensus)

    # Platform ecology: source -> real ecology (governance fallback).
    primary = source_to_ecology(obs.source, m["governance_type"])
    platforms = [primary]
    # Owned-demand / tollbooth -> add a merchant-sovereignty ecology.
    if fc["value_capture_role"] in ("PREDATOR", "HABITAT") or fc["tollbooth_status"] == "TOLLBOOTH":
        platforms.append("shopify")
    platforms = list(dict.fromkeys(platforms))

    def opt(x, fallback):
        return clamp(x) if x is not None else clamp(fallback)

    # Mythos reality map IS the fundamental confirmation.
    reality_confirmation = clamp(0.7 * econ + 0.3 * rc_conf)
    # Reality-vs-narrative divergence drives the blind score: narrative above
    # reality is a perception premium that Fable's purity gate must see.
    perception_premium = max(0.0, narr - econ)
    blind = clamp(econ - 0.6 * perception_premium)

    # Engagement proxies derived from ECONOMIC substance (adoption/retention),
    # never from narrative — so genuine behavior registers in Fable's attention
    # / vitality funnel, while a hype-only signal (econ ~ 0) stays near-zero.
    adoption = opt(obs.customer_adoption, econ)
    retention = opt(obs.retention, econ if obs.claim_type == "retention_up" else 0.5 * econ)
    return SignalDossier(
        signal_id=f"mythos::{obs.entity}",
        text=obs.raw_text or obs.resolved_claim(),
        platforms=platforms,
        views=round(econ * 4000),
        likes=round(adoption * 150),
        saves=round(retention * 60),
        conversions=round(adoption * 80),
        conversion_strength=adoption,
        retention_strength=retention,
        reproduction_strength=clamp(0.5 * econ + 0.3 * obs.amplification),
        business_confirmation=opt(obs.demand, econ),
        financial_confirmation=opt(obs.margin_trend, 0.8 * econ),
        reality_confirmation=reality_confirmation,
        price_recognition=clamp(0.4 * consensus + 0.3 * saturation + 0.3 * narr),
        crowding=clamp(max(saturation, 0.5 * priced_in)),
        blind_score=blind,
        age_days=float(obs.catalyst_elapsed_days or 0.0),
    )


# ==========================================================================
# Orchestrator
# ==========================================================================
def run_mythos(obs: MythosObservation) -> dict[str, Any]:
    """The full Observation -> Interpretation -> Routing -> Reality-check loop."""
    # 1. observation
    oq = observation_quality(obs)
    # 2. governance
    gov = classify_governance(obs)
    # 9. two-map (needed for feature vector + casino)
    tmap = two_map_model(obs)
    econ_lite = {"economic_reality_score": tmap["economic_reality_score"]}
    narr_lite = {"narrative_belief_score": tmap["narrative_belief_score"]}
    features = _feature_vector(obs, econ_lite, narr_lite)
    # 3. worldviews
    worldview_reads = [_worldview_read(w, features) for w in WORLDVIEWS]
    # 5. map-matching (computed early; feeds ambiguity)
    mm = match_explanations(obs)
    # 4. interpretation (beholders via token mass)
    tok = extract_tokens(obs.raw_text or obs.resolved_claim())
    beholders = interpret_beholders(tok.category_mass)
    # Worldview disagreement = direction *balance* (how evenly cost functions
    # split), not score range. Worldviews always span bull..bear, so the range
    # saturates; the minority-direction fraction discriminates split vs lopsided.
    dirs = [w["implied_interpretation"] for w in worldview_reads]
    n_bull = dirs.count("BULLISH")
    n_bear = dirs.count("BEARISH")
    minority_frac = (min(n_bull, n_bear) / (n_bull + n_bear)) if (n_bull + n_bear) else 0.0
    wv_disagreement = clamp(2.0 * minority_frac)
    interpretation_gap_score = r3(clamp(0.6 * beholders.interpretation_gap
                                        + 0.4 * wv_disagreement))
    # Strategy-gating ambiguity is content-driven: unclear when interpretations
    # split AND the explanation is unresolved AND reality is barely observed.
    ambiguity_score = r3(clamp(0.45 * beholders.interpretation_gap
                               + 0.30 * (0.0 if mm["resolved"] else 1.0)
                               + 0.25 * (1.0 - tmap["economic_coverage"])))
    dominant = beholders.dominant
    interpretation_confidence = clamp(
        0.4 * oq["observation_quality_score"] + 0.3 * gov["governance_trust_score"]
        + 0.3 * (1.0 - ambiguity_score))
    misinterpretation_risk = r3(clamp(ambiguity_score * (1.0 - gov["governance_trust_score"])))
    # 6. reality check
    prior = clamp(oq["initial_claim_confidence"] + gov["confidence_adjustment"])
    claim = run_reality_check(obs, gov, dominant.direction, prior)
    reality_check_score = _STATUS_SCORE.get(claim.status, 0.3)
    # Unresolved explanation keeps reality provisional.
    if not mm["resolved"] and reality_check_score > 0.45:
        reality_check_score = 0.45
    # 8. ETA
    eta = thesis_eta(obs, gov)
    # 10. bridge
    fc = _food_chain(obs)
    casino = _casino(obs, tmap, reality_check_score)
    # 11. layer integrity
    integrities = {
        "observation_integrity": oq["observation_quality_score"],
        "interpretation_integrity": r3(clamp(interpretation_confidence * (1.0 - 0.5 * ambiguity_score))),
        "governance_integrity": gov["governance_trust_score"],
        "reality_check_integrity": r3(reality_check_score),
        "food_chain_integrity": r3(clamp(0.5 + 0.5 * fc["food_chain_capture_score"])
                                   if (obs.capture_rate is not None or obs.flow_growth is not None)
                                   else 0.4),
        "casino_odds_integrity": casino["casino_odds_integrity"],
        "timing_integrity": eta["timing_integrity"],
        "feedback_integrity": r3(clamp(0.4 + 0.15 * claim.survival_count
                                       - 0.2 * claim.contradiction_count)),
    }
    vals = list(integrities.values())
    final_integrity = r3(clamp(0.5 * mean(vals) + 0.5 * min(vals)))  # weakest link bites
    final_confidence = r3(min(interpretation_confidence, final_integrity, reality_check_score + 0.2))

    # 7. routing + eligibility
    routing = _route(obs, tmap, mm, claim, fc, casino, integrities,
                     final_integrity, ambiguity_score, dominant.direction)
    eligibility = _strategy_eligibility(final_integrity, integrities, ambiguity_score, claim)

    return {
        "entity": obs.entity,
        "source": obs.source,
        "claim": obs.resolved_claim(),
        # layer 1-2
        "observation_quality_score": oq["observation_quality_score"],
        "observation_reason_codes": oq["observation_reason_codes"],
        "governance_type": gov["governance_type"],
        "governance_trust_score": gov["governance_trust_score"],
        "expected_validation_mode": gov["expected_validation_mode"],
        "likely_distortion": gov["likely_distortion"],
        # layer 3-4
        "worldview_interpretations": worldview_reads,
        "dominant_interpretation": dominant.to_dict(),
        "minority_interpretation": beholders.minority.to_dict(),
        "contrarian_interpretation": beholders.contrarian.to_dict(),
        "interpretation_gap_score": interpretation_gap_score,
        "worldview_disagreement": r3(wv_disagreement),
        "interpretation_confidence": r3(interpretation_confidence),
        "misinterpretation_risk": misinterpretation_risk,
        "ambiguity_score": r3(ambiguity_score),
        # layer 5
        "map_matching": mm,
        # layer 6
        "reality_check": claim.to_dict(),
        "claim_status": claim.status,
        "reality_check_score": r3(reality_check_score),
        # layer 8
        "eta": eta,
        # layer 9
        "two_map": tmap,
        "economic_reality_score": tmap["economic_reality_score"],
        "narrative_belief_score": tmap["narrative_belief_score"],
        "reality_narrative_divergence": tmap["reality_narrative_divergence"],
        "divergence_type": tmap["divergence_type"],
        # layer 10
        "food_chain": fc,
        "casino": casino,
        "mythos_to_fable5_payload": _fable5_payload(obs, tmap, fc, casino, claim,
                                                    dominant, final_integrity, routing),
        # layer 11
        "layer_integrity": integrities,
        "layer_integrity_score": final_integrity,
        "strategy_eligibility_score": final_integrity,
        "strategy_eligibility": eligibility,
        "final_mythos_confidence": final_confidence,
        # routing
        "routes": routing["routes"],
        "primary_route": routing["primary_route"],
        "recommended_next_module": routing["recommended_next_module"],
        # stamps
        "advisory_status": ADVISORY,
        "real_money_execution": REAL_MONEY,
        "broker_api_called": False,
    }


def _route(obs, tmap, mm, claim, fc, casino, integrities, final_integrity,
           ambiguity, direction) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []

    def add(name, reason, payoff, risk, ante, timing, conf, disconf):
        routes.append({"route": name, "reason": reason, "expected_payoff": payoff,
                       "risk": risk, "ante_cost": ante, "timing": timing,
                       "confidence": r3(clamp(conf)), "disconfirmation_condition": disconf})

    dtype = tmap["divergence_type"]
    status = claim.status

    # 1. dead theses first.
    if status in ("DISCONFIRMED", "STALE"):
        add("REJECT_INTERPRETATION", f"claim {status}", "none", "high", 0.0,
            "now", 0.2, "n/a")
        add("EXIT", "thesis invalidated / overdue", "avoid loss", "low", 0.0,
            "now", 0.4, "fresh confirming evidence appears")
    # 2. theme-only / weak capture -> food-chain.
    if obs.claim_type == "theme_sector" or (fc["capture_power"] < 0.4 and (obs.flow_growth or 0) >= 0.5):
        add("ROUTE_TO_FOOD_CHAIN_ANALYSIS",
            "sector/flow exposure without proven value capture", "depends", "med",
            0.1, "pre-decision", 0.5, "capture power stays low after analysis")
    # 3. narrative without reality -> reality check + odds.
    if dtype in ("NARRATIVE_UP_REALITY_DOWN", "NARRATIVE_EARLY_REALITY_FORMING"):
        add("ROUTE_TO_REALITY_CHECK", "narrative leads reality; unconfirmed", "depends",
            "high", 0.05, "weeks", 0.4, "reality fails to form in window")
        add("ROUTE_TO_CASINO_ODDS", "test if buzz is already priced", "small", "med",
            0.05, "weeks", 0.45, "odds edge negative")
    # 4. unresolved explanation -> collect evidence.
    if not mm["resolved"]:
        add("COLLECT_MORE_EVIDENCE", "best explanation unresolved", "info", "low",
            0.05, "weeks", 0.5, "corroboration never arrives")
    # 5. reality up, narrative down, supported -> Fable 5.
    if dtype == "REALITY_UP_NARRATIVE_DOWN" and status in ("SUPPORTED", "HIGH_CONFIDENCE", "PROVISIONAL"):
        add("ROUTE_TO_FABLE5", "reality ahead of belief (mispricing)", "high", "med",
            0.2, "weeks-months", 0.6, "reality reverses / margins fade")
        add("WATCHLIST", "stage entry on confirmation", "high", "med", 0.1,
            "weeks", 0.55, "narrative stays right and crowds in")
    # 6. saturated narrative -> no fresh edge.
    if dtype == "REALITY_CONFIRMED_NARRATIVE_SATURATED":
        add("AVOID", "real but fully priced / crowded", "low", "med", 0.0, "now",
            0.5, "a fresh second-order catalyst appears")
    # 7. ambiguity high -> clarity.
    if ambiguity >= 0.6:
        add("WATCHLIST", "interpretation ambiguous across worldviews", "depends",
            "med", 0.0, "weeks", 0.4, "worldviews converge")

    if not routes:
        add("WATCHLIST", "no decisive edge yet", "depends", "low", 0.0, "weeks",
            0.45, "a clear divergence or confirmation appears")

    # Primary: prefer reject/exit, then food-chain/reality routing, then fable5.
    priority = ["REJECT_INTERPRETATION", "EXIT", "ROUTE_TO_FOOD_CHAIN_ANALYSIS",
                "ROUTE_TO_REALITY_CHECK", "COLLECT_MORE_EVIDENCE", "ROUTE_TO_FABLE5",
                "AVOID", "WATCHLIST", "ROUTE_TO_CASINO_ODDS"]
    primary = min(routes, key=lambda r: priority.index(r["route"])
                  if r["route"] in priority else 99)["route"]
    next_module = {
        "ROUTE_TO_FOOD_CHAIN_ANALYSIS": "food_chain", "ROUTE_TO_REALITY_CHECK": "reality_check",
        "ROUTE_TO_FABLE5": "fable5", "ROUTE_TO_CASINO_ODDS": "casino_odds",
        "COLLECT_MORE_EVIDENCE": "evidence_intake",
    }.get(primary, "watch")
    return {"routes": routes, "primary_route": primary, "recommended_next_module": next_module}


def _strategy_eligibility(final_integrity, integrities, ambiguity, claim) -> str:
    if final_integrity < 0.30 or claim.status in ("DISCONFIRMED", "STALE"):
        return "REJECT_STRATEGY"
    if integrities["reality_check_integrity"] < 0.40:
        return "NEEDS_REALITY_CHECK"
    if ambiguity >= 0.6 or integrities["interpretation_integrity"] < 0.40:
        return "NEEDS_INTERPRETATION_CLARITY"
    if integrities["casino_odds_integrity"] < 0.35:
        return "NEEDS_ODDS_CHECK"
    if final_integrity < 0.50:
        return "WATCH_ONLY"
    if final_integrity < 0.62:
        return "STRATEGY_ALLOWED_LOW_CONFIDENCE"
    return "STRATEGY_ALLOWED"


def _fable5_payload(obs, tmap, fc, casino, claim, dominant, final_integrity,
                    routing) -> dict[str, Any]:
    return {
        "entity": obs.entity,
        "interpretation_summary": f"{dominant.direction} (dominant); divergence={tmap['divergence_type']}",
        "dominant_direction": dominant.direction,
        "economic_reality_score": tmap["economic_reality_score"],
        "narrative_belief_score": tmap["narrative_belief_score"],
        "divergence_type": tmap["divergence_type"],
        "claim_status": claim.status,
        "value_capture_role": fc["value_capture_role"],
        "food_chain_capture_score": fc["food_chain_capture_score"],
        "odds_edge": casino["odds_edge"],
        "model_probability": casino["model_probability"],
        "market_implied_probability": casino["market_implied_probability"],
        "confidence_cap": final_integrity,   # strategy confidence <= layer integrity
        "recommended_next_module": routing["recommended_next_module"],
        "advisory_status": ADVISORY,
    }


__all__ = [
    "MythosObservation", "run_mythos", "observation_quality", "classify_governance",
    "match_explanations", "two_map_model", "thesis_eta", "run_reality_check",
    "build_fable5_dossier", "WORLDVIEWS", "GOVERNANCE_PROFILES",
]
