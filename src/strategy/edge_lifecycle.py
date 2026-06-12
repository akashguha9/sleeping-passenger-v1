"""Edge Lifecycle Engine: detect live, underpriced acceleration before
edge decays below threshold.

The reflection's closing truth, operationalized:

    The MVP should not predict winners; it should detect live
    underpriced acceleration before the edge decays below threshold.

Five components the repo did NOT already have (half-life physics,
threshold gates, narrative phases, crowding, belief gaps, friction and
anti-streak discipline all predate this module and are reused, not
rebuilt — see STRATEGY_ENGINE.md):

* **Carrying capacity** — growth is logistic, not exponential:
  ``G(t) = K / (1 + A·e^(−rt))``. Estimates the hidden ceiling K,
  remaining runway ``K − G``, growth quality ``r × (K − G)``, detects
  bending toward saturation, and flags fake-exponential narratives
  (claimed growth that would cross the ceiling inside the horizon).
* **Acceleration path (brachistochrone)** — the fastest path is not the
  shortest: Path A reckless drop, Path B controlled acceleration,
  Path C slow straight line. Potential energy must convert into market
  velocity: ``conversion = realized momentum / latent potential``.
* **Arbitrage convergence** — a gap only matters if it closes:
  ``net edge = gap × P(convergence) − friction − break risk``; a gap
  with no convergence catalyst is a value trap, not an opportunity.
* **Hedged-edge decomposition** — survival before upside:
  ``hedged edge = thesis edge − unwanted beta − hedge cost``; hedge
  efficiency = risk reduced / return sacrificed; over-hedging kills
  the very edge it protects.
* **Thesis expiry clock** — every thesis gets a death date:
  ``E(t) = E0 · 0.5^(t/h) > T  =>  t_expiry = h · log2(E0/T)``,
  computed from the payload's own signal-tyre physics when available
  (self-feed style, with provenance).

The verdict never promotes — ADVISORY_ONLY, conservative-wins: a
"live_underpriced_acceleration" label is a research finding, while an
expired edge or a priced-in saturating compounder caps the ladder.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip, safe_div
from src.utils.validation_utils import coerce_float, normalized_score

# ---------------------------------------------------------------------------
# Carrying capacity
# ---------------------------------------------------------------------------

SATURATION_STATES: tuple[str, ...] = (
    "early_runway", "mid_curve", "bending_toward_saturation", "saturated",
)


@dataclass(slots=True)
class CarryingCapacityReport:
    """The hidden ceiling K and how close growth has bent toward it."""

    k_proxy: float  # normalized ceiling estimate, 0..1 scale of "scale"
    current_scale: float
    ceiling_utilization: float  # G/K
    remaining_runway: float  # K − G
    growth_quality: float  # r × (K − G)
    saturation_state: str
    fake_exponential: bool
    binding_constraint: str = "blended_headroom"
    ceilings: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def estimate_carrying_capacity(
    *,
    current_scale: float = 0.0,
    market_penetration: float = 0.0,
    tam_evidence: float = 0.5,
    expansion_optionality: float = 0.0,
    pricing_power: float = 0.5,
    competitive_pressure: float = 0.5,
    regulatory_headroom: float = 0.5,
    claimed_growth_rate: float = 0.0,
    growth_rate_trend: list[float] | None = None,
    horizon_years: float = 3.0,
    ceilings: dict[str, float] | None = None,
) -> CarryingCapacityReport:
    """G(t) ≤ K, never G(t) ≤ e: the ceiling is structural, not magic.

    ``K = f(TAM evidence, pricing power, optionality, competition,
    regulation)`` on a normalized scale where ``current_scale`` is the
    company's present size relative to its addressable opportunity.
    A 60% grower at 0.8 utilization is worse than a 20% grower at 0.2:
    ``growth_quality = r × (K − G)``.

    ``ceilings`` decomposes K into named bottlenecks (market, adoption,
    pricing, margin, regulatory, capital, competition, execution,
    attention…): growth does not hit one ceiling, it hits the TIGHTEST
    bottleneck first — ``K_eff = min(K_blend, min_i(K_i))``, and the
    binding constraint is named. An attention/narrative bottleneck is
    a ceiling made of hype, and the report says so.
    """
    scale = normalized_score(current_scale)
    penetration = normalized_score(market_penetration)
    evidence = normalized_score(tam_evidence, 0.5)
    optionality = normalized_score(expansion_optionality)
    power = normalized_score(pricing_power, 0.5)
    competition = normalized_score(competitive_pressure, 0.5)
    regulation = normalized_score(regulatory_headroom, 0.5)
    growth = max(coerce_float(claimed_growth_rate), 0.0)

    # The ceiling: current scale plus the headroom the evidence actually
    # supports — evidenced TAM stretched by optionality and pricing
    # power, compressed by competition and regulatory walls. K can never
    # sit below where the company already is.
    headroom_factor = clamp01(
        evidence * (0.7 + 0.2 * optionality + 0.1 * power)
        * (1.0 - 0.3 * competition)
        * (0.7 + 0.3 * regulation)
    )
    k_proxy = clamp01(scale + (1.0 - scale) * headroom_factor)
    # Bottleneck decomposition: the tightest declared ceiling binds.
    ceiling_map = {
        str(name): clamp01(coerce_float(value))
        for name, value in (ceilings or {}).items()
    }
    binding_constraint = "blended_headroom"
    if ceiling_map:
        tightest_name, tightest = min(
            ceiling_map.items(), key=lambda kv: kv[1]
        )
        if tightest < k_proxy:
            # A ceiling below current scale means fully saturated, not
            # impossible: K_eff floors at the company's present size.
            k_proxy = max(tightest, scale)
            binding_constraint = tightest_name
    utilization = clamp01(safe_div(scale, max(k_proxy, 1e-9)))
    # Penetration is direct saturation evidence; trust the worse signal.
    utilization = max(utilization, penetration)
    runway = clamp01(1.0 - utilization)
    growth_quality = growth * runway

    trend = [coerce_float(v) for v in (growth_rate_trend or [])]
    decelerating = len(trend) >= 3 and trend[-1] < trend[-2] < trend[-3]
    if utilization >= 0.85:
        state = "saturated"
    elif utilization >= 0.6 or (decelerating and utilization >= 0.4):
        state = "bending_toward_saturation"
    elif utilization >= 0.3:
        state = "mid_curve"
    else:
        state = "early_runway"

    # Fake exponential: the claimed rate, compounded over the horizon,
    # would overrun the evidenced ceiling — the narrative is selling
    # e^rt where only K/(1+Ae^-rt) is structurally possible.
    horizon = max(coerce_float(horizon_years), 0.0)
    implied_scale = scale * ((1.0 + growth) ** horizon) if scale > 0 else 0.0
    fake_exponential = bool(
        growth > 0 and scale > 0 and implied_scale > k_proxy * 1.05
    )

    rationale = [
        f"K≈{k_proxy:.2f}, utilization {utilization:.0%} -> {state}; "
        f"runway {runway:.2f}, growth quality {growth_quality:.3f} "
        f"(rate {growth:.0%} × runway)",
    ]
    if fake_exponential:
        rationale.append(
            f"claimed {growth:.0%}/yr for {horizon:.0f}y implies scale "
            f"{implied_scale:.2f} > K {k_proxy:.2f} — exponential "
            "narrative on a logistic curve"
        )
    if decelerating:
        rationale.append(
            "growth deceleration across 3 consecutive periods — the "
            "curve is bending"
        )
    if binding_constraint != "blended_headroom":
        rationale.append(
            f"binding constraint: {binding_constraint} ceiling "
            f"({ceiling_map[binding_constraint]:.2f}) — growth hits the "
            "tightest bottleneck first, not the blended average"
        )
        if binding_constraint in ("attention", "narrative"):
            rationale.append(
                "the ceiling is made of attention, not revenue — a "
                "hype-bound TAM saturates when the crowd moves on"
            )
    return CarryingCapacityReport(
        k_proxy=round(k_proxy, 4),
        current_scale=scale,
        ceiling_utilization=round(utilization, 4),
        remaining_runway=round(runway, 4),
        growth_quality=round(growth_quality, 4),
        saturation_state=state,
        fake_exponential=fake_exponential,
        binding_constraint=binding_constraint,
        ceilings=ceiling_map,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Acceleration path (brachistochrone)
# ---------------------------------------------------------------------------

PATH_CLASSES: tuple[str, ...] = (
    "controlled_acceleration",  # Path B — drops early, converts, rides
    "reckless_drop",            # Path A — max velocity, no support
    "slow_straight_line",       # Path C — shortest story, slowest move
    "stalled_potential",        # energy stored, nothing converting
)


@dataclass(slots=True)
class AccelerationPathReport:
    """Does hidden potential convert into market velocity early?"""

    path_class: str
    acceleration_edge: float
    conversion_ratio: float  # realized momentum / latent potential
    latent_potential: float
    realized_momentum: float
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_acceleration_path(
    *,
    latent_potential: float = 0.0,
    realized_momentum: float = 0.0,
    catalyst_strength: float = 0.0,
    catalyst_proximity_days: float | None = None,
    evidence_support: float = 0.5,
    friction: float = 0.2,
    decay_risk: float = 0.3,
    crowding: float = 0.0,
) -> AccelerationPathReport:
    """mgh → ½mv²: potential matters only when it becomes velocity.

    ``AccelerationEdge = (catalyst × early momentum) / (friction +
    decay + crowding)``. Path B beats both the reckless vertical drop
    (momentum without evidence) and the clean slow line (potential
    without a catalyst).
    """
    potential = normalized_score(latent_potential)
    momentum = normalized_score(realized_momentum)
    catalyst = normalized_score(catalyst_strength)
    support = normalized_score(evidence_support, 0.5)
    drag = (
        normalized_score(friction, 0.2)
        + normalized_score(decay_risk, 0.3)
        + normalized_score(crowding)
    )
    proximity_boost = 1.0
    if catalyst_proximity_days is not None:
        days = max(coerce_float(catalyst_proximity_days), 0.0)
        proximity_boost = clip(1.0 + 0.5 * (1.0 - min(days, 90.0) / 90.0),
                               1.0, 1.5)
    acceleration_edge = clip(
        safe_div(catalyst * proximity_boost * momentum, max(drag, 0.1)),
        0.0, 10.0,
    )
    conversion = clamp01(safe_div(momentum, max(potential, 1e-9))) if (
        potential > 0
    ) else 0.0

    if momentum >= 0.6 and support < 0.35:
        path = "reckless_drop"
    elif catalyst >= 0.4 and momentum >= 0.3 and support >= 0.35:
        path = "controlled_acceleration"
    elif potential >= 0.5 and catalyst < 0.3:
        path = "stalled_potential"
    else:
        path = "slow_straight_line"

    rationale = [
        f"potential {potential:.2f} -> momentum {momentum:.2f} "
        f"(conversion {conversion:.0%}); acceleration edge "
        f"{acceleration_edge:.2f} = catalyst {catalyst:.2f} × "
        f"proximity {proximity_boost:.2f} × momentum / drag {drag:.2f}",
        {
            "controlled_acceleration": "Path B: early conversion with "
            "evidence behind it — the cycloid, not the cliff",
            "reckless_drop": "Path A: velocity without evidential "
            "support — a vertical drop that cannot brake",
            "slow_straight_line": "Path C: the shortest story and the "
            "slowest repricing — clean, late, crowd-visible",
            "stalled_potential": "stored energy with no catalyst to "
            "convert it — mgh that never becomes ½mv²",
        }[path],
    ]
    return AccelerationPathReport(
        path_class=path,
        acceleration_edge=round(acceleration_edge, 4),
        conversion_ratio=round(conversion, 4),
        latent_potential=potential,
        realized_momentum=momentum,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Arbitrage convergence
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ArbitrageReport:
    """A mispricing gap is worthless unless it converges in time."""

    gap: float  # reality − priced belief
    safe_gap: float  # gap after uncertainty, staleness, evidence quality
    convergence_probability: float
    net_edge: float
    value_trap: bool
    gap_unsupported: bool
    gap_half_life_days: float
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def detect_arbitrage_gap(
    *,
    reality_score: float = 0.0,
    priced_belief: float = 0.0,
    convergence_catalyst: str = "",
    convergence_probability: float = 0.0,
    friction: float = 0.1,
    break_risk: float = 0.2,
    crowding: float = 0.0,
    gap_half_life_days: float = 45.0,
    uncertainty_band: float = 0.0,
    evidence_quality: float | None = None,
    price_already_moved: float = 0.0,
) -> ArbitrageReport:
    """Net edge = gap × P(convergence) − friction − break risk.

    Arbitrage is mismatch capture, not free money: the gap must close
    before decay, friction, and crowding consume it. A gap without a
    named convergence catalyst is a value trap.

    The SAFE gap is the disciplined version of P_model − P_market:

        safe_gap = (gap − uncertainty_band − 0.5·price_already_moved·gap)
                   × evidence_quality

    A wide gap built on low-quality evidence, wide uncertainty, or a
    price that already moved is heat, not edge (``gap_unsupported``).
    With no discipline inputs supplied, safe_gap == gap (back-compat).
    """
    reality = normalized_score(reality_score)
    belief = normalized_score(priced_belief)
    gap = round(reality - belief, 4)
    band = normalized_score(uncertainty_band)
    moved = normalized_score(price_already_moved)
    quality = (
        normalized_score(evidence_quality, 1.0)
        if evidence_quality is not None else 1.0
    )
    safe_gap = round(
        clip((gap - band - 0.5 * moved * max(gap, 0.0)) * quality,
             -1.0, 1.0),
        4,
    )
    gap_unsupported = gap > 0.1 and safe_gap <= 0.02
    has_catalyst = bool(str(convergence_catalyst).strip())
    p_convergence = normalized_score(convergence_probability) if (
        has_catalyst
    ) else 0.0
    fr = normalized_score(friction, 0.1)
    brk = normalized_score(break_risk, 0.2)
    crowd = normalized_score(crowding)
    half_life = max(coerce_float(gap_half_life_days), 1.0)
    # Crowding shortens the window — the crowd closes (or tramples) it.
    effective_half_life = half_life * (1.0 - 0.5 * crowd)

    net_edge = round(max(gap, 0.0) * p_convergence - fr - brk * 0.5, 4)
    value_trap = gap > 0.1 and (not has_catalyst or p_convergence < 0.25)

    rationale = [
        f"gap {gap:+.2f} (reality {reality:.2f} − belief {belief:.2f}); "
        f"net edge {net_edge:+.3f} = gap × P(conv {p_convergence:.2f}) "
        f"− friction {fr:.2f} − ½·break {brk:.2f}; window "
        f"≈{effective_half_life:.0f}d",
    ]
    if safe_gap != gap:
        rationale.append(
            f"safe gap {safe_gap:+.2f} = (gap − band {band:.2f} − "
            f"½·moved {moved:.2f}·gap) × evidence quality {quality:.2f}"
        )
    if gap_unsupported:
        rationale.append(
            "the gap is heat, not edge: wide on paper, gone after "
            "uncertainty, staleness, and evidence quality"
        )
    if value_trap:
        rationale.append(
            "gap without a credible convergence path — cheap can stay "
            "cheap; this is a value trap until a catalyst is named"
        )
    elif gap <= 0.05:
        rationale.append(
            "reality is not ahead of belief — nothing to converge"
        )
    return ArbitrageReport(
        gap=gap,
        safe_gap=safe_gap,
        convergence_probability=p_convergence,
        net_edge=net_edge,
        value_trap=value_trap,
        gap_unsupported=gap_unsupported,
        gap_half_life_days=round(effective_half_life, 2),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Hedged-edge decomposition
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class HedgedEdgeReport:
    """Survival before upside: isolate alpha from unwanted exposure."""

    thesis_edge: float
    unwanted_exposure: float
    hedge_cost: float
    hedged_edge: float
    hedge_efficiency: float | None
    over_hedged: bool
    survival_viable: bool
    exposures: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def decompose_hedged_edge(
    *,
    thesis_edge: float = 0.0,
    exposures: dict[str, float] | None = None,
    hedge_cost: float = 0.0,
    risk_reduced: float = 0.0,
    ruin_risk: float = 0.2,
) -> HedgedEdgeReport:
    """Hedged edge = thesis edge − unwanted beta − hedge cost.

    ``exposures`` are unwanted-beta magnitudes (market, sector, rates,
    FX, commodity…). Hedge efficiency = risk reduced / return
    sacrificed; an over-hedge (cost ≥ thesis edge, or efficiency < 1)
    kills the edge it was bought to protect. This recommends hedge
    STRUCTURE for research — no instrument is ever traded here.
    """
    edge = normalized_score(thesis_edge)
    exposure_map = {
        str(k): normalized_score(v) for k, v in (exposures or {}).items()
    }
    unwanted = clamp01(sum(exposure_map.values()) * 0.5)
    cost = normalized_score(hedge_cost)
    reduced = normalized_score(risk_reduced)
    hedged = round(edge - unwanted * 0.5 - cost, 4)
    efficiency = (
        round(safe_div(reduced, cost), 4) if cost > 0 else None
    )
    over_hedged = cost > 0 and (
        cost >= edge or (efficiency is not None and efficiency < 1.0)
    )
    ruin = normalized_score(ruin_risk, 0.2)
    survival_viable = hedged > 0 and ruin < 0.5

    rationale = [
        f"hedged edge {hedged:+.3f} = thesis {edge:.2f} − ½·unwanted "
        f"{unwanted:.2f} − cost {cost:.2f}"
        + (f"; efficiency {efficiency:.2f}" if efficiency is not None
           else "; unhedged"),
        (
            "over-hedged: the protection costs more than the edge it "
            "protects" if over_hedged else (
                "survival viable: the thesis can be wrong without ruin"
                if survival_viable else
                "survival NOT viable: ruin risk or negative hedged edge "
                "— upside is irrelevant if the path kills you first"
            )
        ),
    ]
    return HedgedEdgeReport(
        thesis_edge=edge,
        unwanted_exposure=round(unwanted, 4),
        hedge_cost=cost,
        hedged_edge=hedged,
        hedge_efficiency=efficiency,
        over_hedged=over_hedged,
        survival_viable=survival_viable,
        exposures=exposure_map,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Thesis expiry clock
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ExpiryClock:
    """Every thesis gets a death date: t = h · log2(E0/T)."""

    live_edge: float
    threshold: float
    half_life_days: float
    days_to_expiry: float
    status: str  # live | marginal | expired
    edge_source: str
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_expiry_clock(
    *,
    live_edge: float = 0.0,
    threshold: float = 0.25,
    half_life_days: float = 30.0,
    edge_source: str = "caller_judgement",
) -> ExpiryClock:
    """E(t) = E0 · 0.5^(t/h) stays above T for t < h·log2(E0/T).

    The goal is not to find edge; the goal is to know when edge has
    expired. ``days_to_expiry`` answers: if nothing new happens, how
    many days until this thesis is no longer actionable?
    """
    edge = normalized_score(live_edge)
    gate = max(normalized_score(threshold, 0.25), 1e-6)
    half_life = max(coerce_float(half_life_days), 0.1)
    if edge <= gate:
        days = 0.0
        status = "expired"
    else:
        days = half_life * math.log2(edge / gate)
        status = "marginal" if days < half_life * 0.5 else "live"
    rationale = [
        f"E0 {edge:.2f} vs threshold {gate:.2f} at half-life "
        f"{half_life:.0f}d -> {days:.1f} days to expiry ({status}); "
        f"edge source: {edge_source}",
        "act only while E(t) > T — a signal existing is not a reason "
        "to act on it",
    ]
    return ExpiryClock(
        live_edge=edge,
        threshold=gate,
        half_life_days=round(half_life, 2),
        days_to_expiry=round(max(days, 0.0), 2),
        status=status,
        edge_source=str(edge_source),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Orchestrator: the Opportunity equation and the lifecycle verdict
# ---------------------------------------------------------------------------

LIFECYCLE_VERDICTS: tuple[str, ...] = (
    "live_underpriced_acceleration",  # the golden state
    "potential_without_catalyst",
    "priced_in",
    "saturating_compounder",
    "decayed_below_threshold",
    "watch_and_revalidate",
)


@dataclass(slots=True)
class EdgeLifecycleReport:
    """One thesis through the full edge lifecycle."""

    verdict: str
    opportunity_score: float  # 0..10
    capacity: dict[str, object]
    path: dict[str, object]
    arbitrage: dict[str, object]
    hedge: dict[str, object]
    expiry: dict[str, object]
    derived_inputs: dict[str, str] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _kwargs_for(func, section: dict) -> dict:
    return {
        k: v for k, v in section.items() if k in func.__kwdefaults__
    }


def assess_edge_lifecycle(
    section: dict,
    *,
    derived: dict | None = None,
) -> EdgeLifecycleReport:
    """Run one ``lifecycle`` payload section through all five components
    and reconcile them with the reflection's Opportunity equation:

        Opportunity = (Potential × Acceleration × Underpricing)
                      / (Decay + Crowding + Friction + ExecutionRisk
                         + UnhedgedExposure)

    ``derived`` carries self-fed inputs (crowding from the theme mapper,
    half-life/live edge from the signal tyres, priced belief from the
    Bayes posterior) with provenance; caller values win only when more
    conservative, mirroring the self-feed asymmetry.
    """
    section = dict(section or {})
    derived = dict(derived or {})
    derived_provenance: dict[str, str] = {}

    # Self-fed conservative merges (engine value vs caller value).
    crowding = normalized_score(section.get("crowding", 0.0))
    if "crowding" in derived:
        engine_crowd = float(derived["crowding"])
        if engine_crowd > crowding:
            crowding = engine_crowd
            derived_provenance["crowding"] = "theme_mapper.crowding"
    half_life = coerce_float(section.get("half_life_days"), 30.0)
    if "half_life_days" in derived and "half_life_days" not in section:
        half_life = float(derived["half_life_days"])
        derived_provenance["half_life_days"] = (
            "signal_tyres.adjusted_half_life_hours/24"
        )
    live_edge = normalized_score(section.get("live_edge", 0.0))
    if "live_edge" in derived:
        engine_edge = float(derived["live_edge"])
        if "live_edge" not in section or engine_edge < live_edge:
            live_edge = engine_edge
            derived_provenance["live_edge"] = (
                "signal_tyres.blended_grip_pct/100"
            )
    belief = section.get("priced_belief")
    if belief is None and "priced_belief" in derived:
        belief = derived["priced_belief"]
        derived_provenance["priced_belief"] = derived.get(
            "priced_belief_source", "bayes.posterior"
        )

    capacity = estimate_carrying_capacity(
        **_kwargs_for(estimate_carrying_capacity,
                      dict(section.get("capacity") or {}))
    )
    path_section = dict(section.get("path") or {})
    path_section.setdefault("crowding", crowding)
    path = score_acceleration_path(
        **_kwargs_for(score_acceleration_path, path_section)
    )
    arb_section = dict(section.get("arbitrage") or {})
    arb_section.setdefault("crowding", crowding)
    if belief is not None:
        arb_section.setdefault("priced_belief", coerce_float(belief))
    arbitrage = detect_arbitrage_gap(
        **_kwargs_for(detect_arbitrage_gap, arb_section)
    )
    hedge = decompose_hedged_edge(
        **_kwargs_for(decompose_hedged_edge,
                      dict(section.get("hedge") or {}))
    )
    expiry = compute_expiry_clock(
        live_edge=live_edge,
        threshold=normalized_score(section.get("threshold", 0.25), 0.25),
        half_life_days=half_life,
        edge_source=(
            derived_provenance.get("live_edge", "caller_judgement")
        ),
    )

    friction = normalized_score(
        dict(section.get("arbitrage") or {}).get("friction", 0.1), 0.1
    )
    execution_risk = normalized_score(section.get("execution_risk", 0.2),
                                      0.2)
    decay_pressure = clamp01(1.0 - expiry.live_edge)
    unhedged = clamp01(hedge.unwanted_exposure if not hedge.over_hedged
                       else hedge.unwanted_exposure + 0.2)
    numerator = (
        capacity.remaining_runway
        * clamp01(path.acceleration_edge / 2.0)
        * clamp01(max(arbitrage.gap, 0.0) * 2.0)
    )
    denominator = (
        decay_pressure + crowding + friction + execution_risk + unhedged
    )
    opportunity = round(
        clip(safe_div(numerator, max(denominator, 0.2)) * 10.0, 0.0, 10.0),
        2,
    )

    if expiry.status == "expired":
        verdict = "decayed_below_threshold"
    elif capacity.saturation_state in (
        "saturated", "bending_toward_saturation",
    ) and arbitrage.gap <= 0.05:
        verdict = "saturating_compounder"
    elif arbitrage.gap <= 0.05:
        verdict = "priced_in"
    elif path.path_class in ("stalled_potential", "slow_straight_line") or (
        arbitrage.value_trap
    ):
        verdict = "potential_without_catalyst"
    elif (
        path.path_class == "controlled_acceleration"
        # The golden state demands the SAFE gap: edge that survives
        # uncertainty, price staleness, and evidence-quality discipline.
        and arbitrage.safe_gap > 0.1
        and capacity.remaining_runway >= 0.3
        and expiry.status == "live"
        and not capacity.fake_exponential
        # Survival before upside: a declared hedge structure that is not
        # viable (over-hedged or ruin-exposed) blocks the golden state.
        and (not section.get("hedge") or hedge.survival_viable)
    ):
        verdict = "live_underpriced_acceleration"
    else:
        verdict = "watch_and_revalidate"

    rationale = [
        f"verdict: {verdict}; opportunity {opportunity:.1f}/10 = "
        f"(runway {capacity.remaining_runway:.2f} × accel "
        f"{clamp01(path.acceleration_edge / 2.0):.2f} × underpricing "
        f"{clamp01(max(arbitrage.gap, 0.0) * 2.0):.2f}) / (decay "
        f"{decay_pressure:.2f} + crowding {crowding:.2f} + friction "
        f"{friction:.2f} + execution {execution_risk:.2f} + unhedged "
        f"{unhedged:.2f})",
        f"expiry clock: {expiry.days_to_expiry:.1f} days "
        f"({expiry.status}) — the goal is not finding edge but knowing "
        "when it dies",
    ]
    if capacity.fake_exponential:
        rationale.append(
            "fake-exponential narrative: golden state is unreachable "
            "until the growth story fits inside its own ceiling"
        )
    return EdgeLifecycleReport(
        verdict=verdict,
        opportunity_score=opportunity,
        capacity=capacity.to_dict(),
        path=path.to_dict(),
        arbitrage=arbitrage.to_dict(),
        hedge=hedge.to_dict(),
        expiry=expiry.to_dict(),
        derived_inputs=derived_provenance,
        rationale=rationale,
    )
