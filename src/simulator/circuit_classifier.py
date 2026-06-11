"""Circuit / map classifier: same signal, different circuit, different rule.

Each circuit (cap-size / regime segment) carries a difficulty profile that
scales thresholds, shortens signal half-lives, caps position size, and
demands a minimum driver license.

    Circuit Difficulty =
        volatility_risk + liquidity_risk + data_quality_risk
        + manipulation_risk + crash_baseline
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.simulator.signal_tyres import (
    COMPOUND_HARD,
    COMPOUND_INTERMEDIATE,
    COMPOUND_MEDIUM,
    COMPOUND_SOFT,
    COMPOUND_WET,
)

CIRCUIT_LARGE_CAP = "large_cap"
CIRCUIT_MID_CAP = "mid_cap"
CIRCUIT_SMALL_CAP = "small_cap"
CIRCUIT_MICRO_CAP = "micro_cap"
CIRCUIT_BIOTECH_EVENT = "biotech_event"
CIRCUIT_COMMODITY_CYCLICAL = "commodity_cyclical"
CIRCUIT_DEFENSIVE = "defensive"
CIRCUIT_POLICY_TAILWIND = "policy_tailwind"
CIRCUIT_HIGH_VOLATILITY_MOMENTUM = "high_volatility_momentum"


@dataclass(slots=True)
class CircuitProfile:
    """Static risk profile of one market circuit."""

    name: str
    volatility_risk: float
    liquidity_risk: float
    data_quality_risk: float
    manipulation_risk: float
    crash_baseline: float
    difficulty: float
    reaction_time_requirement_hours: float
    allowed_signal_compounds: list[str]
    position_size_cap_pct: float
    required_driver_license: str
    threshold_multiplier: float
    half_life_decay_multiplier: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _profile(
    name: str,
    *,
    volatility: float,
    liquidity: float,
    data: float,
    manipulation: float,
    crash: float,
    reaction_hours: float,
    compounds: list[str],
    size_cap: float,
    license_: str,
    threshold_mult: float,
    decay_mult: float,
) -> CircuitProfile:
    return CircuitProfile(
        name=name,
        volatility_risk=volatility,
        liquidity_risk=liquidity,
        data_quality_risk=data,
        manipulation_risk=manipulation,
        crash_baseline=crash,
        difficulty=volatility + liquidity + data + manipulation + crash,
        reaction_time_requirement_hours=reaction_hours,
        allowed_signal_compounds=compounds,
        position_size_cap_pct=size_cap,
        required_driver_license=license_,
        threshold_multiplier=threshold_mult,
        half_life_decay_multiplier=decay_mult,
    )


_ALL = [COMPOUND_SOFT, COMPOUND_MEDIUM, COMPOUND_HARD, COMPOUND_INTERMEDIATE, COMPOUND_WET]

CIRCUIT_PROFILES: dict[str, CircuitProfile] = {
    CIRCUIT_LARGE_CAP: _profile(
        CIRCUIT_LARGE_CAP,
        volatility=0.2, liquidity=0.1, data=0.1, manipulation=0.1, crash=0.2,
        reaction_hours=168.0, compounds=_ALL, size_cap=10.0,
        license_="learner", threshold_mult=1.0, decay_mult=1.0,
    ),
    CIRCUIT_MID_CAP: _profile(
        CIRCUIT_MID_CAP,
        volatility=0.35, liquidity=0.25, data=0.25, manipulation=0.2, crash=0.3,
        reaction_hours=96.0, compounds=_ALL, size_cap=7.5,
        license_="rookie", threshold_mult=1.1, decay_mult=0.9,
    ),
    CIRCUIT_SMALL_CAP: _profile(
        CIRCUIT_SMALL_CAP,
        volatility=0.5, liquidity=0.45, data=0.4, manipulation=0.4, crash=0.45,
        reaction_hours=48.0,
        compounds=[COMPOUND_MEDIUM, COMPOUND_HARD, COMPOUND_INTERMEDIATE, COMPOUND_WET],
        size_cap=5.0, license_="club_racer", threshold_mult=1.25, decay_mult=0.75,
    ),
    CIRCUIT_MICRO_CAP: _profile(
        CIRCUIT_MICRO_CAP,
        volatility=0.7, liquidity=0.75, data=0.7, manipulation=0.8, crash=0.65,
        reaction_hours=24.0, compounds=[COMPOUND_HARD, COMPOUND_WET],
        size_cap=2.0, license_="pro_driver", threshold_mult=1.5, decay_mult=0.5,
    ),
    CIRCUIT_BIOTECH_EVENT: _profile(
        CIRCUIT_BIOTECH_EVENT,
        volatility=0.85, liquidity=0.5, data=0.55, manipulation=0.5, crash=0.8,
        reaction_hours=24.0, compounds=[COMPOUND_HARD, COMPOUND_MEDIUM],
        size_cap=2.0, license_="engineer", threshold_mult=1.6, decay_mult=0.5,
    ),
    CIRCUIT_COMMODITY_CYCLICAL: _profile(
        CIRCUIT_COMMODITY_CYCLICAL,
        volatility=0.55, liquidity=0.3, data=0.3, manipulation=0.3, crash=0.5,
        reaction_hours=72.0,
        compounds=[COMPOUND_MEDIUM, COMPOUND_HARD, COMPOUND_INTERMEDIATE, COMPOUND_WET],
        size_cap=5.0, license_="pro_am", threshold_mult=1.2, decay_mult=0.8,
    ),
    CIRCUIT_DEFENSIVE: _profile(
        CIRCUIT_DEFENSIVE,
        volatility=0.15, liquidity=0.15, data=0.15, manipulation=0.1, crash=0.15,
        reaction_hours=336.0, compounds=_ALL, size_cap=10.0,
        license_="learner", threshold_mult=0.95, decay_mult=1.1,
    ),
    CIRCUIT_POLICY_TAILWIND: _profile(
        CIRCUIT_POLICY_TAILWIND,
        volatility=0.4, liquidity=0.3, data=0.35, manipulation=0.35, crash=0.45,
        reaction_hours=72.0,
        compounds=[COMPOUND_SOFT, COMPOUND_MEDIUM, COMPOUND_HARD, COMPOUND_INTERMEDIATE],
        size_cap=5.0, license_="pro_am", threshold_mult=1.2, decay_mult=0.8,
    ),
    CIRCUIT_HIGH_VOLATILITY_MOMENTUM: _profile(
        CIRCUIT_HIGH_VOLATILITY_MOMENTUM,
        volatility=0.9, liquidity=0.4, data=0.4, manipulation=0.6, crash=0.7,
        reaction_hours=12.0, compounds=[COMPOUND_MEDIUM, COMPOUND_HARD],
        size_cap=2.5, license_="pro_driver", threshold_mult=1.5, decay_mult=0.4,
    ),
}

# Cap-size boundaries in USD.
LARGE_CAP_FLOOR = 10_000_000_000
MID_CAP_FLOOR = 2_000_000_000
SMALL_CAP_FLOOR = 300_000_000

_DEFENSIVE_SECTORS = {"utilities", "consumer_staples", "healthcare_staples"}
_COMMODITY_SECTORS = {"energy", "materials", "mining", "commodities", "agriculture"}


@dataclass(slots=True)
class CircuitClassification:
    """Result of classifying one stock onto a circuit."""

    circuit: str
    profile: CircuitProfile
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "circuit": self.circuit,
            "profile": self.profile.to_dict(),
            "reason_codes": list(self.reason_codes),
        }


def classify_circuit(
    *,
    market_cap_usd: float,
    sector: str = "",
    is_biotech_event_driven: bool = False,
    annualized_volatility: float = 0.0,
    policy_dependent: bool = False,
) -> CircuitClassification:
    """Assign a stock to its circuit. Special regimes outrank cap size."""
    sector_norm = str(sector).strip().lower()
    reasons: list[str] = []

    if is_biotech_event_driven:
        circuit = CIRCUIT_BIOTECH_EVENT
        reasons.append("BIOTECH_BINARY_EVENT")
    elif float(annualized_volatility) >= 0.80:
        circuit = CIRCUIT_HIGH_VOLATILITY_MOMENTUM
        reasons.append("EXTREME_VOLATILITY")
    elif policy_dependent:
        circuit = CIRCUIT_POLICY_TAILWIND
        reasons.append("POLICY_DEPENDENT")
    elif sector_norm in _COMMODITY_SECTORS:
        circuit = CIRCUIT_COMMODITY_CYCLICAL
        reasons.append("COMMODITY_SECTOR")
    elif sector_norm in _DEFENSIVE_SECTORS:
        circuit = CIRCUIT_DEFENSIVE
        reasons.append("DEFENSIVE_SECTOR")
    else:
        cap = max(float(market_cap_usd), 0.0)
        if cap >= LARGE_CAP_FLOOR:
            circuit = CIRCUIT_LARGE_CAP
        elif cap >= MID_CAP_FLOOR:
            circuit = CIRCUIT_MID_CAP
        elif cap >= SMALL_CAP_FLOOR:
            circuit = CIRCUIT_SMALL_CAP
        else:
            circuit = CIRCUIT_MICRO_CAP
        reasons.append("CAP_SIZE_CLASSIFICATION")

    profile = CIRCUIT_PROFILES[circuit]
    if profile.difficulty >= 2.5:
        reasons.append("HIGH_DIFFICULTY_CIRCUIT")
    return CircuitClassification(circuit=circuit, profile=profile, reason_codes=reasons)
