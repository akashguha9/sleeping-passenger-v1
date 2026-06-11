"""Crash-case permutation simulator: crash cases are the wall.

Risks interact nonlinearly. Pairwise and triple-wise combinations are
stress-tested with interaction terms:

    Crash Risk = Σ R_i + Σ β_ij R_i R_j + Σ β_ijk R_i R_j R_k
    Crash Density = severe combinations / total tested combinations

Upside without crash survival is not an opportunity.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, safe_div

CRASH_CATEGORY_FUNDAMENTAL = "fundamental_crash"
CRASH_CATEGORY_NARRATIVE = "narrative_crash"
CRASH_CATEGORY_MARKET_STRUCTURE = "market_structure_crash"
CRASH_CATEGORY_MACRO = "macro_crash"
CRASH_CATEGORY_TIMING = "timing_crash"
CRASH_CATEGORY_DATA = "data_crash"
CRASH_CATEGORY_DRIVER = "driver_behavior_crash"

CRASH_CATEGORIES: tuple[str, ...] = (
    CRASH_CATEGORY_FUNDAMENTAL,
    CRASH_CATEGORY_NARRATIVE,
    CRASH_CATEGORY_MARKET_STRUCTURE,
    CRASH_CATEGORY_MACRO,
    CRASH_CATEGORY_TIMING,
    CRASH_CATEGORY_DATA,
    CRASH_CATEGORY_DRIVER,
)

# Known risk factor -> crash category. Unknown factors default to
# fundamental_crash so they are never silently dropped.
RISK_FACTOR_CATEGORIES: dict[str, str] = {
    "high_valuation": CRASH_CATEGORY_FUNDAMENTAL,
    "weak_fcf": CRASH_CATEGORY_FUNDAMENTAL,
    "margin_compression": CRASH_CATEGORY_FUNDAMENTAL,
    "receivables_spike": CRASH_CATEGORY_FUNDAMENTAL,
    "high_leverage": CRASH_CATEGORY_FUNDAMENTAL,
    "social_hype": CRASH_CATEGORY_NARRATIVE,
    "stale_signal": CRASH_CATEGORY_NARRATIVE,
    "dirty_air": CRASH_CATEGORY_NARRATIVE,
    "narrative_crowding": CRASH_CATEGORY_NARRATIVE,
    "low_volume": CRASH_CATEGORY_MARKET_STRUCTURE,
    "insider_selling": CRASH_CATEGORY_MARKET_STRUCTURE,
    "low_liquidity": CRASH_CATEGORY_MARKET_STRUCTURE,
    "concentrated_holders": CRASH_CATEGORY_MARKET_STRUCTURE,
    "rising_rates": CRASH_CATEGORY_MACRO,
    "recession_risk": CRASH_CATEGORY_MACRO,
    "election_uncertainty": CRASH_CATEGORY_MACRO,
    "regulatory_delay": CRASH_CATEGORY_MACRO,
    "price_already_ran": CRASH_CATEGORY_TIMING,
    "catalyst_slipped": CRASH_CATEGORY_TIMING,
    "late_detection": CRASH_CATEGORY_TIMING,
    "weak_data_quality": CRASH_CATEGORY_DATA,
    "estimate_uncertainty": CRASH_CATEGORY_DATA,
    "chasing": CRASH_CATEGORY_DRIVER,
    "oversizing": CRASH_CATEGORY_DRIVER,
    "revenge_trading": CRASH_CATEGORY_DRIVER,
}

# Default interaction coefficients.
DEFAULT_PAIR_BETA = 0.5
DEFAULT_TRIPLE_BETA = 0.25

# Known deadly synergies get amplified pairwise betas.
SYNERGY_PAIR_BETAS: dict[frozenset[str], float] = {
    frozenset({"high_valuation", "rising_rates"}): 1.0,
    frozenset({"high_valuation", "weak_fcf"}): 0.9,
    frozenset({"social_hype", "low_volume"}): 0.9,
    frozenset({"social_hype", "insider_selling"}): 0.8,
    frozenset({"price_already_ran", "low_volume"}): 0.8,
    frozenset({"margin_compression", "receivables_spike"}): 0.8,
    frozenset({"election_uncertainty", "regulatory_delay"}): 0.7,
    frozenset({"stale_signal", "dirty_air"}): 0.7,
}

# A tested combination is severe when its combined score crosses this.
SEVERE_COMBINATION_THRESHOLD = 1.0
HIGH_CRASH_RISK_THRESHOLD = 0.60


@dataclass(slots=True)
class CrashCombination:
    """One tested permutation of interacting risks."""

    factors: list[str]
    combined_score: float
    interaction_effect: float
    severe: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CrashReport:
    """Full stress-test output for one candidate."""

    individual_risks: dict[str, float]
    crash_risk_raw: float
    crash_risk_score: float
    crash_density: float
    total_tested_combinations: int
    severe_combination_count: int
    worst_crash_combination: list[str]
    worst_combination_score: float
    primary_crash_vector: str
    primary_crash_category: str
    safe_to_enter_conditions: list[str] = field(default_factory=list)
    thesis_damage_triggers: list[str] = field(default_factory=list)
    tested_combinations: list[CrashCombination] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def pair_beta(a: str, b: str) -> float:
    return SYNERGY_PAIR_BETAS.get(frozenset({a, b}), DEFAULT_PAIR_BETA)


def simulate_crash_cases(
    risk_factors: dict[str, float],
    *,
    max_factors: int = 10,
) -> CrashReport:
    """Stress-test interacting risk factors (each severity in [0, 1]).

    Generates all pairwise and triple-wise combinations of the supplied
    factors (capped at ``max_factors`` strongest to bound combinatorics).
    """
    cleaned = {
        str(name): clamp01(float(value)) for name, value in risk_factors.items()
    }
    # Keep the strongest factors when too many are supplied.
    ranked = sorted(cleaned.items(), key=lambda kv: kv[1], reverse=True)
    active = dict(ranked[: max(int(max_factors), 2)])
    names = list(active)

    combinations: list[CrashCombination] = []
    for size in (2, 3):
        for combo in itertools.combinations(names, size):
            base = sum(active[f] for f in combo)
            if size == 2:
                a, b = combo
                interaction = pair_beta(a, b) * active[a] * active[b]
            else:
                a, b, c = combo
                interaction = (
                    pair_beta(a, b) * active[a] * active[b]
                    + pair_beta(a, c) * active[a] * active[c]
                    + pair_beta(b, c) * active[b] * active[c]
                    + DEFAULT_TRIPLE_BETA * active[a] * active[b] * active[c]
                )
            combined = base + interaction
            combinations.append(
                CrashCombination(
                    factors=list(combo),
                    combined_score=combined,
                    interaction_effect=interaction,
                    severe=combined >= SEVERE_COMBINATION_THRESHOLD
                    and all(active[f] > 0.0 for f in combo),
                )
            )

    severe = [c for c in combinations if c.severe]
    density = safe_div(len(severe), len(combinations)) if combinations else 0.0

    # Crash risk: individual sums plus all pairwise/triple interactions,
    # normalized by a softcap so the score stays in [0, 1].
    individual_sum = sum(active.values())
    pair_interactions = sum(
        pair_beta(a, b) * active[a] * active[b]
        for a, b in itertools.combinations(names, 2)
    )
    triple_interactions = sum(
        DEFAULT_TRIPLE_BETA * active[a] * active[b] * active[c]
        for a, b, c in itertools.combinations(names, 3)
    )
    raw = individual_sum + pair_interactions + triple_interactions
    # Softcap: 1 - 2^(-raw/2) maps 0->0, 2->~0.5, large->1 monotonically.
    score = clamp01(1.0 - 0.5 ** (raw / 2.0)) if raw > 0 else 0.0

    if combinations:
        worst = max(combinations, key=lambda c: c.combined_score)
        worst_factors, worst_score = worst.factors, worst.combined_score
    else:
        worst_factors, worst_score = [], 0.0

    if active:
        primary = max(active.items(), key=lambda kv: kv[1])[0]
    else:
        primary = "none"
    primary_category = RISK_FACTOR_CATEGORIES.get(primary, CRASH_CATEGORY_FUNDAMENTAL)

    safe_conditions = [
        f"{name} severity must fall below 0.40 (currently {value:.2f})"
        for name, value in ranked
        if value >= 0.40
    ]
    damage_triggers = [
        f"{name} worsening beyond {min(value + 0.2, 1.0):.2f} breaks the thesis"
        for name, value in ranked[:3]
        if value > 0.0
    ]

    reasons: list[str] = []
    if score >= HIGH_CRASH_RISK_THRESHOLD:
        reasons.append("HIGH_CRASH_RISK")
    if density >= 0.5:
        reasons.append("HIGH_CRASH_DENSITY")
    if any(c.severe for c in combinations):
        reasons.append("SEVERE_COMBINATION_FOUND")
    if not reasons:
        reasons.append("CRASH_SURVIVABLE")

    return CrashReport(
        individual_risks=active,
        crash_risk_raw=raw,
        crash_risk_score=score,
        crash_density=density,
        total_tested_combinations=len(combinations),
        severe_combination_count=len(severe),
        worst_crash_combination=worst_factors,
        worst_combination_score=worst_score,
        primary_crash_vector=primary,
        primary_crash_category=primary_category,
        safe_to_enter_conditions=safe_conditions,
        thesis_damage_triggers=damage_triggers,
        tested_combinations=combinations,
        reason_codes=reasons,
    )
