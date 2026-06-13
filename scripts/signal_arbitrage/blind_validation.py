"""Layer 4 — Blind / Double-Blind / Triple-Blind Reality Validation.

Would the signal still score well if ticker / brand / platform / social-proof
were hidden?  If performance collapses when the story is removed, the thesis
is perception-dependent.

    Signal Purity      = Blind Performance / Visible Performance
    Perception Premium = Visible Performance - Blind Performance

If a caller has run an actual blind cohort it can pass ``blind_score``
directly (double/triple-blind).  Otherwise this module *derives* a blind score
from the visible score by stripping the contribution of social-proof tokens
(hype + bot mass) and synthetic contamination — i.e. it removes the popularity
cues and asks what is left.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3, safe_ratio


@dataclass(frozen=True)
class BlindValidationResult:
    visible_score: float
    blind_score: float
    perception_premium: float    # visible - blind, in [0,1]
    reality_purity: float        # blind / visible, in [0,1]  (the cap)
    blind_mode: str              # "EXPLICIT" | "DERIVED"
    fragility_reasons: list[str] = field(default_factory=list)

    @property
    def is_fragile(self) -> bool:
        return self.reality_purity < 0.5

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("visible_score", "blind_score", "perception_premium", "reality_purity"):
            d[k] = r3(d[k])
        d["is_fragile"] = self.is_fragile
        return d


def validate_blind(
    *,
    visible_score: float,
    blind_score: float | None = None,
    hype_mass: float = 0.0,
    bot_mass: float = 0.0,
    contamination: float = 0.0,
    substance_mass: float = 0.0,
) -> BlindValidationResult:
    """Compute reality purity (the multiplicative fraud cap).

    ``visible_score`` is the signal's score *with* all popularity cues. When
    ``blind_score`` is not supplied it is derived by discounting the visible
    score in proportion to how much of its support comes from social-proof
    (hype/bot) tokens and synthetic contamination, then floored by genuine
    substance mass so a signal with real demand/trust/adoption tokens cannot
    be blinded to zero.
    """
    visible = clamp(visible_score)
    reasons: list[str] = []

    if blind_score is not None:
        blind = clamp(blind_score)
        mode = "EXPLICIT"
    else:
        mode = "DERIVED"
        total_mass = hype_mass + bot_mass + substance_mass
        # perception_share: fraction of the signal's support that is pure
        # popularity cue (hype + bot), amplified by measured contamination.
        perception_share = safe_ratio(hype_mass + bot_mass, total_mass, 0.0)
        perception_share = clamp(perception_share + 0.5 * contamination)
        # Substance floor: real demand/trust/adoption keep the signal alive
        # even with the story removed.
        substance_floor = clamp(safe_ratio(substance_mass, total_mass, 0.0))
        blind = clamp(visible * (1.0 - perception_share))
        blind = max(blind, visible * substance_floor)
        if perception_share >= 0.5:
            reasons.append("PERCEPTION_DEPENDENT_SUPPORT")
        if contamination >= 0.4:
            reasons.append("CONTAMINATION_DRIVEN_VISIBILITY")

    perception_premium = clamp(visible - blind)
    reality_purity = clamp(safe_ratio(blind, visible, 1.0))

    if reality_purity < 0.5:
        reasons.append("FRAGILE_LOW_PURITY")
    if perception_premium >= 0.4:
        reasons.append("HIGH_PERCEPTION_PREMIUM")
    if reality_purity >= 0.8:
        reasons.append("SURVIVES_BLIND")

    return BlindValidationResult(
        visible_score=visible,
        blind_score=blind,
        perception_premium=perception_premium,
        reality_purity=reality_purity,
        blind_mode=mode,
        fragility_reasons=reasons,
    )


__all__ = ["BlindValidationResult", "validate_blind"]
