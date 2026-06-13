"""Layer 8 — Interpretation / Beholder Layer.

Beauty lies in the eyes of the beholder.  A signal has no fixed meaning until
a specific audience interprets it through its own incentive.

    Meaning_i        = f(tokens, beholder_i, incentive_i)
    Interpretation Gap = max_i(meaning) - min_i(meaning)
    Mispricing         = Interpretation Gap x Reality Confirmation

Each beholder reads the same token mass through a weighting that reflects what
that actor cares about (a short seller weights churn/friction up and hype down;
a long-only investor weights adoption/margin up).  The gap between the most-
bullish and most-bearish reading is where mispricing lives — *if* reality
confirms the minority view.

This is a self-contained beholder model so the package stays deterministic and
dependency-free.  The repo's richer ``contextual_interpretation`` package is a
natural future enrichment hook (multi-lens drift over time).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, mean, r3

# How each beholder weights token categories into a bullishness reading.
# Positive weights = bullish for that beholder; negative = bearish.
BEHOLDERS: dict[str, dict[str, float]] = {
    "retail_customer":   {"demand": 1.0, "aesthetic": 0.8, "hype": 0.6, "friction": -0.8},
    "expert_user":       {"friction": 0.9, "adoption": 0.8, "demand": 0.6, "hype": -0.5, "bot": -0.6},
    "creator_influencer":{"hype": 1.0, "aesthetic": 0.9, "demand": 0.7, "churn": -0.4},
    "employee":          {"adoption": 0.8, "margin": -0.6, "policy": -0.5, "friction": -0.4},
    "competitor":        {"churn": 1.0, "friction": 0.8, "adoption": -0.7, "pricing_power": -0.6},
    "regulator":         {"policy": 1.0, "hype": -0.3, "demand": 0.2},
    "analyst":           {"margin": 0.9, "adoption": 0.8, "pricing_power": 0.8, "churn": -0.8, "hype": -0.4},
    "institution":       {"margin": 1.0, "adoption": 0.7, "sovereignty": 0.7, "hype": -0.6, "bot": -0.8},
    "short_seller":      {"churn": 1.0, "friction": 0.9, "bot": 0.8, "hype": 0.5, "margin": -0.9, "adoption": -0.8},
    "long_only":         {"adoption": 0.9, "margin": 0.8, "demand": 0.7, "pricing_power": 0.8, "churn": -0.9},
    "market_maker":      {"hype": 0.6, "interpretation": 0.6, "policy": 0.4},
    "management":        {"adoption": 0.8, "demand": 0.8, "margin": 0.7, "friction": -0.7, "churn": -0.8},
}


@dataclass(frozen=True)
class BeholderReading:
    beholder: str
    meaning: float       # -1 bearish .. +1 bullish
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InterpretationResult:
    readings: list[BeholderReading]
    dominant: BeholderReading            # market-controlling view (heaviest actor set)
    minority: BeholderReading            # most-divergent contrarian view
    contrarian: BeholderReading          # most-bearish reading
    interpretation_gap: float            # 0..1 normalized spread of meanings
    interpretation_migration: float      # 0..1 how far meaning has spread across groups
    market_interpretation_lag: float     # 0..1 minority-vs-market divergence
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "readings": [r.to_dict() for r in self.readings],
            "dominant": self.dominant.to_dict(),
            "minority": self.minority.to_dict(),
            "contrarian": self.contrarian.to_dict(),
            "interpretation_gap": r3(self.interpretation_gap),
            "interpretation_migration": r3(self.interpretation_migration),
            "market_interpretation_lag": r3(self.market_interpretation_lag),
            "reason_codes": self.reason_codes,
        }


# Which beholders' consensus the *market price* currently reflects.
_MARKET_CONTROLLERS = ("analyst", "institution", "long_only", "market_maker")


def _direction(meaning: float) -> str:
    if meaning >= 0.15:
        return "BULLISH"
    if meaning <= -0.15:
        return "BEARISH"
    return "NEUTRAL"


def interpret_beholders(
    category_mass: dict[str, float],
    *,
    beholder_adoption: list[str] | None = None,
) -> InterpretationResult:
    """Read the token mass through every beholder lens.

    ``category_mass`` is the per-category token weight from the tokenizer.
    ``beholder_adoption`` lists the beholder groups that have *already* adopted
    the signal's meaning (drives interpretation migration).
    """
    # Normalize mass so meanings land in a comparable range.
    total = sum(abs(v) for v in category_mass.values()) or 1.0
    norm = {k: v / total for k, v in category_mass.items()}

    readings: list[BeholderReading] = []
    for name, weights in BEHOLDERS.items():
        raw = sum(weights.get(cat, 0.0) * norm.get(cat, 0.0) for cat in norm)
        # Squash into [-1, 1].
        meaning = max(-1.0, min(1.0, raw * 3.0))
        readings.append(BeholderReading(name, round(meaning, 3), _direction(meaning)))

    by_name = {r.beholder: r for r in readings}
    meanings = [r.meaning for r in readings]
    hi, lo = max(meanings), min(meanings)
    gap = clamp((hi - lo) / 2.0)  # spread in [0,2] → [0,1]

    # Dominant = mean reading of the market-controlling actors.
    market_view = mean([by_name[b].meaning for b in _MARKET_CONTROLLERS if b in by_name])
    dominant = min(
        (by_name[b] for b in _MARKET_CONTROLLERS if b in by_name),
        key=lambda r: abs(r.meaning - market_view),
        default=readings[0],
    )
    # Contrarian = most bearish; minority = reading furthest from market view.
    contrarian = min(readings, key=lambda r: r.meaning)
    minority = max(readings, key=lambda r: abs(r.meaning - market_view))

    migration = clamp(len(set(beholder_adoption or [])) / len(BEHOLDERS))
    market_lag = clamp(abs(minority.meaning - market_view) / 2.0)

    reasons = [
        f"GAP:{round(gap,2)}",
        f"DOMINANT:{dominant.beholder}:{dominant.direction}",
        f"MINORITY:{minority.beholder}:{minority.direction}",
    ]
    if gap >= 0.5:
        reasons.append("WIDE_INTERPRETATION_GAP")
    if minority.direction == "BULLISH" and dominant.direction != "BULLISH":
        reasons.append("EARLY_BULLS_AHEAD_OF_MARKET")
    if minority.direction == "BEARISH" and dominant.direction == "BULLISH":
        reasons.append("HIDDEN_BEAR_CASE")

    return InterpretationResult(
        readings=readings,
        dominant=dominant,
        minority=minority,
        contrarian=contrarian,
        interpretation_gap=gap,
        interpretation_migration=migration,
        market_interpretation_lag=market_lag,
        reason_codes=reasons,
    )


__all__ = [
    "BEHOLDERS",
    "BeholderReading",
    "InterpretationResult",
    "interpret_beholders",
]
