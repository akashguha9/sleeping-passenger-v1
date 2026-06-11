"""Signal tyre physics: compounds, half-life, grip, and freshness.

A signal is treated like a tyre compound. Each compound has a base
half-life; grip decays exponentially with age:

    Signal Grip % = 100 * 0.5 ** (signal_age / adjusted_half_life)

Effective strength combines decay with detection latency and source quality:

    Effective Signal Strength =
        raw_strength * grip * reaction_freshness
        * source_quality * confirmation_multiplier
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip, safe_div
from src.utils.validation_utils import normalized_score

COMPOUND_SOFT = "soft"
COMPOUND_MEDIUM = "medium"
COMPOUND_HARD = "hard"
COMPOUND_INTERMEDIATE = "intermediate"
COMPOUND_WET = "wet"

SIGNAL_COMPOUNDS: tuple[str, ...] = (
    COMPOUND_SOFT,
    COMPOUND_MEDIUM,
    COMPOUND_HARD,
    COMPOUND_INTERMEDIATE,
    COMPOUND_WET,
)

# Base half-life per compound, in hours. Soft hype dies in under a day;
# hard balance-sheet evidence persists for a quarter.
BASE_HALF_LIFE_HOURS: dict[str, float] = {
    COMPOUND_SOFT: 18.0,
    COMPOUND_MEDIUM: 120.0,
    COMPOUND_HARD: 2160.0,
    COMPOUND_INTERMEDIATE: 336.0,
    COMPOUND_WET: 720.0,
}

# Detection-latency budget per compound, in hours. Soft signals must be
# caught fast; hard signals tolerate slow discovery.
ALLOWED_REACTION_WINDOW_HOURS: dict[str, float] = {
    COMPOUND_SOFT: 12.0,
    COMPOUND_MEDIUM: 72.0,
    COMPOUND_HARD: 720.0,
    COMPOUND_INTERMEDIATE: 168.0,
    COMPOUND_WET: 336.0,
}

# Signal-type → compound classification table.
SIGNAL_TYPE_COMPOUNDS: dict[str, str] = {
    "social_spike": COMPOUND_SOFT,
    "viral_article": COMPOUND_SOFT,
    "breaking_headline": COMPOUND_SOFT,
    "forum_hype": COMPOUND_SOFT,
    "earnings_beat": COMPOUND_MEDIUM,
    "earnings_miss": COMPOUND_MEDIUM,
    "analyst_revision": COMPOUND_MEDIUM,
    "contract_win": COMPOUND_MEDIUM,
    "guidance_change": COMPOUND_MEDIUM,
    "free_cash_flow": COMPOUND_HARD,
    "roic": COMPOUND_HARD,
    "low_debt": COMPOUND_HARD,
    "moat": COMPOUND_HARD,
    "backlog": COMPOUND_HARD,
    "insider_ownership": COMPOUND_HARD,
    "early_turnaround": COMPOUND_INTERMEDIATE,
    "newspaper_discovery": COMPOUND_INTERMEDIATE,
    "unconfirmed_catalyst": COMPOUND_INTERMEDIATE,
    "defensive_balance_sheet": COMPOUND_WET,
    "low_beta": COMPOUND_WET,
    "recession_resilience": COMPOUND_WET,
}

# A compound is "worn" once grip falls below this fraction.
WORN_GRIP_THRESHOLD = 0.50
# Hard-conviction promotion requires at least this much hard evidence.
HARD_EVIDENCE_FLOOR = 0.60


@dataclass(slots=True)
class TyreState:
    """Decayed state of one signal."""

    compound: str
    raw_strength: float
    signal_age_hours: float
    base_half_life_hours: float
    adjusted_half_life_hours: float
    signal_grip_pct: float
    reaction_lag_hours: float
    allowed_reaction_window_hours: float
    reaction_freshness: float
    source_quality: float
    confirmation_multiplier: float
    effective_signal_strength: float
    is_worn: bool
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_signal_compound(signal_type: str) -> str:
    """Map a raw signal type label to its tyre compound (soft by default)."""
    return SIGNAL_TYPE_COMPOUNDS.get(
        str(signal_type).strip().lower(), COMPOUND_SOFT
    )


def adjusted_half_life_hours(
    compound: str,
    *,
    circuit_decay_multiplier: float = 1.0,
    track_condition_score: float = 0.5,
) -> float:
    """Half-life adjusted for circuit and track condition.

    Hostile circuits (multiplier < 1) and bad track conditions shorten the
    usable life of every compound; supportive conditions extend it mildly.
    Track condition is normalized [0, 1] with 0.5 neutral.
    """
    base = BASE_HALF_LIFE_HOURS.get(compound, BASE_HALF_LIFE_HOURS[COMPOUND_SOFT])
    condition_factor = clip(0.7 + 0.6 * normalized_score(track_condition_score, 0.5), 0.7, 1.3)
    multiplier = clip(circuit_decay_multiplier, 0.1, 2.0)
    return max(base * multiplier * condition_factor, 1.0)


def signal_grip_pct(signal_age_hours: float, half_life_hours: float) -> float:
    """Grip % = 100 * 0.5 ** (age / half_life). Never negative."""
    age = max(float(signal_age_hours), 0.0)
    half_life = max(float(half_life_hours), 1e-9)
    return clip(100.0 * 0.5 ** (age / half_life), 0.0, 100.0)


def reaction_freshness(
    reaction_lag_hours: float, allowed_window_hours: float
) -> float:
    """Freshness = max(0, 1 - lag / allowed_window). Late detection decays value."""
    lag = max(float(reaction_lag_hours), 0.0)
    window = max(float(allowed_window_hours), 1e-9)
    return clamp01(1.0 - lag / window)


def score_signal_tyre(
    *,
    signal_type: str,
    raw_strength: float,
    signal_age_hours: float,
    reaction_lag_hours: float = 0.0,
    source_quality: float = 1.0,
    confirmation_multiplier: float = 1.0,
    circuit_decay_multiplier: float = 1.0,
    track_condition_score: float = 0.5,
) -> TyreState:
    """Compute the full decayed tyre state for one signal.

    ``raw_strength`` is on a 0–100 scale; grip/freshness/quality multipliers
    are fractions, so ``effective_signal_strength`` is also 0–100.
    """
    compound = classify_signal_compound(signal_type)
    raw = clip(raw_strength, 0.0, 100.0)
    half_life = adjusted_half_life_hours(
        compound,
        circuit_decay_multiplier=circuit_decay_multiplier,
        track_condition_score=track_condition_score,
    )
    grip_pct = signal_grip_pct(signal_age_hours, half_life)
    grip = grip_pct / 100.0
    window = ALLOWED_REACTION_WINDOW_HOURS.get(
        compound, ALLOWED_REACTION_WINDOW_HOURS[COMPOUND_SOFT]
    )
    freshness = reaction_freshness(reaction_lag_hours, window)
    quality = normalized_score(source_quality, 1.0)
    confirmation = clip(confirmation_multiplier, 0.0, 1.5)
    effective = clip(raw * grip * freshness * quality * confirmation, 0.0, 150.0)
    is_worn = grip < WORN_GRIP_THRESHOLD

    reasons: list[str] = []
    if is_worn:
        reasons.append("WORN_TYRE")
    if freshness <= 0.0:
        reasons.append("REACTION_WINDOW_MISSED")
    elif freshness < 0.5:
        reasons.append("LATE_DETECTION")
    if compound == COMPOUND_SOFT and is_worn:
        reasons.append("STALE_SOFT_SIGNAL")
    if effective >= 60.0:
        reasons.append("HIGH_EFFECTIVE_STRENGTH")

    return TyreState(
        compound=compound,
        raw_strength=raw,
        signal_age_hours=max(float(signal_age_hours), 0.0),
        base_half_life_hours=BASE_HALF_LIFE_HOURS.get(
            compound, BASE_HALF_LIFE_HOURS[COMPOUND_SOFT]
        ),
        adjusted_half_life_hours=half_life,
        signal_grip_pct=grip_pct,
        reaction_lag_hours=max(float(reaction_lag_hours), 0.0),
        allowed_reaction_window_hours=window,
        reaction_freshness=freshness,
        source_quality=quality,
        confirmation_multiplier=confirmation,
        effective_signal_strength=effective,
        is_worn=is_worn,
        reason_codes=reasons,
    )


def hard_conviction_allowed(
    tyres: list[TyreState], *, hard_evidence_score: float
) -> tuple[bool, list[str]]:
    """Gate: a stale soft signal can never support hard conviction.

    Allowed only when (a) at least one non-worn hard/medium/wet tyre exists
    or hard evidence clears the floor, and (b) the thesis does not rest
    solely on worn soft compounds.
    """
    reasons: list[str] = []
    hard_evidence = normalized_score(hard_evidence_score)
    live_tyres = [t for t in tyres if not t.is_worn]
    soft_only = bool(tyres) and all(t.compound == COMPOUND_SOFT for t in tyres)
    worn_soft_only = bool(tyres) and all(
        t.compound == COMPOUND_SOFT and t.is_worn for t in tyres
    )

    if not tyres:
        reasons.append("NO_SIGNALS_PRESENT")
        return False, reasons
    if worn_soft_only:
        reasons.append("STALE_SOFT_CANNOT_SUPPORT_HARD_CONVICTION")
        return False, reasons
    if soft_only and hard_evidence < HARD_EVIDENCE_FLOOR:
        reasons.append("SOFT_ONLY_NEEDS_HARD_EVIDENCE")
        return False, reasons
    if hard_evidence < HARD_EVIDENCE_FLOOR and not any(
        t.compound in (COMPOUND_HARD, COMPOUND_MEDIUM, COMPOUND_WET)
        for t in live_tyres
    ):
        reasons.append("INSUFFICIENT_HARD_EVIDENCE")
        return False, reasons
    reasons.append("HARD_CONVICTION_SUPPORTED")
    return True, reasons


def blended_grip_pct(tyres: list[TyreState]) -> float:
    """Strength-weighted average grip across all supplied signals."""
    if not tyres:
        return 0.0
    total_weight = sum(t.raw_strength for t in tyres)
    if total_weight <= 0:
        return 0.0
    return safe_div(
        sum(t.signal_grip_pct * t.raw_strength for t in tyres), total_weight
    )
